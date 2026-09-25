"""P4 开发简报: 素材采集 → 降级生成 → refs 深链 → 落地锚点。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

import topoone_app_architect.ctx as C  # noqa: E402
import topoone_app_architect.store as store  # noqa: E402


class TestDevDigest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="topo-digest-")
        C.setup(data_dir=self.dir)
        # build_app 内部 ctx.setup() 无参 → 回退 ARCH_DATA_DIR/默认 ~/.topocode；
        # 必须钉住环境变量，否则测试读写真实项目库(污染 + 串数据)
        os.environ["ARCH_DATA_DIR"] = self.dir
        from topoone_app_architect.server import build_app
        self.client = TestClient(build_app())

    def _seed(self):
        now = store._ts() if hasattr(store, "_ts") else 0
        from topoone_app_architect.common import _ts
        now = _ts()
        conv = store.ConversationsStore.create({"kind": "requirement", "title": "支付重构讨论"})
        store.ConversationsStore.update(conv["id"], {"summary": "完成支付网关重构方案定型"})

        store.DocsStore.create({
            "conversationId": conv["id"], "type": "requirement_summary",
            "title": "支付需求快照", "contentMd": "# 支付\n网关改造"})
        return conv

    def test_generate_digest_fallback_and_refs(self):
        """LLM 不可达 → 素材直排；refs.entries 带深链数据。"""
        conv = self._seed()
        # LLM 通道修复后本机模型可达 → 显式打桩模拟不可达，锁定降级直排断言
        from unittest.mock import patch as _mock_patch
        import topoone_app_architect.agent.tools.req_agent as _RA
        # 真实 llm_sync 在 LLM 不可达时内部吞错返回 None → 模拟同行为(非抛错)
        _ra_patch = _mock_patch.object(_RA, "llm_sync", lambda *a, **k: None)
        _ra_patch.start()
        self.addCleanup(_ra_patch.stop)
        r = self.client.post("/api/architect/digest", json={"sinceDays": 7})
        self.assertEqual(r.status_code, 200)
        doc = r.json()["data"]
        self.assertEqual(doc["type"], "dev_digest")
        self.assertIn("开发简报", doc["title"])
        # 素材直排可见
        self.assertIn("支付重构讨论", doc["contentMd"])
        self.assertIn("支付需求快照", doc["contentMd"])
        entries = (doc.get("refs") or {}).get("entries") or []
        types = {e["type"] for e in entries}
        self.assertIn("session", types)
        self.assertIn("doc", types)

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

