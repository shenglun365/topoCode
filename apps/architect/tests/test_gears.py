"""挡位体系(环节十二a, 刻度 T0-T2)回归: 解析链 / 指令分叉 / 轮次下发 / REST。

Run: cd <repo> && python -m pytest apps/architect/tests/test_gears.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.agent.governance.gears import (
    GEAR_MODES, default_policy, gear_note, normalize_mode, resolve_gear)

# ── 解析链 ───────────────────────────────────────────────────────────

def test_quick_pins_t0():
    p = resolve_gear("quick")
    assert p.tier == "T0" and p.kb is False


def test_strict_is_auto():
    assert resolve_gear("strict").tier == "T1"          # 无执行器配置 → 默认 T1
    assert resolve_gear("strict", {"capability": "T2"}).tier == "T2"


def test_legacy_tier_values_normalized():
    """旧刻度(T3/T4)在解析链/写侧归一为 T2。"""
    assert resolve_gear("strict", {"capability": "T3"}).tier == "T2"
    assert resolve_gear("T4").tier == "T2"
    assert normalize_mode("T3") == "T2" and normalize_mode("T4") == "T2"


def test_auto_prefers_probed_over_capability():
    cfg = {"capability": "T0", "tierProbed": "T2"}
    assert resolve_gear("auto", cfg).tier == "T2"
    assert resolve_gear("auto", {"capability": "T2"}).tier == "T2"
    assert resolve_gear("auto", {}).tier == "T1"
    assert resolve_gear("auto").tier == "T1"


def test_invalid_values_fall_to_default():
    assert resolve_gear("auto", {"capability": "T9"}).tier == "T1"
    assert resolve_gear("bogus").tier == "T1"
    assert resolve_gear("").tier == "T1"


def test_pinned_tier():
    assert resolve_gear("T2").tier == "T2"
    assert resolve_gear("T2", {"capability": "T0"}).tier == "T2"  # 钉死优先于配置


def test_policy_fields_data_driven():
    t2 = resolve_gear("T2")
    assert t2.pre_split == "steps" and t2.cadence == "key_step"
    assert t2.max_iterations == 300
    assert t2.depends_source == "linear" and t2.logic_diagram == "uml"
    assert resolve_gear("T0").max_iterations == 2000
    assert resolve_gear("T1").depends_source == "llm"


def test_gear_modes_whitelist_and_note():
    assert set(GEAR_MODES) == {"strict", "quick", "auto", "T0", "T1", "T2"}
    assert "T0" in gear_note("quick") and gear_note("T2").startswith("挡位 T2")


# ── 指令按挡分叉 ─────────────────────────────────────────────────────

def test_instruction_fork_by_tier():
    from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction
    task = {"title": "T", "instruction": "做"}
    t2 = assemble_task_instruction(task, "", policy=resolve_gear("T2"))
    assert "步骤序列" in t2 and "执行方式（按任务挡位）" in t2
    t0 = assemble_task_instruction(task, "", policy=resolve_gear("quick"))
    assert "自主推进" in t0
    assert "步骤序列" not in t0
    default = assemble_task_instruction(task, "")
    assert default_policy().agent_note in default          # None → 默认档


def test_milestone_protocol_always_present():
    from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction
    for mode in ("quick", "T1", "T2"):
        text = assemble_task_instruction({"title": "T", "instruction": "x"},
                                         "", policy=resolve_gear(mode))
        assert "里程碑协议" in text and "禁止未提交报告就连续跨里程碑推进" in text


# ── confirm_task: 轮次随挡下发 + 指令分叉 ────────────────────────────

def _mk_fixture(arch_env, tmp_path, monkeypatch, mode="T2"):
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
         "config": {"max_iterations": 2000, "capability": "T2"}}])
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


def test_confirm_tier_iterations_injected(arch_env, tmp_path, monkeypatch):
    """会话钉 T2 → 任务级轮次 300 覆盖注册表 2000; 指令含步骤编排段。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch, mode="T2")
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"}, gate_diagram=False)
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["executorConfig"]["max_iterations"] == 300
    assert "步骤序列" in pl["instruction"]


def test_confirm_quick_mode_registry_iterations(arch_env, tmp_path, monkeypatch):
    """quick(T0) → 2000; 注册表 capability=T1 不影响钉死的 quick。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch, mode="quick")
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"}, gate_diagram=False)
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["executorConfig"]["max_iterations"] == 2000


def test_confirm_auto_uses_executor_capability(arch_env, tmp_path, monkeypatch):
    """strict(=auto) + 执行器 capability=T2 → 轮次 300。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch, mode="strict")
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"}, gate_diagram=False)
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["executorConfig"]["max_iterations"] == 300
    assert "关键步骤" in pl["instruction"]


# ── REST 白名单 ──────────────────────────────────────────────────────

def test_analysis_mode_rest_accepts_tiers_and_legacy(client):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    r = client.post(f"/api/architect/sessions/{conv['id']}/analysis-mode",
                    json={"mode": "T2"})
    assert r.status_code == 200
    assert store.ConversationsStore.get(conv["id"])["analysisMode"] == "T2"
    # 旧刻度 T3/T4 归一为 T2 后接受
    r = client.post(f"/api/architect/sessions/{conv['id']}/analysis-mode",
                    json={"mode": "T3"})
    assert r.status_code == 200
    assert store.ConversationsStore.get(conv["id"])["analysisMode"] == "T2"
    r = client.post(f"/api/architect/sessions/{conv['id']}/analysis-mode",
                    json={"mode": "bogus"})
    assert r.status_code == 400


def test_tool_rounds_by_tier():
    """M4-B: chat 侧工具轮次按挡——强/中挡保持现行为 4, 弱挡更早触顶(损失有界)。"""
    from topoone_app_architect.agent.governance.gears import _TIERS, resolve_gear
    assert resolve_gear("quick", {}).tool_rounds == 4      # T0 现行为不变
    assert resolve_gear("strict", {}).tool_rounds == 4     # T1 现行为不变
    assert _TIERS["T2"].tool_rounds == 3
    # 封顶链(replace 只改 tier 字段): T1 被封顶为 T2 时轮次保持 T1 现值(既有语义)
    capped = resolve_gear("strict", {"tierProbed": "T1",
                                     "probeDetail": "指令跟随探针未过——上限T3"})
    assert capped.tier == "T2" and capped.tool_rounds == 4
