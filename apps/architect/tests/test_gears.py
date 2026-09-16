"""挡位体系(环节十二a)回归: 解析链 / 指令分叉 / 轮次下发 / REST 白名单。

Run: cd <repo> && python -m pytest apps/architect/tests/test_gears.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import store
from topoone_app_architect.agent.governance.gears import (
    GEAR_MODES, default_policy, gear_note, resolve_gear)

# ── 解析链 ───────────────────────────────────────────────────────────

def test_quick_pins_t0():
    p = resolve_gear("quick")
    assert p.tier == "T0" and p.kb is False


def test_strict_is_auto():
    assert resolve_gear("strict").tier == "T1"          # 无执行器配置 → 默认 T1
    assert resolve_gear("strict", {"capability": "T3"}).tier == "T3"


def test_auto_prefers_probed_over_capability():
    cfg = {"capability": "T1", "tierProbed": "T2"}
    assert resolve_gear("auto", cfg).tier == "T2"
    assert resolve_gear("auto", {"capability": "T3"}).tier == "T3"
    assert resolve_gear("auto", {}).tier == "T1"
    assert resolve_gear("auto").tier == "T1"


def test_invalid_values_fall_to_default():
    assert resolve_gear("auto", {"capability": "T9"}).tier == "T1"
    assert resolve_gear("bogus").tier == "T1"
    assert resolve_gear("").tier == "T1"


def test_pinned_tier():
    assert resolve_gear("T4").tier == "T4"
    assert resolve_gear("T2", {"capability": "T0"}).tier == "T2"  # 钉死优先于配置


def test_policy_fields_data_driven():
    t3 = resolve_gear("T3")
    assert t3.pre_split == "steps" and t3.cadence == "key_step"
    assert t3.max_iterations == 300
    assert resolve_gear("T0").max_iterations == 2000
    assert resolve_gear("T4").cadence == "every_step"


def test_gear_modes_whitelist_and_note():
    assert set(GEAR_MODES) == {"strict", "quick", "auto", "T0", "T1", "T2", "T3", "T4"}
    assert "T0" in gear_note("quick") and gear_note("T2").startswith("挡位 T2")


# ── 指令按挡分叉 ─────────────────────────────────────────────────────

def test_instruction_fork_by_tier():
    from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction
    task = {"title": "T", "instruction": "做"}
    t4 = assemble_task_instruction(task, "", policy=resolve_gear("T4"))
    assert "微步模式" in t4 and "执行方式（按任务挡位）" in t4
    t0 = assemble_task_instruction(task, "", policy=resolve_gear("quick"))
    assert "自主推进" in t0
    assert "微步模式" not in t0
    default = assemble_task_instruction(task, "")
    assert default_policy().agent_note in default          # None → 默认档


def test_milestone_protocol_always_present():
    from topoone_app_architect.agent.planning.task_plan import assemble_task_instruction
    for mode in ("quick", "T1", "T4"):
        text = assemble_task_instruction({"title": "T", "instruction": "x"},
                                         "", policy=resolve_gear(mode))
        assert "里程碑协议" in text and "禁止未提交报告就连续跨里程碑推进" in text


# ── confirm_task: 轮次随挡下发 + 指令分叉 ────────────────────────────

def _mk_fixture(arch_env, tmp_path, monkeypatch, mode="T4"):
    conv = store.ConversationsStore.create({
        "projectId": "proj-g", "title": "g", "meta": {"root": str(tmp_path / "p")},
        "analysisMode": mode})
    (tmp_path / "p").mkdir(exist_ok=True)
    from topoone_app_architect.arch_routes import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "p"), "proj-g"))
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex-g", "type": "cline-sdk", "enabled": True,
         "config": {"max_iterations": 2000, "capability": "T3"}}])
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
    """会话钉 T4 → 任务级轮次 100 覆盖注册表 2000; 指令含微步段。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch, mode="T4")
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"})
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["executorConfig"]["max_iterations"] == 100
    assert "微步模式" in pl["instruction"]


def test_confirm_quick_mode_registry_iterations(arch_env, tmp_path, monkeypatch):
    """quick(T0) → 2000; 注册表 capability=T1 不影响钉死的 quick。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch, mode="quick")
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"})
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["executorConfig"]["max_iterations"] == 2000


def test_confirm_auto_uses_executor_capability(arch_env, tmp_path, monkeypatch):
    """strict(=auto) + 执行器 capability=T3 → 轮次 300。"""
    conv, eb, calls = _mk_fixture(arch_env, tmp_path, monkeypatch, mode="strict")
    task = eb.propose_task(conv, "T", "x", {"executorType": "cline-sdk",
                                            "executorId": "ex-g"})
    assert eb.confirm_task(task["id"])["ok"]
    pl = [pl for p, pl in calls["implement"] if p == "/api/implement"][0]
    assert pl["executorConfig"]["max_iterations"] == 300
    assert "关键步骤" in pl["instruction"]


# ── REST 白名单 ──────────────────────────────────────────────────────

def test_analysis_mode_rest_accepts_tiers(client):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    r = client.post(f"/api/architect/sessions/{conv['id']}/analysis-mode",
                    json={"mode": "T2"})
    assert r.status_code == 200
    assert store.ConversationsStore.get(conv["id"])["analysisMode"] == "T2"
    r = client.post(f"/api/architect/sessions/{conv['id']}/analysis-mode",
                    json={"mode": "bogus"})
    assert r.status_code == 400
