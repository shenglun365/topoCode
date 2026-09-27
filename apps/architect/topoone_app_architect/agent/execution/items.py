"""A6.2 Item 投影 — runner/architect 事件 → item 级稳定原语(开放注册制)。

裁决(2026-09-17): 方案 A 全量投影 + **不局限于四类**——item 类型注册制,
按需拓展(register_item_type); 未知 kind 不丢信息, 落 `event` 透传 item。
前端一次性替换: 会话流只按 item 渲染(UI 守门: 禁 executorType/meta.kind
分支渲染; 执行器特有能力经 B1 能力矩阵开关)。

item 形状(codex Thread/Turn/Item 参照):
  {type, id, ts, seq?, status?, text?, payload{}} — 纯 JSON, 稳定键。
投影语义:
  - runner JobEvent(packages/core plugins/runner/events.py 单一事实源)为主输入;
  - architect 侧事件(计划卡/推理流)以合成事件注册(同 registry, 无特权);
  - 一个事件可产出多个 item(如 done → turn_completed + file_change);
  - 进度计数类(progress/usage/team/mcp)不产 item(属进度条域, 防刷屏)。
反向桥 `as_legacy_events`: item → 存量事件形状, 存量消费方(卡片落库/units
沉淀/SSE)不感知投影层存在(零协议破坏)。

分层: 纯函数, 零 IO, 零 arch_routes 依赖(R1/R2 干净); conformance kit
(adapter_conformance)对本模块映射语义逐项断言。
"""
from __future__ import annotations

import hashlib
import time
from typing import Any, Callable, Dict, List, Optional

# 注册表: item type → {from_kinds, project}。开放词汇——新类型注册即生效,
# 禁止在任何消费方写 `if item["type"] == ...` 的封闭分支以外的新硬编码类型表。
_REGISTRY: Dict[str, Dict[str, Any]] = {}


def register_item_type(item_type: str, from_kinds: tuple,
                       project: Callable[[dict], List[dict]]) -> None:
    """注册 item 类型(只追加; 重复注册 = 开发错误)。

    from_kinds: 触发事件 kind 集合(声明性, 供 conformance 覆盖率检查);
    project: 事件 → item 列表(就地构造, 返回 []表示该事件此类型不产出)。
    """
    if item_type in _REGISTRY:
        raise RuntimeError(f"item 类型重复注册: {item_type}")
    _REGISTRY[item_type] = {"from_kinds": tuple(from_kinds), "project": project}


def item_types() -> Dict[str, Dict[str, Any]]:
    return {k: dict(v) for k, v in _REGISTRY.items()}


def _item_id(ev: dict, type_: str) -> str:
    raw = f"{type_}|{ev.get('seq') or ''}|{ev.get('ts') or ''}|{(ev.get('text') or '')[:80]}"
    return "it-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def _base(type_: str, ev: dict, **kw) -> dict:
    it = {"type": type_, "id": _item_id(ev, type_),
          "ts": int(ev.get("ts") or time.time() * 1000)}
    if ev.get("seq") is not None:
        it["seq"] = ev["seq"]
    it.update(kw)
    return it


# ── 内置投影器(批次 5 起步词汇; 新类型 register_item_type 按需拓展) ──

def _status_of_tool_text(text: str) -> str:
    if text.startswith("✓"):
        return "ok"
    if text.startswith("✗") or text.startswith("❌"):
        return "error"
    return "running"          # ▶ 或无标记


def _project_tool_call(ev: dict) -> List[dict]:
    return [_base("tool_call", ev, status=_status_of_tool_text(ev.get("text") or ""),
                  tool=str(ev.get("toolName") or ""),
                  text=(ev.get("text") or "").lstrip("▶✓✗❌ ").strip()[:2000])]


def _project_file_change(ev: dict) -> List[dict]:
    files = [str(f) for f in (ev.get("changedFiles") or [])]
    if not files:
        return []
    return [_base("file_change", ev, status="ok",
                  payload={"files": files[:50]})]


def _project_approval(ev: dict) -> List[dict]:
    return [_base("approval", ev, status="pending",
                  tool=str(ev.get("toolName") or ""),
                  payload={"requestId": str(ev.get("requestId") or ""),
                           "toolInput": ev.get("toolInput") or {}})]


def _project_verify(ev: dict) -> List[dict]:
    stages = {}
    for s in ("build", "test"):
        r = ev.get(s)
        if r:
            stages[s] = {"verdict": r.get("verdict"), "reason": r.get("reason") or ""}
    return [_base("verify", ev, status=str(ev.get("overall") or "?"),
                  payload={"stages": stages, "text": (ev.get("text") or "")[:400]})]


