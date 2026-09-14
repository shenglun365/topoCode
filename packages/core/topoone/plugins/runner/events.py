"""JobEvent — runner 实施作业事件 schema(单一事实源)。

P3 schema 化: 事件形状 {seq, ts, kind, text, **extra} 由本模块单源定义,
implement.emit / WS 订阅面 / snapshot / architect 泵 共同消费。
契约纪律(只增不改): 既有字段形状冻结; 新增 kind/extra 字段向后兼容。

kind 语义(回合级粒度):
  session_ready   执行器会话就绪(start 成功)
  user_input      用户输入入队/下达
  input_required  回合结束等待输入([[NEED_INPUT]] 或无标记兜底)
  done            交付完成([[IMPLEMENT_DONE]], 携 changedFiles)
  failed          回合/通道失败(看门狗中止/异常, 携 error 文本)
  progress        执行进展(toolCount/msgCount 计数, 不落会话消息)
  aborted         回合中止(用户/看门狗)
  finished        作业收尾(finish, 保 worktree)
  text            流式 token 片段(预留: TurnAdapter 逐段 emit, 泵原生承载)
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict

_TEXT_LIMIT = 20000          # 单事件文本截断(与既有 emit 行为一致)
_KINDS = (
    "session_ready", "user_input", "input_required", "done", "failed",
    "progress", "aborted", "finished", "text",
)


class EventKind:
    """事件类型常量(字符串单源; 用 plain str 便于 JSON 直传与存量比较)。"""
    SESSION_READY = "session_ready"
    USER_INPUT = "user_input"
    INPUT_REQUIRED = "input_required"
    DONE = "done"
    FAILED = "failed"
    PROGRESS = "progress"
    ABORTED = "aborted"
    FINISHED = "finished"
    TEXT = "text"

    @classmethod
    def all(cls) -> tuple:
        return _KINDS


def is_valid_kind(kind: str) -> bool:
    return kind in _KINDS


def make_event(seq: int, kind: str, text: str = "", **extra: Any) -> Dict[str, Any]:
    """构造事件 dict(形状单源)。kind 非法抛 ValueError——编程错误即时暴露。"""
    if not is_valid_kind(kind):
        raise ValueError(f"unknown event kind: {kind!r} (valid: {_KINDS})")
    ev: Dict[str, Any] = {"seq": int(seq), "ts": int(time.time() * 1000),
                          "kind": kind, "text": (text or "")[:_TEXT_LIMIT]}
    ev.update(extra)
    return ev


def parse_event(raw: Dict[str, Any]) -> Dict[str, Any]:
    """校验/归一外部事件(architect 泵消费面): 形状合法原样返回, 非法抛 ValueError。

    宽容策略: kind 未收录但带 seq/text 的dict 不拒(向后兼容——老 runner 新 kind),
    仅要求 seq 可整型化。
    """
    if not isinstance(raw, dict):
        raise ValueError(f"event not a dict: {type(raw).__name__}")
    seq = int(raw.get("seq") or 0)
    return raw


class EventBus:
    """事件环 + 实时扇出(自 ImplementJob 内联逻辑抽出, 行为保真)。

    - 环容量 _MAX_EVENTS(超出丢最旧; 订阅端有 snapshot 兜底校准)
    - 订阅队列满 256, 满队列丢最旧(非阻塞扇出)
    """

    MAX_EVENTS = 800
    QUEUE_SIZE = 256

    def __init__(self):
        self.seq = 0
        self.events: list = []
        self._subscribers: list = []   # asyncio.Queue 集合

    def emit(self, kind: str, text: str = "", **extra: Any) -> int:
        self.seq += 1
        ev = make_event(self.seq, kind, text, **extra)
        self.events.append(ev)
        if len(self.events) > self.MAX_EVENTS:
            self.events = self.events[-self.MAX_EVENTS:]
        for q in list(self._subscribers):
            try:
                if q.full():
                    q.get_nowait()
                q.put_nowait(ev)
            except Exception:  # noqa: BLE001
                pass
        return ev["seq"]

    def since(self, seq: int = 0) -> list:
        return [e for e in self.events if e["seq"] > seq]

    def subscribe(self):
        q: asyncio_Queue = _new_queue(self.QUEUE_SIZE)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass


def _new_queue(maxsize: int):
    import asyncio
    return asyncio.Queue(maxsize=maxsize)


asyncio_Queue = Any   # 类型别名(避免模块级 asyncio 依赖; 仅注解用)
