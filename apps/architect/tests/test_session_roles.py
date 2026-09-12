"""执行器实例化 REST(host/models) + 模型探活参数面(角色目录已退役)。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path):
    from topoone_app_architect.arch_routes import ctx as C
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
