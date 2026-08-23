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
_PROBE_FAIL_LIMIT = 5       # 连续探针失败次数（5×5s=25s）判定为挂死 → kill 重启
_KEEP_LOGS = 3              # 每个 worker 保留的历史日志文件数（按 pid 分文件）


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
    probe_fails: int = 0               # 连续健康探针失败计数（挂死检测）
    log_file: Optional[object] = None  # 子进程 stdout 重定向的日志文件句柄
    tail_task: Optional[asyncio.Task] = None  # 日志 tail 协程（每次 spawn 重建）

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

    def __init__(self, log_dir: Optional[str] = None):
        self._workers: dict[str, WorkerInfo] = {}
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._monitor_task: Optional[asyncio.Task] = None
        # 子进程 stdout 落盘目录（关键解耦：普通文件写入永不阻塞子进程，
        # 而 64KB 的管道一旦排空不及时就会把子进程主线程卡死在 write()）
        self._log_dir = log_dir
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)

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
            except asyncio.TimeoutError:
                logger.warning(f"[Supervisor] {label} not ready within {_READY_TIMEOUT}s")
                continue
            if wi.is_alive and wi.status == "ready":
                logger.info(f"[Supervisor] {label} is ready")
            else:
                logger.warning(f"[Supervisor] {label} not ready (process exited early?)")

        # 启动监控协程
        self._monitor_task = self._loop.create_task(self._monitor_loop())

    async def _wait_health(self, wi: WorkerInfo):
        """轮询 HTTP 健康端点直到就绪（进程已退出则立即返回，由监控循环重启）"""
        while self._running:
            if not wi.is_alive:
                return
            # _http_ok 是同步阻塞调用（urllib），必须放到线程池，避免阻塞事件循环
            ok = await self._loop.run_in_executor(None, _http_ok, wi.health_url)
            if ok:
                wi.status = "ready"
                wi.ready_event.set()
                return
            await asyncio.sleep(_PROBE_INTERVAL)

    def _close_log(self, wi: WorkerInfo):
        """关闭 worker 的日志文件句柄（若存在）"""
        try:
            if wi.log_file:
                wi.log_file.close()
        except Exception:
            pass
        wi.log_file = None

    def _open_worker_log(self, label: str, pid: int) -> object:
        """为 worker 打开按 pid 分文件的 stdout 日志，并裁剪历史文件。

        注意必须是可读可写模式（"a+"）：子进程写 + supervisor tail 读共用此句柄。
        """
        path = os.path.join(self._log_dir, f"{label}-{pid}.log")
        # ab+：二进制可读可写、写端追加；无缓冲。子进程继承 fd 直接写盘，
        # supervisor 侧从当前读位置增量 read（普通文件 read 无数据时立即返回）。
        f = open(path, "ab+", buffering=0)
        if self._log_dir:
            try:
                old = sorted(
                    (os.path.join(self._log_dir, n) for n in os.listdir(self._log_dir)
                     if n.startswith(f"{label}-") and n.endswith(".log") and n != os.path.basename(path)),
                    key=os.path.getmtime, reverse=True)
                for stale in old[_KEEP_LOGS - 1:]:
                    os.remove(stale)
            except Exception:
                pass
        return f

    def _spawn(self, label: str):
        """启动一个 worker 进程"""
        wi = self._workers[label]
        if wi.proc and wi.is_alive:
            return
        wi.status = "starting"
        wi.restart_count += 1
        wi.ready_event.clear()
        wi.probe_fails = 0
        # 关闭上一轮实例的日志句柄与 tail 协程，避免泄漏/重复 tail
        self._close_log(wi)
        if wi.tail_task and not wi.tail_task.done():
            wi.tail_task.cancel()
        wi.tail_task = None
        try:
            env = dict(os.environ)
            # JSON 信号 worker（db_service/agent_worker 等）默认按 distributed 模式启动；
            # plain 服务（uvicorn/FastAPI）保持调用方模式，可经 env 显式覆盖。
            if wi.health_url is None:
                env.setdefault("TOPO_MODE", "distributed")
            if wi.env:
                env.update(wi.env)
            # stdout 必须落盘（普通文件写入永不阻塞子进程）；无 log_dir 时丢弃
            log_file = self._open_worker_log(label, time.time_ns() // 10**6) if self._log_dir \
                else open(os.devnull, "ab")
            proc = subprocess.Popen(
                wi.args,
                stdout=log_file, stderr=subprocess.STDOUT,
                env=env,
            )
            wi.proc = proc
            wi.last_heartbeat = time.time()
            if self._log_dir:
                wi.log_file = log_file
            else:
                log_file.close()
            logger.info(f"[Supervisor] spawned {label} (pid={proc.pid}, attempt={wi.restart_count})")
            # 启动日志 tail 协程（普通文件读取立即返回，替代旧的阻塞 readline）
            if self._log_dir:
                wi.tail_task = self._loop.create_task(self._tail_worker_logs(label))
        except Exception as e:
            logger.error(f"[Supervisor] failed to spawn {label}: {e}")
            self._close_log(wi)
            wi.status = "fatal"

    async def _tail_worker_logs(self, label: str):
        """tail worker 的 stdout 日志文件，解析 JSON 信令。

        普通文件的 read(n) 在无数据时立即返回 b''（不像管道 readline 会永久
        占住线程），因此不会耗尽线程池，也不会因排空延迟反压子进程。
        进程死亡检测/重启统一由 _monitor_loop 负责（单一触发点，无竞态）。
        """
        wi = self._workers[label]
        f = wi.log_file
        if f is None:
            return
        buf = ""
        try:
            while True:
                try:
                    chunk = await self._loop.run_in_executor(None, f.read, 1 << 16)
                except (OSError, ValueError) as e:
                    logger.warning(f"[Supervisor] {label} log tail stopped: {e}")
                    break
                if chunk:
                    buf += chunk.decode("utf-8", errors="replace")
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        self._ingest_line(label, line.strip())
                    continue  # 有数据 → 立即续读，快速排空日志突发
                # 无数据：顺带非阻塞收割僵尸（poll 返回退出码即完成 reap）
                if wi.proc is not None:
                    wi.proc.poll()
                await asyncio.sleep(0.4)
        except asyncio.CancelledError:
            pass
        finally:
            # 仅关闭本协程启动时持有的句柄（新一轮 spawn 可能已换新文件）
            if wi.log_file is f:
                self._close_log(wi)

    def _ingest_line(self, label: str, line: str):
        """处理 worker 日志行：JSON 信令 → 状态机；其余 → 透传日志。"""
        if not line:
            return
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            logger.info(f"[{label}] {line}")
            return
        self._handle_msg(label, msg)

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
        """定期检查 worker：死亡重启 + 挂死检测 + 心跳兜底。

        本循环是重启的唯一触发点：
        - 进程已退出（崩溃/被杀）→ 退避重启
        - 进程存活但 /health 连续失败 ≥ _PROBE_FAIL_LIMIT（事件循环挂死，
          即"进程活着但服务不了请求"）→ kill 后由死亡检测路径重启
        - 无 health_url 的 JSON 信令 worker → 心跳超时 kill
        """
        while self._running:
            await asyncio.sleep(5.0)
            now = time.time()
            for label, wi in list(self._workers.items()):
                if wi.status in ("stopped", "fatal") or wi.stop_requested:
                    continue
                if not wi.is_alive:
                    # 死亡（崩溃或被 kill）：标记并重启
                    wi.status = "dead"
                    logger.info(f"[Supervisor] {label} exited (pid={wi.proc.pid if wi.proc else '?'})")
                    # 退避可能长达 30s —— 用独立 task，避免阻塞本轮其余 worker 的检查
                    self._loop.create_task(self._restart(label))
                    continue
                if wi.health_url:
                    # plain 服务：进程存活 + HTTP 探针（探针在线程池执行，不阻塞循环）
                    ok = await self._loop.run_in_executor(None, _http_ok, wi.health_url, 2.0)
                    if ok:
                        if wi.probe_fails:
                            logger.info(f"[Supervisor] {label} health probe recovered")
                        wi.probe_fails = 0
                        if wi.status in ("starting", "dead"):
                            wi.status = "ready"
                            logger.info(f"[Supervisor] {label} is ready")
                    else:
                        wi.probe_fails += 1
                        if wi.probe_fails == 1:
                            logger.warning(f"[Supervisor] {label} health probe failed")
                        elif wi.probe_fails >= _PROBE_FAIL_LIMIT:
                            logger.error(
                                f"[Supervisor] {label} 疑似挂死（连续 {wi.probe_fails} 次探针失败），"
                                f"kill pid={wi.proc.pid} 触发重启")
                            wi.probe_fails = 0
                            wi.proc.kill()
                    continue
                elapsed = now - wi.last_heartbeat
                if elapsed > _DEAD_TIMEOUT:
                    logger.warning(f"[Supervisor] {label} heartbeat timeout ({elapsed:.0f}s), terminating")
                    wi.proc.kill()
                elif elapsed > _HEARTBEAT_TIMEOUT:
                    logger.warning(f"[Supervisor] {label} heartbeat overdue ({elapsed:.0f}s)")

    async def _restart(self, label: str):
        """重启 worker（指数退避）。退避期间若 supervisor 已停止则放弃。"""
        wi = self._workers[label]
        if wi.restart_count > wi.restart_limit:
            wi.status = "fatal"
            logger.error(f"[Supervisor] restart limit reached ({wi.restart_limit}), marking FATAL")
            return
        backoff = wi.backoff()
        logger.info(f"[Supervisor] restarting {label} in {backoff:.0f}s (attempt {wi.restart_count}/{wi.restart_limit})")
        await asyncio.sleep(backoff)
        if not self._running:
            return
        self._spawn(label)

    # ── 人工重启 / 管理端点（P1） ──────────────────────────────

    async def restart(self, label: str):
        """人工重启指定 worker：重置崩溃预算后重启，不占 restart_limit。

        进程存活时发 SIGTERM，进程退出后由监控循环的死亡检测触发 _restart；
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
        if not wi:
            return
        if wi.tail_task and not wi.tail_task.done():
            wi.tail_task.cancel()
        if not wi.is_alive:
            self._close_log(wi)
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
        self._close_log(wi)
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
                "probe_fails": wi.probe_fails,
                "alive": wi.is_alive,
            }
            for label, wi in self._workers.items()
        }
