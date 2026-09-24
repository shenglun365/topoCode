"""阶段③ 消息装配(M1 自 orchestrator 机械搬迁, 行为等价)。

A 轴 chat 形态: 角色模型路由 → 懒探测 → 挡位解析 → 消息组装 + 挡位文案注入
(文案经 compensation.providers, R1.1 收编)。设计 §4 ChatTurn 的装配半边。

反思闭环注入面(采纳文档 2609 P0, S1/S3):
- 溢出摘要: 历史超 policy.overflowTrigger → 溢出段摘要瞬态注入(不落消息流,
  cv-194); 按溢出锚点缓存于 conv.meta.overflowDigest; LLM 失败保持现截断行为。
- 修复经验: repair_note 单元按 policy.injections.repairNotes 注入(上限/弱挡收紧)。
- 统一装配预算 _apply_assembly_budget: 注入段全部过挡位系数字数预算(防守线③)。
- 规则数值全部走 agent.flow.policy(governance/flow_policy.py); 行为开关在
  agent.comp.overrides(缺省启用, 显式 false 回退)。
"""
from __future__ import annotations

from typing import List, Optional


def _swallow(tag: str) -> None:
    """S2 吞错计数: 装配路径静默降级可观测, 业务语义零变化(开关 swallow_counters)。"""
    try:
        from ..reflection import dataset as _ds
        _ds.swallow(tag)
    except Exception:  # noqa: BLE001
        pass


def _kb_face_enabled(gear, r34: bool, root: str, project: str) -> bool:
    """R3.4 挡位 kb 开关 ∧ cv-187 项目关联硬门(kb_degraded 共用口径)。

    未关联 KB(无基线) → kb.*/mcp.call 工具自动关闭(提示面; 执行面拦截在
    run_arch_tool)。判定失败保持原状不误关。"""
    enabled = bool(getattr(gear, "kb", True)) if r34 else True
    try:
        from ...arch_routes.project import kb_degraded as _kb_deg
        if _kb_deg(root, project):
            enabled = False
    except Exception:  # noqa: BLE001
        _swallow("ctx.kb_degraded")
    return enabled


def _record_comp_gap(gear, model_id: str) -> None:
    """M5 探测-策略闭环遥测: 只记差距, 不动态升挡(D6)。失败不阻塞主链。"""
    try:
        from ..cognition import model_profile as _mp2
        from ..compensation.ctx import (PURPOSE_WEAK_SCORE, CapabilityScores,
                                Purpose as _Purpose)
        _caps = ((_mp2.get_profile(model_id or "") or {}).get("caps") or {})
        _scores = CapabilityScores(
            requirement=_caps.get("requirementScore"),
            arch=_caps.get("archScore"), module=_caps.get("moduleScore"))
        _ps = _scores.dimension(_Purpose.REQUIREMENT)
        from ..governance.gears import WEAKEST_TIER as _weakest
        if _ps is not None and _ps < PURPOSE_WEAK_SCORE and gear.tier != _weakest:
            from ..reflection import dataset as _lds
            _lds.record("comp_gap", purpose="requirement", tier=gear.tier,
                        score=_ps, model=model_id or "")
    except Exception:  # noqa: BLE001
        _swallow("ctx.comp_gap")


def _clarify_directive_msg(gate: dict, conv: dict) -> str:
    """cv-190 澄清挡位指令(auto 缺口驱动 | forced 先澄清后落卡; 明确指令免澄清)。

    规约快照(已绑定需求)供缺口矩阵; 判定失败静默(不阻塞主链)。"""
    try:
        from ...arch_routes import store as _store
        from ..requirements.clarify import clarify_directive as _cd_fn
        _mode = str((conv or {}).get("clarifyMode") or "auto").strip()
        _question = str((gate or {}).get("question") or "")
        _snap = {}
        _rid = str((conv or {}).get("reqId") or "")
        if _rid:
            _active = _store.RequirementsStore.spec_active(_rid) or {}
            _snap = _active.get("snapshot") or {}
        return _cd_fn(_mode, _question, _snap)
    except Exception:  # noqa: BLE001
        _swallow("ctx.clarify_directive")
        return ""


# ── 反思闭环注入面(S1/S3) ─────────────────────────────────────────────

