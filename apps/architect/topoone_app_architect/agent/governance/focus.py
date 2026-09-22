"""焦点栈(工作记忆/情景记忆显式化) — 会话判别的派生单源(批戊)。

归位 governance: 与相位机同源同族(判别治理面), 且需引用 states 常量——
flow.py 先例(governance 顶层引 arch_routes.store.states)。

定位: 任务/需求/计划实体状态 → 栈帧投影。**零新存储/零写点**——每回合从
实体行全量重算(声明式派生, 非命令式 push/pop; 「状态存实体, 每回合重建不
累积」红线)。帧的生灭=谓词真伪: 实体进入某状态即"入栈", 离开即"消亡";
新帧对旧帧是遮蔽(排序下沉), 不是弹出。

三层判别模型(各司其职):
  词表(match_imperative) → 意图原语  execute/confirm/continue/retry/extract
  焦点(本模块)           → 指代消解  top 帧 = 哪张卡/哪步/哪个需求
  实体(任务/需求/计划行)  → 状态真相  焦点栈是投影, 不另存真相

帧型(用户动作紧迫度序, 同级按状态变更时间就近):
  task_input_wait  ⏸ subagent 等输入(被点名, 最强)
  task_running     🔄 执行中(含 waiting 之外的运行占用)
  plan_step_ready  ➡️ 计划步骤已预填待确认(绑定任务 saved/pending_confirm)
  task_confirm     📋 独立任务卡待确认(同上状态、非计划步骤)
  spec_ready       📝 需求卡就绪待执行(该 rid 无计划无任务——同链互斥)
  reviewing        ✅ 完成回执待验收(done 未 dismiss)

phase: 相位兼容视图(原 flow.derive_flow_state 判定序+interrupted 粘滞
整体迁入, 判定只吃任务帧——与旧行为逐条等价); flow.py 降级为纯配置消费者。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from ...arch_routes.store.states import (
    FLOW_ARMED, FLOW_CLARIFYING, FLOW_EXECUTING, FLOW_FREE,
    FLOW_INTERRUPTED, FLOW_REVIEWING,
    TASK_DONE, TASK_PENDING_CONFIRM, TASK_RUNNING,
    TASK_SAVED, TASK_WAITING_INPUT,
)

__all__ = ["build_focus", "derive_phase", "frames_from_entities",
           "resolve_intent", "RECENT_WINDOW_MS", "RECENT_LIMIT"]

# 事件栈近窗双限(情景记忆; 实体时间戳派生, 滑窗自然进出)
RECENT_WINDOW_MS = 60 * 60 * 1000
RECENT_LIMIT = 10

# 帧紧迫度(主键; 越小越靠顶)
_KIND_PRIORITY = {
    "task_input_wait": 0,
    "task_running": 1,
    "plan_step_ready": 2,
    "task_confirm": 3,
    "spec_ready": 4,
    "reviewing": 5,
}
_CONFIRM_KINDS = ("plan_step_ready", "task_confirm")
_RUN_FRAME_KINDS = ("task_input_wait", "task_running")
_ARMED_FRAME_KINDS = ("plan_step_ready", "task_confirm", "spec_ready")

_TASK_CONFIRM_STATES = (TASK_SAVED, TASK_PENDING_CONFIRM)


def _ts(row: dict, *names: str) -> int:
    for n in names:
        v = row.get(n)
        if v:
            try:
                return int(v)
            except (TypeError, ValueError):
                continue
    return 0


def frames_from_entities(conv: Optional[dict], tasks: Optional[List[dict]],
                         req: Optional[dict] = None,
                         plan: Optional[List[dict]] = None) -> List[Dict[str, Any]]:
    """实体行 → 栈帧(纯函数; phase 派生与 build_focus 共用的唯一造帧点)。"""
    frames: List[Dict[str, Any]] = []
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status") or "")
        since = _ts(t, "updated_at", "updatedAt", "created_at", "createdAt")
        tid = str(t.get("id") or "")
        rid = str(t.get("reqId") or t.get("req_id") or "")
        if st == TASK_WAITING_INPUT:
            frames.append({"kind": "task_input_wait", "taskId": tid,
                           "reqId": rid, "since": since,
                           "label": f"「{(t.get('title') or '')[:24]}」等待你的输入"})
        elif st == TASK_RUNNING:
            frames.append({"kind": "task_running", "taskId": tid,
                           "reqId": rid, "since": since,
                           "label": f"「{(t.get('title') or '')[:24]}」执行中"})
        elif st in _TASK_CONFIRM_STATES:
            step = _plan_step_of(plan or [], tid)
            if step is not None:
                frames.append({"kind": "plan_step_ready", "taskId": tid,
                               "reqId": rid, "since": since, "idx": step["idx"],
                               "label": f"计划步骤 {step['idx'] + 1} "
                                        f"「{(step.get('title') or '')[:24]}」待确认"})
            else:
                frames.append({"kind": "task_confirm", "taskId": tid,
                               "reqId": rid, "since": since,
                               "label": f"任务卡「{(t.get('title') or '')[:24]}」待确认"})
        elif st == TASK_DONE and not t.get("dismissedAt"):
            # req-done 豁免(迁移自 derive_flow_state): 需求已完结 → 回执视为已
            # 消化, 不进验收帧(全局出口, 不按 id 匹配——与旧行为逐条等价)
            if str((req or {}).get("status") or "") == "done":
                continue
            frames.append({"kind": "reviewing", "taskId": tid,
                           "reqId": rid, "since": _ts(t, "finished_at", "finishedAt",
                                                      "updated_at", "updatedAt"),
                           "label": f"「{(t.get('title') or '')[:24]}」完成待验收"})
    # spec_ready: 绑定需求 + 规约 confirmed + 该 rid 无计划无任务(同链互斥)
    rid = str((conv or {}).get("reqId") or "")
    if rid and (req or {}).get("id") == rid \
            and str((req or {}).get("status") or "") != "done":
        has_plan = bool(plan)
        has_task = any(str(t.get("reqId") or t.get("req_id") or "") == rid
                       for t in tasks or [])
        if not has_plan and not has_task:
            frames.append({"kind": "spec_ready", "reqId": rid,
                           "since": _ts(req, "updated_at", "updatedAt"),
                           "label": f"需求 {rid} 就绪待执行"})
    return frames


def _plan_step_of(plan: List[dict], task_id: str) -> Optional[dict]:
    for i, s in enumerate(plan or []):
        if str(s.get("taskId") or "") == task_id:
            return {"idx": i, "title": s.get("title") or ""}
    return None


def _meta_of(conv: Optional[dict]) -> dict:
    meta = (conv or {}).get("meta")
    if isinstance(meta, str):
        try:
            import json as _json
            meta = _json.loads(meta or "{}")
        except (TypeError, ValueError):
            meta = {}
    return meta if isinstance(meta, dict) else {}


def derive_phase(frames: List[Dict[str, Any]], conv: Optional[dict],
                 cached: str = "", force: bool = False) -> str:
    """相位兼容视图(原 flow.derive_flow_state 判定序整体迁入)。

    判定只吃任务帧(task_input_wait/run → executing; confirm/ready/spec →
    armed; reviewing → reviewing)——与旧行为逐条等价; interrupted 粘滞保留
    (仅 force=True 的自愈/恢复路径可解除)。
    """
    if cached == FLOW_INTERRUPTED and not force:
        return FLOW_INTERRUPTED
    kinds = {f.get("kind") for f in frames or []}
    if kinds & set(_RUN_FRAME_KINDS):
        return FLOW_EXECUTING
    if kinds & set(_ARMED_FRAME_KINDS):
        return FLOW_ARMED
    if "reviewing" in kinds:
        return FLOW_REVIEWING
    if _meta_of(conv).get("specDraft") is not None:
        return FLOW_CLARIFYING
    return FLOW_FREE


def _recent_events(tasks: List[dict], now: int) -> List[Dict[str, Any]]:
    """事件栈(情景记忆): 任务状态转换近窗投影——实体时间戳派生, 滑窗进出。

    v1 事件源=任务行(done/failed/waiting 转换); retry 指代与遥测消费。
    """
    lo = now - RECENT_WINDOW_MS
    evs: List[Dict[str, Any]] = []
    for t in tasks or []:
        if not isinstance(t, dict):
            continue
        st = str(t.get("status") or "")
        kind = {"done": "task_done", "failed": "task_failed",
                TASK_WAITING_INPUT: "task_input"}.get(st)
        if not kind:
            continue
        ts = _ts(t, "finished_at", "finishedAt", "updated_at", "updatedAt")
        if ts and ts >= lo:
            evs.append({"kind": kind, "ts": ts,
                        "taskId": str(t.get("id") or ""),
                        "reqId": str(t.get("reqId") or t.get("req_id") or ""),
                        "title": (t.get("title") or "")[:24]})
    evs.sort(key=lambda e: -e["ts"])
    return evs[:RECENT_LIMIT]


def build_focus(conv_id: str, now: Optional[int] = None, *,
                cached_phase: str = "", force: bool = False) -> Dict[str, Any]:
    """会话焦点上下文(派生单源入口): 实体行 → {stack, recent, top, phase}。

    每回合全量重算(幂等; 同实体状态 ⇒ 同栈)。零写点——帧生灭由既有动作链
    改变实体状态自然驱动。
    """
    now = int(now or time.time() * 1000)
    from ...arch_routes import store as _s
    from ..planning.task_plan import get_plan
    conv = _s.ConversationsStore.get(conv_id) or {}
    tasks = [t for t in (_s.TasksStore.of_conv(conv_id) or [])
             if isinstance(t, dict)]
    rid = str(conv.get("reqId") or "")
    req = _s.RequirementsStore.get(rid) if rid else None
    plan = get_plan(rid) if rid else None
    if req:
        req = dict(req)
        active = _s.RequirementsStore.spec_active(rid) or {}
        req["specConfirmed"] = (active.get("state") == "confirmed")
    frames = frames_from_entities(conv, tasks, req, plan)
    frames.sort(key=lambda f: (_KIND_PRIORITY.get(f.get("kind") or "", 99),
                               -(f.get("since") or 0)))
    phase = derive_phase(frames, conv, cached=cached_phase, force=force)
    return {"convId": conv_id, "stack": frames, "recent": _recent_events(tasks, now),
            "top": frames[0] if frames else None, "phase": phase,
            "reqId": rid, "now": now}


# ── 就近消解(意图原语 × 焦点帧 → 动作; 判别矩阵代码单源) ────────────────

def resolve_intent(intent: str, focus: Dict[str, Any]) -> Dict[str, Any]:
    """意图原语 → 焦点指代消解(纯函数)。

    返回 {action, frame?, note?}: action ∈ confirm_task / execute /
    retry_failed / extract / relay_hint / none / fallthrough。
    fallthrough = 焦点无对应指代 → 调用方回落 GU 对话链(旧行为的"回落"
    由消解矩阵自然表达, 无独立分支)。
    """
    top = focus.get("top") or {}
    kinds = {f.get("kind") for f in focus.get("stack") or []}
    if intent == "extract":
        return {"action": "extract"}
    if intent == "retry":
        failed = next((e for e in focus.get("recent") or []
                       if e.get("kind") == "task_failed"), None)
        if failed:
            return {"action": "retry_failed", "frame": failed}
        return {"action": "none",
                "note": "近期没有可重试的失败步骤。"}
    if intent in ("execute", "continue", "confirm"):
        if top.get("kind") in _CONFIRM_KINDS:
            # 推进/确认类意图 × 待确认焦点 → 就近启动栈顶(cv-241 病灶根治)
            return {"action": "confirm_task", "frame": top}
        if intent == "confirm":
            return {"action": "fallthrough"}      # 无待确认焦点 → GU 对话链
        if top.get("kind") == "task_input_wait":
            return {"action": "relay_hint",
                    "note": f"{top.get('label') or 'subagent 等待输入中'}——"
                            "请直接回复要转达的内容。"}
        if top.get("kind") == "task_running":
            return {"action": "none",
                    "note": f"{top.get('label') or '任务'}正在执行中——"
                            "完成后会自动汇报; 如需干预请先停止。"}
        if "spec_ready" in kinds or top.get("kind") == "spec_ready":
            return {"action": "execute"}          # 需求就绪 → 生成计划/单卡
        return {"action": "execute"}              # 无焦点 → 既有绑定提示/单卡路径
    return {"action": "fallthrough"}
