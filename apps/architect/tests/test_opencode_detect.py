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
    models, total = AE._parse_oc_providers(_PROVIDERS, _PROVIDER_LIST)
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
    models, total = AE._parse_oc_providers(_PROVIDERS, None)
    # source=config 恒保留; env 无密钥未连接被过滤
    assert total == 4
    assert {m["model"] for m in models} == {"ollama/qwen3:32b"}
    assert "context" not in models[0] and models[0]["connected"] is False


def test_parse_oc_agents_sort_and_fullname():
    agents = AE._parse_oc_agents([
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
    monkeypatch.setattr(AE, "_start_opencode_serve",
                        lambda cfg, cwd="": {"status": "ok", "port": 3478,
                                             "note": "serve 已拉起"})
    by_path = {"/config/providers": _PROVIDERS,
               "/provider": _PROVIDER_LIST,
               "/agent": [{"name": "build", "mode": "primary", "builtIn": True}]}

    def fake_get_json(url, timeout=10.0):
        return by_path.get(f"http://127.0.0.1:3478".join(url.split("http://127.0.0.1:3478")[1:]))

    monkeypatch.setattr(AE, "_get_json", fake_get_json)
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
    monkeypatch.setattr(AE, "_start_opencode_serve",
                        lambda cfg, cwd="": {"status": "ok", "port": 3478, "note": ""})
    monkeypatch.setattr(AE, "_get_json", lambda url, timeout=10.0: None)
    monkeypatch.setattr(AE.urllib.request, "urlopen",
                        lambda url, timeout=10: _FakeResp({"provider": {
                            "ollama": {"options": {"baseURL": "http://127.0.0.1:11434/v1"},
                                       "models": {"qwen3:32b": {}}}}}))
    monkeypatch.setattr(_t, "sleep", lambda s: None)
    d = _detect(client).json()["data"]
    assert d["status"] == "ok"
    assert d["models"] == [{"name": "qwen3:32b", "model": "ollama/qwen3:32b",
                            "url": "http://127.0.0.1:11434/v1", "kind": "local"}]
    assert d["agents"] == [] and d["total"] == 0 and d["omitted"] == 0
