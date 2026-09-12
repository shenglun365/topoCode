"""生命周期重构 v2 回归：workState 相位 / roles 声明 / 规约版本链 / 登记簿状态。

Run: cd <repo> && python -m pytest apps/architect/tests/test_session_lifecycle.py -q
"""
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
from topoone_app_architect.arch_routes import store

from fastapi.testclient import TestClient
from topoone_app_architect.server import build_app


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    return data


def _client(monkeypatch, data):
    app = build_app(data_dir=data)
    return TestClient(app)


def _h(client):
    return {"Authorization": "Bearer test"}


def _mk_confirmed_req(rid, **snap):
    s = {"title": "T", "desc": "", "designMd": "方案", "allowedScope": ["modules/x/"],
         "forbiddenScope": [], "acceptance": ["编译通过"], "functionalScope": [],
         "assessmentSummary": "", "estMin": 0}
    s.update(snap)
    store.RequirementsStore.create({
        "id": rid, "title": s["title"], "status": "ready",
        "specVersions": [{"ver": 1, "state": "confirmed", "snapshot": s,
                          "source": {"convId": "", "actor": "t"},
                          "reason": "", "createdAt": 1}],
        "activeVer": 1, "updatedAt": 1, "createdAt": 1})


# ── 会话: roles 声明 + workState ──

def test_session_binding_and_workstate(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    assert store.ConversationsStore.roles_of(conv["id"]) == ["architect"]
    assert (store.ConversationsStore.get(conv["id"]) or {}).get("executorId") == ""
    store.ConversationsStore.update(conv["id"], {"executorId": "ex-1"})
    assert (store.ConversationsStore.get(conv["id"]) or {}).get("executorId") == "ex-1"
    store.ConversationsStore.set_work_state(conv["id"], "running")
    assert store.ConversationsStore.work_state(conv["id"]) == "running"
    store.ConversationsStore.set_work_state(conv["id"], "architect")
    assert store.ConversationsStore.work_state(conv["id"]) == "architect"


def test_rest_bind_clone_and_lifecycle(tmp_path, monkeypatch):
    data = _setup(tmp_path, monkeypatch)
    client = _client(monkeypatch, data)
    # 注册两个执行器(collab config 单源)
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex-1", "type": "opencode", "enabled": True, "config": {}, "models": []},
        {"id": "ex-2", "type": "cline-sdk", "enabled": True, "config": {}, "models": []},
    ])
    # 创建即绑定
    c = client.post("/api/architect/sessions",
                    json={"kind": "generic", "executorId": "ex-1"}, headers=_h(client)).json()["data"]
    assert c["executorId"] == "ex-1" and c["workState"] == "architect"
    # 不存在执行器 → 400
    r = client.post("/api/architect/sessions",
                    json={"kind": "generic", "executorId": "ghost"}, headers=_h(client))
    assert r.status_code == 400
    # 已绑定再 bind → 409; PATCH 改绑定 → 409
    r = client.post(f"/api/architect/sessions/{c['id']}/bind",
                    json={"executorId": "ex-2"}, headers=_h(client))
    assert r.json()["code"] == 409
    r = client.patch(f"/api/architect/sessions/{c['id']}",
                     json={"executorId": "ex-2"}, headers=_h(client))
    assert r.json()["code"] == 409
    # 克隆 → 新会话带新绑定 + seed 标记
    r = client.post(f"/api/architect/sessions/{c['id']}/clone",
                    json={"executorId": "ex-2"}, headers=_h(client))
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["executorId"] == "ex-2" and d["id"] != c["id"] and d["reqId"] == c["reqId"]
    # 未绑定会话 bind → 成功; 二次 → 409
    c2 = client.post("/api/architect/sessions",
                     json={"kind": "generic"}, headers=_h(client)).json()["data"]
    r = client.post(f"/api/architect/sessions/{c2['id']}/bind",
                    json={"executorId": "ex-1"}, headers=_h(client))
    assert r.status_code == 200 and r.json()["data"]["executorId"] == "ex-1"
    r = client.post(f"/api/architect/sessions/{c2['id']}/bind",
                    json={"executorId": "ex-2"}, headers=_h(client))
    assert r.json()["code"] == 409
    # status 仅 active|archived; 归档不可逆
    r = client.patch(f"/api/architect/sessions/{c['id']}",
                     json={"status": "running"}, headers=_h(client))
    assert r.status_code == 400
    r = client.patch(f"/api/architect/sessions/{c['id']}",
                     json={"status": "archived"}, headers=_h(client))
    assert r.status_code == 200 and r.json()["data"]["status"] == "archived"
    r = client.patch(f"/api/architect/sessions/{c['id']}",
                     json={"status": "active"}, headers=_h(client))
    assert r.status_code == 400


