"""
Supervisor — 子进程生命周期管理器

管理 DB Service / AST Worker / Agent Worker 的启停、监控、重启。
与 worker 进程通过 stdout JSON lines 通信：
  {"type": "ready",    "pid": 12345}                — 初始化完成
  {"type": "heartbeat","pid": 12345, "ts": 1.23}    — 心跳 (每 5s)
  {"type": "error",    "pid": 12345, "msg": "..."}  — 错误报告
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_HEARTBEAT_TIMEOUT = 15.0   # 秒，超过此时间未收到心跳判定为可疑
_DEAD_TIMEOUT = 30.0        # 秒，超过此时间判定为死亡
_READY_TIMEOUT = 30.0       # 秒，启动后等待 ready 的最长时间
_PROBE_INTERVAL = 1.0       # 秒，HTTP 健康探针间隔


@dataclass
class WorkerInfo:
    label: str
    args: list[str]
    proc: Optional[subprocess.Popen] = None
    status: str = "stopped"        # stopped | starting | ready | dead | fatal
    restart_count: int = 0
    restart_limit: int = 3
    last_heartbeat: float = 0.0
    ready_event: asyncio.Event = field(default_factory=asyncio.Event)
    stop_requested: bool = False
    health_url: Optional[str] = None   # 若设置，就绪判定改用 HTTP 探针（plain 服务）
    env: Optional[dict] = None         # 追加的子进程环境变量

    @property
    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def backoff(self) -> float:
        """指数退避等待时间（秒）"""
        return min(2.0 ** (self.restart_count - 1), 30.0)


def _http_ok(url: str, timeout: float = 2.0) -> bool:
    """对健康端点发起 GET，返回是否 2xx/3xx。"""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            return 200 <= resp.status < 400
    except Exception:
        return False


class Supervisor:
    """子进程监督者"""

    def __init__(self):
        self._workers: dict[str, WorkerInfo] = {}
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._monitor_task: Optional[asyncio.Task] = None

    # ── 注册 ────────────────────────────────────────────────────

    def register(self, label: str, args: list[str], restart_limit: int = 3,
                 health_url: Optional[str] = None, env: Optional[dict] = None):
        """注册一个受管理的子进程

        - 默认（health_url=None）：就绪/存活依赖 worker 在 stdout 发 JSON 信号
          （{"type": "ready"} / {"type": "heartbeat"}）。
        - health_url 设置后（plain 服务，如 uvicorn/FastAPI）：就绪判定改为 HTTP
          健康探针，监控改为进程存活 + 周期探针，不再依赖 JSON 信号。
        - env：追加到子进程环境的变量（覆盖 os.environ）。
        """
        self._workers[label] = WorkerInfo(
            label=label, args=args, restart_limit=restart_limit,
            health_url=health_url, env=env,
        )
        logger.info(f"[Supervisor] registered: {label}" + (f" (health={health_url})" if health_url else ""))

    # ── 启动 ────────────────────────────────────────────────────

    async def start_all(self):
        """启动所有注册的 worker 并等待 ready"""
        self._running = True
        self._loop = asyncio.get_running_loop()

        for label, wi in self._workers.items():
            self._spawn(label)

        # 等待所有 worker 就绪
        for label, wi in self._workers.items():
            try:
                if wi.health_url:
                    await asyncio.wait_for(self._wait_health(wi), timeout=_READY_TIMEOUT)
                else:
                    await asyncio.wait_for(wi.ready_event.wait(), timeout=_READY_TIMEOUT)
                logger.info(f"[Supervisor] {label} is ready")
            except asyncio.TimeoutError:
                logger.warning(f"[Supervisor] {label} not ready within {_READY_TIMEOUT}s")

        # 启动监控协程
        self._monitor_task = self._loop.create_task(self._monitor_loop())

    async def _wait_health(self, wi: WorkerInfo):
        """轮询 HTTP 健康端点直到就绪"""
        while self._running:
            if _http_ok(wi.health_url):
                wi.status = "ready"
                wi.ready_event.set()
                return
            await asyncio.sleep(_PROBE_INTERVAL)

    def _spawn(self, label: str):
        """启动一个 worker 进程"""
        wi = self._workers[label]
        if wi.proc and wi.is_alive:
            return
        wi.status = "starting"
        wi.restart_count += 1
        wi.ready_event.clear()
        try:
            env = dict(os.environ)
            # JSON 信号 worker（db_service/agent_worker 等）默认按 distributed 模式启动；
            # plain 服务（uvicorn/FastAPI）保持调用方模式，可经 env 显式覆盖。
            if wi.health_url is None:
                env.setdefault("TOPO_MODE", "distributed")
            if wi.env:
                env.update(wi.env)
            proc = subprocess.Popen(
                wi.args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env=env,
            )
            wi.proc = proc
            wi.last_heartbeat = time.time()
            logger.info(f"[Supervisor] spawned {label} (pid={proc.pid}, attempt={wi.restart_count})")
            # 启动读取 stdout 的协程
            self._loop.create_task(self._read_worker_stdout(label))
        except Exception as e:
            logger.error(f"[Supervisor] failed to spawn {label}: {e}")
            wi.status = "fatal"

    async def _read_worker_stdout(self, label: str):
        """异步读取 worker 的 stdout，解析 JSON 信令"""
        wi = self._workers[label]
        if not wi.proc or not wi.proc.stdout:
            return
        try:
            async for line in self._aiter_lines(wi.proc.stdout):
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    logger.info(f"[{label}] {line}")
                    continue
                self._handle_msg(label, msg)
        except Exception:
            pass
        finally:
            # worker 进程已退出
            if wi.is_alive:
                wi.proc.wait()
            wi.status = "dead" if not wi.stop_requested else "stopped"
            logger.info(f"[Supervisor] {label} exited (status={wi.status}, pid={wi.proc.pid if wi.proc else '?'})")
            # 如果不是主动停止，尝试重启
            if not wi.stop_requested and self._running:
                await self._restart(label)

    async def _aiter_lines(self, stream):
        """异步行迭代器"""
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, stream.readline)
            if not line:
                break
            yield line.decode("utf-8", errors="replace").rstrip("\n\r")

    def _handle_msg(self, label: str, msg: dict):
        """处理 worker 发来的信令消息"""
        wi = self._workers[label]
        msg_type = msg.get("type", "")
        if msg_type == "ready":
            wi.status = "ready"
            wi.ready_event.set()
            wi.last_heartbeat = time.time()
        elif msg_type == "heartbeat":
            wi.last_heartbeat = time.time()
        elif msg_type == "error":
            logger.warning(f"[{label}] error: {msg.get('msg', '')}")
        else:
            logger.debug(f"[{label}] {json.dumps(msg)}")

    # ── 监控 ────────────────────────────────────────────────────

    async def _monitor_loop(self):
        """定期检查 worker 心跳/健康"""
        while self._running:
            await asyncio.sleep(5.0)
            now = time.time()
            for label, wi in list(self._workers.items()):
                if wi.status == "stopped":
                    continue
                if wi.stop_requested:
                    continue
                if not wi.is_alive:
                    continue
                if wi.health_url:
                    # plain 服务：无心跳信号，靠进程存活 + HTTP 探针
                    if not _http_ok(wi.health_url, timeout=2.0):
                        logger.warning(f"[Supervisor] {label} health probe failed")
                    continue
                elapsed = now - wi.last_heartbeat
                if elapsed > _DEAD_TIMEOUT:
                    logger.warning(f"[Supervisor] {label} heartbeat timeout ({elapsed:.0f}s), terminating")
                    wi.proc.kill()
                elif elapsed > _HEARTBEAT_TIMEOUT:
                    logger.warning(f"[Supervisor] {label} heartbeat overdue ({elapsed:.0f}s)")

    async def _restart(self, label: str):
        """重启 worker（指数退避）"""
        wi = self._workers[label]
        if wi.restart_count > wi.restart_limit:
            wi.status = "fatal"
            logger.error(f"[Supervisor] {label} restart limit reached ({wi.restart_limit}), marking FATAL")
            return
        backoff = wi.backoff()
        logger.info(f"[Supervisor] restarting {label} in {backoff:.0f}s (attempt {wi.restart_count}/{wi.restart_limit})")
        await asyncio.sleep(backoff)
        self._spawn(label)

    # ── 人工重启 / 管理端点（P1） ──────────────────────────────

    async def restart(self, label: str):
        """人工重启指定 worker：重置崩溃预算后重启，不占 restart_limit。

        进程存活时发 SIGTERM，由退出路径（_read_worker_stdout finally）触发 _restart；
        已死亡/致命则直接 _spawn。
        """
        wi = self._workers.get(label)
        if wi is None:
            raise KeyError(label)
        wi.restart_count = 0
        wi.stop_requested = False
        if wi.proc and wi.is_alive:
            wi.status = "starting"
            logger.info(f"[Supervisor] manual restart {label} (pid={wi.proc.pid})")
            if sys.platform == "win32":
                wi.proc.terminate()
            else:
                wi.proc.send_signal(signal.SIGTERM)
        else:
            logger.info(f"[Supervisor] manual restart {label} (not running, spawning)")
            self._spawn(label)

    async def start_admin_server(self, host: str = "127.0.0.1", port: int = 3450,
                                 token: Optional[str] = None):
        """启动 localhost 管理端点（P1）：GET /apps · POST /restart/{name}。

        仅绑定 127.0.0.1；鉴权复用主 token（token=全权，与网关 /api 一致）。
        """
        self._admin_token = token
        self._admin_server = await asyncio.start_server(
            self._handle_admin_conn, host, port)
        logger.info(f"[Supervisor] admin endpoint listening on http://{host}:{port}")

    async def stop_admin_server(self):
        server = getattr(self, "_admin_server", None)
        if server:
            server.close()
            try:
                await server.wait_closed()
            except Exception:
                pass
            self._admin_server = None

    def _admin_authorized(self, headers: dict, raw_path: str) -> bool:
        token = getattr(self, "_admin_token", None)
        if not token:
            return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(raw_path).query)
        if q.get("token") and q["token"][0] == token:
            return True
        if headers.get("authorization") == f"Bearer {token}":
            return True
        return False

    async def _handle_admin_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = (await asyncio.wait_for(reader.readline(), timeout=10.0)).decode().strip()
            if not request_line:
                return
            parts = request_line.split()
            if len(parts) < 2:
                await self._write_json(writer, 400, {"error": "bad request"})
                return
            method, raw_path = parts[0], parts[1]
            headers = {}
            while True:
                line = (await reader.readline()).decode().strip()
                if not line:
                    break
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip().lower()] = v.strip()
            content_length = int(headers.get("content-length", "0") or "0")
            body = b""
            while len(body) < content_length:
                chunk = await reader.read(content_length - len(body))
                if not chunk:
                    break
                body += chunk

            if not self._admin_authorized(headers, raw_path):
                await self._write_json(writer, 401, {"error": "unauthorized"})
                return

            path = urllib.parse.urlparse(raw_path).path
            if method == "GET" and path == "/apps":
                await self._write_json(writer, 200, self.get_status())
            elif method == "POST" and path.startswith("/restart/"):
                label = urllib.parse.unquote(path.split("/")[2])
                if label not in self._workers:
                    await self._write_json(writer, 404, {"error": f"unknown app: {label}"})
                    return
                try:
                    await self.restart(label)
                except KeyError:
                    await self._write_json(writer, 404, {"error": f"unknown app: {label}"})
                    return
                await self._write_json(writer, 200, {"restarted": label})
            else:
                await self._write_json(writer, 404, {"error": "not found"})
        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"[Supervisor] admin handler error: {e}")
        finally:
            try:
                writer.close()
            except Exception:
                pass

    async def _write_json(self, writer: asyncio.StreamWriter, status: int, payload):
        data = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        writer.write(
            (f"HTTP/1.1 {status} OK\r\nContent-Type: application/json\r\n"
             f"Content-Length: {len(data)}\r\nConnection: close\r\n\r\n").encode("utf-8"))
        writer.write(data)
        await writer.drain()

    # ── 停止 ────────────────────────────────────────────────────

    async def stop_worker(self, label: str, timeout: float = 5.0):
        """优雅停止指定 worker"""
        wi = self._workers.get(label)
        if not wi or not wi.is_alive:
            return
        wi.stop_requested = True
        logger.info(f"[Supervisor] stopping {label} (pid={wi.proc.pid})")
        if sys.platform == "win32":
            wi.proc.terminate()
        else:
            wi.proc.send_signal(signal.SIGTERM)
        try:
            await asyncio.wait_for(
                self._loop.run_in_executor(None, wi.proc.wait),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[Supervisor] {label} did not stop in {timeout}s, killing")
            wi.proc.kill()
            await self._loop.run_in_executor(None, wi.proc.wait)
        wi.status = "stopped"
        logger.info(f"[Supervisor] {label} stopped")

    async def shutdown_all(self, timeout: float = 5.0):
        """停止所有 worker"""
        self._running = False
        await self.stop_admin_server()
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        for label in list(self._workers.keys()):
            await self.stop_worker(label, timeout=timeout)

    def get_status(self) -> dict:
        """返回所有 worker 状态"""
        return {
            label: {
                "status": wi.status,
                "pid": wi.proc.pid if wi.proc else None,
                "restart_count": wi.restart_count,
                "last_heartbeat": wi.last_heartbeat,
                "alive": wi.is_alive,
            }
            for label, wi in self._workers.items()
        }
