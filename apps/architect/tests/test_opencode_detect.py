"""opencode 探测面(全量模型目录/内置代理)解析 + /models/detect 路由降级。

覆盖:
- _parse_oc_providers: 降噪过滤(已连接∪有密钥∪source=config) + /provider 元数据合并
- _parse_oc_agents: builtIn 置前 + model 全名
- 路由: /config/providers 主探测面; 旧版 serve 探测面缺失 → /config 兜底
"""
import json

import pytest
from fastapi.testclient import TestClient

from topoone_app_architect.arch_routes import agent_executors as AE
from topoone_app_architect.arch_routes import opencode_detect as OD


@pytest.fixture()
def client(tmp_path):
    from topoone_app_architect import ctx as C
    C._db = None; C._kb = None; C._data_dir = None
    C._project_dbs.clear()
    from topoone_app_architect import server as _srv
    app = _srv.build_app(data_dir=str(tmp_path / "arch"))
    return TestClient(app)


def _h(client):
    tok = client.get("/api/architect/health").json().get("data", {}).get("token")
    return {"Authorization": f"Bearer {tok}"} if tok else {}


_PROVIDERS = {
    "providers": [
        {"id": "anthropic", "source": "env", "env": ["ANTHROPIC_API_KEY"],
         "options": {},
         "models": {"claude-sonnet-4": {}, "claude-opus-4": {}}},
        {"id": "ollama", "source": "config", "env": [],
         "options": {"baseURL": "http://127.0.0.1:11434/v1"},
         "models": {"qwen3:32b": {}}},
        {"id": "google", "source": "env", "env": [], "options": {},
         "models": {"gemini-3-pro": {}}},  # 无密钥未连接 → 折叠进 total
    ],
}

_PROVIDER_LIST = {
    "connected": ["anthropic"],
    "all": [
        {"id": "anthropic", "models": {"claude-sonnet-4": {"limit": {"context": 200000, "output": 64000}},
                                       "claude-opus-4": {}}},
        {"id": "ollama", "models": {"qwen3:32b": {"limit": {"context": 32768, "output": 8192}}}},
        {"id": "google", "models": {"gemini-3-pro": {}}},
    ],
}


def test_parse_oc_providers_filter_and_merge():
    models, total = OD._parse_oc_providers(_PROVIDERS, _PROVIDER_LIST)
    assert total == 4
    got = {m["model"]: m for m in models}
    # google 无密钥未连接 → 过滤; 已连接(anthropic)与 source=config(ollama)保留
    assert set(got) == {"anthropic/claude-sonnet-4", "anthropic/claude-opus-4",
                        "ollama/qwen3:32b"}
    an = got["anthropic/claude-sonnet-4"]
    # 四字段与旧 /config 解析同形(白名单匹配兼容) + 元数据
    assert an["name"] == "claude-sonnet-4" and an["kind"] == "cloud"
    assert an["connected"] is True and an["authed"] is True
    assert an["context"] == 200000 and an["output"] == 64000
    assert an["source"] == "env"
    ol = got["ollama/qwen3:32b"]
    assert ol["kind"] == "local" and ol["url"] == "http://127.0.0.1:11434/v1"
    assert ol["context"] == 32768 and ol["source"] == "config"
    # 排序稳定(全名小写序)
    assert [m["model"] for m in models] == sorted(
        [m["model"] for m in models], key=str.lower)


def test_parse_oc_providers_no_metadata_source():
    """仅 /config/providers(无 /provider 探测面) → 全部保留且无 limit。"""
    models, total = OD._parse_oc_providers(_PROVIDERS, None)
    # source=config 恒保留; env 无密钥未连接被过滤
    assert total == 4
    assert {m["model"] for m in models} == {"ollama/qwen3:32b"}
    assert "context" not in models[0] and models[0]["connected"] is False


def test_parse_oc_agents_sort_and_fullname():
    agents = OD._parse_oc_agents([
        {"name": "reviewer", "mode": "subagent", "builtIn": False, "description": "评审",
         "model": {"providerID": "anthropic", "modelID": "claude-sonnet-4"}},
        {"name": "plan", "mode": "primary", "builtIn": True},
        {"name": "build", "mode": "primary", "builtIn": True},
        "junk", {"name": ""},
    ])
    assert [a["name"] for a in agents] == ["build", "plan", "reviewer"]
    assert agents[-1]["model"] == "anthropic/claude-sonnet-4"
    assert agents[0]["builtIn"] is True and agents[0]["model"] == ""
    assert agents[0]["description"] == ""


class _FakeResp:
    def __init__(self, payload):
        self._p = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._p

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _detect(client, **kw):
    h = _h(client)
    return client.post("/api/architect/agent/executors/models/detect",
                       json={"entry": {"type": "opencode", "config": {}}, "cwd": ""},
                       headers=h)