def test_execution_kind_removed(tmp_path, monkeypatch):
    data = _setup(tmp_path, monkeypatch)
    client = _client(monkeypatch, data)
    r = client.post("/api/architect/sessions",
                    json={"kind": "execution"}, headers=_h(client))
    c = r.json()["data"]
    assert c["kind"] == "requirement"      # 非法 kind 落默认


# ── 规约版本链 + 登记簿 ──

def test_spec_lifecycle_versions(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    store.RequirementsStore.create({
        "id": "RQ-A", "title": "A", "status": "draft",
        "specVersions": [{"ver": 1, "state": "draft",
                          "snapshot": {"title": "A", "designMd": "v1", "acceptance": ["a"],
                                       "allowedScope": ["modules/a/"]},
                          "source": {"convId": "", "actor": "t"}, "reason": "", "createdAt": 1}],
        "activeVer": 1, "updatedAt": 1, "createdAt": 1})
    # append v2 → active 切换, 仍 draft
    e = store.RequirementsStore.spec_append("RQ-A", {"title": "A", "designMd": "v2",
        "acceptance": ["a"], "allowedScope": ["modules/b/"]}, reason="修订")
    assert e["ver"] == 2
    assert store.RequirementsStore.get("RQ-A")["status"] == "draft"
    # confirm → ready + v1 隐式 superseded? v1 是 draft 不是 confirmed → 保持 draft
    res = store.RequirementsStore.spec_confirm("RQ-A")
    assert res["ok"]
    vs = store.RequirementsStore.spec_versions("RQ-A")
    assert vs[0]["state"] == "draft" and vs[1]["state"] == "confirmed"
    # 再修订 + confirm → v2 superseded(隐式废弃)
    store.RequirementsStore.spec_append("RQ-A", {"title": "A", "designMd": "v3",
        "acceptance": ["a"], "allowedScope": ["modules/c/"]})
    store.RequirementsStore.spec_confirm("RQ-A")
    vs = store.RequirementsStore.spec_versions("RQ-A")
    assert vs[1]["state"] == "superseded" and vs[2]["state"] == "confirmed"
    assert store.RequirementsStore.get("RQ-A")["status"] == "ready"
    # 用户完成判定 → done; 之后 spec_append 不应发生(工具层拦), store 层保护状态
    store.RequirementsStore.mark_done("RQ-A")
    row = store.RequirementsStore.get("RQ-A")
    assert row["status"] == "done" and row["doneMark"] == 1


def test_migration_v2_from_legacy(tmp_path, monkeypatch):
    """存量 RQ(analysis/status=analyzed) → v1 confirmed + ready。"""
    _setup(tmp_path, monkeypatch)
    store.RequirementsStore.create({
        "id": "RQ-M", "title": "迁移", "status": "analyzed",
        "analysis": json.dumps({"designMd": "旧方案", "acceptance": ["x"],
                                "allowedScope": ["src/a/"]}),
        "updatedAt": 111})
    from topoone_app_architect.arch_routes.db_schema import _migrate_lifecycle_v2
    from topoone_app_architect.arch_routes.store.base import _db
    _migrate_lifecycle_v2(_db())
    _migrate_lifecycle_v2(_db())  # 幂等
    r = store.RequirementsStore.get("RQ-M")
    assert r["status"] == "ready" and r["activeVer"] == 1
    v = store.RequirementsStore.spec_active("RQ-M")
    assert v["state"] == "confirmed" and v["snapshot"]["designMd"] == "旧方案"
    # analysis 派生缓存同步
    assert r["analysis"]["designMd"] == "旧方案"


def test_migration_v2_deletes_execution_convs(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    ce = store.ConversationsStore.create({"kind": "execution", "title": "旧执行会话"})
    store.ConversationsStore.append_message({"id": "m-x", "conversationId": ce["id"],
                                              "role": "assistant", "time": 1, "content": "x"})
    cn = store.ConversationsStore.create({"kind": "generic", "title": "留"})
    from topoone_app_architect.arch_routes.db_schema import _migrate_lifecycle_v2
    from topoone_app_architect.arch_routes.store.base import _db
    _migrate_lifecycle_v2(_db())
    assert store.ConversationsStore.get(ce["id"]) is None
    assert store.ConversationsStore.get(cn["id"]) is not None
    assert store.ConversationsStore.messages(ce["id"]) == []
