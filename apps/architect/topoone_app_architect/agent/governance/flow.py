"""会话流程相位机(小内核 + 行为注册制) — 策略/守卫/自愈的公共事实轴。

相位(states.py FLOW_*)是**派生物化缓存**(derive-on-write): 真相源 = 领域实体
(需求版本链 / arch_tasks); 只经领域事件 recompute 迁移, 无直改入口——避免重蹈
meta.jobs 双源覆辙(P6 清退裁决)。缓存可随时重建(幂等纯函数)。

设计裁决(2026-09 定稿留痕, 与 gears.py 裁决记录同风格):
- R1 方向单向: phase → 策略(resolve_gear P 轴)仅作输入; 策略对相位零反写。
- R2 面分离: P 轴只叠加 architect_note(对话面); agent_note/cadence/cap 等
  任务面字段禁触——任务指令只反映挡位与安全等级, 不反映会话对话相位。
- R3 开关矩阵: derive 恒开(纯缓存零行为); P 轴(p_axis_phase_overlay)与
  守卫(flow_guards_enabled)各自独立开关; P 轴叠加在最终基线之后(独立于
  r2_1_axis_stack 旧短路)。
- G1 守卫次序: 相位硬闸落编排阶段①.5(闸门之后/路由之前, 先于直通指令);
  意图匹配复用 perception.intent.GENERIC_EXEC_RE(单源, 不造第二解析器)。
- 硬闸仅 2 类: archived(既有 gate.py) / interrupted(本模块, 下发类意图)。
  rollback-409 为既有 REST 硬闸(requirements.py)。其余全软(note/hint)。
- 行为面数据驱动(S0, agent.flow.policy): 相位 note/守卫规则(意图按名引用,
  确定性单源——LLM 意图不入硬闸)/hint 模板/P 轴 elementHints 全部走
  flow_policy.load_flow_policy(代码缺省+配置深合并, 坏值回落缺省);
  迁移面(derive)不配置化——防第二真相源(架构红线)。

拓展面(按需拓展 = 行为注册, 非加状态): register_flow_guard / register_flow_hint /
register_phase_overlay; 精细化流程在 architect 核心机制内实现(LLM+hint+软守卫),
通用/未拓展能力路由执行器(cline/opencode/codex, 经 task.propose + safetyClass)。
"""
from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional

from ...arch_routes.store.states import (
    CONV_ACTIVE,
    FLOW_ARMED, FLOW_CLARIFYING, FLOW_EXECUTING, FLOW_FREE,
    FLOW_INTERRUPTED, FLOW_PHASES, FLOW_REVIEWING,
    REQ_DONE, TASK_DONE, TASK_PENDING_CONFIRM, TASK_RUNNING,
    TASK_SAVED, TASK_WAITING_INPUT,
)
from .flow_policy import (
    guard_reply,
    hint_text,
    load_flow_policy,
    phase_guards,
    phase_note as _policy_note,
)

__all__ = [
    "derive_flow_state", "drift_check", "phase_guard", "flow_hints",
    "phase_note", "phase_element_boost", "p_axis_overlay_fields",
    "recompute", "set_flow_state", "mark_stale_interrupted", "recover_session",
    "register_flow_guard", "register_flow_hint", "register_phase_overlay",
]

# 运行占用态(pending_confirm/saved 属 armed——与 confirm_task 互斥口径一致)
_RUN_STATES = (TASK_RUNNING, TASK_WAITING_INPUT)
_ARMED_STATES = (TASK_SAVED, TASK_PENDING_CONFIRM)
# reviewing 消化出口: 合并/已阅(dismissed_at)/建下张卡/req done


def _meta_of(conv: Optional[dict]) -> dict:
    meta = (conv or {}).get("meta")
    if isinstance(meta, str):
        try:
            meta = json.loads(meta or "{}")
        except (TypeError, ValueError):
            meta = {}
    return meta if isinstance(meta, dict) else {}


def derive_flow_state(conv: Optional[dict], tasks: Optional[List[dict]],
                      req: Optional[dict] = None, *, cached: str = "",
                      force: bool = False) -> str:
    """相位派生(批戊收编): 单源迁 memory.focus.derive_phase——薄委托回退点。

    判定序/interrupted 粘滞语义逐条保留(用户可见行为零变化);
    全量绿后本委托由焦点栈直连替代(两步提交策略第一步)。"""
    from .focus import derive_phase, frames_from_entities
    frames = frames_from_entities(conv, tasks, req)
    return derive_phase(frames, conv, cached=cached, force=force)