def _load_flow_policy() -> dict:
    """生效 policy(每回合读, 同 read_overrides 口径; 坏值回落缺省——S0 fail-soft)。"""
    try:
        from ...arch_routes import store as _s
        from ..governance.flow_policy import load_flow_policy
        return load_flow_policy(_s.CollabConfigStore.get)
    except Exception:  # noqa: BLE001
        from ..governance.flow_policy import DEFAULT_FLOW_POLICY
        import copy as _copy
        return _copy.deepcopy(DEFAULT_FLOW_POLICY)


def _conv_meta_of(conv: Optional[dict]) -> dict:
    meta = (conv or {}).get("meta")
    if isinstance(meta, str):
        try:
            import json as _json
            meta = _json.loads(meta or "{}")
        except (TypeError, ValueError):
            meta = {}
    return meta if isinstance(meta, dict) else {}


def _repair_notes_msg(conv: dict, model_id: str, pol: dict) -> str:
    """S1 修复经验注入: repair_note 单元 → system 段(规则走 policy)。

    maxPerTurn 每回合上限; 最弱挡(模型档案 tier 判定)收紧至 weakTierMax; 最新优先。
    开关: repair_note_injection ∧ policy.enabled。失败静默(计数)。"""
    try:
        from ..cognition import model_profile as _mp
        from ...arch_routes import store as _s
        from ..compensation.overrides import override_enabled, read_overrides
        _get = _s.CollabConfigStore.get
        if not override_enabled(read_overrides(_get), "repair_note_injection"):
            return ""
        cfg = (pol.get("injections") or {}).get("repairNotes") or {}
        if cfg.get("enabled", True) is False:
            return ""
        units = _s.ContextUnitsStore.all(
            conversation_id=str((conv or {}).get("id") or ""),
            type_="repair_note", limit=50)
        if not units:
            return ""
        cap = int(cfg.get("maxPerTurn") or 3)
        if _mp.tier_of(model_id or "") >= 2:
            cap = min(cap, int(cfg.get("weakTierMax") or 1))
        rows = sorted(units, key=lambda u: int(u.get("createdAt") or 0))[-cap:]
        lines = []
        for u in reversed(rows):
            n = int((u.get("refs") or {}).get("count") or 1)
            lines.append(f"• {u.get('title') or ''}: {u.get('content') or ''}"
                         + (f"(已复发×{n})" if n > 1 else ""))
        if not lines:
            return ""
        return "【近期修复经验】同类报错先对照, 不要重复已修过的路:\n" + "\n".join(lines)
    except Exception:  # noqa: BLE001
        _swallow("ctx.repair_notes")
        return ""


def _overflow_digest_msg(conv: dict, history: list, pol: dict) -> str:
    """S3 溢出摘要: 历史超 trigger → 溢出段 LLM 压缩为瞬态注入(不落消息流)。

    缓存: conv.meta.overflowDigest = {anchor, digest}; anchor=条数+首条溢出
    内容指纹, 不变不重算。LLM 失败/未配模型 → 返回""(保持现截断行为, 确定性
    降级, 绝不 5xx)。开关: overflow_digest ∧ policy.enabled。"""
    try:
        cfg = (pol.get("injections") or {}).get("overflowDigest") or {}
        from ..compensation.overrides import override_enabled, read_overrides
        from ...arch_routes import store as _s
        if cfg.get("enabled", True) is False \
                or not override_enabled(read_overrides(_s.CollabConfigStore.get),
                                        "overflow_digest"):
            return ""
        msgs = [(str(m.get("role")), str(m.get("content") or ""))
                for m in (history or [])
                if isinstance(m, dict)
                and m.get("role") in ("user", "assistant")
                and str(m.get("content") or "").strip()]
        win = int(cfg.get("windowCap") or 20)
        trig = int(cfg.get("overflowTrigger") or 30)
        if len(msgs) < trig:
            return ""
        overflow = msgs[:-win]
        import hashlib as _h
        anchor = f"{len(msgs)}:" + _h.sha1(
            overflow[0][1][:80].encode("utf-8")).hexdigest()[:10]
        cid = str((conv or {}).get("id") or "")
        if cid:    # 取库里新行: 上回合可能已写缓存(gate 传入的 conv 是回合快照)
            try:
                fresh = _s.ConversationsStore.get(cid)
                if fresh:
                    conv = fresh
            except Exception:  # noqa: BLE001
                pass
        meta = _conv_meta_of(conv)
        cached = meta.get("overflowDigest") or {}
        digest = str(cached.get("digest") or "") \
            if cached.get("anchor") == anchor else ""
        if not digest:
            material = "\n".join(f"{r}: {c}" for r, c in overflow)[:6000]
            try:
                from ..reflection.repair import summarize_task
                res = summarize_task(
                    task_id="overflow_digest",
                    system=("你是会话摘要器。将历史对话压缩为要点纪要"
                            "(已做决策/关键事实/未尽事项)，不超过 400 字，中文。"),
                    material=material, max_tokens=600,
                    dataset_kind="overflow_digest")
            except Exception:  # noqa: BLE001 — 含 ModelNotConfigured: 禁降级出垃圾
                _swallow("ctx.overflow_digest")
                return ""
            digest = str((res or {}).get("output") or "").strip()
            if not digest:
                return ""          # LLM 失败 → 保持现截断行为(确定性降级)
            digest = digest[:int(cfg.get("maxChars") or 1200)]
            try:
                meta["overflowDigest"] = {"anchor": anchor, "digest": digest}
                _s.ConversationsStore.update(str((conv or {}).get("id") or ""),
                                             {"meta": meta})
            except Exception:  # noqa: BLE001 — 缓存失败不影响本回合注入
                _swallow("ctx.overflow_cache")
        return f"【历史摘要(更早 {len(overflow)} 条对话, 已压缩)】{digest}"
    except Exception:  # noqa: BLE001
        _swallow("ctx.overflow_digest")
        return ""


