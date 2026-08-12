"""KbGateway 单元测试：逐调用超时覆盖 + 超时/不可达日志区分。

Run:  cd <repo> && python -m pytest plugins/architect/tests/test_kb_gateway.py -q
"""
import json
import os
import socket
import sys
import urllib.error

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)
sys.path.insert(0, os.path.join(_repo, "backend-core"))

import plugins.architect.arch_routes.kb_gateway as G
from plugins.architect.arch_routes import req_agent as RA


def _gw():
    return G.KbGateway(base_url="http://kb.test", mcp_url="http://mcp.test", timeout=10.0)


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload if isinstance(payload, bytes) else json.dumps(payload).encode()

    def read(self):
        return self._payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_call_passes_per_call_timeout(monkeypatch):
    """显式 timeout 应覆盖实例默认，且不把 timeout 打进 body。"""
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        body = json.loads(req.data)
        assert "timeout" not in body
        return _FakeResp({"result": {"ok": True}})
    monkeypatch.setattr(G.urllib.request, "urlopen", fake_urlopen)
    res = _gw().call("llm.sync", timeout=300, modelId="m1")
    assert res == {"ok": True}
    assert captured["timeout"] == 300


def test_call_defaults_to_instance_timeout(monkeypatch):
    captured = {}
    def fake_urlopen(req, timeout=None):
        captured["timeout"] = timeout
        return _FakeResp({"result": 1})
    monkeypatch.setattr(G.urllib.request, "urlopen", fake_urlopen)
    assert _gw().call("architecture.catalog") == 1
    assert captured["timeout"] == 10.0


def test_call_timeout_logs_timeout_not_unreachable(monkeypatch, caplog):
    """socket.timeout → 明确记 timeout，不再误报 unreachable。"""
    import logging
    def fake_urlopen(req, timeout=None):
        raise socket.timeout("timed out")
    monkeypatch.setattr(G.urllib.request, "urlopen", fake_urlopen)
    with caplog.at_level(logging.INFO, logger="plugins.architect.arch_routes.kb_gateway"):
        assert _gw().call("llm.sync", timeout=300) is None
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "timeout after" in joined and "unreachable" not in joined


def test_call_connection_refused_still_unreachable(monkeypatch, caplog):
    """连接拒绝 → 保持 unreachable 语义。"""
    import logging
    def fake_urlopen(req, timeout=None):
        raise urllib.error.URLError(socket.gaierror("name or service not known"))
    monkeypatch.setattr(G.urllib.request, "urlopen", fake_urlopen)
    with caplog.at_level(logging.INFO, logger="plugins.architect.arch_routes.kb_gateway"):
        assert _gw().call("architecture.model") is None
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "unreachable" in joined and "timeout after" not in joined


def test_req_agent_llm_sync_uses_long_timeout(monkeypatch):
    """llm_sync 应给 llm.sync 传长超时(默认 300s)，避免本地模型慢响应被误杀。"""
    captured = {}
    def fake_gateway():
        class _G:
            def call(self, method, **kw):
                captured["method"] = method
                captured["timeout"] = kw.pop("timeout", None)
                return {"content": "ok", "output": {"assets": []}}
        return _G()
    monkeypatch.setattr(RA, "_kb_gateway", fake_gateway)
    res = RA.llm_sync([{"role": "user", "content": "hi"}], mode="chat")
    assert res is not None
    assert captured["method"] == "llm.sync"
    assert captured["timeout"] == RA._LLM_CALL_TIMEOUT
    assert RA._LLM_CALL_TIMEOUT >= 300
