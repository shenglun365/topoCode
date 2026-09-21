"""进程内事件总线(job 消息实时推送)。

exec_bridge 等后端写入会话消息 → publish → SSE(/events)fan-out → 前端
EventSource 收到后刷新当前会话信息流(主会话实时显示 coding 子会话内容,
无需手动刷新)。线程安全: publish 可从任意线程调用(call_soon_threadsafe)。
"""
import asyncio
import collections
import logging
from typing import Set

logger = logging.getLogger("arch.ws_events")

_queues: Set["asyncio.Queue[dict]"] = set()
_loop: asyncio.AbstractEventLoop = None  # type: ignore[assignment]


def bind_loop() -> None:
    """绑定当前事件循环(应用启动时调用)。"""
    global _loop
    _loop = asyncio.get_running_loop()
    logger.info("[sse] loop bound, queues=%d", len(_queues))


def subscribe() -> "asyncio.Queue[dict]":
    q: asyncio.Queue = asyncio.Queue(maxsize=64)
    _queues.add(q)
    logger.info("[sse] subscribe queues=%d", len(_queues))
    return q


def unsubscribe(q: "asyncio.Queue[dict]") -> None:
    _queues.discard(q)
    logger.info("[sse] unsubscribe queues=%d", len(_queues))


def publish(event: dict) -> None:
    """广播事件到全部订阅者(满队列丢弃——SSE 客户端重拉兜底)。"""
    if _loop is None:
        logger.warning("[sse] publish dropped(loop unbound): %s", event.get("type"))
        return
    if not _queues:
        # cv-205 诊断: 事件无人接收(前端 SSE 未挂/被网关断开)——落卡不可见的
        # 根因定位口(实证: keep-alive 到达而 conv-message 为零)
        logger.warning("[sse] publish dropped(no subscriber): type=%s conv=%s",
                       event.get("type"), event.get("conversationId"))

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


# ── B: 统一事件出口(类型化 emit + 审计环) ─────────────────────────────
# 事件类型常量(单点 schema): conv-message/task/progress 三类对外事件。
EV_CONV_MESSAGE = "conv-message"
EV_TASK = "task"
EV_PROGRESS = "progress"

_recent: "collections.deque[dict]" = collections.deque(maxlen=200)


def emit(ev_type: str, conversation_id: str, **payload) -> dict:
    """统一事件出口: 形状单点 {type, conversationId, **payload} + 最近 200 条留痕。

    新事件一律走 emit; 禁止再散布裸 publish(dict)——审计/测试/订阅方
    依赖稳定形状。线程安全同 publish。
    ev_type ∈ EV_CONV_MESSAGE/EV_TASK/EV_PROGRESS(payload 键名可与 ev_type 重名)。"""
    event = {"type": ev_type, "conversationId": conversation_id, **payload}
    _recent.append(event)
    publish(event)
    return event


def recent_events(limit: int = 50) -> list:
    """最近事件(审计/调试); 新→旧。"""
    out = list(_recent)[-limit:]
    out.reverse()
    return out
