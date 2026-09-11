"""P1 会话中心: /sessions CRUD + 分组 + 备案文档 + exec 会话外链。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import topoone_app_architect.arch_routes.ctx as C  # noqa: E402
import topoone_app_architect.arch_routes.store as store  # noqa: E402


class TestSessionsCenter(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="topo-sessions-")
        C.setup(data_dir=self.dir)
        from topoone_app_architect.server import build_app
        self.client = TestClient(build_app())

    def _mk(self, kind="requirement", title="测试会话"):
        r = self.client.post("/api/architect/sessions", json={"kind": kind, "title": title})
        self.assertEqual(r.status_code, 200)
        return r.json()["data"]

    def test_session_crud_and_tags(self):
        conv = self._mk(kind="asset", title="支付模块资产讨论")
        self.assertEqual(conv["kind"], "asset")
        self.assertEqual(conv["tags"], {"modules": [], "groups": []})

        r = self.client.patch(f"/api/architect/sessions/{conv['id']}",
                              json={"tags": {"modules": ["pay"], "groups": ["迭代一"]},
                                    "title": "支付模块讨论(改)", "reviewState": "unread"})
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual(data["title"], "支付模块讨论(改)")
        self.assertEqual(data["tags"]["modules"], ["pay"])
        self.assertEqual(data["reviewState"], "unread")

        r = self.client.get("/api/architect/sessions", params={"q": "支付模块"})
        self.assertIn(conv["id"], [x["id"] for x in r.json()["data"]])

        r = self.client.put("/api/architect/sessions/groups", json={"groups": ["迭代一", "调研"]})
        self.assertEqual(r.status_code, 200)
        g = self.client.get("/api/architect/sessions/groups").json()["data"]
        self.assertIn("迭代一", g["groups"])
        self.assertIn("调研", g["groups"])
        self.assertIn("pay", g["modules"])

        r = self.client.delete(f"/api/architect/sessions/{conv['id']}")
        self.assertEqual(r.status_code, 200)
        r = self.client.get(f"/api/architect/sessions/{conv['id']}/messages")
        self.assertEqual(r.json()["code"], 404)

    def test_session_summarize_fallback(self):
        """LLM 不可达 → 标题兜底(首条用户消息截断)。"""
        conv = self._mk(kind="design", title="")
        store.ConversationsStore.append_message({
            "id": store.next_id("m"), "conversationId": conv["id"],
            "role": "user", "time": 1, "content": "帮我分析下单流程的改造方案",
        })
        r = self.client.post(f"/api/architect/sessions/{conv['id']}/summarize")
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertTrue(data["title"])
        self.assertIn("下单流程", data["title"])

    def test_session_docs(self):
        conv = self._mk(kind="requirement", title="需求讨论")
        r = self.client.post("/api/architect/session-docs",
                             json={"conversationId": conv["id"], "title": "需求快照",
                                   "contentMd": "# 需求快照\n正文"})
        self.assertEqual(r.status_code, 200)
        doc = r.json()["data"]
        self.assertEqual(doc["conversationId"], conv["id"])

        r = self.client.get("/api/architect/session-docs",
                            params={"conversation_id": conv["id"]})
        self.assertTrue(any(d["id"] == doc["id"] for d in r.json()["data"]))

        r = self.client.patch(f"/api/architect/session-docs/{doc['id']}",
                              json={"title": "需求快照2"})
        self.assertEqual(r.json()["data"]["title"], "需求快照2")
        r = self.client.delete(f"/api/architect/session-docs/{doc['id']}")
        self.assertEqual(r.status_code, 200)

