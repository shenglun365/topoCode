"""
TransportLayer — 进程间通信抽象

Phase 1: InMemoryTransport (即 MessageBus，同步调用)
Phase 2: ZmqTransport (ZMQ ROUTER/DEALER，跨进程)

monolith 模式使用 InMemoryTransport
distributed 模式使用 ZmqTransport
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, Callable

import zmq
import zmq.asyncio

logger = logging.getLogger(__name__)

_TIMEOUT = 30.0

HandlerFn = Callable[[str, dict], Any]


class TransportLayer(ABC):
    """通信层抽象 — 所有 IPC 行为通过此接口"""

    @abstractmethod
    async def request(self, target: str, method: str, params: dict,
                      timeout: float = _TIMEOUT) -> dict:
        ...

    @abstractmethod
    def publish(self, subject: str, data: dict):
        ...

    @abstractmethod
    def subscribe(self, subject: str, handler: HandlerFn):
        ...

    @abstractmethod
    def start(self):
        ...

    @abstractmethod
    async def stop(self):
        ...


# ═══════════════════════════════════════════════════════════════
# 单进程模式 (InMemoryTransport)
# ═══════════════════════════════════════════════════════════════

class InMemoryTransport(TransportLayer):
    """单进程通信 — 直接函数调用，无序列化开销"""

    def __init__(self):
        self._handlers: dict[str, list[HandlerFn]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self):
        self._loop = asyncio.get_running_loop()

    async def stop(self):
        self._handlers.clear()

    def subscribe(self, subject: str, handler: HandlerFn):
        self._handlers.setdefault(subject, []).append(handler)

    def publish(self, subject: str, data: dict):
        for handler in self._handlers.get(subject, []):
            try:
                r = handler(subject, data)
                if asyncio.iscoroutine(r):
                    if self._loop:
                        asyncio.run_coroutine_threadsafe(r, self._loop)
            except Exception as e:
                logger.warning(f"[InMemoryTransport] handler error {subject}: {e}")

    async def request(self, target: str, method: str, params: dict,
                      timeout: float = _TIMEOUT) -> dict:
        subject = f"{target}.{method}"
        handlers = self._handlers.get(subject, [])
        if not handlers:
            raise TimeoutError(f"No handler for {subject}")
        handler = handlers[0]
        result = handler(subject, params)
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=timeout)
        return result if result is not None else {}


# ═══════════════════════════════════════════════════════════════
# 多进程模式 (ZmqTransport)
# ═══════════════════════════════════════════════════════════════

class ZmqTransport(TransportLayer):
    """跨进程 ZMQ 通信 — ROUTER/DEALER 模式"""

    def __init__(self, connect_addr: str, identity: str = ""):
        self._addr = connect_addr
        self._identity = identity or f"cli-{uuid.uuid4().hex[:8]}"
        self._context: zmq.asyncio.Context | None = None
        self._socket: zmq.asyncio.Socket | None = None
        self._pending: dict[str, asyncio.Future] = {}
        self._recv_task: asyncio.Task | None = None
        self._sub_handlers: dict[str, list[HandlerFn]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self):
        self._loop = asyncio.get_running_loop()
        self._context = zmq.asyncio.Context()
        self._socket = self._context.socket(zmq.DEALER)
        self._socket.setsockopt_string(zmq.IDENTITY, self._identity)
        self._socket.connect(self._addr)
        self._recv_task = self._loop.create_task(self._recv_loop())
        logger.info(f"[ZmqTransport] connected to {self._addr} as {self._identity}")

    async def stop(self):
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self._socket:
            self._socket.close(linger=0)
            self._socket = None
        if self._context:
            self._context.term()
            self._context = None

    def subscribe(self, subject: str, handler: HandlerFn):
        self._sub_handlers.setdefault(subject, []).append(handler)

    def publish(self, subject: str, data: dict):
        if not self._socket:
            return
        try:
            self._socket.send_multipart([
                b"__pub__",
                subject.encode("utf-8"),
                json.dumps(data, default=str).encode("utf-8"),
            ], flags=zmq.NOBLOCK)
        except zmq.Again:
            pass
        except Exception as e:
            logger.debug(f"[ZmqTransport] publish error: {e}")

    async def request(self, target: str, method: str, params: dict,
                      timeout: float = _TIMEOUT) -> dict:
        if not self._socket:
            raise RuntimeError("ZmqTransport not started")
        request_id = uuid.uuid4().hex[:12]
        future = self._loop.create_future()
        self._pending[request_id] = future
        try:
            await self._socket.send_multipart([
                target.encode("utf-8"),
                request_id.encode("utf-8"),
                method.encode("utf-8"),
                json.dumps(params, default=str).encode("utf-8"),
            ])
            return await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise TimeoutError(f"[ZmqTransport] request {target}.{method} timeout after {timeout}s")
        except Exception as e:
            self._pending.pop(request_id, None)
            raise

    async def _recv_loop(self):
        """接收响应和推送消息"""
        while True:
            try:
                frames = await self._socket.recv_multipart()
            except asyncio.CancelledError:
                break
            except Exception:
                continue
            if not frames:
                continue
            # 推送消息: [b"__pub__", subject, data_json]
            if frames[0] == b"__pub__":
                subject = frames[1].decode("utf-8")
                data = json.loads(frames[2]) if len(frames) > 2 else {}
                for handler in self._sub_handlers.get(subject, []):
                    try:
                        r = handler(subject, data)
                        if asyncio.iscoroutine(r):
                            self._loop.create_task(r)
                    except Exception as e:
                        logger.warning(f"[ZmqTransport] sub handler error: {e}")
                continue
            # 响应: [request_id, result_json]
            if len(frames) >= 2:
                request_id = frames[0].decode("utf-8")
                result = json.loads(frames[1])
                future = self._pending.pop(request_id, None)
                if future and not future.done():
                    future.set_result(result)
