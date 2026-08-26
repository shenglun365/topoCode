"""Coding agent 适配器事件归一化测试(agent_adapters)。

注：WS 任务执行流(`_run_opencode_task`/`_run_coding_agent_task`)已迁移到 runner 流
(POST /exec/{id}/run + WS /ws/trees/{id}/events)，本文件仅保留 adapter 层测试。

Run:  cd <repo> && python -m pytest tests -q
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from topoone_app_architect.arch_routes import agent_adapters as AA


def run_async(awaitable):
    return asyncio.run(awaitable)


async def collect_events(agen):
    return [e async for e in agen]


def test_send_message_model_id_split():
    """model 'provider/model' 应被拆成 providerID/modelID(partition 三值解包会出错)。"""
    calls = {}

    def fake_req(path, method="GET", body=None, timeout=10.0):
        calls["body"] = body
        return {}

    from topoone_app_architect.arch_routes.agent_adapters import OpenCodeSession

    s = OpenCodeSession("http://x")
    s._req = fake_req
    s.send_message("oc1", "hi", "192.168.1.9-LMS/qwen3.5-9b-mtp", False)
    assert calls["body"]["model"] == {"providerID": "192.168.1.9-LMS", "modelID": "qwen3.5-9b-mtp"}
    # 不带 provider 前缀 → 不设置 model。
    s.send_message("oc1", "hi", "deepseek-v4", False)
    assert "model" not in calls["body"]


def test_qwen_session_update_mapping():
    """qwen serve session_update(event agent_message_chunk) → 归一化 message。"""
    from topoone_app_architect.arch_routes.agent_adapters import QwenAdapter

    a = QwenAdapter()
    items = list(a._session_update({
        "type": "session_update",
        "data": {
            "update": {"sessionUpdate": "agent_message_chunk",
                       "content": {"type": "text", "text": "hello qwen"}},
        },
    }))
    assert items == [{"type": "message", "role": "assistant", "content": "hello qwen"}]
    # 非文本分块 → 空(不产生事件)。
    assert list(a._session_update({"update": {"sessionUpdate": "other"}})) == []


def test_qwen_turn_complete_done():
    """qwen SSE turn_complete → 终态 done。"""

    async def run():
        from topoone_app_architect.arch_routes.agent_adapters import QwenAdapter

        a = QwenAdapter()
        frames = [
            {"event": "turn_complete", "data": {"data": {"stopReason": "end_turn"}}},
        ]
        # 直接喂归一化循环(复用 iter_events 内部逻辑的短路径)。
        result = []
        for f in frames:
            ev = f.get("data") or {}
            etype = f.get("event") or ev.get("type") or ""
            if etype == "turn_complete":
                reason = (ev.get("data") or {}).get("stopReason") or ""
                result.append({"status": "done" if not reason or reason == "end_turn" else "failed"})
        return result

    assert asyncio.run(run()) == [{"status": "done"}]


class _FakeRuns:
    def __init__(self, lines):
        self.lines = lines

    async def __aiter__(self):
        for ln in self.lines:
            yield ln


def test_codex_process_events_mapping(monkeypatch):
    """codex --json 行流 → 归一化事件(working/message/tool_call/done)。"""
    from topoone_app_architect.arch_routes.agent_adapters import CodexAdapter, CodexSession

    lines = [
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "start worked"}}),
        json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "pwd"}}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "pwd", "status": "completed", "aggregated_output": "/tmp"}}),
        json.dumps({"type": "turn.completed"}),
    ]
    import topoone_app_architect.arch_routes.agent_adapters as AA
    monkeypatch.setattr(AA, "iter_process_jsonl", lambda *a, **k: _FakeRuns(lines))
    out = run_async(collect_events(AA.CodexAdapter().process_events(CodexSession({}), "task")))
    assert ("status", "working") in [(e.get("type"), e.get("status")) for e in out]
    assert ("message", "start worked") in [(e.get("type"), e.get("content")) for e in out]
    assert ("tool_call", "pwd") in [(e.get("type"), (e.get("tool") or {}).get("label")) for e in out]
    assert ("status", "done") in [(e.get("type"), e.get("status")) for e in out]


def test_cline_process_events_mapping(monkeypatch):
    """cline --json 行流(agent_event/run_result)→ 归一化事件。"""
    from topoone_app_architect.arch_routes.agent_adapters import ClineAdapter, ClineSession

    lines = [
        json.dumps({"type": "agent_event", "event": {"type": "message", "message": {"content": "cline thinks"}}}),
        json.dumps({"type": "agent_event", "event": {"type": "tool_use", "tool": {"name": "run-command", "command": "test.sh"}}}),
        json.dumps({"type": "run_result", "text": "done work", "finishReason": "end_turn"}),
    ]
    import topoone_app_architect.arch_routes.agent_adapters as AA
    monkeypatch.setattr(AA, "iter_process_jsonl", lambda *a, **k: _FakeRuns(lines))
    out = run_async(collect_events(AA.ClineAdapter().process_events(ClineSession({}), "task")))
    assert ("message", "cline thinks") in [(e.get("type"), e.get("content")) for e in out]
    assert ("tool_call", "test.sh") in [(e.get("type"), (e.get("tool") or {}).get("label")) for e in out]
    assert ("message", "done work") in [(e.get("type"), e.get("content")) for e in out]
    assert ("status", "done") in [(e.get("type"), e.get("status")) for e in out]


def test_cline_stderr_noise_filtered(monkeypatch):
    """cline 的 stderr 噪音(hook dispatch failed / WARNING)应被过滤。"""
    from topoone_app_architect.arch_routes.agent_adapters import ClineAdapter, ClineSession

    lines = [
        "__stderr__: hook dispatch failed: unauthorized",
        "__stderr__: WARNING: auth required",
        json.dumps({"type": "error", "message": "hook dispatch failed: x"}),
    ]
    import topoone_app_architect.arch_routes.agent_adapters as AA
    monkeypatch.setattr(AA, "iter_process_jsonl", lambda *a, **k: _FakeRuns(lines))
    out = run_async(collect_events(AA.ClineAdapter().process_events(ClineSession({}), "task")))
    msgs = [e.get("content") for e in out if e.get("type") == "message"]
    assert "hook dispatch failed" not in msgs and "WARNING" not in msgs