def _project_turn_completed(ev: dict) -> List[dict]:
    ok = ev.get("kind") == "done"
    return [_base("turn_completed", ev,
                  status="done" if ok else "failed",
                  text=(ev.get("text") or "")[:4000])]


def _project_task_input(ev: dict) -> List[dict]:
    return [_base("task_input", ev, status="waiting",
                  text=(ev.get("text") or "").replace("[[NEED_INPUT]]", "").strip()[:4000])]


def _project_notice(ev: dict) -> List[dict]:
    return [_base("notice", ev, text=(ev.get("text") or "")[:500],
                  payload={"reason": str(ev.get("reason") or "")})]


def _project_reasoning(ev: dict) -> List[dict]:
    return [_base("reasoning", ev, text=(ev.get("text") or ev.get("delta") or "")[:2000])]


def _project_plan(ev: dict) -> List[dict]:
    steps = ev.get("steps") or []
    return [_base("plan", ev,
                  status=str(ev.get("planStatus") or "proposed"),
                  payload={"steps": steps,
                           "blocked": ev.get("blocked") or ""})]


# 注册表装配(声明 from_kinds 供 conformance 覆盖检查)
register_item_type("tool_call", ("tool",), _project_tool_call)
register_item_type("file_change", ("done",), _project_file_change)
register_item_type("approval", ("approval_request",), _project_approval)
register_item_type("verify", ("verify",), _project_verify)
register_item_type("turn_completed", ("done", "failed"), _project_turn_completed)
register_item_type("task_input", ("input_required",), _project_task_input)
register_item_type("notice", ("notice",), _project_notice)
register_item_type("reasoning", ("reasoning",), _project_reasoning)      # architect 合成
register_item_type("plan", ("plan",), _project_plan)                     # architect 合成
# 卡片域合成类型(不产自 runner 事件流, 供 item_from_card 统一词汇)
register_item_type("task_status", ("task_status",),
                   lambda ev: [_base("task_status", ev,
                                     status=str(ev.get("status") or ""),
                                     text=(ev.get("text") or "")[:500])])
register_item_type("turn_error", ("turn_error",),
                   lambda ev: [_base("turn_error", ev, status="error",
                                     text=(ev.get("text") or "")[:2000])])
register_item_type("digest", ("digest",),
                   lambda ev: [_base("digest", ev, text=(ev.get("text") or "")[:500])])
register_item_type("spec", ("spec",),
                   lambda ev: [_base("spec", ev,
                                     status=str(ev.get("status") or ""),
                                     text=(ev.get("text") or "")[:500])])

# 不产 item 的计数/进度域(进度条消费, 防刷屏)——声明性黑名单
NON_ITEM_KINDS = ("progress", "usage", "team", "mcp", "session_ready",
                  "user_input", "turn_outcome", "text", "aborted", "finished")

# 落库/独立 SSE 的流类型: 今日「不落会话消息」的事件投影(工具轨迹/文件变更/
# 通知)。其余类型(approval/verify/task_input/turn_completed 等)既有落消息路径
# 不变——经 GET /messages 的 item_from_card 投影渲染, 避免双源双渲染。
STREAM_PERSIST_TYPES = ("tool_call", "file_change", "notice")


# ── 卡片 → item(会话消息读侧投影; 前端零 meta.kind 分支的依据) ──────

# meta.kind → (item.type, 覆盖字段); 未列出 = 非卡片消息(纯 markdown)
CARD_ITEM_MAP: Dict[str, Dict[str, Any]] = {
    "task_card": {"type": "task", "payload": "meta"},
    "task_status": {"type": "task_status", "payload": "meta"},   # cv-203 状态卡
    "task_start": {"type": "task_status", "status": "running"},
    "task_approval_done": {"type": "task_status", "status": "approved"},
    "task_done": {"type": "turn_completed", "status": "done"},
    "task_failed": {"type": "turn_completed", "status": "failed"},
    "task_input": {"type": "task_input", "status": "waiting"},
    "task_input_echo": {"type": "task_input", "status": "echo"},
    "task_approval": {"type": "approval", "status": "pending"},
    "task_verify": {"type": "verify", "payload": "meta"},
    "turnError": {"type": "turn_error", "status": "error"},
    "taskPlan": {"type": "plan", "payload": "meta"},
    "taskPlanDone": {"type": "plan", "status": "done", "payload": "meta"},
    "digest_sent": {"type": "digest"},
    "specCreated": {"type": "spec", "status": "created", "payload": "meta"},
    "specReady": {"type": "spec", "status": "ready", "payload": "meta"},
    "choices": {"type": "choices", "payload": "meta"},   # cv-247 问询卡
    "proxy": {"type": "job", "payload": "meta"},   # cv-283 直通作业卡(仅 jobCard=1 渲染 JobCard, 其余文本回执)
}