def drift_check(cached: str, actual: str) -> bool:
    """漂移判定: 缓存相位 ≠ 实际派生相位(中断粘滞不算漂移)。"""
    return cached != actual if cached != FLOW_INTERRUPTED else False


def phase_guard(phase: str, text: str,
                policy: Optional[dict] = None) -> Optional[str]:
    """相位硬闸(纯函数): 拦截返回引导文案(直通回复, 零 LLM); 放行返回 None。

    规则面走 flow_policy(意图按名引用, 匹配器=确定性代码单源——LLM 意图
    不入硬闸, 防守线①); 仅配置了 guards 的相位参与拦截(缺省仅 interrupted)。
    interrupted 不锁死对话(互斥锁死会话是 cv-153 类事故模式)——只拦新作业下发。
    """
    pol = policy if policy is not None else load_flow_policy()
    for g in phase_guards(pol, phase):
        reply = guard_reply(g, text)
        if reply:
            return reply
    return None


def flow_hints(conv: Optional[dict], tasks: Optional[List[dict]],
               req: Optional[dict] = None,
               policy: Optional[dict] = None) -> List[str]:
    """hint 层(非权威, 随时可算): 下一步建议——原 spec_ready/task_saved/done
    流水线态在此降级为提示(裁决: 需求/任务正交可选, 不强制流水线)。
    文案模板走 flow_policy.hintTemplates({n} 占位)。
    批戊: 计数改读焦点帧(派生单源; armed 提示口径=预填/待确认帧,
    不含 spec_ready——"任务卡"文案语义不变)。"""
    pol = policy if policy is not None else load_flow_policy()
    from .focus import frames_from_entities
    frames = [f for f in frames_from_entities(conv, tasks, req)
              if isinstance(f, dict)]

    out: List[str] = []
    armed = [f for f in frames
             if f.get("kind") in ("plan_step_ready", "task_confirm")]
    if armed:
        out.append(hint_text(pol, "armed", len(armed)))
    done_open = [f for f in frames if f.get("kind") == "reviewing"]
    if done_open:
        out.append(hint_text(pol, "reviewing", len(done_open)))
    if req and (req.get("status") or "") == REQ_DONE:
        out.append(hint_text(pol, "reqDone", 0))
    for fn in _custom_hints:   # 注册制提示(个性化/项目级; 故障静默跳过)
        try:
            extra = fn(conv, tasks, req)
        except Exception:  # noqa: BLE001
            continue
        for h in extra or []:
            if h and h not in out:
                out.append(str(h))
    return out


def phase_note(phase: str, policy: Optional[dict] = None) -> str:
    """P 轴 architect_note 追加段(对话面指引; 任务面零接触)。文案走 flow_policy。"""
    pol = policy if policy is not None else load_flow_policy()
    return _policy_note(pol, phase)


def phase_element_boost(phase: str, policy: Optional[dict] = None) -> bool:
    """element_hints 单调上调(复用 U 轴要素清单机制)——由 policy.elementHints 驱动。"""
    from .flow_policy import element_boost as _boost
    pol = policy if policy is not None else load_flow_policy()
    return _boost(pol, phase)


def p_axis_overlay_fields(policy: Any, phase: str,
                          fp: Optional[dict] = None) -> dict:
    """P 轴字段覆盖(纯): replace 字段集(空=无叠加); element_hints 只升不降。"""
    pol = fp if fp is not None else load_flow_policy()
    fields: dict = {}
    note = phase_note(phase, pol)
    if note:
        base = str(getattr(policy, "architect_note", "") or "")
        fields["architect_note"] = (base + "\n" + note).strip()
    if phase_element_boost(phase, pol) \
            and getattr(policy, "element_hints", "") != "high":
        fields["element_hints"] = "high"
    return fields


_GuardFn = Callable[[str, str], Optional[str]]   # (phase, text) -> reply|None
_HintFn = Callable[[Optional[dict], List[dict], Optional[dict]], List[str]]

_custom_guards: List[dict] = []      # {id, phases, fn}
_custom_hints: List[_HintFn] = []
_custom_overlays: Dict[str, dict] = {}   # phase -> replace 字段(项目/用户级注册)


