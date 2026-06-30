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
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

_HEARTBEAT_TIMEOUT = 15.0   # 秒，超过此时间未收到心跳判定为可疑
_DEAD_TIMEOUT = 30.0        # 秒，超过此时间判定为死亡
_READY_TIMEOUT = 30.0       # 秒，启动后等待 ready 的最长时间


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

    @property
    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def backoff(self) -> float:
        """指数退避等待时间（秒）"""
        return min(2.0 ** (self.restart_count - 1), 30.0)


class Supervisor:
    """子进程监督者"""

    def __init__(self):
        self._workers: dict[str, WorkerInfo] = {}
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._monitor_task: Optional[asyncio.Task] = None

    # ── 注册 ────────────────────────────────────────────────────

    def register(self, label: str, args: list[str], restart_limit: int = 3):
        """注册一个受管理的子进程"""
        self._workers[label] = WorkerInfo(label=label, args=args, restart_limit=restart_limit)
        logger.info(f"[Supervisor] registered: {label}")

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
                await asyncio.wait_for(wi.ready_event.wait(), timeout=_READY_TIMEOUT)
                logger.info(f"[Supervisor] {label} is ready")
            except asyncio.TimeoutError:
                logger.warning(f"[Supervisor] {label} not ready within {_READY_TIMEOUT}s")

        # 启动监控协程
        self._monitor_task = self._loop.create_task(self._monitor_loop())

    def _spawn(self, label: str):
        """启动一个 worker 进程"""
        wi = self._workers[label]
        if wi.proc and wi.is_alive:
            return
        wi.status = "starting"
        wi.restart_count += 1
        wi.ready_event.clear()
        try:
            proc = subprocess.Popen(
                wi.args,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                env={**os.environ, "TOPO_MODE": os.environ.get("TOPO_MODE", "distributed")},
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
        """定期检查 worker 心跳"""
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
