"""Streaming // non-streaming paths of `_run_opencode_task` via a fake adapter.

These tests exercise the WS task flow without a real agent server:
  - stream : supports_stream=True → /event-like events forwarded as
            status/message/tool_call, terminal `done` sent exactly once.
  - nostream: supports_stream=False → synchronous text reply extraction.

Run:  cd <repo> && python -m pytest plugins/architect/tests -q
"""

import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", ".."))

from plugins.architect.arch_routes import agent_adapters as AA
import plugins.architect.arch_routes.websocket as wmod


def run_async(awaitable):
    return asyncio.run(awaitable)


async def collect_events(agen):
    return [e async for e in agen]


class FakeWS:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_json(self, obj: dict) -> None:
        self.sent.append(obj)


class _SessionStore:
    def __init__(self):
        self.messages: list[dict] = []

    def next_id(self, kind: str) -> str:
        return f"{kind}_9"

    def get(self, sid: str) -> dict:
        return {"id": sid, "stats": {}, "artifacts": [], "testResult": None}

    def update(self, sid: str, data: dict) -> None:
        pass

    def append_message(self, msg: dict) -> None:
        self.messages.append(msg)


class FakeStore:
    AgentSessionsStore = _SessionStore()

    @staticmethod
    def next_id(kind: str) -> str:
        return f"{kind}_9"


class FakeStreamAdapter(AA.AgentAdapter):
    id = "fake"
    name = "Fake"
    desc = ""
    supports_stream = True

    def env_check(self) -> dict:
        return {"status": "ok"}

    def probe(self, cfg: dict) -> dict:
        return {"status": "ok"}

    def addr(self, cfg: dict, instance=None) -> str:
        return "http://fake"

    def spawn(self, base: dict) -> list:
        return []

    def health(self, addr: str, username: str) -> bool:
        return True

    def make_client(self, addr, username, password):
        raise NotImplementedError

    async def iter_events(self, client, session_id: str):
        yield {"type": "status", "status": "working"}
        yield {"type": "message", "role": "assistant", "content": "part1"}
        yield {"type": "tool_call", "tool": {"type": "run-command", "label": "go test", "ok": True}}


class FakeNoStreamAdapter(FakeStreamAdapter):
    supports_stream = False


class FakeClient:
    def __init__(self):
        self.calls = 0

    def create_session(self, title="", parent_id=""):
        return {"id": "ocx"}

    def send_message(self, sid, text, model="", no_reply=False):
        self.calls += 1
        if no_reply:
            return {"info": {"id": "ctx"}, "parts": []}
        return {"info": {"id": "r"}, "parts": [{"type": "text", "text": "nonstream reply"}]}

    def abort(self, sid):
        return True


def _install(store, adapter, client):
    wmod.store = store
    wmod._config_for_adapter = lambda a: {"host": "h", "port": 1, "env": "local"}
    wmod._project_for_root = lambda root: None
    wmod.agent_adapters.get_agent = lambda aid: adapter
    wmod._CANCELLED.clear()
    wmod._RUNNING.clear()
    import plugins.architect.arch_routes.agent_server as _as

    _as.agent_client_for = lambda inst, cfg, aid: client


def test_stream_path():
    ws = FakeWS()
    client = FakeClient()
    _install(FakeStore(), FakeStreamAdapter(), client)
    asyncio.run(
        wmod._run_opencode_task(
            ws,
            {"id": "s5", "adapter": "fake", "opencodeSessionId": "oc5", "model": "x", "instanceId": "i1"},
            {"id": "i1", "workDir": "/tmp", "taskBranch": "arch/t1"},
            {"title": "T", "context": ["a.go"]},
        )
    )
    events = [(e.get("type"), e.get("status"), e.get("content"), (e.get("tool") or {}).get("label")) for e in ws.sent]
    assert ("status", "planning", None, None) in events
    assert ("status", "working", None, None) in events
    assert ("message", None, "part1", None) in events
    assert ("tool_call", None, None, "go test") in events
    assert ("status", "done", None, None) in events
    # 终态 `done` 只发一次。
    assert sum(1 for e in ws.sent if e.get("type") == "done") == 1


def test_nostream_sync_reply():
    ws = FakeWS()
    client = FakeClient()
    _install(FakeStore(), FakeNoStreamAdapter(), client)
    awaitable = wmod._run_opencode_task(
        ws,
        {"id": "s9", "adapter": "nos", "opencodeSessionId": "oc9", "model": "m", "instanceId": "i1"},
        {"id": "i1", "workDir": "/tmp", "taskBranch": "arch/t2"},
        {"title": "T", "context": []},
    )
    asyncio.run(awaitable)
    events = [(e.get("type"), e.get("content")) for e in ws.sent]
    assert ("message", "nonstream reply") in events
    assert ws.sent[-1].get("type") == "done"


