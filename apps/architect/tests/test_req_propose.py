"""S5 req.propose 工具 — 资产地图对话形成需求提案。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone_app_architect.arch_routes import ctx  # noqa: E402


class TestReqPropose(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.dir = tempfile.mkdtemp(prefix="topo-propose-")
        ctx.setup(data_dir=self.dir)

    def test_propose_creates_requirement_with_source(self):
        from topoone_app_architect.arch_routes import req_agent, store
        # 模拟资产对话上下文（会话 id）
        token = ctx.set_conv("conv-test-1")
        try:
            r = req_agent.tool_req_propose(
                title="优化 QUIC 握手路径", requirementMd="背景：握手延迟高",
                designMd="改造 nginx-http-core 的握手分支", assessmentMd="收益高/风险中",
                priority="P1", estMin=120)
        finally:
            ctx.reset_conv(token)
        self.assertTrue(r.get("ok"), r)
        req = store.RequirementsStore.get(r["requirementId"])
        self.assertEqual(req["sourceType"], "asset-chat")
        self.assertEqual(req["sourceConversationId"], "conv-test-1")
        self.assertEqual(req["status"], "draft")                      # 生命周期重构: draft|ready|done
        self.assertEqual(req["activeVer"], 1)
        vs = req["specVersions"]
        self.assertTrue(vs and vs[0]["state"] == "draft" and vs[0]["snapshot"]["estMin"] == 120)
        self.assertIn("## 需求", req["desc"])
        self.assertIn("## 方案", req["desc"])
        self.assertIn("## 评估", req["desc"])
        self.assertEqual(req["analysis"]["estMin"], 120)               # active 版本派生缓存


if __name__ == "__main__":
    unittest.main()
