"""统一 DB 布局测试：中心项目库路径 / proj-id 签名 / chat.db 双库路由 / 重关联。

Run: cd <repo> && python -m pytest packages/core/tests/test_db_layout.py -q
"""
import asyncio
import os
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", ".."))
sys.path.insert(0, os.path.join(_ROOT, "backend-core"))

from topoone.db.manager import MultiDBManager  # noqa: E402


class _FakeServer:
    def __init__(self):
        self.methods = {}
        self.published = []

    def register(self, name):
        def deco(fn):
            self.methods[name] = fn
            return fn
        return deco

    def publish(self, topic, event, payload):
        self.published.append((topic, event, payload))


def _mk(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    return md


# ── 中心路径 + 签名 ────────────────────────────────────────────

class TestCentralLayout:
    def test_project_db_path_is_central(self, tmp_path):
        md = _mk(tmp_path)
        p = md.project_db_path("proj-abc123")
        assert p == os.path.join(str(tmp_path), "projects", "proj-abc123", "project.db")

    def test_init_project_db_at_central_path(self, tmp_path):
        md = _mk(tmp_path)
        # project_root 传源码目录也不影响落点
        db = md.init_project_db("proj-x1", project_root="/nonexistent/source")
        assert db.db_path == os.path.join(str(tmp_path), "projects", "proj-x1", "project.db")
        assert os.path.isfile(os.path.join(str(tmp_path), "projects", "proj-x1", "project.db"))
        row = db.fetchone("SELECT COUNT(*) AS c FROM source_files")
        assert row["c"] == 0

    def test_get_project_db_central(self, tmp_path):
        md = _mk(tmp_path)
        db = md.get_project_db("proj-g1")
        assert os.path.isfile(md._project_db_path("proj-g1"))
        assert db is md.get_project_db("proj-g1")  # LRU 命中

    def test_delete_project_db_cleans_dir(self, tmp_path):
        md = _mk(tmp_path)
        md.get_project_db("proj-d1")
        md.delete_project_db("proj-d1")
        assert not os.path.exists(os.path.join(str(tmp_path), "projects", "proj-d1", "project.db"))

    def test_proj_signature_roundtrip(self, tmp_path):
        root = str(tmp_path / "src")
        os.makedirs(root)
        MultiDBManager.write_proj_signature(root, "proj-s1")
        assert MultiDBManager.read_proj_signature(root) == "proj-s1"
        MultiDBManager.remove_proj_signature(root)
        assert MultiDBManager.read_proj_signature(root) == ""

    def test_chat_db_tables(self, tmp_path):
        md = _mk(tmp_path)
        for t in ("chat_drafts", "chat_archives", "doc_categories", "llm_sessions", "llm_messages"):
            row = md.chat_db.fetchone(
                "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?", (t,))
            assert row["c"] == 1, t
        assert os.path.isfile(os.path.join(str(tmp_path), "chat.db"))


# ── LLM 会话双库路由 ───────────────────────────────────────────

class TestChatRouting:
    def _svc(self, tmp_path):
        from topoone.llm.service import LLMService
        return LLMService(_mk(tmp_path))

    def test_create_routes_by_module(self, tmp_path):
        from topoone.llm.service import LLMService
        svc = self._svc(tmp_path)
        md = svc.multi_db
        chat_s = svc.create_session("ai_assistant", "chat 会话")
        assert chat_s["id"].startswith("ai-")
        assert md.chat_db.fetchone("SELECT id FROM llm_sessions WHERE id=?", (chat_s["id"],))
        assert not md.sessions_db.fetchone("SELECT id FROM llm_sessions WHERE id=?", (chat_s["id"],))

        other_s = svc.create_session("project_analysis", "分析会话")
        assert md.sessions_db.fetchone("SELECT id FROM llm_sessions WHERE id=?", (other_s["id"],))
        assert not md.chat_db.fetchone("SELECT id FROM llm_sessions WHERE id=?", (other_s["id"],))

    def test_list_sessions_merges_both_dbs(self, tmp_path):
        svc = self._svc(tmp_path)
        svc.create_session("ai_assistant", "c1")
        svc.create_session("project_analysis", "s1")
        svc.create_session("knowledge_base", "s2")
        all_ids = {s["id"] for s in svc.list_sessions()}
        assert len(all_ids) == 3
        chat_only = {s["id"] for s in svc.list_sessions(module_type="ai_assistant")}
        assert len(chat_only) == 1
        sess_only = {s["id"] for s in svc.list_sessions(module_type="project_analysis")}
        assert len(sess_only) == 1

    def test_route_by_session(self, tmp_path):
        svc = self._svc(tmp_path)
        chat_s = svc.create_session("ai_assistant", "c")
        other_s = svc.create_session("project_analysis", "s")
        assert svc._route_by_session(chat_s["id"]) is svc._chat_db()
        assert svc._route_by_session(other_s["id"]) is svc._sessions_db()
        # 未知 id → 缺省会话库
        assert svc._route_by_session("nope") is svc._sessions_db()


# ── 导入重关联(源码目录移动后) ─────────────────────────────────

class TestReassociation:
    def _import(self, tmp_path, path, mode="static"):
        from topoone.engine.service import register_project_methods
        md = _mk(tmp_path)
        srv = _FakeServer()
        register_project_methods(srv, md)
        job = srv.methods["project.import"](path=path, mode=mode)
        # 后台导入任务 → 轮询 project.importStatus 直至完成
        deadline = time.time() + 60
        while True:
            st = srv.methods["project.importStatus"](requestId=job["requestId"])
            if st.get("status") in ("done", "error"):
                break
            assert time.time() < deadline, f"import timeout: {st}"
            time.sleep(0.2)
        assert st.get("status") == "done", f"import failed: {st}"
        row = dict(srv.methods["project.get"](id=st["projectId"]) or {})
        row["reassociated"] = bool(st.get("reassociated"))
        return md, srv, row

    def test_import_writes_signature_and_central_db(self, tmp_path):
        src = tmp_path / "mymod"
        src.mkdir()
        (src / "a.py").write_text("X = 1\n", encoding="utf-8")
        md, srv, row = self._import(tmp_path, str(src))
        assert row["id"].startswith("proj-")
        assert row["root_path"] == str(src)
        # 签名写入 + 项目库中心化
        assert MultiDBManager.read_proj_signature(str(src)) == row["id"]
        assert os.path.isfile(os.path.join(str(tmp_path), "projects", row["id"], "project.db"))
        assert not os.path.exists(os.path.join(str(src), ".topocode", "data"))

    def test_moved_dir_reassociates(self, tmp_path):
        # 1) 先正常导入
        old = tmp_path / "old"
        old.mkdir()
        (old / "a.py").write_text("X = 1\n", encoding="utf-8")
        md, _srv, row1 = self._import(tmp_path, str(old))
        pid = row1["id"]
        # 2) 目录整体“移动”
        new = tmp_path / "moved"
        os.rename(str(old), str(new))
        # 3) 重新导入新路径 → 命中签名重关联(不产生新项目)
        md2, _srv2, row2 = self._import(tmp_path, str(new))
        assert row2.get("reassociated") is True
        assert row2["id"] == pid
        assert row2["root_path"] == str(new)
        n = md2.main_db.fetchone("SELECT COUNT(*) AS c FROM projects")["c"]
        assert n == 1

    def test_remove_cleans_db_and_signature(self, tmp_path):
        from topoone.engine.service import register_project_methods  # noqa: F841
        src = tmp_path / "rm"
        src.mkdir()
        (src / "a.py").write_text("X = 1\n", encoding="utf-8")
        md, srv, row = self._import(tmp_path, str(src))
        pid = row["id"]
        srv.methods["project.remove"](id=pid)
        assert md.main_db.fetchone("SELECT id FROM projects WHERE id=?", (pid,)) is None
        assert not os.path.exists(md.project_db_path(pid))
        assert MultiDBManager.read_proj_signature(str(src)) == ""

    def test_update_path_migrates_signature(self, tmp_path):
        from topoone.engine.service import register_project_methods  # noqa: F841
        src1 = tmp_path / "p1"
        src2 = tmp_path / "p2"
        src1.mkdir()
        src2.mkdir()
        (src1 / "a.py").write_text("X = 1\n", encoding="utf-8")
        (src2 / "a.py").write_text("X = 1\n", encoding="utf-8")
        md, srv, row = self._import(tmp_path, str(src1))
        pid = row["id"]
        out = srv.methods["project.updatePath"](id=pid, newRootPath=str(src2))
        assert out["project"]["root_path"] == str(src2)
        assert MultiDBManager.read_proj_signature(str(src2)) == pid
        assert MultiDBManager.read_proj_signature(str(src1)) == ""
        # 项目库仍为中心路径(不受根目录变更影响)
        assert os.path.isfile(md.project_db_path(pid))

    def test_storage_stats_uses_central_path(self, tmp_path):
        from topoone.engine.service import register_project_methods  # noqa: F841
        src = tmp_path / "st"
        src.mkdir()
        (src / "a.py").write_text("X = 1\n", encoding="utf-8")
        md, srv, row = self._import(tmp_path, str(src))
        stats = srv.methods["project.getStorageStats"](projectId=row["id"])
        assert stats["dbFileSize"] > 0
        assert os.path.isfile(os.path.join(str(tmp_path), "projects", row["id"], "project.db"))

    def test_exports_dir_central(self, tmp_path):
        from topoone.engine.export_service import exports_dir_for
        md = _mk(tmp_path)
        d = exports_dir_for(md, "proj-e1")
        assert d == os.path.join(str(tmp_path), "exports", "proj-e1")
