"""策略单源回归(2610 挡位体系退役版): 统一策略行恒定 / A·P 轴补偿保留 /
轮次下发注册表优先 / REST 挡位端点退役。

Run: cd <repo> && python -m pytest apps/architect/tests/test_gears.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.agent.governance.gears import (
    UNIFIED_POLICY, default_policy, normalize_mode, resolve_gear)

# ── 解析链(2610 裁决: 恒统一策略行) ──────────────────────────────────

def test_all_modes_collapse_to_unified():
    """挡位退役: quick/strict/auto/T0-T2/未知值/执行器配置 → 恒统一策略(T1 行)。"""
    for mode in ("quick", "strict", "auto", "T0", "T1", "T2", "bogus", ""):
        p = resolve_gear(mode)
        assert p.tier == "T1" and p is not None
    for cfg in ({"capability": "T2"}, {"tierProbed": "T0"}, {}):
        p = resolve_gear("auto", cfg)
        assert p.max_iterations == UNIFIED_POLICY.max_iterations
        assert p.pre_split == UNIFIED_POLICY.pre_split


def test_unified_policy_fields():
    """统一策略 = 原 T1 值: 任务级预拆+结构化指令+工具契约。"""
    p = default_policy()
    assert p.kb is True and p.pre_split == "plan" and p.cadence == "milestone"
    assert p.max_iterations == 800
    assert p.depends_source == "llm" and p.logic_diagram == ""
    assert p.tool_rounds == 4 and p.structured_output is True
    assert p.ctx_budget == 0.6


def test_normalize_mode_legacy_values():
    """legacy 值归一(T3/T4→T2)保留(gate 预置兼容路径)。"""
    assert normalize_mode("T3") == "T2" and normalize_mode("T4") == "T2"
    assert normalize_mode("quick") == "quick" and normalize_mode("") == ""


def test_a_axis_overlay_still_applies():
    """A 轴补偿(architect 模型档案)保留: 不随挡位退役。"""
    from unittest import mock
    from topoone_app_architect.agent.cognition import model_profile as mp
    with mock.patch.object(mp, "tier_of", return_value=2):
        p = resolve_gear("strict", {}, architect_model_id="m-lite")
    assert p.schedule_discipline == "strict_pipeline" and p.element_hints == "high"


# ── 指令组装(统一策略: 无挡位分叉) ────────────────────────────────────

def test_instruction_no_tier_fork():
    from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction
    task = {"title": "T", "instruction": "做"}
    out = assemble_task_instruction(task, "", policy=resolve_gear("T2"))
    assert "步骤序列" not in out          # T2 步骤级编排分叉已退役
    assert default_policy().agent_note in out


def test_milestone_protocol_always_present():
    from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction
    for mode in ("quick", "T1", "T2"):
        text = assemble_task_instruction({"title": "T", "instruction": "x"},
                                         "", policy=resolve_gear(mode))
        assert "里程碑协议" in text and "禁止未提交报告就连续跨里程碑推进" in text


# ── confirm_task: 轮次下发(注册表优先, 策略值兜底) ────────────────────

def _mk_fixture(arch_env, tmp_path, monkeypatch, mode="strict", reg_max=2000):
    conv = store.ConversationsStore.create({
        "projectId": "proj-g", "title": "g", "meta": {"root": str(tmp_path / "p")},
        "analysisMode": mode})
    (tmp_path / "p").mkdir(exist_ok=True)
    from topoone_app_architect.agent.execution import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "p"), "proj-g"))
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex-g", "type": "cline-sdk", "enabled": True,
         "config": {"max_iterations": reg_max, "capability": "T2"}}])
    calls = {"implement": []}

    def _fake_runner(path, payload=None, timeout=12.0):
        calls["implement"].append((path, payload))
        if path == "/api/implement":
            return {"ok": True, "jobId": "job-g", "branch": "task/g",
                    "worktree": str(tmp_path / "wt"), "sessionId": "s",
                    "baseCommit": "sha-g"}
        return {"ok": True}

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    return conv, eb, calls


def test_confirm_registry_iterations_preserved(arch_env, tmp_path, monkeypatch):
    """注册表轮次(用户/护栏调优)不再被挡位封顶——2000 原样下发。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch, mode="T2")
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"}, gate_diagram=False)
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["executorConfig"]["max_iterations"] == 2000


def test_confirm_policy_iterations_fallback(arch_env, tmp_path, monkeypatch):
    """注册表未设轮次 → 统一策略值兜底(800)。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch,
                                  mode="strict", reg_max=0)
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"}, gate_diagram=False)
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["executorConfig"]["max_iterations"] == 800


# ── REST 挡位端点退役 ─────────────────────────────────────────────────

def test_analysis_mode_endpoint_retired(client):
    """挡位端点已退役(2610): 换绑执行器见 /sessions/{id}/executor。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    r = client.post(f"/api/architect/sessions/{conv['id']}/analysis-mode",
                    json={"mode": "T2"})
    assert r.status_code in (404, 405), "挡位切换端点应已下线"


def test_confirm_task_injects_default_mcp(arch_env, tmp_path, monkeypatch):
    """2610 P3: 任务链默认 MCP 同落 executorConfig.mcp_servers(与直通同口径)。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch, mode="strict")
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"}, gate_diagram=False)
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    mcp = pl["executorConfig"].get("mcp_servers")
    assert isinstance(mcp, list) and any(
        e.get("name") == "topo-architect" for e in mcp), \
        "cline 任务下发应含默认 topo-architect MCP(修复: 顶层字段 runner 不读)"
    # 2610 cv-12/14: 任务链与直通同源注入 MCP 工具指引(统筹缺口修补)
    assert "topo-architect MCP 已接线" in pl["instruction"], \
        "任务链 instruction 应含 MCP 工具指引 brief"
