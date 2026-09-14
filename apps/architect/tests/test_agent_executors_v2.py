"""执行器注册表 v2 配置面测试（cline 默认化 + 探测增强）。

Run: cd <repo> && python -m pytest apps/architect/tests/test_agent_executors_v2.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone_app_architect.arch_routes import agent_executors as ae  # noqa: E402


def test_cline_is_default_executor():
    entries = ae.load_executors()
    defaults = [e for e in entries if e.get("default")]
    assert len(defaults) == 1
    assert defaults[0]["id"] == "cline"
    assert defaults[0]["type"] == "cline-sdk"
    # opencode 保留可选
    oc = [e for e in entries if e.get("id") == "opencode"]
    assert oc and oc[0].get("default") is False


def test_cline_config_schema_extended():
    entry = [e for e in ae.load_executors() if e.get("id") == "cline"][0]
    cfg = entry["config"]
    for key in ("node_bin", "sidecar_script", "provider_id", "model_id",
                "api_key", "max_iterations", "system_prompt",
                "tool_policies", "models"):
        assert key in cfg, f"cline config 缺 {key}"


def test_validate_rejects_double_default():
    entries = [
        {"id": "cline", "type": "cline-sdk", "default": True, "config": {}},
        {"id": "opencode", "type": "opencode", "default": True, "config": {}},
    ]
    assert ae._validate(entries) is not None


def test_cline_probe_node_version_gate(monkeypatch, tmp_path):
    """node < 22 → fail（@cline/core 硬性门槛）。"""
    script = tmp_path / "index.js"
    script.write_text("// sidecar")
    monkeypatch.setattr(ae, "_default_sidecar_path", lambda: str(script))

    class _R:
        stdout = "v20.11.0"
        stderr = ""

    monkeypatch.setattr(ae.subprocess, "run",
                        lambda *a, **k: _R())
    class _Req:
        def json(self):
            body = {"entry": {"type": "cline-sdk", "config": {}}}
            import asyncio as _aio

            async def _j():
                return body
            return _j()

    res = asyncio.run(ae.probe_executor(_Req()))
    data = res["data"] if isinstance(res, dict) and "data" in res else res
    status = data.get("status") if isinstance(data, dict) else None
    assert status == "fail"
    assert "22" in (data.get("detail") or "")


def test_probe_llm_model_stream_detection(monkeypatch):
    """流式探测：SSE 响应 → ok；非流式 200 → fail + Ollama 建议。"""
    import io

    class _Hdrs:
        def __init__(self, ct):
            self._ct = ct

        def get(self, k, default=""):
            return self._ct if k == "Content-Type" else default

    class _Resp:
        def __init__(self, body, ct):
            self.status = 200
            self.headers = _Hdrs(ct)
            self._b = body

        def read(self, n=-1):
            return self._b

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    calls = []

    def fake_urlopen(req, timeout=0):
        calls.append(req.full_url)
        if "/models" in req.full_url:
            return _Resp(b'{"data":[{"id":"m1"}]}', "application/json")
        # chat/completions: 流式请求 → SSE
        if getattr(req, "_is_stream", False) or b'"stream": true' in (req.data or b""):
            return _Resp(b'data: {"choices":[]}\n\n', "text/event-stream")
        return _Resp(b"{}", "application/json")

    monkeypatch.setattr(ae.urllib.request, "urlopen", fake_urlopen)
    r = ae._probe_llm_model("http://x:1234", "m1", "")
    assert r["status"] == "ok"
    assert "流式" in r["detail"]

    # 非流式 200 → fail + 建议
    def fake_urlopen_nostream(req, timeout=0):
        if "/models" in req.full_url:
            return _Resp(b'{"data":[{"id":"m1"}]}', "application/json")
        return _Resp(b"{}", "application/json")

    monkeypatch.setattr(ae.urllib.request, "urlopen", fake_urlopen_nostream)
    r2 = ae._probe_llm_model("http://x:1234", "m1", "")
    assert r2["status"] == "fail"
    assert "Ollama" in (r2.get("note") or "")
