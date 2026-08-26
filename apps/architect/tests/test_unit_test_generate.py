"""P2-B B1 测试：POST /unit-tests/generate — agentic_loop 生成单测草稿。

临时 DB + TestClient + ScriptedGateway(脚本化 LLM)，零真实 HTTP/LLM。验证：
- LLM 返回合法 JSON → 200 草稿(规范化 name/levels/scriptPath/desc)
- scope 为空 → 400
- LLM 返回非法 JSON / 不可达 → 502(明确降级，不伪造)
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from topoone_app_architect.arch_routes import ctx, kb_gateway
from topoone_app_architect.server import build_app


class ScriptedGateway:
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


DRAFT_JSON = json.dumps({"tests": [
    {"name": "订单创建幂等", "levels": ["L2", "L3"], "scriptPath": "tests/test_order_create.py", "desc": "重复创建不重复扣款"},
    {"name": "退款金额边界", "levels": ["L3"], "scriptPath": "tests/test_refund.py", "desc": "超额/负数拒绝"},
    {"name": "bad", "levels": ["L9"], "scriptPath": "", "desc": ""},  # 非法 level 应被过滤
]})


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ctx, "_db", None, raising=False)
    monkeypatch.setattr(ctx, "_data_dir", None, raising=False)
    app = build_app(data_dir=str(tmp_path / "arch"))
    return TestClient(app)


def test_generate_returns_draft(client, monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway",
                        lambda: ScriptedGateway([{"content": DRAFT_JSON, "mode": "chat"}]))
    res = client.post("/api/architect/unit-tests/generate",
                      json={"scope": "订单服务创建/退款", "root": "/tmp/x", "project": ""})
    assert res.status_code == 200, res.text
    data = res.json()["data"]
    assert data["draft"] is True and data["scope"] == "订单服务创建/退款"
    tests = data["tests"]
    assert len(tests) == 3, tests
    assert tests[0]["name"] == "订单创建幂等"
    assert tests[0]["levels"] == ["L2", "L3"]
    assert tests[0]["scriptPath"] == "tests/test_order_create.py"
    # 非法 level L9 被过滤
    assert tests[2]["levels"] == [], tests[2]


def test_generate_empty_scope_400(client):
    res = client.post("/api/architect/unit-tests/generate", json={"scope": "  "})
    assert res.status_code == 400, res.text
    assert res.json()["code"] == 400


def test_generate_invalid_json_502(client, monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway",
                        lambda: ScriptedGateway([{"content": "这不是 JSON", "mode": "chat"}]))
    res = client.post("/api/architect/unit-tests/generate", json={"scope": "x"})
    assert res.status_code == 502, res.text
    assert res.json()["code"] == 502


def test_generate_unreachable_502(client, monkeypatch):
    # KB/LLM 网关不可达 → generate_unit_tests 返回 None → 502
    monkeypatch.setattr(kb_gateway, "get_gateway", lambda: None)
    res = client.post("/api/architect/unit-tests/generate", json={"scope": "x"})
    assert res.status_code == 502, res.text
    assert res.json()["code"] == 502
