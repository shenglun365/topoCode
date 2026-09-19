"""挡位策略表 M1/M2 维度回归（刻度 T0-T2, 2026-09-17 三维矩阵收敛）。

M1 实测硬上限: tierProbed 被探针封顶(cap_note 携带); 人工 capability 不封顶;
显式会话挡位不封顶(人的意志优先)。
M2 小模型特化维度: 维度随挡声明(策略表一行 = 编排参数源, 消费端禁散落分支)。
职责归属(C)=执行器模型能力驱动; depends_source/logic_diagram 为 A2/三维矩阵新维度。

Run: cd <repo> && python -m pytest apps/architect/tests/test_gear_policy_matrix.py -q
"""
from topoone_app_architect.agent.governance.gears import (
    _TIERS, apply_cap, default_policy, normalize_mode, probe_hard_cap,
    resolve_gear)


def test_m2_policy_table_dims():
    """维度随挡全量声明(T0 直出 / T1 任务级预拆 / T2 全面补偿)。

    D11(2026-09-19): reasoning_effort 迁出 GearPolicy——推理强度属模型能力
    属性(探测支持位)+用户自选, 不随挡位(见 agent-capability-design §5.2)。"""
    expect = {
        # (surface, budget, style, structured)
        "T0": ("full", 1.0, "standard", False),
        "T1": ("full", 0.6, "structured", True),
        "T2": ("reduced", 0.35, "structured", True),
    }
    for tid, (surface, budget, style, structured) in expect.items():
        p = _TIERS[tid]
        assert (p.tool_surface, p.ctx_budget, p.prompt_style,
                p.structured_output) == (surface, budget, style, structured), tid
    assert default_policy().cap_note == ""
    assert not hasattr(_TIERS["T0"], "reasoning_effort")   # D11 迁出守恒


def test_m3_matrix_attribution_fields():
    """三维矩阵新增字段: 职责归属(C) 直推——T0/T1 产依赖图, T2 线性链+核心逻辑图。"""
    assert _TIERS["T0"].depends_source == "llm"
    assert _TIERS["T1"].depends_source == "llm"
    assert _TIERS["T2"].depends_source == "linear"
    assert _TIERS["T2"].logic_diagram == "uml"
    assert _TIERS["T1"].logic_diagram == ""
    assert _TIERS["T2"].pre_split == "steps"


def test_legacy_tier_mapping():
    """旧刻度归一: T0/T1 不变, 旧 T2/T3/T4 → T2(读路径)。"""
    assert normalize_mode("T0") == "T0"
    assert normalize_mode("T1") == "T1"
    assert normalize_mode("T2") == "T2"
    assert normalize_mode("T3") == "T2"
    assert normalize_mode("T4") == "T2"
    assert normalize_mode("strict") == "strict"


def test_m1_apply_cap_semantics():
    """封顶方向: T0 最强/T2 最弱——「上限 T2」把强挡降档, 弱挡不动。"""
    assert apply_cap("T1", "T2") == "T2"
    assert apply_cap("T0", "T2") == "T2"
    assert apply_cap("T2", "T2") == "T2"


def test_m1_cap_from_probe_detail_string():
    """历史形态: probeDetail 含旧「上限T3」标记 → 实测档 T1 被降档到 T2。"""
    cfg = {"tierProbed": "T1", "probeScore": 0.8,
           "probeDetail": "3/5(指令跟随否决→上限T3)"}
    policy = resolve_gear("strict", cfg)
    assert policy.tier == "T2"
    assert "指令跟随" in policy.cap_note


def test_m1_cap_from_structured_flags():
    """新形态: 结构化 probeFlags.followGate 优先(实测 T1 被封顶到 T2)。"""
    cfg = {"tierProbed": "T1", "probeFlags": {"followGate": True}}
    policy = resolve_gear("auto", cfg)
    assert policy.tier == "T2" and policy.cap_note


def test_m1_manual_capability_not_capped():
    """人工显式 capability 不封顶(人的意志优先); cap 只约束实测来源。"""
    cfg = {"capability": "T1", "probeDetail": "3/5(指令跟随否决→上限T3)"}
    assert resolve_gear("strict", cfg).tier == "T1"


def test_m1_explicit_session_mode_not_capped():
    """用户显式会话挡位(T1/strict→链之外)不被探针封顶。"""
    cfg = {"tierProbed": "T1", "probeFlags": {"followGate": True}}
    assert resolve_gear("T1", cfg).tier == "T1"


def test_legacy_tierprobed_normalized_in_resolve():
    """存量 tierProbed 旧值(T3/T4)在解析链归一为 T2。"""
    assert resolve_gear("strict", {"tierProbed": "T3"}).tier == "T2"
    assert resolve_gear("strict", {"tierProbed": "T4"}).tier == "T2"


def test_m1_cap_not_binding_below_ceiling():
    """实测档已弱于上限(T2) → 原样, 不升不降, cap_note 为空。"""
    cfg = {"tierProbed": "T2", "probeDetail": "2/5(指令跟随否决→上限T3)"}
    policy = resolve_gear("strict", cfg)
    assert policy.tier == "T2" and policy.cap_note == ""


def test_m1_probe_hard_cap_unit():
    assert probe_hard_cap({"probeFlags": {"followGate": True}})[0] == "T2"
    assert probe_hard_cap({"probeDetail": "…否决→上限T3"})[0] == "T2"
    assert probe_hard_cap({"probeDetail": "…上限T2"})[0] == "T2"
    assert probe_hard_cap({"probeDetail": "5/5"}) == (None, "")
    assert probe_hard_cap(None) == (None, "")


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
