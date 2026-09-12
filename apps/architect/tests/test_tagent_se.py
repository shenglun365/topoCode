"""I5 基础层测试：architect → tAgent SE 接线（KbGatewayLLMClient + 工具适配 + SE 组装）。

fake gateway（duck-typed .call）脚本化 llm.sync 响应，零真实 HTTP/LLM。
验证：LLM 客户端映射、不可达降级、领域工具适配、SE 组装、
以及 TextFallback 文本 [TOOL_CALL] 的 agentic 循环端到端（analyze）。
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes.tagent_se import (
    KbGatewayLLMClient,
    ArchitectToolAdapter,
)


def _run(coro):
    import asyncio
    return asyncio.run(coro)


# ── fake gateway ──────────────────────────────────────────────────

class ScriptedGateway:
    """duck-typed KbGateway：.call(method, **params) 按脚本返回。"""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def call(self, method, timeout=None, **params):
        self.calls.append((method, params))
        if method != "llm.sync":
            return None
        if not self.script:
            return {"content": "", "mode": "chat"}
        return self.script.pop(0)


# ── KbGatewayLLMClient ────────────────────────────────────────────

def test_llm_client_chat_maps_content():
    gw = ScriptedGateway([{"content": "分析结果", "mode": "chat",
                           "usage": {"total_tokens": 42}}])
    llm = KbGatewayLLMClient(gw, model_id="m1")
    resp = _run(llm.chat([{"role": "user", "content": "hi"}]))
    assert resp.content == "分析结果"
    assert resp.tokens_used == 42
    method, params = gw.calls[0]
    assert method == "llm.sync"
    assert params["mode"] == "chat"
    assert params["modelId"] == "m1"
    assert params["messages"] == [{"role": "user", "content": "hi"}]


def test_llm_client_supports_tools_false():
    llm = KbGatewayLLMClient(ScriptedGateway([]), model_id="m1")
    assert llm.supports_tools is False


def test_llm_client_model_fallback():
    """model 参数优先于构造默认。"""
    gw = ScriptedGateway([{"content": "x", "mode": "chat"}])
    llm = KbGatewayLLMClient(gw, model_id="default")
    _run(llm.chat([{"role": "user", "content": "hi"}], model="override"))
    assert gw.calls[0][1]["modelId"] == "override"
    _run(llm.chat([{"role": "user", "content": "hi"}]))
    assert gw.calls[1][1]["modelId"] == "default"


def test_llm_client_unavailable_degrades():
    gw = ScriptedGateway([])
    gw.call = lambda *a, **k: None  # 模拟不可达
    llm = KbGatewayLLMClient(gw, model_id="m1")
    resp = _run(llm.chat([{"role": "user", "content": "hi"}]))
    assert resp.content == ""
    assert resp.finish_reason == "error"


def test_llm_client_stream_wraps_chat():
    gw = ScriptedGateway([{"content": "abc", "mode": "chat"}])
    llm = KbGatewayLLMClient(gw, model_id="m1")

    async def _collect():
        evs = []
        async for e in llm.chat_stream([{"role": "user", "content": "hi"}]):
            evs.append(e)
        return evs

    evs = _run(_collect())
    assert evs[0].type == "delta" and evs[0].content == "abc"
    assert evs[-1].type == "done"


# ── ArchitectToolAdapter ──────────────────────────────────────────

def test_tool_adapter_schema_and_execute():
    def fn(root, project, text=None):
        return {"root": root, "project": project, "text": text, "hits": [1, 2]}

    tool = ArchitectToolAdapter(
        "kb.asset.search", "检索资产", fn,
        parameters={"text": {"type": "string", "description": "关键词", "required": True}},
        root="/proj", project="p1")
    assert tool.llm_visible is True
    # 点号名净化为 tAgent 安全名
    assert tool.name == "kb_asset_search"
    schema = tool.to_openai_schema()
    assert schema["function"]["name"] == "kb_asset_search"
    assert "text" in schema["function"]["parameters"]["properties"]
    assert schema["function"]["parameters"]["required"] == ["text"]

    res = _run(tool.execute(text="订单"))
    assert res.success is True
    assert res.data == {"root": "/proj", "project": "p1", "text": "订单", "hits": [1, 2]}


def test_tool_adapter_error_to_fail():
    def boom(root, project, **kw):
        raise RuntimeError("kb down")
    tool = ArchitectToolAdapter("x", "d", boom, root=None, project=None)
    res = _run(tool.execute())
    assert res.success is False
    assert "kb down" in res.error


# ── build_architect_se ────────────────────────────────────────────
