"""plan agent P2 工具测试：req.finalize(定稿→待执行) + mcp.call(MCP 出向) + 能力文档注入。

Run: cd <repo> && python -m pytest apps/architect/tests/test_req_agent_tools.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store
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


class TestReqFinalize:
    """规约确认(交托门禁)——生命周期重构 v2 语义。"""

    def _mk_req(self, rid, **snap_extra):
        import json as _json
        snap = {"title": "旧标题", "desc": "", "designMd": "", "allowedScope": [],
                "forbiddenScope": [], "acceptance": [], "functionalScope": [],
                "assessmentSummary": "", "estMin": 0}
        snap.update(snap_extra)
        store.RequirementsStore.create({
            "id": rid, "title": snap["title"], "status": "draft", "priority": "P1",
            "kind": "user-story", "activeVer": 1,
            "specVersions": [{"ver": 1, "state": "draft", "snapshot": snap,
                              "source": {"convId": "", "actor": "t"},
                              "reason": "", "createdAt": 1}],
            "updatedAt": 1, "createdAt": 1,
        })

    def test_finalize_gate_and_ready(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        tok_p = C.set_project("proj-f1")
        try:
            # 门禁: 缺方案+验收 → 拒绝
            self._mk_req("RQ-1")
            tok_r = C.set_req("RQ-1")
            try:
                res = req_agent.tool_req_finalize()
                assert res["ok"] is False and "门禁" in res["error"]
                # 补齐后确认 → ready
                req_agent.tool_req_amend(designMd="方案A", acceptance=["编译通过"],
                                         allowedScope=["modules/x/"])
                res2 = req_agent.tool_req_finalize()
            finally:
                C.reset_req(tok_r)
            assert res2["ok"] is True, res2
            row = store.RequirementsStore.get("RQ-1")
            assert row["status"] == "ready"
            assert row["activeVer"] == 2                       # amend 追加了 v2
            active = store.RequirementsStore.spec_active("RQ-1")
            assert active["state"] == "confirmed" and active["snapshot"]["designMd"] == "方案A"
            assert res2["boundaryFiles"] == ["modules/x"]      # 边界可解析
        finally:
            C.reset_project(tok_p)

    def test_finalize_supersedes_old_confirmed(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        self._mk_req("RQ-2", designMd="v1方案", acceptance=["a"])
        store.RequirementsStore.spec_confirm("RQ-2")
        # 修订新版本 → 确认 → 旧 confirmed 隐式废弃
        req_agent.tool_req_amend(reqId="RQ-2", designMd="v2方案")
        res = req_agent.tool_req_finalize(reqId="RQ-2")
        assert res["ok"] is True
        vs = store.RequirementsStore.spec_versions("RQ-2")
        assert vs[0]["state"] == "superseded" and vs[1]["state"] == "confirmed"

    def test_finalize_done_req_rejected(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        self._mk_req("RQ-3", designMd="d", acceptance=["a"])
        store.RequirementsStore.mark_done("RQ-3")
        res = req_agent.tool_req_finalize(reqId="RQ-3")
        assert res["ok"] is False and "已完结" in res["error"]

    def test_finalize_no_req_ctx(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        res = req_agent.tool_req_finalize()
        assert res["ok"] is False
        assert "未绑定需求" in res["error"]

    def test_finalize_unknown_req(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        res = req_agent.tool_req_finalize(reqId="RQ-nope")
        assert res["ok"] is False and "不存在" in res["error"]


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
        req_agent._MCP_TOOLS_CACHE.update({
            "ts": 9999999999.0,
            "tools": [{"name": "arch.read", "description": "x"}],
        })
        prompt = req_agent.chat_system_prompt(None, "proj-x")
        assert "mcp.call" in prompt
        assert "req.finalize" in prompt
        assert "arch.read" in prompt