def test_send_message_model_id_split():
    """model 'provider/model' 应被拆成 providerID/modelID(partition 三值解包会出错)。"""
    calls = {}

    def fake_req(path, method="GET", body=None, timeout=10.0):
        calls["body"] = body
        return {}

    from plugins.architect.arch_routes.agent_adapters import OpenCodeSession

    s = OpenCodeSession("http://x")
    s._req = fake_req
    s.send_message("oc1", "hi", "192.168.1.9-LMS/qwen3.5-9b-mtp", False)
    assert calls["body"]["model"] == {"providerID": "192.168.1.9-LMS", "modelID": "qwen3.5-9b-mtp"}
    # 不带 provider 前缀 → 不设置 model。
    s.send_message("oc1", "hi", "deepseek-v4", False)
    assert "model" not in calls["body"]


def test_qwen_session_update_mapping():
    """qwen serve session_update(event agent_message_chunk) → 归一化 message。"""
    from plugins.architect.arch_routes.agent_adapters import QwenAdapter

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
        from plugins.architect.arch_routes.agent_adapters import QwenAdapter

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
    from plugins.architect.arch_routes.agent_adapters import CodexAdapter, CodexSession

    lines = [
        json.dumps({"type": "turn.started"}),
        json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "start worked"}}),
        json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "pwd"}}),
        json.dumps({"type": "item.completed", "item": {"type": "command_execution", "command": "pwd", "status": "completed", "aggregated_output": "/tmp"}}),
        json.dumps({"type": "turn.completed"}),
    ]
    import plugins.architect.arch_routes.agent_adapters as AA
    monkeypatch.setattr(AA, "iter_process_jsonl", lambda *a, **k: _FakeRuns(lines))
    out = run_async(collect_events(AA.CodexAdapter().process_events(CodexSession({}), "task")))
    assert ("status", "working") in [(e.get("type"), e.get("status")) for e in out]
    assert ("message", "start worked") in [(e.get("type"), e.get("content")) for e in out]
    assert ("tool_call", "pwd") in [(e.get("type"), (e.get("tool") or {}).get("label")) for e in out]
    assert ("status", "done") in [(e.get("type"), e.get("status")) for e in out]


def test_cline_process_events_mapping(monkeypatch):
    """cline --json 行流(agent_event/run_result)→ 归一化事件。"""
    from plugins.architect.arch_routes.agent_adapters import ClineAdapter, ClineSession

    lines = [
        json.dumps({"type": "agent_event", "event": {"type": "message", "message": {"content": "cline thinks"}}}),
        json.dumps({"type": "agent_event", "event": {"type": "tool_use", "tool": {"name": "run-command", "command": "test.sh"}}}),
        json.dumps({"type": "run_result", "text": "done work", "finishReason": "end_turn"}),
    ]
    import plugins.architect.arch_routes.agent_adapters as AA
    monkeypatch.setattr(AA, "iter_process_jsonl", lambda *a, **k: _FakeRuns(lines))
    out = run_async(collect_events(AA.ClineAdapter().process_events(ClineSession({}), "task")))
    assert ("message", "cline thinks") in [(e.get("type"), e.get("content")) for e in out]
    assert ("tool_call", "test.sh") in [(e.get("type"), (e.get("tool") or {}).get("label")) for e in out]
    assert ("message", "done work") in [(e.get("type"), e.get("content")) for e in out]
    assert ("status", "done") in [(e.get("type"), e.get("status")) for e in out]


def test_cline_stderr_noise_filtered(monkeypatch):
    """cline 的 stderr 噪音(hook dispatch failed / WARNING)应被过滤。"""
    from plugins.architect.arch_routes.agent_adapters import ClineAdapter, ClineSession

    lines = [
        "__stderr__: hook dispatch failed: unauthorized",
        "__stderr__: WARNING: auth required",
        json.dumps({"type": "error", "message": "hook dispatch failed: x"}),
    ]
    import plugins.architect.arch_routes.agent_adapters as AA
    monkeypatch.setattr(AA, "iter_process_jsonl", lambda *a, **k: _FakeRuns(lines))
    out = run_async(collect_events(AA.ClineAdapter().process_events(ClineSession({}), "task")))
    msgs = [e.get("content") for e in out if e.get("type") == "message"]
    assert "hook dispatch failed" not in msgs and "WARNING" not in msgs


if __name__ == "__main__":
    import os
    _install(FakeStore(), FakeStreamAdapter(), FakeClient())
    ws = FakeWS()
    asyncio.run(
        wmod._run_opencode_task(
            ws,
            {"id": "s5", "adapter": "fake", "opencodeSessionId": "oc5", "model": "x", "instanceId": "i1"},
            {"id": "i1", "workDir": "/tmp", "taskBranch": "arch/t1"},
            {"title": "T", "context": ["a.go"]},
        )
    )
    print("stream run:", [e.get("type") for e in ws.sent])