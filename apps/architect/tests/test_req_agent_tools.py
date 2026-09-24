"""plan agent P2 工具测试：req.finalize(定稿→待执行) + mcp.call(MCP 出向) + 能力文档注入。

Run: cd <repo> && python -m pytest apps/architect/tests/test_req_agent_tools.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C
import topoone_app_architect.store as store
from topoone_app_architect.arch_routes import req_agent


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    req_agent._MCP_TOOLS_CACHE["ts"] = 0.0
    req_agent._MCP_TOOLS_CACHE["tools"] = []
    return C.setup(data_dir=data)


class _FakeGW:
    """KbGateway 替身：可控 query/tools 返回。"""

    def __init__(self, query_ret=None, tools_ret=None):
        self.mcp_url = "http://127.0.0.1:3460"
        self._query_ret = query_ret
        self._tools_ret = tools_ret or []
        self.calls = []

    def query(self, tool, timeout=None, **params):
        self.calls.append((tool, params))
        return self._query_ret

    def tools(self, timeout=None):
        return self._tools_ret


class TestMcpCall:
    def test_mcp_call_forwards(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        fake = _FakeGW(query_ret={"ok": True, "tool": "arch.read", "call": {"data": 42}})
        monkeypatch.setattr(req_agent, "_kb_gateway", lambda: fake)
        res = req_agent.tool_mcp_call("arch.read", {"path": "/x"})
        assert res["ok"] is True
        assert fake.calls == [("arch.read", {"path": "/x"})]

    def test_mcp_call_missing_tool(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        res = req_agent.tool_mcp_call("")
        assert res["ok"] is False
        assert "缺少" in res["error"]

    def test_mcp_call_unreachable(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(req_agent, "_kb_gateway", lambda: _FakeGW(query_ret=None))
        res = req_agent.tool_mcp_call("arch.read", {})
        assert res["ok"] is False
        assert "不可达" in res["error"]


class TestCapabilityDoc:
    def test_doc_lists_mcp_tools(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        req_agent._MCP_TOOLS_CACHE.update({
            "ts": 9999999999.0,
            "tools": [{"name": "arch.read", "description": "Read a file"},
                      {"name": "arch.status", "description": "Query status"}],
        })
        doc = req_agent._mcp_doc()
        assert "arch.read" in doc
        assert "arch.status" in doc

    def test_doc_empty_when_no_tools(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        monkeypatch.setattr(req_agent, "_kb_gateway",
                            lambda: _FakeGW(tools_ret=[]))
        doc = req_agent._mcp_doc()
        assert "无可用 MCP 工具" in doc

    def test_mcp_tool_list_caches(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        fake = _FakeGW(tools_ret=[{"name": "arch.read", "description": "x"}])
        monkeypatch.setattr(req_agent, "_kb_gateway", lambda: fake)
        assert req_agent._mcp_tool_list()[0]["name"] == "arch.read"
        n = len(fake.calls)  # tools() 被调用次数
        req_agent._mcp_tool_list()  # 命中缓存
        assert len(fake.calls) == n  # 不再调用

    def test_system_prompt_includes_new_tools(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        # cv-189: 降级项目 MCP 块整块不注入——本测试测 MCP 渲染, 用非降级口径
        import topoone_app_architect.arch_routes.project as _proj_mod
        monkeypatch.setattr(_proj_mod, "kb_degraded",
                            lambda root=None, project_id=None: False)
        req_agent._MCP_TOOLS_CACHE.update({
            "ts": 9999999999.0,
            "tools": [{"name": "arch.read", "description": "x"}],
        })
        prompt = req_agent.chat_system_prompt(None, "proj-x")
        assert "mcp.call" in prompt
        assert "req.finalize" not in prompt   # 已退役(需求卡创建即 ready)
        assert "arch.read" in prompt
