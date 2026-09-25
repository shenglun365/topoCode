"""I2 chat 薄化基础层测试：tAgent 集成（LLM 客户端 / web 工具适配 / 流式 agentic 运行器）。

零真实 LLM/HTTP：fake LLMClient（原生 + 文本 fallback）、fake executor、fake sdb。
Run:  cd <repo>/apps/workbench/chat_service && python -m pytest tests/test_tagent_chat.py -q
"""
import asyncio
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topocode_agent.core.llm.protocol import ChatResponse, StreamEvent, ToolCall
from topoone_app_chat import tagent_chat as T


# ── fake LLM ─────────────────────────────────────────────────────

class FakeLLM:
    """脚本化 LLMClient。script: list of (content, tool_calls|None) 每轮。"""

    def __init__(self, script, supports_tools=True):
        self.script = list(script)
        self._supports = supports_tools

    @property
    def supports_tools(self):
        return self._supports

    async def chat(self, messages, **kw):
        content, tcs = self.script.pop(0) if self.script else ("", None)
        return ChatResponse(content=content, tool_calls=tcs or [])

    async def chat_stream(self, messages, **kw):
        content, tcs = self.script.pop(0) if self.script else ("", None)
        if content:
            yield StreamEvent(type="delta", content=content)
        yield StreamEvent(type="done", content="", tool_calls=tcs)


class FakeExecutor:
    def __init__(self, results=None):
        self._results = results or {}
        self.calls = []

    def execute(self, name, args):
        self.calls.append((name, args))
        return self._results.get(name, {"ok": True, "name": name})


class FakeSDB:
    def __init__(self):
        self.rows = []

    def execute(self, sql, params):
        self.rows.append((sql, params))


def _run(agen):
    async def _collect():
        out = []
        async for ev in agen:
            out.append(ev)
        return out
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_collect())
    finally:
        loop.close()


