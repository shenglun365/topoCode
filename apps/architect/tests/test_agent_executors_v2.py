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


def test_cline_config_schema_extended(tmp_path, monkeypatch):
    """隔离环境(规范化环节六): 读默认注册表, 不受开发机真实库状态影响。"""
    from tests.conftest import isolate_arch
    isolate_arch(tmp_path, monkeypatch)
    entry = [e for e in ae.load_executors() if e.get("id") == "cline"][0]
    cfg = entry["config"]
    for key in ("node_bin", "sidecar_script", "provider_id", "model_id",
                "api_key", "max_iterations", "system_prompt",
                "tool_policies", "models"):
        assert key in cfg, f"cline config 缺 {key}"


def test_cline_builtin_self_heal(tmp_path, monkeypatch):
    """cline 内置执行器自愈: 注册表缺失(旧数据/误删) → 注入置首;
    已有用户默认执行器时不抢 default; 幂等不重复注入。"""
    from tests.conftest import isolate_arch
    isolate_arch(tmp_path, monkeypatch)
    ae.save_executors([{"id": "opencode", "type": "opencode", "enabled": True,
                        "default": True, "config": {"auto_start": True}}])
    entries = ae.load_executors()
    assert [e["id"] for e in entries] == ["cline", "opencode"]      # 置首
    assert [e.get("default") for e in entries] == [False, True]     # 尊重用户默认
    assert sum(1 for e in ae.load_executors() if e["id"] == "cline") == 1


def test_builtin_cline_models_projection(tmp_path, monkeypatch):
    """内置 cline 模型面=architect 实例模型实时投影: 任务下发注入全量实例条目
    (端点/密钥随实例), 执行器只持默认模型 model_id; PUT 保存不落盘模型快照。"""
    import asyncio
    from fastapi import BackgroundTasks
    from tests.conftest import isolate_arch
    isolate_arch(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import agent_executors as ae
    from topoone_app_architect.arch_routes import exec_bridge as EB
    from topoone_app_architect.arch_routes import mcp_collab as MC
    MC.save_llm_models([
        {"source": "manual", "id": "m1", "name": "LMS-a", "model": "ma",
         "provider": "p", "url": "http://u1/v1", "apiKey": "sk-a"},
        {"source": "manual", "id": "m2", "name": "LMS-b", "model": "mb",
         "provider": "p", "url": "http://u2/v1"},
    ])
    ae.save_executors([{"id": "cline", "type": "cline-sdk", "enabled": True,
                        "default": True,
                        "config": {"node_bin": "node", "sidecar_script": "",
                                   "model_id": "LMS-b", "models": [],
                                   "api_key": "", "max_iterations": 40}}])
    # 任务下发: 模型面=实例投影(含密钥/端点), 默认模型=用户选定
    hint = EB.executor_hint_by_id("cline")
    cfgx = hint["executorConfig"]
    assert [m["name"] for m in cfgx["models"]] == ["LMS-a", "LMS-b"]
    assert cfgx["models"][0]["apiKey"] == "sk-a"
    assert hint["model"] == "LMS-b"            # 默认模型=用户选定(解析链顶层)
    # PUT 保存: 投影不落盘(config.models 保持空, 防快照过期复活)
    class _Req:
        def __init__(self, body):
            self._b = body
        async def json(self):
            return self._b
    entries = ae.load_executors()
    entries[0]["config"]["models"] = [{"name": "stale", "model": "s", "url": "http://x/v1"}]
    r = asyncio.run(ae.put_executors(_Req({"executors": entries}), BackgroundTasks()))
    assert r.get("code") == 0, r
    assert ae.load_executors()[0]["config"]["models"] == []


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


def test_validate_rejects_cline_without_models():
    """环节四: cline-sdk(外部) 无任何模型配置 → 写入拒绝(cv-163 空模型教训前移到写侧)。
    内置 cline 豁免——模型面=实例实时投影, 空 models 合法。"""
    from topoone_app_architect.arch_routes import agent_executors as ae
    msg = ae._validate([{"id": "cline-x", "type": "cline-sdk", "enabled": True,
                         "config": {"models": []}}])
    assert msg and "需配置模型" in msg
    assert ae._validate([{"id": "cline", "type": "cline-sdk", "enabled": True,
                          "config": {"models": []}}]) is None


def test_validate_rejects_dangling_default_model_id():
    """顶层默认 model_id 未命中 models 条目 → 拒绝(执行模型与 UI 展示一致性)。"""
    from topoone_app_architect.arch_routes import agent_executors as ae
    msg = ae._validate([{"id": "cline-x", "type": "cline-sdk", "enabled": True,
                         "config": {"model_id": "gone",
                                    "models": [{"name": "m1", "model": "q", "url": "http://h:8082"}]}}])
    assert msg and "未命中" in msg
    ok = ae._validate([{"id": "cline-x", "type": "cline-sdk", "enabled": True,
                        "config": {"model_id": "m1",
                                   "models": [{"name": "m1", "model": "q", "url": "http://h:8082"}]}}])
    assert ok is None


def test_validate_url_rule_scoped_to_cline():
    """url 强校验仅 cline-sdk; opencode models 条目 url 可选(自身服务器语义)。"""
    from topoone_app_architect.arch_routes import agent_executors as ae
    ok = ae._validate([{"id": "oc", "type": "opencode", "enabled": True,
                        "config": {"models": [{"name": "备模型", "model": "dup"}]}}])
    assert ok is None


def test_validate_rejects_bad_model_url():
    from topoone_app_architect.arch_routes import agent_executors as ae
    msg = ae._validate([{"id": "cline-x", "type": "cline-sdk", "enabled": True,
                         "config": {"models": [{"name": "m1", "model": "q", "url": "ftp://h"}]}}])
    assert msg and "url 非法" in msg
