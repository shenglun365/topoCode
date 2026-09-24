"""M5 收尾测试(R3.4 对话面接线 / R2.5 同挡微调 / comp_gap 遥测)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_comp_m5.py -q
"""
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.compensation.providers.intratier import (
    intra_tier_note)
from topoone_app_architect.agent.cognition.prompt import (
    capability_doc_from_tools)


# ── R3.4: 工具面裁剪 + 预算系数 ──────────────────────────────────────

def test_r34_full_surface_unchanged():
    doc = capability_doc_from_tools()
    assert "kb.asset.search" in doc and "mcp.call" in doc
    assert "asset.semantic.save" in doc


def test_r34_kb_false_drops_retrieval():
    doc = capability_doc_from_tools(kb_enabled=False)
    assert "kb.asset.search" not in doc and "kb.graph" not in doc
    assert "mcp.call" not in doc                          # cv-189: KB MCP 出向同裁


def test_r34_reduced_drops_writes():
    doc = capability_doc_from_tools(tool_surface="reduced")
    assert "asset.semantic.save" not in doc and "mcp.call" not in doc
    assert "kb.asset.search" in doc                       # 读面保留


def test_r34_minimal_readonly_core():
    doc = capability_doc_from_tools(tool_surface="minimal")
    assert "kb.asset.search" in doc and "code.read_symbols" in doc
    assert "map.rules" not in doc and "kb.graph" not in doc


def test_r34_ctx_budget_coefficient(arch_env, monkeypatch):
    """ctx_budget 系数实消费: 预算 = 基线 × 系数(裁剪更早触发)。"""
    import topoone_app_architect.agent.cognition.prompt as P
    seen = {}

    def _fake_trim(rendered, budget, tier, logger):
        seen["budget"] = budget
        return rendered, []

    monkeypatch.setattr(P, "budget_for", lambda tier: 1000)
    monkeypatch.setattr(
        "topoone_app_architect.agent.compensation.providers.trim_optional_blocks",
        _fake_trim)
    P.render_system({"tier": 1, "ctx_budget": 0.35})
    assert seen["budget"] == 350


# ── R2.5: 同挡密度微调 ───────────────────────────────────────────────

def test_r25_weak_score_denser_note():
    note = intra_tier_note("T2", 0.20)
    assert "更细粒度" in note
    assert intra_tier_note("T1", 0.20) != ""


def test_r25_strong_t2_coarser_note():
    assert "组合推进" in intra_tier_note("T2", 0.80)
    assert intra_tier_note("T1", 0.80) == ""              # T1 偏强不放宽


def test_r25_t0_and_none_noop():
    assert intra_tier_note("T0", 0.10) == ""
    assert intra_tier_note("T2", None) == ""
    assert intra_tier_note("T2", "bad") == ""


def test_r25_assemble_injects_note(arch_env):
    """指令组装注入同挡微调段(T2 + 弱分)。"""
    import dataclasses
    from topoone_app_architect.agent.governance.gears import _TIERS
    from topoone_app_architect.agent.planning.task_plan import (
        assemble_task_instruction)
    task = {"title": "T", "instruction": "做事情"}
    base = assemble_task_instruction(task, policy=_TIERS["T2"])
    tuned = assemble_task_instruction(task, policy=_TIERS["T2"], probe_score=0.20)
    assert "更细粒度" in tuned and "更细粒度" not in base


# ── M5: comp_gap 差距遥测(只记不升挡) ────────────────────────────────

def test_m5_comp_gap_telemetry(arch_env, monkeypatch):
    """A 弱分 + 挡位高于 T2 → 记 comp_gap; 挡位已 T2 → 不记。"""
    from topoone_app_architect.agent.cognition import model_profile as mp
    from topoone_app_architect.agent.turns import context as tctx
    from topoone_app_architect import store
    mp.set_manual_tier("m-gap", 0)                        # A 强挡基线
    gaps = []
    monkeypatch.setattr(
        "topoone_app_architect.agent.reflection.dataset.record",
        lambda kind, **kw: gaps.append(kind) if kind == "comp_gap" else None)
    # 直接构造档案 caps(弱需求分)——绕过探测, 只验遥测判定
    import json as _j
    store.CollabConfigStore.set("llm.modelProfiles", _j.dumps({
        "m-gap": {"modelId": "m-gap", "tier": 0, "source": "manual",
                  "caps": {"requirementScore": 0.20}, "probes": [],
                  "updatedAt": 1}}))
    gate = {"conv": {"analysisMode": "T1"}, "conv_id": "cv-x"}
    data = {"modelId": "m-gap"}
    tctx._chat_context(data, gate, [], [], "m-gap", None)
    assert gaps == ["comp_gap"]