def _await(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


# ── make_chat_llm / llm_call_kwargs ──────────────────────────────

def test_make_chat_llm():
    cfg = {"url": "http://x:1234/v1", "api_key": "k", "model": "m1",
           "temperature": 0.5, "max_tokens": 1000, "timeout": 60}
    llm = T.make_chat_llm(cfg)
    assert llm._base_url == "http://x:1234"  # /v1 剥离
    assert llm._api_key == "k"
    assert llm._model == "m1"
    assert llm.supports_tools is True
    kw = T.llm_call_kwargs(cfg)
    assert kw["temperature"] == 0.5
    assert kw["max_tokens"] == 1000


def test_make_chat_llm_extra_config():
    cfg = {"url": "http://x", "api_key": "", "model": "m",
           "frequency_penalty": 0.2,
           "extra_config": json.dumps({"top_p": 0.9})}
    kw = T.llm_call_kwargs(cfg)
    assert kw["extra"]["frequency_penalty"] == 0.2
    assert kw["extra"]["top_p"] == 0.9


# ── build_web_tool_registry ──────────────────────────────────────

def _def(name, desc="d"):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": {}}}}


def test_build_web_tool_registry():
    ex = FakeExecutor({"web_read_file": {"content": "data"}})
    defs = [_def("web_read_file"), _def("web_search_symbols")]
    reg = T.build_web_tool_registry(["web_read_file", "web_search_symbols"], ex, definitions=defs)
    assert reg.get("web_read_file") is not None
    assert reg.get("web_search_symbols") is not None
    assert reg.get("web_unknown") is None
    # 执行委托 executor；dict 结果序列化为 JSON 文本（LLM 可读 + 路由进上下文清单）
    res = _await(reg.get("web_read_file").execute(path="a.py"))
    assert res.success and isinstance(res.data, str)
    assert json.loads(res.data) == {"content": "data"}
    assert ex.calls == [("web_read_file", {"path": "a.py"})]


def test_build_web_tool_registry_error():
    class BoomEx:
        def execute(self, name, args):
            return {"error": "boom"}
    reg = T.build_web_tool_registry(["t"], BoomEx(), definitions=[_def("t")])
    res = _await(reg.get("t").execute())
    assert res.success is False and "boom" in res.error


# ── split_history ────────────────────────────────────────────────

def test_split_history():
    ctx = [{"role": "system", "content": "sys"},
           {"role": "user", "content": "hi"},
           {"role": "assistant", "content": "yo"},
           {"role": "user", "content": "second"}]
    hist, user = T.split_history(ctx, "second")
    assert user == "second"
    assert hist[-1] == {"role": "assistant", "content": "yo"}
    assert len(hist) == 3


# ── run_tagent_chat ──────────────────────────────────────────────

def test_run_tagent_chat_plain():
    llm = FakeLLM([("Hello answer", None)])
    reg = T.build_web_tool_registry([], FakeExecutor(), definitions=[])
    sdb = FakeSDB()
    events = _run(T.run_tagent_chat(
        llm=llm, tools=reg, system_prompt="sys",
        history=[{"role": "system", "content": "sys"}], user_input="hi",
        session_id="s1", sdb=sdb, persist=True))
    types = [e["type"] for e in events]
    assert "chunk" in types
    assert types[-1] == "done"
    done = events[-1]
    assert done["content"] == "Hello answer" and done["quality"] == "ok"
    # 落库 assistant 消息
    assert any("assistant" in r[1] for r in sdb.rows)


def test_run_tagent_chat_tool_call_native():
    """原生 function calling：turn1 工具调用 → 执行 → turn2 最终答案。"""
    llm = FakeLLM([
        ("", [ToolCall("web_read_file", {"path": "a.py"})]),
        ("Done reading", None),
    ], supports_tools=True)
    ex = FakeExecutor({"web_read_file": {"content": "file-data"}})
    reg = T.build_web_tool_registry(["web_read_file"], ex, definitions=[_def("web_read_file")])
    sdb = FakeSDB()
    events = _run(T.run_tagent_chat(
        llm=llm, tools=reg, system_prompt="sys",
        history=[{"role": "system", "content": "sys"}], user_input="read a.py",
        session_id="s1", sdb=sdb, persist=True))
    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    assert types.index("tool_result") < types.index("done")
    assert ex.calls == [("web_read_file", {"path": "a.py"})]
    assert events[-1]["content"] == "Done reading"
    # 落库 tool + assistant 消息
    roles = [r[1][2] for r in sdb.rows]
    assert "tool" in roles and "assistant" in roles


def test_run_tagent_chat_text_fallback():
    """无原生 function calling：文本 [TOOL_CALL] → TextFallback 解析执行。"""
    llm = FakeLLM([
        ('[TOOL_CALL: web_read_file]\n{"path": "a.py"}\n[/TOOL_CALL]', None),
        ("Fell back fine", None),
    ], supports_tools=False)
    ex = FakeExecutor({"web_read_file": {"content": "fb-data"}})
    reg = T.build_web_tool_registry(["web_read_file"], ex, definitions=[_def("web_read_file")])
    events = _run(T.run_tagent_chat(
        llm=llm, tools=reg, system_prompt="sys",
        history=[{"role": "system", "content": "sys"}], user_input="read a.py",
        session_id="s1", sdb=FakeSDB(), persist=False))
    types = [e["type"] for e in events]
    assert "tool_call" in types and "tool_result" in types
    assert ex.calls == [("web_read_file", {"path": "a.py"})]
    assert events[-1]["content"] == "Fell back fine"


def test_run_tagent_chat_no_content_low_quality():
    llm = FakeLLM([("", None)])  # 无内容
    reg = T.build_web_tool_registry([], FakeExecutor(), definitions=[])
    events = _run(T.run_tagent_chat(
        llm=llm, tools=reg, system_prompt="sys",
        history=[], user_input="hi", session_id="s1", sdb=None, persist=False))
    assert events[-1]["type"] == "done"
    assert events[-1]["quality"] == "low"


# ── context 编译体系接线（phase=chat + 本轮诉求钉驻 + cm 可注入）──


class CapLLM(FakeLLM):
    """记录每轮 chat_stream 收到的 messages。"""

    def __init__(self, script, **kw):
        super().__init__(script, **kw)
        self.seen = []

    async def chat_stream(self, messages, **kw):
        self.seen.append([dict(m) for m in messages])
        async for e in super().chat_stream(messages, **kw):
            yield e


def test_run_tagent_chat_pins_requirement_into_system():
    """默认 cm(phase=chat)：本轮诉求钉驻 Base → 并入 system 消息。"""
    llm = CapLLM([("ok answer", None)])
    reg = T.build_web_tool_registry([], FakeExecutor(), definitions=[])
    events = _run(T.run_tagent_chat(
        llm=llm, tools=reg, system_prompt="sys",
        history=[{"role": "system", "content": "sys"}], user_input="本轮诉求XYZ",
        session_id="s1", sdb=None, persist=False))
    assert events[-1]["content"] == "ok answer"
    first_sys = llm.seen[0][0]
    assert first_sys["role"] == "system"
    assert "sys" in first_sys["content"]
    assert "本轮诉求XYZ" in first_sys["content"]


def test_run_tagent_chat_injected_cm_used_and_tool_result_to_manifest():
    """注入共享 cm：被实际使用(turn 递增)，工具结果路由进清单(参与后续编译)。"""
    from topocode_agent.core.context import ContextManager
    cm = ContextManager(phase="chat")
    cm.pin_requirement("持久规格ABC")
    llm = FakeLLM([
        ("", [ToolCall("web_read_file", {"path": "a.py"})]),
        ("Done reading", None),
    ], supports_tools=True)
    ex = FakeExecutor({"web_read_file": {"content": "file-data-xyz"}})
    reg = T.build_web_tool_registry(["web_read_file"], ex,
                                    definitions=[_def("web_read_file")])
    events = _run(T.run_tagent_chat(
        llm=llm, tools=reg, system_prompt="sys",
        history=[], user_input="read a.py", session_id="s1", sdb=None,
        persist=False, context_manager=cm))
    assert events[-1]["content"] == "Done reading"
    assert cm.turn >= 1  # 注入的 cm 被实际使用
    # 工具结果(str)路由进清单
    assert any("file-data-xyz" in (e.text or "") for e in cm.manifest.entries())
