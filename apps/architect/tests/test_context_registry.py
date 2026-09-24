"""P2 上下文注册表: 单元写入钩子 + ctx.* 检索 + 执行回执 + 会话摘要单元。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import topoone_app_architect.ctx as C  # noqa: E402
import topoone_app_architect.store as store  # noqa: E402


class TestContextRegistry(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="topo-ctxreg-")
        C.setup(data_dir=self.dir)

    def _conv(self, kind="requirement", title="支付模块讨论"):
        return store.ConversationsStore.create({"kind": kind, "title": title})

    def test_tool_call_and_artifact_units(self):
        from topoone_app_architect.agent.memory import units as cr
        conv = self._conv()
        cr.record_tool_call(conv["id"], "kb.asset.search", {"query": "支付"}, True,
                            "命中 3 条资产")
        units = store.ContextUnitsStore.all(conversation_id=conv["id"])
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["type"], "tool_call")

        # 产物类工具 → tool_call + artifact 双单元
        cr.record_tool_call(conv["id"], "req.propose", {"title": "x"}, True,
                            "已创建需求 RQ-1")
        units = store.ContextUnitsStore.all(conversation_id=conv["id"])
        self.assertEqual(len(units), 3)
        self.assertEqual(sum(1 for u in units if u["type"] == "artifact"), 1)

    def test_summarize_creates_session_summary_unit(self):
        """LLM 不可达 → 标题兜底 + session_summary 单元。

        固化说明: 本机可能运行真实 KB 栈(:3459 可达时 summarize_task 会拿到
        真 LLM 标题, 如「订单流程…」)——本测试验证的是降级路径, 显式断开 LLM。
        """
        from unittest.mock import patch
        from topoone_app_architect.agent.memory import units as cr
        import topoone_app_architect.arch_routes.req_agent as _ra
        conv = self._conv(kind="design", title="")
        store.ConversationsStore.append_message({
            "id": store.next_id("m"), "conversationId": conv["id"],
            "role": "user", "time": 1, "content": "讨论下单流程重构方案",
        })
        with patch.object(_ra, "llm_sync", lambda *a, **k: None):
            updated = cr.summarize_conversation(conv["id"])
        self.assertIn("下单流程", updated["title"])
        units = store.ContextUnitsStore.all(conversation_id=conv["id"],
                                            type_="session_summary")
        self.assertEqual(len(units), 1)
        self.assertEqual(units[0]["importance"], 1)

    def test_ctx_search_across_units_messages_docs(self):
        from topoone_app_architect.agent.memory import units as cr
        conv = self._conv(title="支付模块资产讨论")
        cr.record_tool_call(conv["id"], "kb.asset.search", {"query": "支付"}, True,
                            "支付网关资产命中")
        store.ConversationsStore.append_message({
            "id": store.next_id("m"), "conversationId": conv["id"],
            "role": "assistant", "time": 2, "content": "支付链路的依赖是 pay-gateway",
        })
        store.DocsStore.create({
            "conversationId": conv["id"], "title": "支付需求快照",
            "contentMd": "# 支付需求快照\n涉及支付网关改造",
        })
        md = cr.ctx_search("支付")
        # 单元 + 消息 + 文档三源命中
        self.assertIn("支付网关资产命中", md)
        self.assertIn("pay-gateway", md)
        self.assertIn("支付需求快照", md)

    def test_mcp_run_tool_dispatch(self):
        from topoone_app_architect.arch_routes import asset_map_tools
        from topoone_app_architect.agent.memory import units as cr
        conv = self._conv(title="登录会话")
        cr.record_tool_call(conv["id"], "kb.asset.search", {}, True, "登录鉴权资产")
        md = asset_map_tools.run_tool("ctx.search", {"query": "登录"})
        self.assertIn("登录鉴权资产", md)
        unknown = asset_map_tools.run_tool("ctx.nope", {})
        self.assertIn("未知工具", unknown)

    def test_chat_tools_registered(self):
        from topoone_app_architect.agent.memory import units as context_registry
        from topoone_app_architect.arch_routes import req_agent
        context_registry.register_chat_tools()
        names = [t["name"] for t in req_agent.architect_tools()]
        self.assertIn("ctx.search", names)
        self.assertIn("ctx.get", names)
        # 工具可执行(markdown 输出)
        r = req_agent.run_arch_tool("ctx.search", {"query": "任意"}, None, None)
        self.assertIn("markdown", r)


if __name__ == "__main__":
    unittest.main()