def item_from_card(meta: Optional[dict], text: str = "",
                   ts: Any = None, msg_id: str = "") -> Optional[dict]:
    """会话卡片消息 → item(读侧投影; 纯函数)。非卡片返回 None。

    meta 携带的结构化字段(taskId/requestId/steps/branch...)进入 payload——
    前端 ItemCard 只吃 item, 不再读 meta.kind(守门规则)。
    """
    kind = str((meta or {}).get("kind") or "")
    spec_ = CARD_ITEM_MAP.get(kind)
    if not spec_:
        return None
    it_: Dict[str, Any] = {"type": spec_["type"], "id": msg_id or _item_id(
        {"text": text, "ts": ts}, spec_["type"])}
    it_["ts"] = int(ts or time.time() * 1000)
    if spec_.get("status"):
        it_["status"] = spec_["status"]
    it_["text"] = (text or "")[:4000]
    payload: Dict[str, Any] = {}
    if spec_.get("payload") == "meta":
        payload = {k: v for k, v in (meta or {}).items() if k != "kind"}
    for k in ("taskId", "requestId", "branch", "approvalRequestId",
              "approvalJobId", "delivery", "reason"):
        if (meta or {}).get(k) and k not in payload:
            payload[k] = meta[k]
    if payload:
        it_["payload"] = payload
    return it_


def project_event(ev: dict) -> List[dict]:
    """事件 → item 列表(注册类型按 from_kinds 命中; 未注册 kind → event 透传)。"""
    kind = str(ev.get("kind") or "")
    if not kind or kind in NON_ITEM_KINDS:
        return []
    out: List[dict] = []
    for t, spec in _REGISTRY.items():
        if kind in spec["from_kinds"]:
            out.extend(spec["project"](ev))
    if out:
        return out
    # 开放拓展兜底: 未注册事件不丢信息 → event 透传 item(前端通用卡渲染)
    return [_base("event", ev, kind=kind, text=(ev.get("text") or "")[:2000],
                  payload={k: v for k, v in ev.items()
                           if k not in ("kind", "seq", "ts", "text")})]


def project_stream(events: List[dict]) -> List[dict]:
    """事件流 fold → item 流(顺序保持; 空 item 事件剔除)。"""
    items: List[dict] = []
    for ev in events or []:
        items.extend(project_event(ev))
    return items


def as_legacy_events(items: List[dict]) -> List[dict]:
    """反向桥: item → 存量事件形状(kind/text/changedFiles/toolName/...)。

    存量消费方(卡片落库/units 沉淀)继续吃事件形状——投影层对其透明。
    """
    out: List[dict] = []
    for it in items or []:
        t = it.get("type")
        ev: Dict[str, Any] = {"ts": it.get("ts")}
        if it.get("seq") is not None:
            ev["seq"] = it["seq"]
        if t == "tool_call":
            ev.update({"kind": "tool", "toolName": it.get("tool") or "",
                       "text": ("▶ " if it.get("status") == "running"
                                else "✓ " if it.get("status") == "ok"
                                else "✗ ") + (it.get("text") or "")})
        elif t == "file_change":
            ev.update({"kind": "done",
                       "changedFiles": (it.get("payload") or {}).get("files") or []})
        elif t == "approval":
            ev.update({"kind": "approval_request",
                       "toolName": it.get("tool") or "",
                       "requestId": (it.get("payload") or {}).get("requestId") or ""})
        elif t == "verify":
            ev.update({"kind": "verify", "overall": it.get("status")})
        elif t == "turn_completed":
            ev.update({"kind": "done" if it.get("status") == "done" else "failed",
                       "text": it.get("text") or ""})
        elif t == "task_input":
            ev.update({"kind": "input_required", "text": it.get("text") or ""})
        elif t == "notice":
            ev.update({"kind": "notice", "text": it.get("text") or "",
                       "reason": (it.get("payload") or {}).get("reason") or ""})
        elif t == "reasoning":
            ev.update({"kind": "reasoning", "text": it.get("text") or ""})
        elif t == "plan":
            ev.update({"kind": "plan", "planStatus": it.get("status"),
                       "steps": (it.get("payload") or {}).get("steps") or []})
        else:  # event 透传/未识别类型: 还原注册时的原始形状
            ev.update({"kind": it.get("kind") or t, "text": it.get("text") or "",
                       **(it.get("payload") or {})})
        out.append(ev)
    return out
