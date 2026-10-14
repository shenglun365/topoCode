"""plan agent P2 工具测试：req.finalize(定稿→待执行) + 能力文档注入(mcp.call 已退役)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_req_agent_tools.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C
import topoone_app_architect.store as store
from topoone_app_architect.agent.tools import req_agent


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
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



class TestCapabilityDoc:
    """mcp.call/_mcp_doc 已退役(2610 MCP 定型): 系统提示不再含 MCP 出向块。"""

    def test_system_prompt_excludes_mcp_call(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        prompt = req_agent.chat_system_prompt(None, "proj-x")
        assert "mcp.call" not in prompt
        assert "req.finalize" not in prompt   # 已退役(需求卡创建即 ready)
