"""I1 测试：TopoLLMClientAdapter（LLMService → tAgent LLMClient 桥接）。"""

from __future__ import annotations

import asyncio
import json

import pytest

from topoone.llm.tagent_adapter import TopoLLMClientAdapter
from topocode_agent.core.llm.protocol import ChatResponse, StreamEvent, ToolCall


class FakeLLMService:
    """LLMService 替身：_sync_call_for_retry 脚本化 + _save_call_log 记录。"""

    def __init__(self, multi_db, raw=None):
        self.multi_db = multi_db
        self._raw = raw or {"content": "hello", "usage": {"total_tokens": 7},
                            "finish_reason": "stop"}
        self.audits: list[dict] = []

    async def _sync_call_for_retry(self, model, messages, mode, tools, output_schema,
                                   max_tokens=None):
        self.last = {"model": model, "messages": messages, "mode": mode,
                     "tools": tools, "max_tokens": max_tokens}
        return dict(self._raw)

    def _save_call_log(self, main_db, session_id, messages, full_content, model,
                       request_id, template_id, extra_meta, tool_calls_recorded,
                       latency_ms, status, error_message, token_data):
        self.audits.append({"session_id": session_id, "status": status,
                            "template_id": template_id, "error": error_message})


@pytest.fixture
def configured_multi_db(multi_db):
    multi_db.main_db.execute(
        "INSERT INTO model_configs (id, name, provider, url, model, is_default) "
        "VALUES ('m1', 'ollama-local', 'ollama', 'http://127.0.0.1:11434', 'qwen3', 1)")
    return multi_db


@pytest.fixture
def patch_llm_service(monkeypatch):
    def _patch(raw=None):
        svc = FakeLLMService(None, raw=raw)
        monkeypatch.setattr("topoone.llm.service.LLMService", lambda mdb: svc)
        return svc
    return _patch


def test_adapter_chat_plain(configured_multi_db, patch_llm_service):
    svc = patch_llm_service({"content": "hello", "usage": {"total_tokens": 7},
                             "finish_reason": "stop"})
    llm = TopoLLMClientAdapter(configured_multi_db)
    resp = asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))
    assert isinstance(resp, ChatResponse)
    assert resp.content == "hello"
    assert resp.tokens_used == 7
    assert resp.tool_calls == []
    # 默认模型解析 + mode=chat + 审计
    assert svc.last["mode"] == "chat"
    assert svc.last["tools"] is None
    assert svc.last["model"]["id"] == "m1"
    assert svc.audits and svc.audits[0]["status"] == "success"
    assert svc.audits[0]["session_id"] == "agent-tagent"
    assert svc.audits[0]["template_id"] == "tagent"


def test_adapter_chat_native_tools(configured_multi_db, patch_llm_service):
    raw = {
        "content": "", "usage": {"total_tokens": 11}, "finish_reason": "tool_calls",
        "tool_calls": [{"id": "c1", "type": "function",
                        "function": {"name": "search_symbols",
                                     "arguments": "{\"pattern\": \"auth\"}"}}],
    }
    svc = patch_llm_service(raw)
    llm = TopoLLMClientAdapter(configured_multi_db)
    tools = [{"type": "function", "function": {"name": "search_symbols"}}]
    resp = asyncio.run(llm.chat([{"role": "user", "content": "find auth"}], tools=tools))
    assert resp.tool_calls and resp.tool_calls[0].name == "search_symbols"
    assert resp.tool_calls[0].arguments == {"pattern": "auth"}
    assert svc.last["mode"] == "tools"
    assert svc.last["tools"] == tools
    assert llm.supports_tools is True


def test_adapter_chat_error_audited(configured_multi_db, monkeypatch):
    def boom(self, model, messages, mode, tools, output_schema, max_tokens=None):
        raise RuntimeError("provider down")
    svc_cls = type("Svc", (FakeLLMService,), {"_sync_call_for_retry": boom})
    monkeypatch.setattr("topoone.llm.service.LLMService", lambda mdb: svc_cls(mdb))
    llm = TopoLLMClientAdapter(configured_multi_db)
    with pytest.raises(RuntimeError, match="provider down"):
        asyncio.run(llm.chat([{"role": "user", "content": "hi"}]))


class FakeProvider:
    """provider.chat_stream 替身：按脚本向队列放 chunk。"""

    supports_tools = True

    def __init__(self, items):
        self._items = items

    def chat_stream(self, model_config, messages, chunk_queue, tools=None,
                    mode="chat", max_tokens=None):
        for item in self._items:
            chunk_queue.put(item)
        chunk_queue.put({"type": "done", "content": "".join(
            i for i in self._items if isinstance(i, str))})
        return {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}


def test_adapter_chat_stream_deltas(configured_multi_db, monkeypatch):
    items = ["Hel", "lo ", "world", {"type": "tool_calls",
                                     "data": json.dumps([
                                         {"id": "c9", "function": {"name": "t",
                                                                  "arguments": "{}"}}])},
             {"type": "done", "content": "Hello world"}]
    provider = FakeProvider(items)
    monkeypatch.setattr("topoone.llm.providers.get_provider", lambda name: provider)

    llm = TopoLLMClientAdapter(configured_multi_db)

    async def run():
        events = []
        async for ev in llm.chat_stream([{"role": "user", "content": "hi"}]):
            events.append(ev)
        return events

    events = asyncio.run(run())
    deltas = [e for e in events if e.type == "delta"]
    done = [e for e in events if e.type == "done"]
    assert "".join(e.content for e in deltas) == "Hello world"
    assert len(done) == 1
    assert done[0].tool_calls and done[0].tool_calls[0].name == "t"
    assert done[0].usage.get("total_tokens") == 8
    assert isinstance(done[0], StreamEvent)


def test_adapter_chat_stream_error(configured_multi_db, monkeypatch):
    provider = FakeProvider(["ok", {"type": "error", "message": "boom"},
                             {"type": "done", "content": "ok"}])
    monkeypatch.setattr("topoone.llm.providers.get_provider", lambda name: provider)
    llm = TopoLLMClientAdapter(configured_multi_db)

    async def run():
        got = []
        async for ev in llm.chat_stream([{"role": "user", "content": "hi"}]):
            got.append(ev)
        return got

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(run())


def test_adapter_supports_tools_false_provider(configured_multi_db, monkeypatch):
    class NoToolsProvider:
        supports_tools = False
    monkeypatch.setattr("topoone.llm.providers.get_provider", lambda name: NoToolsProvider())
    llm = TopoLLMClientAdapter(configured_multi_db)
    assert llm.supports_tools is False
    # tools 不支持时降级 chat 模式
    svc = FakeLLMService(None)
    monkeypatch.setattr("topoone.llm.service.LLMService", lambda mdb: svc)
    asyncio.run(llm.chat([{"role": "user", "content": "hi"}],
                         tools=[{"type": "function", "function": {"name": "x"}}]))
    assert svc.last["mode"] == "chat"
    assert svc.last["tools"] is None
