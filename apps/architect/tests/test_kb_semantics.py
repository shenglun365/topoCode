"""kb_gateway MCP 出向消费路由冒烟（MS7-W6，裁决① 收口）。

验证：/kb/semantics/tools 与 /kb/semantics/query 的接线、结果透传与
MCP 不可达降级（query→None → err）。
"""
import sys, os

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi import FastAPI
from fastapi.testclient import TestClient

import topoone_app_architect.kb_gateway as G
from topoone_app_architect.arch_routes.knowledge import router as knowledge_router


def _client():
    app = FastAPI()
    app.include_router(knowledge_router)
    return TestClient(app)


def test_semantics_tools_passthrough(monkeypatch):
    gw = G.get_gateway()
    monkeypatch.setattr(gw, "tools", lambda timeout=None: [{"name": "kb_semantic_search"}])
    r = _client().get("/kb/semantics/tools")
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["tools"] == [{"name": "kb_semantic_search"}]


def test_semantics_query_passthrough(monkeypatch):
    gw = G.get_gateway()
    captured = {}

    def fake_query(tool, timeout=None, **params):
        captured["tool"] = tool
        captured["params"] = params
        return {"ok": True, "hits": [{"component": "comm-1"}]}

    monkeypatch.setattr(gw, "query", fake_query)
    r = _client().post("/kb/semantics/query", json={"tool": "kb_semantic_search", "params": {"q": "登录"}})
    assert r.status_code == 200
    assert captured["tool"] == "kb_semantic_search"
    assert captured["params"] == {"q": "登录"}
    assert r.json()["data"]["hits"][0]["component"] == "comm-1"


def test_semantics_query_degrades_when_mcp_down(monkeypatch):
    gw = G.get_gateway()
    monkeypatch.setattr(gw, "query", lambda tool, timeout=None, **params: None)
    r = _client().post("/kb/semantics/query", json={"tool": "kb_semantic_search", "params": {}})
    assert r.status_code == 503
    assert "KB MCP" in r.text
