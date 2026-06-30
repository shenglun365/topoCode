"""
MessageBus — 模块间消息总线

Phase 1: 单进程内存总线，模块通过 subject 发布/订阅消息。
Phase 2+: 底层可切换为 ZMQ 跨进程总线，接口不变。

使用方式:
    bus = MessageBus()
    bus.subscribe("task.complete", my_handler)
    bus.publish("task.complete", {"taskId": "xxx", "status": "done"})
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

HandlerFn = Callable[..., Coroutine[Any, Any, None] | None]


class MessageBus:
    def __init__(self):
        self._subscribers: dict[str, list[HandlerFn]] = {}
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── 生命周期 ────────────────────────────────────────────────────

    def start(self):
        self._loop = asyncio.get_running_loop()

    # ── 订阅/取消 ──────────────────────────────────────────────────

    def subscribe(self, subject: str, handler: HandlerFn):
        """订阅主题。handler 接收 (subject, data) 参数。"""
        self._subscribers.setdefault(subject, []).append(handler)
        logger.debug(f"[Bus] subscribe: {subject}")

    def unsubscribe(self, subject: str, handler: HandlerFn):
        handlers = self._subscribers.get(subject, [])
        if handler in handlers:
            handlers.remove(handler)
            logger.debug(f"[Bus] unsubscribe: {subject}")

    # ── 发布 ────────────────────────────────────────────────────────

    def publish(self, subject: str, data: dict):
        """
        发布消息到指定主题。
        同步调用：在 Phase 1 是线程安全的（asyncio.run_coroutine_threadsafe）。
        """
        handlers = self._subscribers.get(subject, []) + self._subscribers.get("*", [])
        if not handlers:
            return
        loop = self._loop or asyncio.get_event_loop()
        for handler in handlers:
            try:
                r = handler(subject, data)
                if asyncio.iscoroutine(r):
                    asyncio.run_coroutine_threadsafe(r, loop)
            except Exception as e:
                logger.warning(f"[Bus] handler error for {subject}: {e}")

    # ── 请求-响应（Phase 2+ 使用） ─────────────────────────────────

    async def request(self, target: str, method: str, params: dict,
                      timeout: float = 30.0) -> dict:
        """
        向指定模块发送请求并等待响应。
        Phase 1 中直接调用注册的模块方法（内存调用）。
        Phase 2+ 改为 ZMQ 请求。
        """
        subject = f"{target}.{method}"
        handlers = self._subscribers.get(subject, [])
        if not handlers:
            raise TimeoutError(f"No handler for {subject}")
        handler = handlers[0]
        result = handler(subject, params)
        if asyncio.iscoroutine(result):
            result = await asyncio.wait_for(result, timeout=timeout)
        return result if result is not None else {}
