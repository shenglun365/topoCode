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
  text            流式 token 片段(TurnAdapter 逐段 emit, 泵原生承载)

流式 kind(cline sidecar v2 接线):
  tool            工具调用开始/结束(text="▶ name"/"✓ name", 携 toolName)
  usage           token/成本增量(携 inputTokens/outputTokens/cost)
  notice          SDK 通知(mistake_limit/压缩等, 携 reason)
  turn_outcome    协议工具结局(携 status: done|need_input)
  approval_request 工具审批请求(携 requestId/toolName/toolInput, 越界确认桥)
  team            团队协作进度(cline teams, 携 teamName/lifecycle)
  mcp             MCP 注入结果(携 server/ok/tools/message)
"""
from __future__ import annotations

import time
from enum import Enum
from typing import Any, Dict

_TEXT_LIMIT = 20000          # 单事件文本截断(与既有 emit 行为一致)
_KINDS = (
    "session_ready", "user_input", "input_required", "done", "failed",
    "progress", "aborted", "finished", "text",
    "tool", "usage", "notice", "turn_outcome", "approval_request",
    "team", "mcp",
    "verify",   # V1 程序化验收门禁: done 后实测验证矩阵(环节级判定+原因码)
    "turn_done",  # cv-267 对话回合制: chat 角色无标记正常收束(非终态, 作业保活)
)

# A6.1 反向请求(ServerRequest)类型契约——runner → 宿主(architect) 需应答的事件:
#   approval_request  宿主必须经 /approval 端点应答(requestId, approved, reason)
#   input_required    宿主必须经 /input 转达用户回复(或显式跳过)
# done/failed 为终态通知(非请求), K2 结构化回执的载体。
SERVER_REQUEST_TYPES = ("approval_request", "input_required")
TURN_COMPLETED_KINDS = ("done", "failed")


def is_server_request(kind: str) -> bool:
    return kind in SERVER_REQUEST_TYPES


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
    TOOL = "tool"
    USAGE = "usage"
    NOTICE = "notice"
    TURN_OUTCOME = "turn_outcome"
    APPROVAL_REQUEST = "approval_request"
    TEAM = "team"
    MCP = "mcp"
    VERIFY = "verify"

    @classmethod
    def all(cls) -> tuple:
        return _KINDS


def is_valid_kind(kind: str) -> bool:
    return kind in _KINDS


def schema_snapshot() -> Dict[str, Any]:
    """事件契约快照(R2 契约门禁; rpc-method-baseline 同模式)。

    输出当前 schema 全量事实, 确定性可序列化(禁时间戳等易变值), 供
    runner 侧基线比对与 architect 侧消费测试共同守护。基线文件:
    packages/core/runner-events-baseline.json(生成: scripts/runner-events-baseline.py)。
    """
    constants = {name: value for name, value in sorted(vars(EventKind).items())
                 if not name.startswith("_") and isinstance(value, str)}
    return {
        "kindCount": len(_KINDS),
        "kinds": list(_KINDS),                       # 顺序即契约: 只许尾部追加
        "eventKindConstants": constants,             # EventKind 常量 ↔ _KINDS 一致性由测试锁定
        "eventBaseShape": ["seq", "ts", "kind", "text"],
        "textLimit": _TEXT_LIMIT,
        "bus": {"maxEvents": EventBus.MAX_EVENTS, "queueSize": EventBus.QUEUE_SIZE},
        "parsePolicy": {"requireDict": True, "requireSeqIntable": True,
                        "unknownKindTolerant": True},  # 老 runner 新 kind 向后兼容
        # A6.1: 反向请求类型契约(宿主应答制) + 终态通知映射
        "serverRequestTypes": list(SERVER_REQUEST_TYPES),
        "turnCompletedKinds": list(TURN_COMPLETED_KINDS),
    }


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

    # cv-176: 800 只够看尾段——失败任务(120 迭代)前半程证据全丢, 排障瞎子摸象
    MAX_EVENTS = 4000
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
