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
        self.proj_id = "proj-digest-t"

    def _seed(self):
        from topoone_app_architect.common import _ts
        # 新契约: 简报素材按项目域采集 → 种子数据挂项目, 调用方传 projectId
        store.ProjectsStore.upsert(self.proj_id, {
            "name": "T", "rootPath": "/tmp/digest-t", "mode": "existing",
            "createdAt": _ts(), "active": True,
            "config": {"estMinMin": 15, "estMinMax": 240},
        })
        conv = store.ConversationsStore.create({
            "projectId": self.proj_id, "kind": "requirement",
            "title": "支付重构讨论"})
        store.ConversationsStore.update(conv["id"], {"summary": "完成支付网关重构方案定型"})

        store.DocsStore.create({
            "projectId": self.proj_id,
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
        r = self.client.post("/api/architect/digest", json={"sinceDays": 7, "projectId": self.proj_id})
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
        # 本测目的=列表项目过滤; LLM 不可达桩与 fallback 测试同型
        # (ModelNotConfigured 按用户裁决显式 400, 不降级出垃圾)
        from unittest.mock import patch as _mock_patch
        import topoone_app_architect.agent.tools.req_agent as _RA
        _ra_patch = _mock_patch.object(_RA, "llm_sync", lambda *a, **k: None)
        _ra_patch.start()
        self.addCleanup(_ra_patch.stop)
        self.client.post("/api/architect/digest", json={"sinceDays": 7, "projectId": self.proj_id})
        r = self.client.get(f"/api/architect/digest?project={self.proj_id}")
        self.assertEqual(r.status_code, 200)
        docs = r.json()["data"]
        self.assertTrue(any(d["type"] if "type" in d else True for d in docs))
        self.assertTrue(len(docs) >= 1)

    def test_digest_empty_window(self):
        r = self.client.post("/api/architect/digest", json={"sinceDays": 1, "projectId": self.proj_id})
        self.assertNotEqual(r.json().get("code"), 0)

