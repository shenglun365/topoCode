"""
RemoteWriteQueue + RemoteCacheStore — 主进程端的同步远程代理

通过同步 ZMQ DEALER socket 将操作转发到 DB Service 进程。
所有方法签名与本地 WriteQueue 一致（sync）。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

import zmq

from config import DB_SERVICE_PORT, AGENT_WORKER_PORT

logger = logging.getLogger(__name__)

_DB_ADDR = f"tcp://127.0.0.1:{DB_SERVICE_PORT}"


def _get_trace_id() -> str:
    """读取当前请求的 trace_id（从 current_call_id contextvar）"""
    try:
        from zmq_server import current_call_id
        return current_call_id.get() or ""
    except Exception:
        return ""


class RemoteWriteQueue:
    """远程 WriteQueue — 同步 ZMQ DEALER → DB Service ROUTER"""

    def __init__(self):
        self._ctx = zmq.Context()
        self._addr = _DB_ADDR
        self._identity = f"wq-{uuid.uuid4().hex[:8]}"
        self._socket = self._ctx.socket(zmq.DEALER)
        self._socket.setsockopt_string(zmq.IDENTITY, self._identity)
        self._socket.connect(self._addr)
        logger.info(f"[RemoteWQ] connected to {self._addr}")

    def _reconnect(self):
        """断线后重建 socket"""
        try:
            self._socket.close(linger=0)
        except Exception:
            pass
        self._socket = self._ctx.socket(zmq.DEALER)
        self._socket.setsockopt_string(zmq.IDENTITY, self._identity)
        self._socket.connect(self._addr)
        logger.info(f"[RemoteWQ] reconnected to {self._addr}")

    def register_db(self, label: str, path: str):
        self._send("register_db", {"label": label, "path": path})

    def register_conn(self, label: str, conn):
        logger.warning(f"[RemoteWQ] register_conn ignored for {label}")

    def execute(self, label: str, sql: str, params: tuple = (), _commit: bool = True):
        self._send_async("execute", {"label": label, "sql": sql,
                                      "params": list(params), "commit": _commit})

    def execute_sync(self, label: str, sql: str, params: tuple = (),
                     _commit: bool = True, timeout: float = 30.0) -> dict:
        return self._send("execute_sync", {"label": label, "sql": sql,
                                            "params": list(params), "commit": _commit,
                                            "timeout": timeout},
                          timeout=timeout + 5.0)

    def execute_batch(self, label: str,
                      items: list[tuple[str, tuple, bool]]) -> list[dict]:
        result = self._send("execute_batch", {
            "label": label,
            "items": [{"sql": s, "params": list(p), "commit": c} for s, p, c in items],
        }, timeout=600.0)
        return result if isinstance(result, list) else [result]

    def shutdown(self, timeout: float = 5.0):
        try:
            self._socket.close(linger=0)
            self._ctx.term()
        except Exception:
            pass

    # ── 内部 ──────────────────────────────────────────────────────

    def _send(self, method: str, params: dict, timeout: float = 30.0) -> Any:
        """同步请求-响应（自动重连一次），携带 trace_id"""
        for attempt in range(2):
            request_id = uuid.uuid4().hex[:12]
            trace_id = _get_trace_id() or request_id
            try:
                self._socket.send_multipart([
                    b"db",
                    request_id.encode("utf-8"),
                    trace_id.encode("utf-8"),
                    method.encode("utf-8"),
                    json.dumps(params, default=str).encode("utf-8"),
                ])
                t0 = time.monotonic()
                poll = zmq.Poller()
                poll.register(self._socket, zmq.POLLIN)
                deadline = t0 + timeout
                while time.monotonic() < deadline:
                    socks = poll.poll(max(1, int((deadline - time.monotonic()) * 1000)))
                    if socks:
                        frames = self._socket.recv_multipart()
                        if len(frames) >= 2:
                            rid = frames[0].decode("utf-8")
                            if rid == request_id:
                                elapsed = (time.monotonic() - t0) * 1000
                                if elapsed > 500:
                                    logger.info(f"[RemoteWQ] {method} req={request_id[:8]} done in {elapsed:.0f}ms")
                                return json.loads(frames[1])
                logger.warning(f"[RemoteWQ] {method} req={request_id[:8]} timeout after {timeout}s")
                raise TimeoutError(f"[RemoteWQ] {method} timeout after {timeout}s")
            except (zmq.ZMQError, TimeoutError) as e:
                if attempt == 0:
                    logger.warning(f"[RemoteWQ] {method} req={request_id[:8]} {e}, reconnecting")
                    self._reconnect()
                    continue
                raise

    def _send_async(self, method: str, params: dict):
        """异步发送（fire-and-forget，不等待响应），携带 trace_id"""
        trace_id = _get_trace_id() or ""
        for attempt in range(2):
            try:
                self._socket.send_multipart([
                    b"db",
                    b"__fire__",
                    trace_id.encode("utf-8"),
                    method.encode("utf-8"),
                    json.dumps(params, default=str).encode("utf-8"),
                ], flags=zmq.NOBLOCK)
                return
            except zmq.Again:
                return
            except Exception as e:
                if attempt == 0:
                    logger.warning(f"[RemoteWQ] send_async error: {e}, reconnecting")
                    self._reconnect()
                    continue
                logger.warning(f"[RemoteWQ] send_async failed after reconnect: {e}")


class RemoteCacheStore:
    """远程 CacheStore 代理 — 通过 RemoteWriteQueue 转发"""

    def __init__(self, wq: RemoteWriteQueue):
        self._wq = wq

    def get(self, key: str, default: Any = None) -> Any:
        result = self._wq._send("cache_get", {"key": key, "default": default})
        return result.get("value", default)

    def set(self, key: str, value: Any, expire: Optional[int] = None):
        self._wq._send("cache_set", {"key": key, "value": value, "expire": expire})

    def delete(self, key: str):
        self._wq._send("cache_delete", {"key": key})

    def incr(self, key: str, delta: int = 1) -> int:
        result = self._wq._send("cache_incr", {"key": key, "delta": delta})
        return result.get("value", 0)


class RemoteAgentManager:
    """远程 Agent Worker 管理器 — 同步 ZMQ DEALER，自动重连"""

    def __init__(self):
        self._addr = f"tcp://127.0.0.1:{AGENT_WORKER_PORT}"
        self._ctx = zmq.Context()
        self._identity = f"agent-cli-{uuid.uuid4().hex[:8]}"
        self._socket = self._ctx.socket(zmq.DEALER)
        self._socket.setsockopt_string(zmq.IDENTITY, self._identity)
        self._socket.connect(self._addr)
        logger.info(f"[RemoteAgent] connected to {self._addr}")

    def _reconnect(self):
        try:
            self._socket.close(linger=0)
        except Exception:
            pass
        self._socket = self._ctx.socket(zmq.DEALER)
        self._socket.setsockopt_string(zmq.IDENTITY, self._identity)
        self._socket.connect(self._addr)
        logger.info(f"[RemoteAgent] reconnected to {self._addr}")

    def _send(self, action: str, params: dict, timeout: float = 60.0) -> Any:
        """同步请求-响应（自动重连一次），携带 trace_id"""
        for attempt in range(2):
            request_id = uuid.uuid4().hex[:12]
            trace_id = _get_trace_id() or request_id
            try:
                self._socket.send_multipart([
                    b"main",
                    request_id.encode("utf-8"),
                    trace_id.encode("utf-8"),
                    action.encode("utf-8"),
                    json.dumps(params, default=str).encode("utf-8"),
                ])
                t0 = time.monotonic()
                poll = zmq.Poller()
                poll.register(self._socket, zmq.POLLIN)
                deadline = t0 + timeout
                while time.monotonic() < deadline:
                    socks = poll.poll(max(1, int((deadline - time.monotonic()) * 1000)))
                    if socks:
                        frames = self._socket.recv_multipart()
                        if len(frames) >= 2:
                            rid = frames[0].decode("utf-8")
                            if rid == request_id:
                                elapsed = (time.monotonic() - t0) * 1000
                                if elapsed > 500:
                                    logger.info(f"[RemoteAgent] {action} req={request_id[:8]} done in {elapsed:.0f}ms")
                                return json.loads(frames[1])
                logger.warning(f"[RemoteAgent] {action} req={request_id[:8]} timeout after {timeout}s")
                raise TimeoutError(f"[RemoteAgent] {action} timeout after {timeout}s")
            except (zmq.ZMQError, TimeoutError) as e:
                if attempt == 0:
                    logger.warning(f"[RemoteAgent] {action} req={request_id[:8]} {e}, reconnecting")
                    self._reconnect()
                    continue
                raise

    # ── 公开 API ──────────────────────────────────────────────────

    def dispatch(self, route: str, task_id: str, context: dict,
                 project_id: str = "", project_root: str = "",
                 project_summary: str = "", **extra) -> dict:
        """发送 dispatch 请求到 Agent Worker"""
        payload = {
            "route": route, "task_id": task_id, "context": context,
            "project_id": project_id, "project_root": project_root,
            "project_summary": project_summary,
        }
        payload.update(extra)
        return self._send("dispatch", payload, timeout=30.0)

    def get_progress(self, agent_id: str) -> dict:
        return self._send("get_progress", {"agent_id": agent_id}, timeout=10.0)

    def cancel(self, agent_id: str) -> dict:
        return self._send("cancel", {"agent_id": agent_id}, timeout=10.0)

    def get_history(self, task_id: str, offset: int = 0, limit: int = 10) -> dict:
        return self._send("get_history", {"task_id": task_id, "offset": offset, "limit": limit}, timeout=10.0)

    def clear_history(self, project_id: str, task_id: str) -> dict:
        return self._send("clear_history", {"project_id": project_id, "task_id": task_id}, timeout=10.0)

    def list_running_tasks(self) -> list[dict]:
        """返回 Agent Worker 中的运行中任务列表"""
        result = self._send("list_running", {}, timeout=10.0)
        return result.get("tasks", [])

    def start_presummary_chain(self, task_id: str, project_id: str, batches: list[str],
                                limit: int = 0, subagent_concurrency: int = 1,
                                project_root: str = "", project_summary: str = "") -> dict:
        return self._send("presummary_chain", {
            "task_id": task_id, "project_id": project_id, "batches": batches,
            "limit": limit, "subagent_concurrency": subagent_concurrency,
            "project_root": project_root, "project_summary": project_summary,
        }, timeout=30.0)
