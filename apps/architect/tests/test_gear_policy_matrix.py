"""挡位策略表 M1/M2 维度回归。

M1 实测硬上限: tierProbed 被探针封顶(cap_note 携带); 人工 capability 不封顶;
显式会话挡位不封顶(人的意志优先)。
M2 小模型特化维度: 五维(工具面/上下文预算/指令风格/结构化输出/推理档)随挡声明。

Run: cd <repo> && python -m pytest apps/architect/tests/test_gear_policy_matrix.py -q
"""
from topoone_app_architect.agent.governance.gears import (
    _TIERS, apply_cap, default_policy, probe_hard_cap, resolve_gear)


def test_m2_policy_table_dims():
    """五维随挡全量声明(策略表一行 = 编排参数源, 消费端禁散落分支)。"""
    expect = {
        "T0": ("full", 1.0, "standard", False, "high"),
        "T1": ("full", 1.0, "standard", False, "high"),
        "T2": ("full", 0.6, "structured", True, "medium"),
        "T3": ("reduced", 0.35, "structured", True, "low"),
        "T4": ("minimal", 0.25, "minimal", True, "low"),
    }
    for tid, (surface, budget, style, structured, effort) in expect.items():
        p = _TIERS[tid]
        assert (p.tool_surface, p.ctx_budget, p.prompt_style,
                p.structured_output, p.reasoning_effort) == \
            (surface, budget, style, structured, effort), tid
    assert default_policy().cap_note == ""


def test_m1_apply_cap_semantics():
    """封顶方向: T0 最强/T4 最弱——「上限 T3」把强挡降档, 弱挡不动。"""
    assert apply_cap("T1", "T3") == "T3"
    assert apply_cap("T0", "T3") == "T3"
    assert apply_cap("T4", "T3") == "T4"
    assert apply_cap("T3", "T3") == "T3"


def test_m1_cap_from_probe_detail_string():
    """历史形态: probeDetail 含「上限T3」标记 → 实测档 T1 被降档到 T3。"""
    cfg = {"tierProbed": "T1", "probeScore": 0.8,
           "probeDetail": "3/5(指令跟随否决→上限T3)"}
    policy = resolve_gear("strict", cfg)
    assert policy.tier == "T3"
    assert "指令跟随" in policy.cap_note


def test_m1_cap_from_structured_flags():
    """新形态: 结构化 probeFlags.followGate 优先。"""
    cfg = {"tierProbed": "T2", "probeFlags": {"followGate": True}}
    policy = resolve_gear("auto", cfg)
    assert policy.tier == "T3" and policy.cap_note


def test_m1_manual_capability_not_capped():
    """人工显式 capability 不封顶(人的意志优先); cap 只约束实测来源。"""
    cfg = {"capability": "T1", "probeDetail": "3/5(指令跟随否决→上限T3)"}
    assert resolve_gear("strict", cfg).tier == "T1"


def test_m1_explicit_session_mode_not_capped():
    """用户显式会话挡位(T1/strict→链之外)不被探针封顶。"""
    cfg = {"tierProbed": "T1", "probeFlags": {"followGate": True}}
    assert resolve_gear("T1", cfg).tier == "T1"


def test_m1_cap_not_binding_below_ceiling():
    """实测档已弱于上限(T4) → 原样, 不升不降, cap_note 为空。"""
    cfg = {"tierProbed": "T4", "probeDetail": "2/5(指令跟随否决→上限T3)"}
    policy = resolve_gear("strict", cfg)
    assert policy.tier == "T4" and policy.cap_note == ""


def test_m1_probe_hard_cap_unit():
    assert probe_hard_cap({"probeFlags": {"followGate": True}})[0] == "T3"
    assert probe_hard_cap({"probeDetail": "…否决→上限T3"})[0] == "T3"
    assert probe_hard_cap({"probeDetail": "5/5"}) == (None, "")
    assert probe_hard_cap(None) == (None, "")
