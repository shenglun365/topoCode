"""P4 开发简报: 素材采集 → 降级生成 → refs 深链 → 落地锚点。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import topoone_app_architect.arch_routes.ctx as C  # noqa: E402
import topoone_app_architect.arch_routes.store as store  # noqa: E402


class TestDevDigest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="topo-digest-")
        C.setup(data_dir=self.dir)
        from topoone_app_architect.server import build_app
        self.client = TestClient(build_app())

    def _seed(self):
        now = store._ts() if hasattr(store, "_ts") else 0
        from topoone_app_architect.arch_routes.common import _ts
        now = _ts()
        conv = store.ConversationsStore.create({"kind": "requirement", "title": "支付重构讨论"})
        store.ConversationsStore.update(conv["id"], {"summary": "完成支付网关重构方案定型"})
        ex = store.ExecutionTasksStore.create({
            "id": store.next_id("ex"), "plan_id": "plan-1", "adapter": "opencode",
            "req_ids": [], "connectivity": "ok", "status": "done",
            "session_ids": [], "taskBranch": "arch/ex-x", "conversationId": conv["id"],
        })
        store.ExecutionTasksStore.update(ex["id"], {
            "branchCommit": "abc123def456", "branchLandedAt": now})
        store.DocsStore.create({
            "conversationId": conv["id"], "type": "requirement_summary",
            "title": "支付需求快照", "contentMd": "# 支付\n网关改造"})
        return conv, ex

    def test_generate_digest_fallback_and_refs(self):
        """LLM 不可达 → 素材直排；refs.entries 带深链数据。"""
        conv, ex = self._seed()
        r = self.client.post("/api/architect/digest", json={"sinceDays": 7})
        self.assertEqual(r.status_code, 200)
        doc = r.json()["data"]
        self.assertEqual(doc["type"], "dev_digest")
        self.assertIn("开发简报", doc["title"])
        # 素材直排可见
        self.assertIn("arch/ex-x", doc["contentMd"])
        self.assertIn("支付重构讨论", doc["contentMd"])
        self.assertIn("支付需求快照", doc["contentMd"])
        entries = (doc.get("refs") or {}).get("entries") or []
        types = {e["type"] for e in entries}
        self.assertIn("exec", types)
        self.assertIn("session", types)
        self.assertIn("doc", types)
        exec_entry = next(e for e in entries if e["type"] == "exec")
        self.assertEqual(exec_entry["execId"], ex["id"])
        self.assertEqual(exec_entry["commit"], "abc123def456")
        self.assertEqual(exec_entry["conversationId"], conv["id"])

    def test_list_digests(self):
        self._seed()
        self.client.post("/api/architect/digest", json={"sinceDays": 7})
        r = self.client.get("/api/architect/digest")
        self.assertEqual(r.status_code, 200)
        docs = r.json()["data"]
        self.assertTrue(any(d["type"] if "type" in d else True for d in docs))
        self.assertTrue(len(docs) >= 1)

    def test_digest_empty_window(self):
        r = self.client.post("/api/architect/digest", json={"sinceDays": 1})
        self.assertNotEqual(r.json().get("code"), 0)

    def test_record_land_snapshot(self):
        from topoone_app_architect.arch_routes import dev_digest
        dev_digest.record_land_snapshot(
            {"id": "ex-9", "title": "登录落地", "taskBranch": "arch/ex-9"}, "deadbeef")
        db = store._target_db("arch_snapshot_records")
        rows = db.fetchall("SELECT * FROM arch_snapshot_records WHERE task_id = 'ex-9'")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["git_commit"], "deadbeef")
        self.assertEqual(rows[0]["git_branch"], "arch/ex-9")


if __name__ == "__main__":
    unittest.main()