def register_flow_guard(rule_id: str, fn: _GuardFn,
                        phases: Optional[List[str]] = None) -> None:
    """注册自定义守卫规则(软/硬自定; 默认全相位)。重复 id 覆盖(幂等注册)。"""
    global _custom_guards
    _custom_guards = [g for g in _custom_guards if g["id"] != rule_id]
    _custom_guards.append({"id": rule_id, "phases": set(phases or FLOW_PHASES),
                           "fn": fn})
    _custom_guards.sort(key=lambda g: g["id"])


def register_flow_hint(fn: _HintFn) -> None:
    """注册提示提供方(个性化/项目级下一步建议; LIFO 叠加)。"""
    if fn not in _custom_hints:
        _custom_hints.append(fn)


def register_phase_overlay(phase: str, fields: dict) -> None:
    """注册相位覆盖字段(经 dataclasses.replace 生效; 禁触任务面字段——R2)。"""
    _FORBIDDEN = ("agent_note", "cadence", "max_iterations", "cap_note",
                  "tool_rounds", "tier", "pre_split")
    bad = [k for k in fields if k in _FORBIDDEN]
    if bad:
        raise ValueError(f"phase overlay 禁触任务面字段(R2 面分离): {bad}")
    _custom_overlays[phase] = {**_custom_overlays.get(phase, {}), **fields}


def _run_custom_guards(phase: str, text: str) -> Optional[str]:
    for g in _custom_guards:
        if phase in g["phases"]:
            try:
                reply = g["fn"](phase, text)
            except Exception:  # noqa: BLE001 — 自定义守卫故障不阻塞主链
                continue
            if reply:
                return reply
    return None


def evaluate_guards(phase: str, text: str,
                    policy: Optional[dict] = None) -> Optional[str]:
    """守卫评估入口(编排器①.5 消费): 内置硬闸 + 注册制自定义守卫(先内置)。"""
    reply = phase_guard(phase, text, policy)
    if reply:
        return reply
    return _run_custom_guards(phase, text)


def _store():
    from ...arch_routes import store
    return store


def _ts_ms() -> int:
    import time
    return int(time.time() * 1000)


def _audit_transition(conv_id: str, pid: str, frm: str, to: str,
                      trigger: str) -> None:
    """迁移审计 → arch_stream_items(运行时台账先例; 随会话级联删除)。"""
    try:
        _store().StreamItemsStore.create({
            "conversationId": conv_id, "projectId": pid,
            "type": "flow_transition", "status": to,
            "text": f"{frm} → {to}",
            "payload": {"from": frm, "to": to, "trigger": trigger,
                        "at": _ts_ms()},
            "createdAt": _ts_ms(),
        })
    except Exception:  # noqa: BLE001 — 审计失败不阻断迁移
        pass


def _publish_transition(conv_id: str, frm: str, to: str) -> None:
    """SSE 广播(flow-transition): 落库为锚、事件为加速——无订阅者丢失时
    前端重拉自然对齐(cv-205 语义, 不依赖事件必达)。"""
    try:
        from ..collab.sse import emit
        emit("flow-transition", conv_id, **{"from": frm, "to": to})
    except Exception:  # noqa: BLE001
        pass


def telemetry(kind: str, **fields) -> None:
    """遥测出口(governance 横切豁免面): 各层经此落 dataset, 避免低层直引
    reflection(R2 层序)。fail-soft。"""
    try:
        from ..reflection import dataset
        dataset.record(kind, **fields)
    except Exception:  # noqa: BLE001
        pass


def _telemetry(kind: str, **fields) -> None:
    telemetry(kind, **fields)