def test_detect_route_providers_and_agents(client, monkeypatch):
    monkeypatch.setattr(OD, "_start_opencode_serve",
                        lambda cfg, cwd="": {"status": "ok", "port": 3478,
                                             "note": "serve 已拉起"})
    by_path = {"/config/providers": _PROVIDERS,
               "/provider": _PROVIDER_LIST,
               "/agent": [{"name": "build", "mode": "primary", "builtIn": True}]}

    def fake_get_json(url, timeout=10.0):
        return by_path.get(url.removeprefix("http://127.0.0.1:3478"))

    monkeypatch.setattr(OD, "_get_json", fake_get_json)
    r = _detect(client)
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["status"] == "ok" and d["port"] == 3478
    assert {m["model"] for m in d["models"]} >= {"anthropic/claude-sonnet-4",
                                                 "ollama/qwen3:32b"}
    assert d["agents"] == [{"name": "build", "mode": "primary", "builtIn": True,
                            "description": "", "model": ""}]
    assert d["total"] == 4 and d["omitted"] == 1
    assert "1 个未配置密钥" in d["note"]


def test_detect_route_config_fallback(client, monkeypatch):
    """旧版 serve(无 /config/providers 与 /agent)→ /config 兜底解析。"""
    import time as _t
    monkeypatch.setattr(OD, "_start_opencode_serve",
                        lambda cfg, cwd="": {"status": "ok", "port": 3478, "note": ""})
    monkeypatch.setattr(OD, "_get_json", lambda url, timeout=10.0: None)
    monkeypatch.setattr(OD.urllib.request, "urlopen",
                        lambda url, timeout=10: _FakeResp({"provider": {
                            "ollama": {"options": {"baseURL": "http://127.0.0.1:11434/v1"},
                                       "models": {"qwen3:32b": {}}}}}))
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    d = _detect(client).json()["data"]
    assert d["status"] == "ok"
    assert d["models"] == [{"name": "qwen3:32b", "model": "ollama/qwen3:32b",
                            "url": "http://127.0.0.1:11434/v1", "kind": "local"}]
    assert d["agents"] == [] and d["total"] == 0 and d["omitted"] == 0


def test_probe_opencode_model_static(monkeypatch):
    """opencode 侧静态探活: 目录命中 + 凭据判定(零 token)。"""
    monkeypatch.setattr(OD, "_start_opencode_serve",
                        lambda cfg, cwd="": {"status": "ok", "port": 3478, "note": ""})
    by_path = {"/config/providers": _PROVIDERS, "/provider": _PROVIDER_LIST}
    monkeypatch.setattr(OD, "_get_json",
                        lambda url, timeout=10.0:
                        by_path.get(url.removeprefix("http://127.0.0.1:3478")))
    # ok: 已连接 provider 全名
    d = OD._probe_opencode_model({}, "", "anthropic/claude-sonnet-4")
    assert d["status"] == "ok" and "已连接" in d["detail"] and "anthropic" in d["detail"]
    # ok: source=config(本地显式配置, 未连接但凭据面成立)
    d = OD._probe_opencode_model({}, "", "ollama/qwen3:32b")
    assert d["status"] == "ok" and "已显式配置" in d["detail"]
    # ok: 裸名(三级匹配)命中已连接 provider
    d = OD._probe_opencode_model({}, "", "claude-opus-4")
    assert d["status"] == "ok"
    # fail: serve 起不来透传
    monkeypatch.setattr(OD, "_start_opencode_serve",
                        lambda cfg, cwd="": {"status": "fail", "detail": "boom"})
    assert OD._probe_opencode_model({}, "", "anthropic/x") == {
        "status": "fail", "detail": "boom"}
    monkeypatch.setattr(OD, "_start_opencode_serve",
                        lambda cfg, cwd="": {"status": "ok", "port": 3478, "note": ""})
    # fail: 模型不在目录
    d = OD._probe_opencode_model({}, "", "nope/none")
    assert d["status"] == "fail" and "不在 opencode 目录" in d["detail"]
    # fail: provider 无凭据(google 无密钥未连接)
    d = OD._probe_opencode_model({}, "", "google/gemini-3-pro")
    assert d["status"] == "fail" and "未配置密钥" in d["detail"]


def test_model_probe_route_opencode_branch(client, monkeypatch):
    """路由分派: opencode+空 url → opencode 探活; 其余直连路径不变。"""
    h = _h(client)
    seen = {}

    def fake_probe(cfg, cwd, model):
        seen.update(cfg=cfg, cwd=cwd, model=model)
        return {"status": "ok", "detail": "静态"}

    monkeypatch.setattr(AE, "_probe_opencode_model", fake_probe)
    r = client.post("/api/architect/agent/executors/model-probe",
                    json={"url": "", "model": "anthropic/claude-sonnet-4",
                          "entry": {"type": "opencode", "config": {"base_port": 3500}},
                          "cwd": "/tmp/proj"},
                    headers=h)
    assert r.status_code == 200
    assert seen == {"cfg": {"base_port": 3500}, "cwd": "/tmp/proj",
                    "model": "anthropic/claude-sonnet-4"}
    # 非 opencode 类型(或带 url)不被劫持 → 直连探测原语义(缺 url 报错)
    r2 = client.post("/api/architect/agent/executors/model-probe",
                     json={"url": "", "model": "m",
                           "entry": {"type": "cline-sdk", "config": {}}}, headers=h)
    d2 = r2.json()["data"]
    assert d2["status"] == "fail" and "缺少模型服务 url" in d2["detail"]
