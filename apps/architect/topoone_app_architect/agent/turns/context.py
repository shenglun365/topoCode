"""阶段③ 消息装配(M1 自 orchestrator 机械搬迁, 行为等价)。

A 轴 chat 形态: 角色模型路由 → 懒探测 → 挡位解析 → 消息组装 + 挡位文案注入
(文案经 compensation.providers, R1.1 收编)。设计 §4 ChatTurn 的装配半边。
"""
from __future__ import annotations

from typing import List, Optional


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
        pass
    return enabled


def _record_comp_gap(gear, model_id: str) -> None:
    """M5 探测-策略闭环遥测: 只记差距, 不动态升挡(D6)。失败不阻塞主链。"""
    try:
        from ...arch_routes import model_profile as _mp2
        from ..compensation.ctx import (PURPOSE_WEAK_SCORE, CapabilityScores,
                                Purpose as _Purpose)
        _caps = ((_mp2.get_profile(model_id or "") or {}).get("caps") or {})
        _scores = CapabilityScores(
            requirement=_caps.get("requirementScore"),
            arch=_caps.get("archScore"), module=_caps.get("moduleScore"))
        _ps = _scores.dimension(_Purpose.REQUIREMENT)
        from ..governance.gears import WEAKEST_TIER as _weakest
        if _ps is not None and _ps < PURPOSE_WEAK_SCORE and gear.tier != _weakest:
            from ...arch_routes import llm_dataset as _lds
            _lds.record("comp_gap", purpose="requirement", tier=gear.tier,
                        score=_ps, model=model_id or "")
    except Exception:  # noqa: BLE001
        pass


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
        return ""


def _chat_context(data: dict, gate: dict, skill_scenarios: list, history: list,
                  model_id: str, assign_contract) -> tuple:
    """管线阶段③ 消息装配(行为等价抽取自 handle_chat)。

    角色模型路由(§9/B1 per-call) → 能力档案懒探测 → 分析挡位(十二a) →
    _build_chat_messages + 通用 agent 路由系统段 + assign 契约段。
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
        from ...arch_routes import model_profile as _mp
        _mp.get_profile_or_lazy(eff_model or model_id or "")
    except Exception:  # noqa: BLE001
        pass

    # ── 分析挡位(会话级 analysisMode → 挡位策略, 环节十二a) ──
    try:
        _mode = str((conv or {}).get("analysisMode") or "strict").strip() or "strict"
    except Exception:  # noqa: BLE001
        _mode = "strict"
    try:
        from ...arch_routes.agent_executors import executor_hint_by_id
        _gear_cfg = (executor_hint_by_id(str((conv or {}).get("executorId") or ""),
                                          conv) or {}).get("executorConfig") or {}
    except Exception:  # noqa: BLE001
        _gear_cfg = {}
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
                                ctx_budget=_ctx_budget)
    # v2 统一会话编排契约: 通用 agent 模式——能力分界 + 路由 + 挡位指引(单消息)
    msgs.insert(1, {"role": "system", "content":
        "【工作模式(通用 agent 路由)】你是 architect 外循环(编排者)。可调度资源: "
        "A. 你自己(知识/分析面): " + ("KB 架构资产检索、" if _kb_enabled else "")
        + "需求澄清与方案设计、数据资产、"
        "图/命名/契约/验收等结构化分析。 "
        "B. coding subagent(cline/opencode/codex, 通用执行 agent): 完整的 shell/文件/"
        "读写代码/编译运行能力——代码实现、环境检测、编译构建、文件统计/批量处理、"
        "跑命令、写脚本、任何需要直接对源码或环境动手的通用任务, 一律交给他, "
        "调用 task.propose 创建任务卡(title + instruction 写实质内容: 目标/方案要点/"
        "边界/验收; 工作环境与 DoD 系统注入不必重复)。任务卡默认保存——"
        "用户点「开始执行」启动、可继续对话调整(你会自动更新卡片)或忽略。 "
        "路由原则: 用户的问题不需要本项目知识库就能动手的(如「检测编译环境」"
        "「统计文件数」「跑个脚本」)→ task.propose, 不要用 KB 检索话术推给用户; "
        "需要项目上下文/架构语义的 → 你自己分析。 "
        "意图映射: 用户说「整理成需求卡/提取需求」→ req.propose; "
        "说「执行/开始做」→ 需求已就绪就 task.propose 建卡, 卡已存在则"
        "告知点「开始执行」; 说「调整/补充」→ req.amend。 "
        "执行期间 subagent 的提问/进展/完成会以消息进入本会话, 用户直接回复即转达。"
        "回执与卡片(需求卡/任务卡)已自动落流展示——回答中**不要复述**其标题/方案/"
        "验收等内容, 一句话确认或只补充增量说明即可。 "
        + architect_note_text(_gear)})
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
    return eff_model, msgs, _gear


def _build_chat_messages(root, project, history, cap=20, diagram_skill: bool = False,
                         skill_scenarios: Optional[List[str]] = None,
                         model_id: str = "",
                         tool_surface: str = "full",
                         kb_enabled: bool = True,
                         ctx_budget: float = 1.0):
    """组装 prompt(P4 委托 memory.working, 原文保真; R3.4 透传工具面/预算)。"""
    from ..memory.working import build_chat_messages
    return build_chat_messages(root, project, history, cap=cap,
                               diagram_skill=diagram_skill,
                               skill_scenarios=skill_scenarios, model_id=model_id,
                               tool_surface=tool_surface, kb_enabled=kb_enabled,
                               ctx_budget=ctx_budget)
