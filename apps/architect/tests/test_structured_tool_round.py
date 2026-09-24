"""M4-A 受限生成: architect 侧 structured 通道(支持位/单轮/循环降级)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_structured_tool_round.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.agent.tools.protocol import TOOL_CALL_SCHEMA  # noqa: E402
from topoone_app_architect import store  # noqa: E402
from topoone_app_architect.arch_routes import req_agent


def _setup_env(tmp_path, monkeypatch):
    import topoone_app_architect.ctx as C
    data = str(tmp_path / "d")
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)


def test_tool_call_schema_shape():
    """单调用/轮 schema: tool 必填 + arguments 对象。"""
    assert TOOL_CALL_SCHEMA["required"] == ["tool"]
    assert TOOL_CALL_SCHEMA["properties"]["arguments"]["type"] == "object"


def test_structured_model_enabled_config(tmp_path, monkeypatch):
    """支持位单源: CollabConfig 键 llm.structuredModels(JSON 数组)。"""
    _setup_env(tmp_path, monkeypatch)
    assert req_agent.structured_model_enabled("m1") is False
    store.CollabConfigStore.set("llm.structuredModels",
                                json.dumps(["m1", "m2"]))
    assert req_agent.structured_model_enabled("m1") is True
    assert req_agent.structured_model_enabled("m9") is False


def test_structured_tool_round_parses_output(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    captured = {}

    def fake_llm_sync(msgs, **kw):
        captured.update(kw)
        return {"content": '{"tool":"kb.baseline"}',
                "mode": "structured",
                "output": {"tool": "kb.baseline", "arguments": {}}}

    monkeypatch.setattr(req_agent, "llm_sync", fake_llm_sync)
    out = req_agent.structured_tool_round([], "m1")
    assert captured["mode"] == "structured"
    assert captured["output_schema"] == TOOL_CALL_SCHEMA
    assert out["calls"] == [{"tool": "kb.baseline", "arguments": {}}]
    assert out["error"] == ""


def test_structured_tool_round_error_surface(tmp_path, monkeypatch):
    """校验失败显式上抛(error 字段)——不静默吞。"""
    _setup_env(tmp_path, monkeypatch)
    monkeypatch.setattr(req_agent, "llm_sync", lambda *a, **k: {
        "content": "not json", "mode": "structured",
        "output": None, "structuredError": "schema mismatch"})
    out = req_agent.structured_tool_round([], "m1")
    assert out["error"] == "schema mismatch" and out["calls"] == []


def test_run_tools_loop_structured_then_final(tmp_path, monkeypatch):
    """双通道循环: 受限轮执行工具 → 空 tool 转终稿轮(普通模式) → 返回散文。"""
    _setup_env(tmp_path, monkeypatch)
    store.CollabConfigStore.set("llm.structuredModels", json.dumps(["m1"]))
    rounds = []

    def fake_llm_sync(msgs, **kw):
        rounds.append(kw.get("mode"))
        if kw.get("mode") == "structured":
            if len([m for m in rounds]) == 1:
                return {"content": "{}", "output":
                        {"tool": "kb.baseline", "arguments": {}}}
            return {"content": "{}", "output": {"tool": "", "arguments": {}}}
        return {"content": "最终答案：基线在 main 分支。"}

    monkeypatch.setattr(req_agent, "llm_sync", fake_llm_sync)
    executed = []
    monkeypatch.setattr(req_agent, "run_arch_tool",
                        lambda name, args, root, project:
                        executed.append(name) or {"baseline": {}})
    out = req_agent.run_tools_loop([{"role": "user", "content": "q"}],
                                   model_id="m1", tool_schema=TOOL_CALL_SCHEMA)
    assert executed == ["kb.baseline"]
    assert rounds == ["structured", "structured", "chat"]
    assert out["content"] == "最终答案：基线在 main 分支。"


def test_run_tools_loop_structured_error_falls_back(tmp_path, monkeypatch):
    """structured 失败 → nudge 后本循环降级文本协议(不静默, 仍出答案)。"""
    _setup_env(tmp_path, monkeypatch)
    store.CollabConfigStore.set("llm.structuredModels", json.dumps(["m1"]))
    modes = []
    seen_msgs = []

    def fake_llm_sync(msgs, **kw):
        modes.append(kw.get("mode"))
        seen_msgs.append([m.get("content") for m in msgs])
        if kw.get("mode") == "structured":
            return {"content": "bad", "output": None,
                    "structuredError": "schema mismatch"}
        return {"content": "文本协议答案。"}

    monkeypatch.setattr(req_agent, "llm_sync", fake_llm_sync)
    out = req_agent.run_tools_loop([{"role": "user", "content": "q"}],
                                   model_id="m1", tool_schema=TOOL_CALL_SCHEMA)
    assert modes == ["structured", "chat"]
    assert out["content"] == "文本协议答案。"
    # nudge 提示已注入消息流(降级可见而非静默)
    assert any(any("结构化工具调用未成功" in (c or "") for c in batch)
               for batch in seen_msgs)
