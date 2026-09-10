"""PR1 双维度状态机: 生命周期(active/running/archived 不可逆) + 查看状态。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path))
    from topoone_app_architect import server as _srv
    app = _srv.build_app(data_dir=str(tmp_path / "arch"))
    return TestClient(app)


def _auth(client):
    tok = client.get("/api/architect/health").json().get("data", {}).get("token")
    h = {"Authorization": f"Bearer {tok}"} if tok else {}
    return h


def test_lifecycle_validation_and_archive_irreversible(client):
    h = _auth(client)
    c = client.post("/api/architect/sessions", json={"kind": "generic", "title": "T"},
                    headers=h).json()["data"]
    assert c["status"] == "active" and c["reviewState"] == "read"
    assert c["roleId"] == "architect"
    # 非法旧值拒绝
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"status": "waiting"}, headers=h)
    assert r.status_code == 400
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"status": "done"}, headers=h)
    assert r.status_code == 400
    # reviewState 校验
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"reviewState": "bad"}, headers=h)
    assert r.status_code == 400
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"reviewState": "unread"}, headers=h)
    assert r.json()["data"]["reviewState"] == "unread"
    # 归档 → 不可逆
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"status": "archived"}, headers=h)
    assert r.json()["data"]["status"] == "archived"
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"status": "active"}, headers=h)
    assert r.status_code == 400
    # 归档后 reviewState 仍可更新(读标记)
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"reviewState": "read"}, headers=h)
    assert r.json()["data"]["reviewState"] == "read"


def test_legacy_status_migration(client):
    """存量单值状态迁移: waiting→awaiting_reply+active; pending→active+pendingExec。"""
    from topoone_app_architect.arch_routes import store
    store.ConversationsStore.create({"id": "cv-old1", "kind": "asset", "status": "waiting"})
    store.ConversationsStore.create({"id": "cv-old2", "kind": "execution", "status": "pending"})
    from topoone_app_architect.arch_routes.db_schema import _migrate_conversation_lifecycle
    db = store._db()
    _migrate_conversation_lifecycle(db)
    c1 = store.ConversationsStore.get("cv-old1")
    assert c1["status"] == "active" and c1["reviewState"] == "awaiting_reply"
    c2 = store.ConversationsStore.get("cv-old2")
    assert c2["status"] == "active" and c2["reviewState"] == "read"
    meta = c2.get("meta") or {}
    assert (meta.get("pendingExec") if isinstance(meta, dict) else True) is True


def test_roles_seed_and_builtin_protection(client):
    from topoone_app_architect.arch_routes import store
    roles = store.SessionRolesStore.all()
    arch = [r for r in roles if r["id"] == "architect"]
    assert arch and arch[0]["kind"] == "architect" and arch[0]["builtin"]
    # 内置角色不可删
    assert store.SessionRolesStore.delete("architect") is False
    # executor 角色可建可删
    r = store.SessionRolesStore.upsert({"id": "exec-cline", "name": "执行器·cline",
                                        "executorId": "cline"})
    assert r["id"] == "exec-cline" and r["kind"] == "executor"
    # 内置角色改绑定被忽略
    store.SessionRolesStore.upsert({"id": "architect", "name": "Architect",
                                    "executorId": "hijack", "kind": "executor"})
    assert store.SessionRolesStore.get("architect")["executorId"] == ""
    assert store.SessionRolesStore.delete("exec-cline") is True


def test_spawn_execution_session_dual_state(client):
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes.requirements import spawn_execution_session
    store.RequirementsStore.create({"id": "RQ-D1", "title": "双态测试", "desc": "d"})
    conv = spawn_execution_session({"id": "RQ-D1", "title": "双态测试",
                                    "analysis": {"acceptance": ["构建通过"]}})
    row = store.ConversationsStore.get(conv["id"])
    assert row["status"] == "active" and row["reviewState"] == "unread"
    meta = row.get("meta") or {}
    assert isinstance(meta, dict) and meta.get("pendingExec") is True


def test_asset_locks_conflict(client):
    from topoone_app_architect.arch_routes import store
    store.AssetLocksStore.__dict__["TABLE"]  # 表存在
    store._insert("arch_asset_locks", {
        "id": "lk-1", "project_id": "p1", "resource": "src/a.ts",
        "granularity": "file", "holder": "exec-1", "holder_title": "任务A",
    })
    conflicts = store.AssetLocksStore.conflicts("p1", ["src/a.ts", "src/b.ts"])
    assert len(conflicts) == 1 and conflicts[0]["holder"] == "exec-1"
    assert store.AssetLocksStore.conflicts("p1", ["src/a.ts"], exclude_holder="exec-1") == []
