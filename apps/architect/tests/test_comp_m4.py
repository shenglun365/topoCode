"""M4 验收测试(R3.2 图门禁 / R3.3 JSON 报告双轨 / 链3② harness CallTurn)。

白名单行为变更(开关默认新行为): r3_2_logic_gate / R3.3 双轨解析。

Run: cd <repo> && python -m pytest apps/architect/tests/test_comp_m4.py -q
"""
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.req_agent as _ra
from topoone_app_architect.agent.compensation.providers.milestone import (
    milestone_section)
from topoone_app_architect.arch_routes.session_guide import _GUIDE_SYSTEM  # noqa: F401

_DIAGRAM = "```mermaid\na->b\nb->c\nc->d\nd->e\n```\n"


def _mk_conv(store, **kw):
    return store.ConversationsStore.create({"kind": "generic", "title": "T", **kw})


# ── R3.2: 图门禁(propose_task, T2 显式挡) ─────────────────────────────

def test_r32_gate_rejects_missing_diagram(arch_env, monkeypatch):
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv(store, analysisMode="T2")
    r = eb.propose_task(conv, "T", "实现功能(无图)", executor_hint={"executorType": "cline-sdk"})
    assert not r["ok"] and "逻辑图" in str(r.get("error"))


def test_r32_gate_passes_with_diagram(arch_env):
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv(store, analysisMode="T2")
    r = eb.propose_task(conv, "T", "实现功能\n" + _DIAGRAM,
                        executor_hint={"executorType": "cline-sdk"})
    assert "error" not in r and r.get("id"), r
    assert r["status"] == "pending_confirm"


def test_r32_plan_steps_exempt(arch_env):
    """计划步骤卡豁免图门禁(gate_diagram=False)。"""
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv(store, analysisMode="T2")
    r = eb.propose_task(conv, "T", "步骤指令(无图)",
                        executor_hint={"executorType": "cline-sdk"},
                        gate_diagram=False)
    assert "error" not in r and r.get("id"), r


def test_r32_switch_off_disables_gate(arch_env):
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes import exec_bridge as eb
    store.CollabConfigStore.set("agent.comp.overrides",
                                json.dumps({"r3_2_logic_gate": False}))
    conv = _mk_conv(store, analysisMode="T2")
    r = eb.propose_task(conv, "T", "实现功能(无图)",
                        executor_hint={"executorType": "cline-sdk"})
    assert "error" not in r and r.get("id"), r


def test_r32_t1_not_gated(arch_env):
    """门禁仅 T2(logic_diagram=uml); T1 无图正常建卡。"""
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv(store, analysisMode="T1")
    r = eb.propose_task(conv, "T", "实现功能(无图)",
                        executor_hint={"executorType": "cline-sdk"})
    assert "error" not in r and r.get("id"), r


# ── R3.3: 里程碑报告 JSON 双轨 ────────────────────────────────────────

def test_r33_milestone_section_structured_hint():
    base = milestone_section(structured=False)
    rich = milestone_section(structured=True)
    assert "changed_files" not in base
    assert "changed_files" in rich and "next" in rich


def test_r33_payload_parses_json_block():
    from topoone_app_architect.arch_routes.exec_bridge import (
        _milestone_report_payload, _milestone_report_files)
    text = ('报告\n```json\n{"changed_files": ["src/a.py", "src/b.py"], '
            '"verify": "ok", "next": "全部完成"}\n```\n')
    assert _milestone_report_payload(text) == ["src/a.py", "src/b.py"]
    # 文本轨降级
    legacy = "改动文件: x.py, y.py\n验证: ok\n下一里程碑: 全部完成"
    assert _milestone_report_payload(legacy) == ["x.py", "y.py"]
    assert _milestone_report_files(legacy) == ["x.py", "y.py"]
    assert _milestone_report_payload("无报告") == []


# ── 链3②: harness clarify/collect 经 CallTurn ───────────────────────

def test_clarify_via_call_turn(arch_env, monkeypatch):
    from topoone_app_architect.agent.requirements.harness import req_harness_clarify
    seen = {}

    def _fake_loop(msgs, **kw):
        seen["kw"] = kw
        return {"content": '[{"key": "goal", "label": "目标?", "type": "text", "hint": ""}]',
                "output": None}

    monkeypatch.setattr(_ra, "run_tools_loop", _fake_loop)
    out = req_harness_clarify({"title": "T", "desc": "D"}, "/tmp/x", "proj")
    assert out and out["questions"][0]["key"] == "goal"
    assert out["degraded"] is False
    assert seen["kw"]["mode"] == "chat"


def test_clarify_fallback_static_questions_t2(arch_env, monkeypatch):
    from topoone_app_architect.agent.requirements.harness import req_harness_clarify
    monkeypatch.setattr(_ra, "run_tools_loop",
                        lambda msgs, **kw: {"content": "不是 JSON", "output": None})
    out = req_harness_clarify({"title": "T", "desc": "D"}, "/tmp/x", "proj", tier="T2")
    assert out and out["degraded"] is True
    keys = {q["key"] for q in out["questions"]}
    assert {"goal", "scope", "acceptance"} <= keys


def test_collect_via_call_turn(arch_env, monkeypatch):
    from topoone_app_architect.agent.requirements.harness import req_harness_collect
    payload = {"functionalScope": ["F"], "entityBoundary": [], "assetScope": [],
               "estMin": 30, "implementationPath": "直接实现",
               "assessmentSummary": "可行"}

    def _fake_loop(msgs, **kw):
        assert kw["mode"] == "structured"
        return {"output": payload, "content": ""}

    monkeypatch.setattr(_ra, "run_tools_loop", _fake_loop)
    out = req_harness_collect({"base": {"title": "T"}, "answers": {"goal": "x"}},
                              "/tmp/x", "proj")
    assert out and out["report"]["functionalScope"] == ["F"]
    assert out["degraded"] is False


def test_collect_failure_returns_none(arch_env, monkeypatch):
    from topoone_app_architect.agent.requirements.harness import req_harness_collect
    monkeypatch.setattr(_ra, "run_tools_loop",
                        lambda msgs, **kw: {"output": None, "content": ""})
    assert req_harness_collect({"base": {"title": "T"}, "answers": {}},
                               "/tmp/x", "proj") is None
