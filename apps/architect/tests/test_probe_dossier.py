"""P3: probe(方案草图) + 前置上下文构造(dossier)。"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import topoone_app_architect.ctx as C  # noqa: E402
import topoone_app_architect.store as store  # noqa: E402


class _MockRunnerHandler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if body.get("instruction", "").find("失败") >= 0:
            payload = {"ok": False, "status": "failed", "changedFiles": [], "diff": "", "summary": "x"}
        else:
            payload = {"ok": True, "status": "done", "changedFiles": ["a.py", "b.py"],
                       "diff": "+print('hello')", "summary": "probe 完成; 2 个文件变更(+1/-0 行)"}
        self.wfile.write(json.dumps(payload).encode())

    def log_message(self, *args):  # 静默
        pass


class TestProbeAndDossier(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="topo-p3-")
        C.setup(data_dir=self.dir)
        # mock runner
        self.srv = HTTPServer(("127.0.0.1", 0), _MockRunnerHandler)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        os.environ["RUNNER_BASE_URL"] = f"http://127.0.0.1:{self.port}"

    def tearDown(self):
        self.srv.shutdown()

    def _conv(self, title="方案讨论"):
        return store.ConversationsStore.create({"kind": "design", "title": title})

    def test_run_probe_records_artifact_unit(self):
        from topoone_app_architect.agent.memory import units as cr
        conv = self._conv()
        result = cr.run_probe(conv["id"], "为支付模块生成重构方案草稿", "/tmp")
        self.assertTrue(result.get("ok"), result)
        units = store.ContextUnitsStore.all(conversation_id=conv["id"], type_="artifact")
        self.assertEqual(len(units), 1)
        self.assertIn("a.py", units[0]["content"])
        self.assertEqual(units[0]["refs"]["files"], ["a.py", "b.py"])

    def test_run_probe_failure_no_unit(self):
        from topoone_app_architect.agent.memory import units as cr
        conv = self._conv()
        result = cr.run_probe(conv["id"], "失败场景", "/tmp")
        self.assertFalse(result.get("ok"))
        units = store.ContextUnitsStore.all(conversation_id=conv["id"])
        self.assertEqual(len(units), 0)

    def test_run_probe_runner_down(self):
        from topoone_app_architect.agent.memory import units as cr
        os.environ["RUNNER_BASE_URL"] = "http://127.0.0.1:1"
        conv = self._conv()
        result = cr.run_probe(conv["id"], "x", "/tmp", timeout_s=5)
        self.assertIn("error", result)

    def test_assemble_dossier_sections_and_budget(self):
        from topoone_app_architect.agent.memory import units as cr
        from topoone_app_architect.agent.memory import dossier as dossier_mod
        conv = self._conv(title="登录重构")
        store.ConversationsStore.update(conv["id"], {
            "summary": "决定用 JWT 替换 session",
            "tags": {"modules": ["auth"], "groups": []}})
        store.DocsStore.create({
            "conversationId": conv["id"], "title": "需求快照",
            "contentMd": "# 需求\n登录改为 JWT\n\n## 方案\n改造 auth 模块"})
        cr.record_tool_call(conv["id"], "req.propose", {}, True, "已创建需求 RQ-9")
        reqs = [{"id": "RQ-9", "title": "JWT 登录", "desc": "## 需求\nJWT 改造"}]
        dossier = dossier_mod.assemble_dossier(conv["id"], reqs=reqs)
        self.assertIsNotNone(dossier)
        self.assertIn("决定用 JWT", dossier)
        self.assertIn("需求快照", dossier)
        self.assertIn("JWT 登录", dossier)
        self.assertIn("artifact", dossier)
        self.assertLessEqual(len(dossier), dossier_mod._DOSSIER_BUDGET + 200)
        # execution_brief 单元留痕
        units = store.ContextUnitsStore.all(conversation_id=conv["id"], type_="execution_brief")
        self.assertEqual(len(units), 1)

    def test_assemble_dossier_missing_conv(self):
        from topoone_app_architect.agent.memory import dossier as cr
        self.assertIsNone(cr.assemble_dossier("cv-none"))


if __name__ == "__main__":
    unittest.main()
