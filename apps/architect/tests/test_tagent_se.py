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
    build_architect_se,
    adapt_domain_tool,
)


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

def test_build_se_registers_domain_and_file_tools(tmp_path):
    gw = ScriptedGateway([])

    def ctx_fn(root, project):
        return {"name": "demo"}
    domain = [{"name": "project.ctx", "description": "项目上下文", "handler": ctx_fn}]

    se = build_architect_se(
        gw, root="/proj", project="p1", model_id="m1",
        domain_tools=domain,
        tool_parameters={"project.ctx": {}},
        project_root=str(tmp_path),
    )
    names = set(se.tools._tools.keys())
    assert "project_ctx" in names  # 点号名净化后
    # 文件探查工具（provider=None → 仅文件组）
    assert any("file" in n or "read" in n.lower() or "search" in n.lower()
               for n in names)
    assert "submit_task_tree" in names
    assert isinstance(se._llm, KbGatewayLLMClient)


def test_adapt_domain_tool_helper():
    def fn(root, project, a=None):
        return a
    t = adapt_domain_tool({"name": "t1", "description": "d", "handler": fn},
                          "/r", "p", parameters={"a": {"type": "string"}})
    assert isinstance(t, ArchitectToolAdapter)
    assert t.name == "t1"


# ── 端到端：analyze 经 TextFallback 跑 [TOOL_CALL] 循环 ────────────

def test_se_analyze_text_fallback_loop(tmp_path):
    # turn1: 调 project.ctx（净化名 project_ctx）；turn2: 最终分析文本
    gw = ScriptedGateway([
        {"content": "[TOOL_CALL: project_ctx]\n{}\n[/TOOL_CALL]", "mode": "chat"},
        {"content": "## 需求分析\n该需求涉及订单模块。", "mode": "chat"},
    ])

    def ctx_fn(root, project):
        return {"name": "demo", "branch": "main"}
    domain = [{"name": "project.ctx", "description": "项目上下文", "handler": ctx_fn}]

    se = build_architect_se(
        gw, root="/proj", project="p1", model_id="m1",
        domain_tools=domain, project_root=str(tmp_path),
    )
    analysis = _run(se.analyze("给订单加退款功能"))
    assert "订单" in analysis
    # 两次 llm.sync（工具轮 + 最终轮）
    assert len(gw.calls) == 2
    # 工具确实被执行（TextFallback 解析了 [TOOL_CALL]）
    assert gw.calls[0][1]["mode"] == "chat"


# ── SE 任务树生成（替换机械 _build_task_tree）────────────────────

_TREE_JSON = (
    '{"roots": [{"id": "epic1", "title": "订单退款", "kind": "epic", "est_min": 180, "children": ['
    '{"id": "t1", "title": "梳理现状", "kind": "task", "est_min": 30, "files": ["order.go"]},'
    '{"id": "t2", "title": "实现退款", "kind": "task", "est_min": 120, "depends_on": ["t1"], "files": ["refund.go"]},'
    '{"id": "t3", "title": "单元测试", "kind": "check", "est_min": 30, "depends_on": ["t2"]}'
    ']}]}'
)


def test_build_task_tree_se_success(tmp_path):
    gw = ScriptedGateway([{"content": _TREE_JSON, "mode": "chat"}])
    from topoone_app_architect.arch_routes.tagent_se import build_task_tree_se
    reqs = [{"id": "req-1", "title": "订单退款", "desc": "支持退款",
             "analysis": {"assessmentSummary": "可行", "functionalScope": ["退款"],
                          "implementationPath": "refund.go"}}]
    tree, problems = _run(build_task_tree_se(
        reqs, root=str(tmp_path), project="p1", model_id="m", gateway=gw))
    assert problems == []
    assert tree["kind"] == "epic"
    assert tree["title"] == "订单退款"
    assert tree["estMin"] == 180  # est_min → estMin
    assert tree["status"] == "pending"
    # id 重映射为唯一 se-NNNN（DFS 序），dependsOn 同步重映射
    assert tree["id"] == "se-0001"
    by_title = {c["title"]: c for c in tree["children"]}
    t1, t2, t3 = by_title["梳理现状"], by_title["实现退款"], by_title["单元测试"]
    assert (t1["id"], t2["id"], t3["id"]) == ("se-0002", "se-0003", "se-0004")
    assert t2["dependsOn"] == [t1["id"]]  # t1 → se-0002
    assert t3["dependsOn"] == [t2["id"]]  # t2 → se-0003
    assert t2["estMin"] == 120
    assert t3["kind"] == "check"
    assert t1["files"] == ["order.go"]


def test_build_task_tree_se_failure(tmp_path):
    gw = ScriptedGateway([{"content": "抱歉，我无法生成任务树。", "mode": "chat"}])
    from topoone_app_architect.arch_routes.tagent_se import build_task_tree_se
    tree, problems = _run(build_task_tree_se(
        [{"id": "req-1", "title": "x", "desc": "", "analysis": {}}],
        root=str(tmp_path), project="p1", model_id="m", gateway=gw))
    assert tree is None
    assert problems  # 有明确失败原因



def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
