"""Architect 项目库路由测试：contextvar 定位 / 主库默认桶 / 全库扫描 / 行定位写。

Run: cd <repo> && python -m pytest plugins/architect/tests/test_project_db_routing.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.arch_routes import db_schema


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    return C.setup(data_dir=data)


# ── ctx 项目库管理 ─────────────────────────────────────────────

class TestCtxProjectDb:
    def test_project_db_created_under_arch_dir(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        db = C.project_db("proj-a1")
        assert db.db_path == os.path.join(str(tmp_path), "arch", "architect", "proj-a1", "arch.db")
        # 表结构已初始化
        assert db.fetchone("SELECT COUNT(*) AS c FROM sqlite_master WHERE name='arch_requirements'")["c"] == 1
        # 缓存命中
        assert C.project_db("proj-a1") is db
        # create=False 且不存在 → None
        assert C.project_db("proj-nope", create=False) is None

    def test_project_pids_on_disk(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        C.project_db("proj-a1")
        C.project_db("proj-b2")
        assert C.project_pids_on_disk() == ["proj-a1", "proj-b2"]

    def test_contextvar(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        assert C.get_project() is None
        token = C.set_project("proj-c3")
        assert C.get_project() == "proj-c3"
        C.reset_project(token)
        assert C.get_project() is None

    def test_delete_project_db(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        C.project_db("proj-d4")
        C.delete_project_db("proj-d4")
        assert not os.path.exists(C.project_db_path("proj-d4"))
        assert C.project_db("proj-d4", create=False) is None


# ── store 路由 ─────────────────────────────────────────────────

class TestStoreRouting:
    def test_global_tables_stay_in_main(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        store.ProjectsStore.create({
            "id": "proj-g1", "name": "G", "rootPath": "/x",
            "createdAt": 1, "updatedAt": 1,
        })
        row = store.ProjectsStore.get("proj-g1")
        assert row["name"] == "G"
        # 主库有行
        assert C.db().fetchone("SELECT id FROM arch_projects WHERE id=?", ("proj-g1",))

    def test_write_without_context_goes_to_main_bucket(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        store.RequirementsStore.create({"id": "req-1", "title": "无上下文", "updatedAt": 1})
        assert C.db().fetchone("SELECT id FROM arch_requirements WHERE id=?", ("req-1",))

    def test_payload_project_id_routes_to_project_db(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        store.ConversationsStore.create({
            "kind": "requirement", "projectId": "proj-p1", "title": "t",
            "createdAt": 1, "updatedAt": 1,
        })
        # 行落在项目库，主库默认桶没有
        pdb = C.project_db("proj-p1", create=False)
        assert pdb is not None
        assert pdb.fetchone("SELECT id FROM arch_conversations") is not None
        assert C.db().fetchone("SELECT id FROM arch_conversations") is None

    def test_context_routes_reads_and_writes(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        token = C.set_project("proj-p2")
        try:
            store.PlansStore.create({"id": "plan-1", "title": "上下文方案", "updatedAt": 1})
            pdb = C.project_db("proj-p2", create=False)
            assert pdb is not None
            assert pdb.fetchone("SELECT id FROM arch_plans WHERE id=?", ("plan-1",))
            # 有上下文读 → 只查项目库
            assert store.PlansStore.get("plan-1")["title"] == "上下文方案"
            assert store.PlansStore.all() == [store._row_to_api(
                pdb.fetchone("SELECT * FROM arch_plans WHERE id=?", ("plan-1",)))]
        finally:
            C.reset_project(token)

    def test_scan_get_without_context(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        # 项目库里的行(经载荷 projectId)
        store.SemanticAssetsStore.create({
            "id": "sa-1", "projectId": "proj-s1", "kind": "entity", "name": "n",
            "scopeType": "files", "scopeKey": "f.py", "status": "active",
            "createdAt": 1, "updatedAt": 1,
        })
        # 主库默认桶的行(无上下文)
        store.TagsStore.create({"id": "tag-1", "label": "x", "createdAt": 1, "updatedAt": 1})
        # 无上下文 get → 全库扫描命中
        assert store.SemanticAssetsStore.get("sa-1")["name"] == "n"
        assert store.TagsStore.get("tag-1")["label"] == "x"
        # 无上下文 all → 合并
        assert any(t["id"] == "tag-1" for t in store.TagsStore.all())
        assert any(a["id"] == "sa-1" for a in store.SemanticAssetsStore.all())

    def test_locate_db_update_without_context(self, tmp_path, monkeypatch):
        """id 定位写: 行在项目库、无上下文 update/delete 仍能命中(WS 后续消息场景)。"""
        _setup(tmp_path, monkeypatch)
        store.AgentSessionsStore.create({"id": "sess-1", "status": "idle", "createdAt": 1, "updatedAt": 1})
        # 会话落入主库默认桶; 改放项目库场景:
        token = C.set_project("proj-l1")
        store.AgentSessionsStore.create({"id": "sess-2", "status": "idle", "createdAt": 1, "updatedAt": 1})
        C.reset_project(token)
        # 无上下文更新项目库里的会话
        out = store.AgentSessionsStore.update("sess-2", {"status": "busy"})
        assert out and out["status"] == "busy"
        pdb = C.project_db("proj-l1", create=False)
        assert pdb.fetchone("SELECT status FROM arch_agent_sessions WHERE id=?", ("sess-2",))["status"] == "busy"
        # 无上下文删除
        assert store.AgentSessionsStore.delete("sess-2") is True
        assert pdb.fetchone("SELECT id FROM arch_agent_sessions WHERE id=?", ("sess-2",)) is None

    def test_project_scoped_read_no_cross_leak(self, tmp_path, monkeypatch):
        """显式项目定位但该库不存在 → 空结果(不跨项目泄漏)。"""
        _setup(tmp_path, monkeypatch)
        store.SemanticAssetsStore.create({
            "id": "sa-9", "projectId": "proj-x9", "kind": "entity", "name": "n9",
            "scopeType": "files", "scopeKey": "f.py", "status": "active",
            "createdAt": 1, "updatedAt": 1,
        })
        # 查一个不存在库的项目 → 空
        assert store.SemanticAssetsStore.search("proj-ghost", text="n9") == []
        assert store.SemanticAssetsStore.count("proj-ghost") == 0
        # 查 proj-x9 → 命中
        assert store.SemanticAssetsStore.search("proj-x9", text="n9")[0]["id"] == "sa-9"

    def test_run_atomic_routes_by_context(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        store.PlansStore.create({"id": "plan-9", "title": "p", "updatedAt": 1})
        token = C.set_project("proj-atom")
        store.PlansStore.create({"id": "plan-10", "title": "p10", "updatedAt": 1})
        try:
            store.run_atomic([
                ("UPDATE arch_plans SET status = ? WHERE id = ?", ("done", "plan-10")),
            ], table="arch_plans")
        finally:
            C.reset_project(token)
        pdb = C.project_db("proj-atom", create=False)
        assert pdb is not None
        assert pdb.fetchone("SELECT status FROM arch_plans WHERE id=?", ("plan-10",))["status"] == "done"

    def test_migration_idempotent_on_project_db(self, tmp_path, monkeypatch):
        """项目库迁移幂等: 重跑 init 不改写已有行(rule 保持一级类别)。"""
        _setup(tmp_path, monkeypatch)
        store.SemanticAssetsStore.create({
            "id": "sa-r1", "projectId": "proj-m1", "kind": "rule", "level": "implementation",
            "name": "规则", "scopeType": "files", "scopeKey": "c.py", "status": "active",
            "createdAt": 1, "updatedAt": 1,
        })
        pdb = C.project_db("proj-m1")
        db_schema.init_architect_project_db(pdb)
        assert store.SemanticAssetsStore.get("sa-r1")["kind"] == "rule"