def recompute(conv_id: str, *, trigger: str = "", force: bool = False) -> Optional[dict]:
    """事件收口: 读源实体 → derive → 落缓存(+漂移自动修复/审计/SSE/遥测)。

    force: 自愈/恢复路径(解除 interrupted 粘滞)。幂等——同事实重复调用零写入。
    任何异常向上静默(相位机故障不阻塞主链, fail-soft)。
    """
    try:
        store = _store()
        conv = store.ConversationsStore.get(conv_id)
        if not conv:
            return None
        if (conv.get("status") or CONV_ACTIVE) == "archived":
            # 归档侧路: 相位冻结(status 字段治理, 不入流程态)
            cached = str(conv.get("flowState") or "")
            return {"conversationId": conv_id, "flowState": cached,
                    "changed": False, "frozen": True}
        tasks = store.TasksStore.of_conv(conv_id) or []
        rid = str(conv.get("reqId") or "")
        req = store.RequirementsStore.get(rid) if rid else None
        cached = str(conv.get("flowState") or "")
        actual = derive_flow_state(conv, tasks, req=req, cached=cached,
                                   force=force)
        if drift_check(cached, actual):
            _telemetry("flow_drift", conversationId=conv_id, cached=cached,
                       actual=actual, trigger=trigger)
        if actual == cached:
            return {"conversationId": conv_id, "flowState": actual,
                    "changed": False}
        ok = set_flow_state(conv, actual, trigger=trigger)
        return {"conversationId": conv_id, "flowState": actual,
                "changed": ok, "from": cached}
    except Exception:  # noqa: BLE001 — fail-soft: 相位故障不阻塞主链
        return None


def set_flow_state(conv: dict, phase: str, *, trigger: str = "") -> bool:
    """显式置位(自愈路径用: interrupted 置位/恢复解除)。经审计+SSE, 不经 derive。"""
    if phase not in FLOW_PHASES:
        return False
    conv_id = conv.get("id") or ""
    if not conv_id:
        return False
    try:
        store = _store()
        store.ConversationsStore.update(conv_id, {
            "flowState": phase, "flowStateAt": _ts_ms()})
        _audit_transition(conv_id, str(conv.get("projectId") or ""),
                          str(conv.get("flowState") or ""), phase, trigger)
        _publish_transition(conv_id, str(conv.get("flowState") or ""), phase)
        return True
    except Exception:  # noqa: BLE001
        return False


def mark_stale_interrupted(conv_id: str) -> bool:
    """sweep 自愈: executing 态下活跃任务 stale 且本轮恢复无收敛 → interrupted。

    「不可控未知卡点」的核心对策: 要么自动恢复、要么显式声明卡住并给出
    恢复动作——绝不静默悬置(cv-153/161/204 事故模式的机制化收口)。
    """
    try:
        from ..governance.timeouts import get as _timeout_of
        store = _store()
        conv = store.ConversationsStore.get(conv_id)
        if not conv:
            return False
        tasks = store.TasksStore.of_conv(conv_id) or []
        active = [t for t in tasks
                  if str(t.get("status") or "") in _RUN_STATES]
        if not active:
            recompute(conv_id, trigger="sweep", force=True)
            return False
        now = _ts_ms()
        newest = max(int(t.get("updatedAt") or 0) for t in active)
        if now - newest <= int(_timeout_of("flow_stale_s") * 1000):
            return False
        conv = store.ConversationsStore.get(conv_id) or conv
        return set_flow_state(conv, FLOW_INTERRUPTED, trigger="stale")
    except Exception:  # noqa: BLE001
        return False


def land_phase_reply(conv_id: str, reply: str) -> str:
    """硬闸直通回执落库(orchestrator ①.5 消费; 同直通指令落库口径)。返回 messageId。"""
    from ...arch_routes import store
    msg_id = store.next_id("m")
    store.ConversationsStore.append_message({
        "id": msg_id, "conversationId": conv_id, "role": "assistant",
        "time": _ts_ms(), "content": reply})
    try:
        store.ConversationsStore.update(conv_id, {"reviewState": "unread"})
    except Exception:  # noqa: BLE001
        pass
    return msg_id


def recover_session(conv_id: str) -> Optional[dict]:
    """interrupted 恢复动作(幂等): 核对执行器实际态收尾任务 + 重算相位。

    返回 {"recovered": 收尾数, "repump": 重挂数, "flowState": 相位}。
    调用方须在事件循环内处理 repump(同 GET messages 先例)。
    """
    try:
        from ..execution.recover import recover_conv_tasks
        rec = recover_conv_tasks(conv_id) or {}
    except Exception:  # noqa: BLE001
        rec = {}
    res = recompute(conv_id, trigger="recover", force=True) or {}
    return {"recovered": int(rec.get("finished") or 0),
            "repump": list(rec.get("repump") or []),
            "flowState": res.get("flowState") or ""}
