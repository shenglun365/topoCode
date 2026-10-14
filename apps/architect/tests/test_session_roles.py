"""执行器实例化 REST(host/models) + 模型探活参数面(角色目录已退役)。"""
import pytest
from fastapi.testclient import TestClient


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


def test_executor_instance_models_validation(client):
    from topoone_app_architect.arch_routes import agent_executors as AE
    entries = [{
        "id": "oc-remote", "type": "opencode", "host": "remote", "enabled": True,
        "config": {"base_url": "http://192.168.1.9:3478", "models": [
            {"name": "主模型", "model": "qwen-32b", "url": "http://192.168.1.9:8200/v1"},
            {"name": "主模型", "model": "dup"},          # 名称重复 → 拒绝
        ]},
    }]
    assert AE._validate(entries) == "执行器 oc-remote 模型名称重复"
    entries[0]["config"]["models"][1]["name"] = "备模型"
    assert AE._validate(entries) is None
    norm = entries[0]["config"]["models"]
    assert norm[0]["maxTokens"] == 0 and norm[1]["url"] == ""
    # host 非法
    entries[0]["host"] = "mars"
    assert AE._validate(entries) == "非法 host: mars(local|remote)"


def test_mask_and_merge_secret_models():
    from topoone_app_architect.arch_routes import agent_executors as AE
    entries = [{"id": "e1", "type": "opencode",
                "config": {"models": [{"name": "m", "model": "q", "apiKey": "sk-真钥"}]}}]
    masked = AE._mask(entries)
    assert masked[0]["config"]["models"][0]["apiKey"] == "******"
    # 保存合并: ****** → 还原旧密钥
    AE._merge_secret_models(entries, {"e1": {"config": {"models": [
        {"name": "m", "apiKey": "sk-真钥"}]}}})
    assert entries[0]["config"]["models"][0]["apiKey"] == "sk-真钥"


def test_model_probe_missing_params(client):
    h = _h(client)
    r = client.post("/api/architect/agent/executors/model-probe",
                    json={"url": ""}, headers=h)
    assert r.status_code == 400


def test_put_duplicate_model_name_is_400_not_500(client):
    """校验失败须回 400+文案(err 单参曾 TypeError→500, 保存静默失败)。"""
    h = _h(client)
    base = client.get("/api/architect/agent/executors", headers=h).json()["data"]["executors"]
    entries = [dict(e) for e in base]   # 保住内置 cline
    oc = next(e for e in entries if e["id"] == "opencode")
    # 同 bare id 跨 provider(name 重复) → 校验拒绝
    oc["config"]["models"] = [
        {"name": "qwen3.8-flash", "model": "dashscope/qwen3.8-flash", "url": ""},
        {"name": "qwen3.8-flash", "model": "qwen/qwen3.8-flash", "url": ""}]
    r = client.put("/api/architect/agent/executors", json={"executors": entries}, headers=h)
    assert r.status_code == 400
    assert "模型名称重复" in r.json()["message"]
    # 全名 name(前端 toggleModel 现行为) → 同 bare id 亦可通过
    oc["config"]["models"] = [
        {"name": "dashscope/qwen3.8-flash", "model": "dashscope/qwen3.8-flash", "url": ""},
        {"name": "qwen/qwen3.8-flash", "model": "qwen/qwen3.8-flash", "url": ""}]
    r2 = client.put("/api/architect/agent/executors", json={"executors": entries}, headers=h)
    assert r2.status_code == 200, r2.json()
    saved = client.get("/api/architect/agent/executors", headers=h).json()["data"]["executors"]
    oc2 = next(e for e in saved if e["id"] == "opencode")
    assert [m["model"] for m in oc2["config"]["models"]] == [
        "dashscope/qwen3.8-flash", "qwen/qwen3.8-flash"]


# ── 直连客户端偏好回退(35B 残留根因修复, 2610-10-08) ─────────────────

def test_extract_model_falls_back_to_preference(arch_env, monkeypatch):
    """角色空 → architect 偏好(llm.modelId); 不再直落 KB is_default。"""
    from topoone_app_architect.arch_routes import asset_extract as ae
    from topoone_app_architect.agent.cognition import llm as llm_mod
    monkeypatch.setattr(llm_mod, "get_model_preference",
                        lambda: "qwen3.5-9b-mtp")
    captured = {}

    class FakeLLM:
        def __init__(self, gateway, model_id: str = "", session_id: str = "x"):
            captured["model"] = model_id
        async def chat(self, messages, **kw):
            raise RuntimeError("stop")

    import topoone_app_architect.arch_routes.tagent_se as tse
    monkeypatch.setattr(tse, "KbGatewayLLMClient", FakeLLM)
    ae._batch_name_enrich("/nonexistent", "", "f.py", "entity",
                          [{"node": {"name": "A", "start_line": 1}}], None)
    assert captured["model"] == "qwen3.5-9b-mtp"


def test_extract_model_explicit_wins(arch_env, monkeypatch):
    from topoone_app_architect.arch_routes import asset_extract as ae
    from topoone_app_architect.agent.cognition import llm as llm_mod
    monkeypatch.setattr(llm_mod, "get_model_preference",
                        lambda: "qwen3.5-9b-mtp")
    captured = {}

    class FakeLLM:
        def __init__(self, gateway, model_id: str = "", session_id: str = "x"):
            captured["model"] = model_id
        async def chat(self, messages, **kw):
            raise RuntimeError("stop")

    import topoone_app_architect.arch_routes.tagent_se as tse
    monkeypatch.setattr(tse, "KbGatewayLLMClient", FakeLLM)
    ae._batch_name_enrich("/nonexistent", "", "f.py", "entity",
                          [{"node": {"name": "A", "start_line": 1}}],
                          "explicit-model")
    assert captured["model"] == "explicit-model"


def test_utgen_model_falls_back_to_preference(arch_env, monkeypatch):
    from topoone_app_architect.arch_routes import tagent_utgen as ut
    from topoone_app_architect.agent.cognition import llm as llm_mod
    from topoone_app_architect import kb_gateway as kg
    monkeypatch.setattr(llm_mod, "get_model_preference",
                        lambda: "qwen3.5-9b-mtp")
    monkeypatch.setattr(kg, "get_gateway", lambda: object())
    captured = {}

    class FakeLLM:
        def __init__(self, gateway, model_id: str = "", session_id: str = "x"):
            captured["model"] = model_id

    monkeypatch.setattr(ut, "KbGatewayLLMClient", FakeLLM)
    monkeypatch.setattr(ut, "_run_gen_async",
                        lambda *a, **k: _async_none())
    ut.generate_unit_tests(scope="s", root="/r", project="", model_id="")
    assert captured["model"] == "qwen3.5-9b-mtp"


def _async_none():
    import asyncio
    async def _n(*a, **k):
        return None
    return _n()
