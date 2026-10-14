"""策略矩阵回归(2610 挡位退役版): 统一策略行维度 / A 轴补偿 / legacy 归一。

退役面: T0-T2 挡位策略表分叉与 M1 实测封顶(probe_hard_cap/apply_cap)——
显性挡位设置与按档策略限制均已取消(用户裁决 2026-10-11)。
保留面: A 轴(architect 模型档案)补偿 / U 轴要素提示 / legacy 值归一。

Run: cd <repo> && python -m pytest apps/architect/tests/test_gear_policy_matrix.py -q
"""
from topoone_app_architect.agent.governance.gears import (
    UNIFIED_POLICY, default_policy, normalize_mode, resolve_gear)


def test_unified_policy_dims():
    """统一策略行(原 T1 值)全量维度声明。

    D11(2026-09-19): reasoning_effort 迁出 GearPolicy——推理强度属模型能力
    属性(探测支持位)+用户自选, 不随策略(见 agent-capability-design §5.2)。"""
    p = UNIFIED_POLICY
    assert (p.tool_surface, p.ctx_budget, p.prompt_style,
            p.structured_output) == ("full", 0.6, "structured", True)
    assert default_policy() is p or default_policy().tier == "T1"
    assert default_policy().cap_note == ""
    assert not hasattr(p, "reasoning_effort")   # D11 迁出守恒


def test_executor_cfg_no_longer_selects_policy():
    """挡位退役: 执行器 capability/tierProbed 不再驱动策略选择(模型档案仅展示)。"""
    for cfg in ({"capability": "T0"}, {"tierProbed": "T2"},
                {"tierProbed": "T1", "probeFlags": {"followGate": True}},
                {"capability": "T1", "probeDetail": "3/5(指令跟随否决→上限T3)"}):
        p = resolve_gear("strict", cfg)
        assert p.tier == "T1" and p.cap_note == ""
        assert p.max_iterations == UNIFIED_POLICY.max_iterations


def test_legacy_tier_mapping():
    """旧刻度归一保留(gate 预置兼容路径): T3/T4 → T2。"""
    assert normalize_mode("T0") == "T0"
    assert normalize_mode("T1") == "T1"
    assert normalize_mode("T2") == "T2"
    assert normalize_mode("T3") == "T2"
    assert normalize_mode("T4") == "T2"
    assert normalize_mode("strict") == "strict"


def test_a_axis_fields_from_architect_profile(tmp_path, monkeypatch):
    """A 轴补偿: architect 模型档案弱档 → 调度纪律+要素提示升档; 无档案中性默认。"""
    from topoone_app_architect.agent.governance import gears
    from topoone_app_architect.agent.cognition import model_profile as mp
    # 无模型 id → 中性默认(现行为)
    p = gears.resolve_gear("strict", {})
    assert p.schedule_discipline == "standard" and p.element_hints == "low"
    # A2 弱档档案 → strict_pipeline + high(函数内 from-import 命中同一模块对象)
    monkeypatch.setattr(mp, "tier_of", lambda mid: 2)
    p2 = gears.resolve_gear("strict", {}, architect_model_id="m-lite")
    assert p2.schedule_discipline == "strict_pipeline"
    assert p2.element_hints == "high"
    # A0 强档 → 中性
    monkeypatch.setattr(mp, "tier_of", lambda mid: 0)
    p3 = gears.resolve_gear("strict", {}, architect_model_id="m-strong")
    assert p3.schedule_discipline == "standard" and p3.element_hints == "low"


def test_element_hints_injected_by_a_axis(monkeypatch):
    """U 轴: A 弱 → 高密度要素提示进对话系统段; A 强 → 无提示。"""
    from topoone_app_architect.agent.cognition import model_profile as mp
    from topoone_app_architect.agent.governance import gears
    from topoone_app_architect.agent.governance.gears import (
        ELEMENT_HINT_HIGH, ELEMENT_HINT_MID)
    assert "①目标" in ELEMENT_HINT_HIGH and "验收标准" in ELEMENT_HINT_HIGH
    monkeypatch.setattr(mp, "tier_of", lambda mid: 2)
    p2 = gears.resolve_gear("strict", {}, architect_model_id="m-lite")
    assert p2.element_hints == "high"
    monkeypatch.setattr(mp, "tier_of", lambda mid: 1)
    p1 = gears.resolve_gear("strict", {}, architect_model_id="m-mid")
    assert p1.element_hints == "mid"
