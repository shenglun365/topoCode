"""目标理解层(GU) 特征测试(goal-understanding-2609, GU-1/2/3)。

覆盖: GoalProfile 分类全分支(L0 指令/显式指令/策略库/意图词表 + L1 上下文/
冲突)/决策表默认映射与文案/规则可配置与 fail-soft/policy.goal 校验/
双层人格结构(静态 posture 块 + 动态指引)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_goal_understanding.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.governance import flow_policy as fp
from topoone_app_architect.agent.turns import goal as gu


# ── GU-1: GoalProfile 分类 ────────────────────────────────────────────

def test_profile_command():
    p = gu.build_goal_profile("/执行", {})
    assert p["kind"] == "command" and p["confidence"] == 1.0
    p = gu.build_goal_profile("确认", {"reqId": "RQ-1"})
    assert p["kind"] == "command"


def test_profile_explicit_instruction_is_requirement():
    p = gu.build_goal_profile("按钮UI 修改为 深色", {})
    assert p["kind"] == "requirement" and p["confidence"] == 0.85
    assert "explicit-instruction" in p["sources"]


def test_profile_strategy_hit_unlocks_env_setup_knowledge():
    """cv-217 复形: 环境搭建诉求 → requirement + env_setup 策略(知识解锁)。"""
    p = gu.build_goal_profile("基于项目的定位，先构建开发环境", {})
    assert p["kind"] == "requirement"
    assert p["strategy"] == "env_setup" and p["strategyLabel"]
    assert p["strategyQuestions"]          # 四问随 profile 携带


def test_profile_generic_exec_is_operation():
    p = gu.build_goal_profile("统计一下源码文件数量", {})
    assert p["kind"] == "operation" and "generic-exec" in p["sources"]


def test_profile_boundary_tiebreak_by_strategy_score():
    """撞车记分裁决: 单词撞车→操作; 多词 topical→需求。"""
    assert gu.build_goal_profile("帮我跑个脚本看看", {})["kind"] == "operation"
    p = gu.build_goal_profile("做一个源码数据统计模块", {})
    assert p["kind"] == "requirement" and p["strategy"] == "data_analysis"


def test_profile_continuation_via_bound_req():
    """无 L0 信号 + 绑定需求 → continuation(上下文兜底, 不误判新目标)。"""
    p = gu.build_goal_profile("那验收标准怎么写?", {"reqId": "RQ-9"})
    assert p["kind"] == "continuation" and p["target"] == "req:RQ-9"
    assert p["boundReq"] == "RQ-9"


def test_profile_inquiry_default():
    p = gu.build_goal_profile("mermaid 和 plantuml 各有什么优劣?", {})
    assert p["kind"] == "inquiry"


def test_profile_interrupted_conflict():
    p = gu.build_goal_profile("帮我搭建开发环境", {"flowState": "interrupted"})
    assert p["conflict"] == "phase:interrupted"
    assert gu.build_goal_profile("帮我搭建开发环境", {})["conflict"] is None


def test_profile_kind_not_overridden_by_context():
    """L1 不改写 L0: 绑定需求中途的操作诉求仍是 operation(目标转换不污染)。"""
    p = gu.build_goal_profile("顺便跑一下测试", {"reqId": "RQ-9"})
    assert p["kind"] == "operation" and p["boundReq"] == "RQ-9"


# ── GU-2: 决策表 ──────────────────────────────────────────────────────

def _pol():
    import copy
    return copy.deepcopy(fp.DEFAULT_FLOW_POLICY)


def test_decision_default_mapping():
    pol = _pol()
    p = gu.build_goal_profile("基于项目的定位，先构建开发环境", {})
    r = gu.resolve_goal_directive(p, pol)
    assert r["action"] == "clarify-first"
    assert "先澄清后落卡" in r["text"] and "语言/运行时" in r["text"]  # 策略四问随文
    r = gu.resolve_goal_directive(gu.build_goal_profile("统计一下源码文件数量", {}), pol)
    assert r["action"] == "propose-task" and "task.propose" in r["text"]
    r = gu.resolve_goal_directive(gu.build_goal_profile("那验收怎么写?", {"reqId": "RQ-9"}), pol)
    assert r["action"] == "continue" and "RQ-9" in r["text"]
    r = gu.resolve_goal_directive(gu.build_goal_profile("mermaid 优劣?", {}), pol)
    assert r["action"] == "answer"
    r = gu.resolve_goal_directive({"kind": "requirement", "confidence": 0.3,
                                   "strategy": None, "boundReq": ""}, pol)
    assert r["action"] == "ask-one-question"      # 低置信兜底
    r = gu.resolve_goal_directive(gu.build_goal_profile("/执行", {}), pol)
    assert r["action"] == "passthrough" and r["text"] == ""


def test_decision_configurable_and_fail_soft():
    pol = _pol()
    # 规则可配置: inquiry 也先问
    pol["goal"]["decision"] = [{"when": {"kind": "inquiry"}, "then": "ask-one-question"}]
    r = gu.resolve_goal_directive(gu.build_goal_profile("mermaid 优劣?", {}), pol)
    assert r["action"] == "ask-one-question"
    # 坏规则跳过(未知动作/未知条件键), 兜底 answer
    pol["goal"]["decision"] = [
        {"when": {"kind": "bogus"}, "then": "answer"},
        {"when": {"kind": "inquiry"}, "then": "not-an-action"},
        {"when": {"weird": 1}, "then": "answer"},
    ]
    r = gu.resolve_goal_directive(gu.build_goal_profile("mermaid 优劣?", {}), pol)
    assert r["action"] == "answer"


def test_apply_goal_directive_injects_and_telemetrizes(arch_env):
    msgs = [{"role": "system", "content": "cap"}, {"role": "user", "content": "q"}]
    res = gu.apply_goal_directive(msgs, "基于项目的定位，先构建开发环境", {})
    assert res["action"] == "clarify-first"
    assert any("目标理解" in m["content"] for m in msgs[:2])
    from topoone_app_architect.agent.reflection import dataset as ds
    assert "goal_profile" in ds.stats()["kinds"]
    # passthrough 不注入
    msgs2 = [{"role": "system", "content": "cap"}, {"role": "user", "content": "q"}]
    gu.apply_goal_directive(msgs2, "/执行", {})
    assert all("目标理解" not in m["content"] for m in msgs2)


# ── policy.goal 校验 ──────────────────────────────────────────────────

def test_goal_policy_validation():
    ok, errs = fp.validate_flow_policy({"goal": {"decision": [
        {"when": {"kind": "alien"}, "then": "answer"},
        {"when": {"kind": "inquiry"}, "then": "nope"},
        {"when": {"confidence<": 5}, "then": "answer"},
        {"when": {}},
    ]}})
    assert not ok
    joined = " ".join(errs)
    assert "kind 非法" in joined and "then 非法" in joined \
        and "confidence<" in joined and "非空对象" in joined
    ok, errs = fp.validate_flow_policy({"goal": {
        "decision": [{"when": {"strategy": "*"}, "then": "clarify-first",
                      "with": "strategy"}],
        "directives": {"answer": "自定义文案"},
        "escalation": {"llmFallback": False, "minConfidence": 0.5}}})
    assert ok, errs


# ── GU-3: 双层人格结构 ────────────────────────────────────────────────

def test_static_persona_block_in_capability_doc(arch_env):
    """人格层恒定: posture 判据块进能力文档(与 policy 无关, 不随回合抖动)。"""
    from topoone_app_architect.agent.tools.req_agent import chat_system_prompt
    doc = chat_system_prompt("", "", model_id="")
    assert "对话路线(判据)" in doc and "三问定性" in doc
    assert "不要复述" in doc


def test_routing_segment_retired(arch_env):
    """旧「通用 agent 路由契约」消息退役; 挡位文案保留; 指引由 GU 注入。"""
    from topoone_app_architect.agent.turns import context as ctx_mod
    _, msgs, _ = ctx_mod._chat_context({"root": "", "project": ""},
                                       {"conv": {"analysisMode": "strict"}},
                                       [], [], "", None)
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    assert not any("工作模式(通用 agent 路由)" in s for s in systems)
    # A 轴挡位文案仍在(挡位挡名 + req.propose 指引为 gear note 特征)
    assert any("挡" in s and "req.propose" in s for s in systems)


# ── GU-4/5 批乙: forced 可配置 / 策略库配置化 / L2 ────────────────────

def test_forced_mode_configurable_ask_first():
    """forced 全量先问属运营可配置扩展位(缺省不启用, 见 DEFAULT 注释)。"""
    pol = _pol()
    pol["goal"]["decision"].insert(
        2, {"when": {"kind": "inquiry", "clarifyMode": "forced"},
            "then": "clarify-first"})
    p = gu.build_goal_profile("mermaid 优劣?", {"clarifyMode": "forced"})
    r = gu.resolve_goal_directive(p, pol)
    assert r["action"] == "clarify-first" and "五要素" in r["text"]
    # auto 同消息 → answer(缺省不受影响)
    p2 = gu.build_goal_profile("mermaid 优劣?", {"clarifyMode": "auto"})
    assert gu.resolve_goal_directive(p2, pol)["action"] == "answer"


def test_strategy_library_config_driven_end_to_end(arch_env):
    """D5 端到端: 改策略库配置 → GU 分类与四问随之变化(零发版)。"""
    from topoone_app_architect import store
    store.CollabConfigStore.set(fp.POLICY_KEY, json.dumps({"goal": {
        "strategies": [{"key": "anim", "label": "动画引擎",
                        "kws": ["动画", "关键帧"],
                        "questions": [["目标", "动画驱动方式？"],
                                      ["验收标准", "怎样算播放正确？"]]}]}}))
    p = gu.build_goal_profile("做一个关键帧动画的播放功能", {})
    assert p["kind"] == "requirement" and p["strategy"] == "anim"
    r = gu.resolve_goal_directive(p, fp.load_flow_policy())
    assert "动画引擎" in r["text"] and "动画驱动方式" in r["text"]
    from topoone_app_architect import store as _s
    _s.CollabConfigStore.set(fp.POLICY_KEY, "")


def test_explicit_instruction_exempt_from_clarify_first(arch_env):
    """explicit 指令直接 propose-requirement(免澄清), 策略规则不截胡。"""
    p = gu.build_goal_profile("按钮UI 修改为 深色主题", {})
    assert p["explicit"] is True
    r = gu.resolve_goal_directive(p, fp.load_flow_policy())
    assert r["action"] == "propose-requirement"


# ── GU-6 批丙: 候选菜单 present-options(策略级 + kind 级) ──────────────

def test_kind_level_candidates_on_independent_weak_collision():
    """kind 级弱撞三判据齐备(策略词独立+构建标记+score<2) → 需求 vs 操作菜单。"""
    p = gu.build_goal_profile("写个脚本统计源码文件数量", {})
    assert [c["id"] for c in p["candidates"]] == ["requirement", "operation"]
    assert p["kind"] == "requirement" and p["confidence"] == 0.6
    assert "boundary-ambiguous" in p["sources"]


def test_dependent_collision_stays_operation_no_menu():
    """策略词全被执行词表覆盖(统计一下文件数)→ 维持操作单判, 不僵硬。"""
    for q in ("统计一下文件数", "帮我跑个脚本看看"):
        p = gu.build_goal_profile(q, {})
        assert p["kind"] == "operation" and p["candidates"] == [], q


def test_strategy_level_candidates_on_near_tie():
    """无执行词 + 策略 top-2 分差≤1 → 策略级候选(两类问题集)。"""
    p = gu.build_goal_profile("帮我封装一个上传组件顺便做个图表看板", {})
    ids = [c["id"] for c in p["candidates"]]
    assert len(ids) == 2 and all(i.startswith("strategy:") for i in ids)
    assert p["strategy"] == ids[0].split(":", 1)[1]      # 首候选=当前策略
    assert p["confidence"] == 0.75


def test_strong_signals_never_menu():
    """强命中/单信号不降级为菜单(既有裁决面冻结)。"""
    for q in ("做一个数据统计模块", "搭建开发环境", "做一个源码数据统计模块"):
        p = gu.build_goal_profile(q, {})
        assert p["candidates"] == [], q


def test_present_options_decision_rule_and_text():
    """决策表 {candidates:true} → present-options; 菜单文案含编号候选。"""
    pol = _pol()
    p = gu.build_goal_profile("写个脚本统计源码文件数量", {})
    r = gu.resolve_goal_directive(p, pol)
    assert r["action"] == "present-options"
    assert "需求规约" in r["text"] and "一次性操作" in r["text"]
    assert " 1. " in r["text"] and " 2. " in r["text"]
    # 策略级菜单同样命中(规则置于 clarify-first 前)
    p2 = gu.build_goal_profile("帮我封装一个上传组件顺便做个图表看板", {})
    r2 = gu.resolve_goal_directive(p2, pol)
    assert r2["action"] == "present-options" and "UI/组件封装" in r2["text"]


def test_present_options_converges_next_turn():
    """收敛回路: 菜单后用户答复 → 下回合 GU 重判自然收敛(零新状态)。
    答复命中策略词 → 确定性落 clarify-first; 未命中词表 → answer 兜底
    (指引文案带「浮现开发类诉求收敛为需求规约」, 由模型收敛)。"""
    pol = _pol()
    r1 = gu.resolve_goal_directive(
        gu.build_goal_profile("写个脚本统计源码文件数量", {}), pol)
    assert r1["action"] == "present-options"
    r2 = gu.resolve_goal_directive(
        gu.build_goal_profile("做成项目里常用的数据看板，长期维护", {}), pol)
    assert r2["action"] == "clarify-first"      # 看板→data_analysis 确定性收敛
    r3 = gu.resolve_goal_directive(
        gu.build_goal_profile("做成项目里的功能", {}), pol)
    assert r3["action"] == "answer"             # 词表未中 → 模型面兜底


def test_candidates_when_key_validation():
    """校验器: candidates 布尔合法/非布尔报错/未知键仍拒绝。"""
    ok, errs = fp.validate_flow_policy({"goal": {"decision": [
        {"when": {"candidates": True}, "then": "present-options"}]}})
    assert ok and not errs
    ok, errs = fp.validate_flow_policy({"goal": {"decision": [
        {"when": {"candidates": "yes"}, "then": "present-options"}]}})
    assert not ok and any("candidates" in e for e in errs)


def test_goal_profile_telemetry_carries_candidates(arch_env):
    """遥测面: goal_profile 事件携带候选数与上下文字数。"""
    import json as _json
    msgs = [{"role": "system", "content": "cap"},
            {"role": "user", "content": "之前的讨论"},
            {"role": "user", "content": "写个脚本统计源码文件数量"}]
    res = gu.apply_goal_directive(msgs, "写个脚本统计源码文件数量", {})
    assert res["action"] == "present-options"
    from topoone_app_architect.agent.reflection import dataset as ds
    rows = [_json.loads(x) for x in open(ds._path(), encoding="utf-8")]
    evs = [e for e in rows if e.get("kind") == "goal_profile"]
    assert evs and evs[-1].get("candidates") == 2
    assert "contextChars" in evs[-1]


# ── GU-L2 上下文携带 ──────────────────────────────────────────────────

def test_recent_user_context_extraction():
    """L2 上下文面: msgs 派生最近用户消息, 排除本回合 question。"""
    msgs = [{"role": "system", "content": "cap"},
            {"role": "user", "content": "第一问：项目用什么渲染？"},
            {"role": "assistant", "content": "D3。"},
            {"role": "user", "content": "当前问题"}]
    ctx = gu._recent_user_context(msgs, "当前问题")
    assert "第一问" in ctx and "当前问题" not in ctx
    assert gu._recent_user_context([], "q") == ""


def test_classify_intent_receives_context(arch_env, monkeypatch):
    """L2 接线: llmFallback 开启时 classify_intent 收到 msgs 派生上下文,
    generic_exec 高置信 → 升格 operation(llm 源)。"""
    seen = {}

    def _fake_classify(q, context=""):
        seen["q"], seen["ctx"] = q, context
        return {"intent": "generic_exec", "confidence": 0.9}

    import topoone_app_architect.agent.turns.intent_llm as il
    monkeypatch.setattr(il, "classify_intent", _fake_classify)
    pol = _pol()
    pol["goal"]["escalation"]["llmFallback"] = True
    msgs = [{"role": "system", "content": "cap"},
            {"role": "user", "content": "先看看仓库结构"},
            {"role": "user", "content": "帮我看看这个仓库"}]
    res = gu.apply_goal_directive(msgs, "帮我看看这个仓库", {}, pol=pol)
    assert seen["ctx"] and "先看看仓库结构" in seen["ctx"]
    assert seen["ctx"].find("帮我看看这个仓库") == -1   # 本回合问题不入上下文
    assert res["profile"]["kind"] == "operation"
    assert res["profile"]["sources"][-1] == "llm"


def test_l2_off_by_default_no_behavior_change():
    """llmFallback 缺省关: 同输入不产生 llm 源(保守面冻结)。"""
    p = gu.build_goal_profile("帮我看看这个仓库", {})
    assert p["kind"] == "inquiry" and "llm" not in p["sources"]
