"""M2 缺口收敛测试(R2.1/R2.3/R2.4 + 输出契约/图门禁, 整体设计 §9-M2)。

白名单行为变更项(开关默认新行为):
- R2.1 r2_1_axis_stack: 显式挡 A 轴叠加(quick 豁免); 关闭回退旧短路;
- R2.3 r2_3_probe_fallback: 探针失败 → 文件树/历史边界启发式兜底(零 LLM);
- R2.4: 分目的有效档细化(只降不升, 弱档才触发);
- R3.3 前置: JSON 块/文本双轨解析; R3.2 前置: 核心逻辑图确定性校验。

Run: cd <repo> && python -m pytest apps/architect/tests/test_comp_m2_gaps.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.compensation import (Axis, CapabilityScores,
                                                      CompensationCtx, Purpose,
                                                      resolve_ctx)
from topoone_app_architect.agent.compensation.overrides import (
    override_enabled, read_overrides)
from topoone_app_architect.agent.compensation.providers import (
    parse_json_block, validate_logic_diagram)
from topoone_app_architect.agent.governance.gears import (
    A_AXIS_POLICY, _TIERS, resolve_gear)
from topoone_app_architect.agent.planning.scope_probe import (
    heuristic_scope_fallback)

_ON = {}                                  # 缺省 = 全部新行为
_OFF = {"r2_1_axis_stack": False}


# ── R2.1: 显式挡 A 轴叠加(quick 豁免) ─────────────────────────────────

def test_r2_1_explicit_tier_stacks_a_axis(arch_env, monkeypatch):
    """显式 T1 + A 弱模型(手工档案 T2) → 调度纪律/要素提示升档。"""
    from topoone_app_architect.agent.cognition import model_profile as mp
    mp.set_manual_tier("m-weak", 2)
    discipline, hints = A_AXIS_POLICY[2]
    p = resolve_gear("T1", architect_model_id="m-weak", overrides=_ON)
    assert p.tier == "T1"                       # 挡位不变, 补偿叠加
    assert (p.schedule_discipline, p.element_hints) == (discipline, hints)


def test_r2_1_quick_exempt_from_a_axis(arch_env, monkeypatch):
    """quick 直通车豁免: 零补偿纯净直通(开关语义内写死)。"""
    from topoone_app_architect.agent.cognition import model_profile as mp
    mp.set_manual_tier("m-weak", 2)
    p = resolve_gear("quick", architect_model_id="m-weak", overrides=_ON)
    assert p.tier == "T0"
    assert (p.schedule_discipline, p.element_hints) == \
        (_TIERS["T0"].schedule_discipline, _TIERS["T0"].element_hints)


def test_r2_1_switch_off_reverts_short_circuit(arch_env, monkeypatch):
    """开关关闭 → 回退旧短路: 显式挡跳过 A 轴叠加。"""
    from topoone_app_architect.agent.cognition import model_profile as mp
    mp.set_manual_tier("m-weak", 2)
    p = resolve_gear("T1", architect_model_id="m-weak", overrides=_OFF)
    assert (p.schedule_discipline, p.element_hints) == \
        (_TIERS["T1"].schedule_discipline, _TIERS["T1"].element_hints)


def test_r2_1_no_a_model_keeps_neutral(arch_env):
    """无 A 轴模型 id → 字段保持中性默认(与旧行为一致)。"""
    p = resolve_gear("T1", overrides=_ON)
    assert (p.schedule_discipline, p.element_hints) == \
        (_TIERS["T1"].schedule_discipline, _TIERS["T1"].element_hints)


# ── R2.4: 分目的有效档细化(只降不升) ──────────────────────────────────

def test_r2_4_weak_purpose_downgrades_effective_tier():
    gear = _TIERS["T0"]
    ctx = resolve_ctx(gear, Axis.S, Purpose.EXTRACTION,
                      scores=CapabilityScores(requirement=0.30))
    assert ctx.a_tier == 1                      # T0(idx0) → 有效档 T1(idx1)
    assert ctx.tier == "T0"                     # 策略行不动


def test_r2_4_good_or_missing_score_keeps_tier():
    ctx = resolve_ctx(_TIERS["T1"], Axis.S, Purpose.EXTRACTION,
                      scores=CapabilityScores(requirement=0.75))
    assert ctx.a_tier == 1
    ctx2 = resolve_ctx(_TIERS["T1"], Axis.S, Purpose.EXTRACTION)   # 未探测
    assert ctx2.a_tier == 1


def test_r2_4_floor_at_t2():
    ctx = resolve_ctx(_TIERS["T2"], Axis.S, Purpose.PROBE,
                      scores=CapabilityScores(module=0.10))
    assert ctx.a_tier == 2                      # 已 T2, 封底不再降


# ── R2.3: 探针失败启发式兜底(零 LLM) ──────────────────────────────────

def test_r2_3_heuristic_fallback_tree_and_history(tmp_path, monkeypatch, arch_env):
    import subprocess
    import topoone_app_architect.store as store
    root = str(tmp_path / "repo")
    os.makedirs(f"{root}/src/http", exist_ok=True)
    for f in ("src/http/server.py", "src/http/router.py", "README.md"):
        open(f"{root}/{f}", "w").write("x")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    r = store.RequirementsStore.create({
        "id": store.next_id("RQ"), "kind": "user-story", "status": "draft",
        "title": "旧需求", "priority": "P1", "activeVer": 1,
        "specVersions": [{"ver": 1, "state": "confirmed",
                          "snapshot": {"allowedScope": ["src/http/"]},
                          "source": {}, "reason": "t", "createdAt": 0}],
        "ownerConv": "", "projectId": "", "updatedAt": 0, "createdAt": 0})
    fb = heuristic_scope_fallback(root, "改造 `src/http/server.py` 增加路由导出",
                                  exclude_rid=r["id"])
    assert fb["degraded"] is True and fb["ok"]
    paths = {f["path"] for f in fb["files"]}
    assert "src/http/server.py" in paths        # 文本 token → 文件树命中
    assert any(f["source"] == "tree" for f in fb["files"])


def test_r2_3_empty_repo_returns_not_ok(tmp_path):
    root = str(tmp_path / "empty")
    os.makedirs(root, exist_ok=True)
    fb = heuristic_scope_fallback(root, "无路径提示的需求")
    assert fb["degraded"] is True
    assert isinstance(fb["files"], list)


# ── overrides 开关语义 ────────────────────────────────────────────────

def test_overrides_read_and_defaults():
    assert override_enabled({}, "r2_1_axis_stack") is True       # 缺省新行为
    assert override_enabled({"r2_3_probe_fallback": False},
                            "r2_3_probe_fallback") is False      # 显式回退
    assert read_overrides(None) == {}
    assert read_overrides(lambda k, d: '{"r2_1_axis_stack": false}') == \
        {"r2_1_axis_stack": False}
    assert read_overrides(lambda k, d: "not-json") == {}         # 损坏 → 空表


# ── R3.3/R3.2 前置: 双轨解析与图门禁(确定性函数) ─────────────────────

def test_parse_json_block_dual_track():
    payload, track = parse_json_block('前言\n```json\n{"changed_files": ["a"]}\n```\n')
    assert track == "json" and payload == {"changed_files": ["a"]}
    payload2, track2 = parse_json_block("改动文件: a\n验证: ok\n下一里程碑: 全部完成")
    assert track2 == "text" and payload2 is None


def test_validate_logic_diagram():
    bad = validate_logic_diagram("没有任何图")
    assert bad.passed is False and "围栏" in bad.note
    few = validate_logic_diagram("```mermaid\na->b\n```\n")
    assert few.passed is False and "边数不足" in few.note
    good = validate_logic_diagram(
        "```mermaid\na->b\nb->c\nc->d\nd->e\n```\n")
    assert good.passed is True
