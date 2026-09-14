"""进程内事件总线(job 消息实时推送)。

exec_bridge 等后端写入会话消息 → publish → SSE(/events)fan-out → 前端
EventSource 收到后刷新当前会话信息流(主会话实时显示 coding 子会话内容,
无需手动刷新)。线程安全: publish 可从任意线程调用(call_soon_threadsafe)。
"""
import asyncio
import logging
from typing import Set

logger = logging.getLogger("arch.ws_events")

_queues: Set["asyncio.Queue[dict]"] = set()
_loop: asyncio.AbstractEventLoop = None  # type: ignore[assignment]


def bind_loop() -> None:
    """绑定当前事件循环(应用启动时调用)。"""
    global _loop
    _loop = asyncio.get_running_loop()


def subscribe() -> "asyncio.Queue[dict]":
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _queues.add(q)
    return q


def unsubscribe(q: "asyncio.Queue[dict]") -> None:
    _queues.discard(q)


def publish(event: dict) -> None:
    """广播事件到全部订阅者(满队列丢弃——SSE 客户端重拉兜底)。"""
    if _loop is None:
        return

    def _fan() -> None:
        for q in list(_queues):
            try:
                q.put_nowait(event)
            except Exception:  # noqa: BLE001
                pass

    try:
        _loop.call_soon_threadsafe(_fan)
    except RuntimeError:  # loop 已关(停机)
        pass