def _apply_assembly_budget(segs: List[str], ctx_budget: float,
                           pol: dict) -> List[str]:
    """统一装配预算(防守线③): 注入段总字数 ≤ baseChars×挡位系数。

    保序消费(摘要优先于经验), 单段越界截断, 余量不足弃尾。ctx_budget 缺省 1。"""
    cfg = (pol.get("injections") or {}).get("assemblyBudget") or {}
    base = float(cfg.get("baseChars") or 4000)
    coef = max(float(cfg.get("coefMin") or 0.2),
               min(float(cfg.get("coefMax") or 2.0), float(ctx_budget or 1.0)))
    budget = max(int(cfg.get("floorChars") or 200), int(base * coef))
    out: List[str] = []
    used = 0
    for s in segs:
        if not s:
            continue
        room = budget - used
        if room < int(cfg.get("floorChars") or 200):
            break
        take = s if len(s) <= room else s[:max(0, room - 1)] + "…"
        out.append(take)
        used += len(take)
    return out


def _chat_context(data: dict, gate: dict, skill_scenarios: list, history: list,
                  model_id: str, assign_contract, gu_allowed=None) -> tuple:
    """管线阶段③ 消息装配(行为等价抽取自 handle_chat)。

    角色模型路由(§9/B1 per-call) → 能力档案懒探测 → 分析挡位(十二a) →
    _build_chat_messages + 通用 agent 路由系统段 + assign 契约段。
    gu_allowed: GU 路线工具限定(批丁, 参与能力文档子集渲染)。
    返回 (eff_model, msgs, gear)——gear.tool_rounds 供执行段轮次按挡(M4-B)。
    """
    conv = gate["conv"]
    # M1 收编: 挡位文案经 compensation.providers(与注册 Provider 同源, R1.1)
    from ..compensation.providers import architect_note_text, element_hint_text
    # tAgent 角色模型路由(§9/B1)：按场景角色取模型；explicit 会话选择优先，
    # 无角色命中时 eff_model=None → 回退全局偏好(既有链不变)。护栏 R3：per-call 参数。
    from ...arch_routes import agent_roles as _roles
    eff_model = _roles.resolve_role_model(_roles.scenario_role(skill_scenarios), model_id)

    # 模型能力档案懒探测(后台执行不阻塞): 无档案模型首轮触发, 探测落档后
    # 后续回合 system 按 tier 分级(小模型收紧预算, 大模型放开)
    try:
        from ..cognition import model_profile as _mp
        _mp.get_profile_or_lazy(eff_model or model_id or "")
    except Exception:  # noqa: BLE001
        _swallow("ctx.model_probe")

    # ── 分析挡位(会话级 analysisMode → 挡位策略, 环节十二a) ──
    try:
        _mode = str((conv or {}).get("analysisMode") or "strict").strip() or "strict"
    except Exception:  # noqa: BLE001
        _mode = "strict"
        _swallow("ctx.analysis_mode")
    try:
        from ...arch_routes.agent_executors import executor_hint_by_id
        _gear_cfg = (executor_hint_by_id(str((conv or {}).get("executorId") or ""),
                                          conv) or {}).get("executorConfig") or {}
    except Exception:  # noqa: BLE001
        _gear_cfg = {}
        _swallow("ctx.executor_hint")
    from ...arch_routes import store as _store_mod
    from ..compensation.overrides import read_overrides, override_enabled
    from ..governance.gears import WEAKEST_TIER
    _overrides = read_overrides(_store_mod.CollabConfigStore.get)
    from ..governance.gears import resolve_gear
    _gear = resolve_gear(_mode, _gear_cfg,
                         architect_model_id=eff_model or model_id or "",
                         overrides=_overrides,
                         flow_state=str((conv or {}).get("flowState") or ""))
    # R3.4(r3_4_dialogue_wiring, 默认启用): 对话面策略消费接线——
    # tool_surface/kb 工具面裁剪 + ctx_budget 预算系数; 开关关闭回退缺省(不变)
    _r34 = override_enabled(_overrides, "r3_4_dialogue_wiring")
    _tool_surface = str(getattr(_gear, "tool_surface", "full") or "full") if _r34 else "full"
    _kb_enabled = _kb_face_enabled(
        _gear, _r34, (data.get("root") or "").strip(),
        (data.get("project") or "").strip())
    _ctx_budget = float(getattr(_gear, "ctx_budget", 1.0) or 1.0) if _r34 else 1.0
    # M5 探测-策略闭环: 只记差距遥测, 不动态升挡(D6)
    _record_comp_gap(_gear, eff_model or model_id or "")
    msgs = _build_chat_messages((data.get("root") or "").strip(),
                                (data.get("project") or "").strip(),
                                history,
                                diagram_skill=bool(data.get("diagramSkill")
                                                   or data.get("diagram_skill")),
                                skill_scenarios=skill_scenarios,
                                model_id=eff_model or model_id or "",
                                tool_surface=_tool_surface,
                                kb_enabled=_kb_enabled,
                                ctx_budget=_ctx_budget,
                                gu_allowed=gu_allowed)
    # 挡位文案(A 轴 architect note): 注入面 GU-3 后单源化——原「通用 agent 路由
    # 契约」已退役(人格→prompt.posture 静态块; 路线判定→GU 决策表回合指引),
    # 本段只保留挡位系统文案
    msgs.insert(1, {"role": "system", "content": architect_note_text(_gear)})
    if assign_contract:
        msgs.insert(1, {"role": "system", "content": assign_contract})
    # U 轴: 要素框架提示(A 弱 → 澄清按要素清单展开, 引导用户喂全信息帮 architect 补位)
    # M1 收编: 文案经 compensation.providers.builtin(与注册 Provider 同源, R1.1)
    _hint = element_hint_text(_gear)
    if _hint:
        msgs.insert(1, {"role": "system", "content": _hint})
    # cv-190 需求澄清挡位(auto/forced, 明确指令免澄清)
    _cd = _clarify_directive_msg(gate, conv)
    if _cd:
        msgs.insert(1, {"role": "system", "content": _cd})
    # S1/S3 反思闭环注入(规则走 flow_policy; 预算统一收口=防守线③):
    # 摘要在前(上下文连续性优先), 修复经验在后; 开关各 helper 内判定。
    _pol = _load_flow_policy()
    for _seg in reversed(_apply_assembly_budget(
            [_overflow_digest_msg(conv, history, _pol),
             _repair_notes_msg(conv, eff_model or model_id or "", _pol)],
            _ctx_budget, _pol)):
        msgs.insert(1, {"role": "system", "content": _seg})
    return eff_model, msgs, _gear


def _build_chat_messages(root, project, history, cap=20, diagram_skill: bool = False,
                         skill_scenarios: Optional[List[str]] = None,
                         model_id: str = "",
                         tool_surface: str = "full",
                         kb_enabled: bool = True,
                         ctx_budget: float = 1.0,
                         gu_allowed=None):
    """组装 prompt(P4 委托 memory.working, 原文保真; R3.4 透传工具面/预算)。"""
    from ..memory.working import build_chat_messages
    return build_chat_messages(root, project, history, cap=cap,
                               diagram_skill=diagram_skill,
                               skill_scenarios=skill_scenarios, model_id=model_id,
                               tool_surface=tool_surface, kb_enabled=kb_enabled,
                               ctx_budget=ctx_budget, gu_allowed=gu_allowed)
