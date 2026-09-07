"""AgentGateway / 会话化执行器 — 单元测试。

覆盖：配置解析三级回退、执行器工厂、executor_id 节点选择贯通、
cline sidecar JSON-RPC 协议握手（伪 sidecar）、opencode 会话执行器（mock HTTP）。
"""

import asyncio
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "topoone"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                "topoOne-tAgent", "src"))

from topoone.plugins.runner import gateway as gw  # noqa: E402
from topoone.plugins.runner.executors.cline import ClineSdkExecutor  # noqa: E402
from topoone.plugins.runner.gateway import AgentGateway  # noqa: E402
from topocode_agent.orchestration import CodingTaskTree  # noqa: E402


def _node(**kw):
    from topocode_agent.orchestration.task_tree import CodingTaskNode
    d = {"id": "T1", "title": "t", "kind": "task", "files": ["a.py"]}
    d.update(kw)
    return d


class TestResolveEntries(unittest.TestCase):
    def test_builtin_default_when_nothing(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for k in ("OPENCODE_SERVE_URL", "CODEX_CMD", "CLAUDE_CMD",
                      "RUNNER_DEFAULT_EXECUTOR"):
                os.environ.pop(k, None)
            entries = gw.resolve_entries(None)
        ids = [e["id"] for e in entries]
        self.assertIn("opencode", ids)
        self.assertIn("cline", ids)
        self.assertIn("mock", ids)
        self.assertTrue(any(e.get("default") for e in entries))

    def test_env_overrides_builtin(self):
        env = {"OPENCODE_SERVE_URL": "http://127.0.0.1:9999",
               "CODEX_CMD": "codex exec {prompt}"}
        with mock.patch.dict(os.environ, env, clear=False):
            os.environ.pop("CLAUDE_CMD", None)
            entries = gw.resolve_entries(None)
        ids = [e["id"] for e in entries]
        self.assertIn("opencode", ids)
        self.assertIn("codex", ids)
        self.assertNotIn("cline", ids)  # env 模式回退旧语义

    def test_arch_entries_win_and_enabled_filter(self):
        arch = [{"id": "x", "type": "mock", "enabled": True, "default": True},
                {"id": "y", "type": "mock", "enabled": False}]
        entries = gw.resolve_entries(arch)
        self.assertEqual([e["id"] for e in entries], ["x"])


class TestBuildOne(unittest.TestCase):
    def test_opencode_session(self):
        ex = gw._build_one({"id": "oc", "type": "opencode",
                            "config": {"base_port": 3500}}, pb=None)
        self.assertEqual(ex.id, "oc")
        self.assertEqual(ex.mode, "serve")
        self.assertEqual(ex._mgr._base_port, 3500)

    def test_cline_sdk(self):
        ex = gw._build_one({"id": "cl", "type": "cline-sdk",
                            "config": {"provider_id": "anthropic"}}, pb=None)
        self.assertEqual(ex.id, "cl")
        self.assertEqual(ex.mode, "embedded")
        self.assertEqual(ex._provider_id, "anthropic")

    def test_unknown_type_none(self):
        self.assertIsNone(gw._build_one({"id": "?", "type": "nope"}, pb=None))

    def test_cli_requires_command(self):
        self.assertIsNone(gw._build_one({"id": "c", "type": "cli", "config": {}}, pb=None))


class TestExecutorIdRouting(unittest.TestCase):
    def test_node_executor_id_from_dict(self):
        tree = CodingTaskTree.from_dict({"roots": [_node(executor_id="cline")]})
        self.assertEqual(tree.roots[0].executor_id, "cline")

    def test_to_dict_roundtrip(self):
        tree = CodingTaskTree.from_dict({"roots": [_node(executor_id="cline")]})
        out = tree.to_dict()
        self.assertEqual(out["roots"][0]["executor_id"], "cline")

    def test_pool_selects_by_executor_id(self):
        from topocode_agent.subagent import ExecutorPool
        from topocode_agent.subagent.protocol import MockCodingExecutor
        m1, m2 = MockCodingExecutor(), MockCodingExecutor()
        m1.id, m2.id = "a", "b"
        pool = ExecutorPool(default_executor=m1, executors=[m2])
        node = CodingTaskTree.from_dict({"roots": [_node(executor_id="b")]}).roots[0]
        ctx = {}
        asyncio.run(pool.execute(node, ctx))
        self.assertEqual(m2.executed, ["T1"])
        self.assertEqual(m1.executed, [])


class TestGatewayPool(unittest.IsolatedAsyncioTestCase):
    async def test_build_pool_builtin(self):
        g = AgentGateway()
        with mock.patch.object(gw, "fetch_runtime_config", return_value=None):
            with mock.patch.dict(os.environ, {}, clear=False):
                for k in ("OPENCODE_SERVE_URL", "CODEX_CMD", "CLAUDE_CMD"):
                    os.environ.pop(k, None)
                pool, entries = await g.build_pool()
        self.assertIn("opencode", pool.available())
        self.assertIn("cline", pool.available())
        self.assertIn("mock", pool.available())


class TestClineSidecarProtocol(unittest.IsolatedAsyncioTestCase):
    """用伪 sidecar（纯 node 脚本，同协议）验证 stdio JSON-RPC 执行链。"""

    FAKE_SIDECAR = r"""
const readline = require('readline');
const rl = readline.createInterface({ input: process.stdin });
function send(o){ process.stdout.write(JSON.stringify(o) + '\n'); }
rl.on('line', (line) => {
  const m = JSON.parse(line);
  if (m.method === 'ping') send({ id: m.id, result: { ok: true } });
  else if (m.method === 'run') {
    send({ method: 'event', params: { type: 'status', taskId: m.params.taskId, stage: 'start' } });
    send({ id: m.id, result: { success: true, output: 'ok', changedFiles: ['x.py'],
                               error: '', iterations: 2, usage: null } });
  } else if (m.method === 'stop') send({ id: m.id, result: { ok: true } });
  else if (m.method === 'dispose') { send({ id: m.id, result: { ok: true } }); process.exit(0); }
  else send({ id: m.id, error: { message: 'unknown ' + m.method } });
});
"""

    def _write_fake(self, d: str) -> str:
        import tempfile
        p = os.path.join(d, "fake-sidecar.js")
        with open(p, "w") as f:
            f.write(self.FAKE_SIDECAR)
        return p

    async def test_execute_via_fake_sidecar(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            script = self._write_fake(d)
            ex = ClineSdkExecutor(id="cline-test", node_bin="node",
                                  sidecar_script=script, timeout=30)
            tree = CodingTaskTree.from_dict({"roots": [_node()]})
            result = await ex.execute(tree.roots[0], {"root": d})
        self.assertTrue(result.success)
        self.assertEqual(result.changed_files, ["x.py"])
        self.assertEqual(result.output, "ok")


class TestOpenCodeSessionMockHttp(unittest.IsolatedAsyncioTestCase):
    """opencode 会话执行器：httpx MockTransport 模拟 opencode serve API。"""

    def _executor(self, transport):
        from topoone.plugins.runner.executors import opencode as oc
        ex = oc.OpenCodeSessionExecutor(id="oc-test", timeout=10)
        ex._mgr = mock.MagicMock()
        sp = oc.ServeProc("/tmp", "http://fake", 3478)
        ex._mgr.ensure = mock.AsyncMock(return_value=sp)
        return ex

    async def test_execute_session_flow(self):
        import httpx
        from topoone.plugins.runner.executors import opencode as oc

        calls = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append((request.method, request.url.path))
            p = request.url.path
            if p == "/session":
                return httpx.Response(200, json={"id": "S1"})
            if p == "/session/S1/message":
                return httpx.Response(200, json={
                    "info": {"id": "M1"},
                    "parts": [{"type": "text", "text": "done output"}]})
            if p == "/session/S1/diff":
                return httpx.Response(200, json=[{"path": "src/a.py"}])
            if p == "/session/status":
                return httpx.Response(200, json={"S1": {"status": "idle"}})
            return httpx.Response(404)

        ex = self._executor(None)
        transport = httpx.MockTransportHandler = httpx.MockTransport(handler)
        # 打桩 AsyncClient 构造
        real_client = httpx.AsyncClient

        def patched_client(*a, **kw):
            kw["transport"] = transport
            return real_client(*a, **kw)

        with mock.patch.object(oc.httpx, "AsyncClient", side_effect=patched_client):
            tree = CodingTaskTree.from_dict({"roots": [_node()]})
            r = await ex.execute(tree.roots[0], {"root": "/tmp"})
        self.assertTrue(r.success)
        self.assertEqual(r.changed_files, ["src/a.py"])
        self.assertEqual(r.output, "done output")
        self.assertEqual(r.metadata.get("opencodeSessionId"), "S1")
        self.assertIn(("POST", "/session/S1/message"), calls)
        self.assertIn(("GET", "/session/S1/diff"), calls)


if __name__ == "__main__":
    unittest.main()


class TestRemoteAgentExecutor(unittest.IsolatedAsyncioTestCase):
    """远端执行器：mock 远端 opencode 会话 + 共享 bare 仓库真实 git 同步。"""

    def _setup_repo(self, d):
        import subprocess as sp
        os.makedirs(d, exist_ok=True)
        def g(*a, cwd):
            p = sp.run(["git"] + list(a), cwd=cwd, capture_output=True, text=True)
            assert p.returncode == 0, p.stderr
            return p.stdout.strip()
        g("init", "-q", "-b", "main", ".", cwd=d)
        g("config", "user.email", "t@t", cwd=d); g("config", "user.name", "t", cwd=d)
        open(os.path.join(d, "a.txt"), "w").write("1\n")
        g("add", "-A", cwd=d); g("commit", "-qm", "init", cwd=d)
        return g("rev-parse", "HEAD", cwd=d)

    async def test_remote_flow_with_shared_bare(self):
        import subprocess as sp
        import tempfile
        import httpx
        from topoone.plugins.runner.executors import remote as rmod

        with tempfile.TemporaryDirectory() as d:
            root = os.path.join(d, "work")
            base = self._setup_repo(root)
            shared = os.path.join(d, "shared.git")
            sp.run(["git", "init", "-q", "--bare", shared], check=True)

            # 假远端 worker：clone 共享仓 → 收到指令时写文件并 push
            worker = os.path.join(d, "worker")
            sp.run(["git", "clone", "-q", shared, worker], check=True)
            for a in (["config", "user.email", "t@t"], ["config", "user.name", "t"]):
                sp.run(["git"] + a, cwd=worker, check=True)

            def handler(request: httpx.Request) -> httpx.Response:
                p = request.url.path
                if p == "/session":
                    return httpx.Response(200, json={"id": "RS1"})
                if p == "/session/RS1/message":
                    # 模拟远端 agent 执行：按指令 push 到共享仓
                    sp.run(["git", "push", "--force", shared,
                            "HEAD:refs/heads/arch/R1"], cwd=worker,
                           capture_output=True)
                    return httpx.Response(200, json={
                        "info": {"id": "M1"},
                        "parts": [{"type": "text", "text": "remote done"}]})
                if p == "/session/RS1/diff":
                    return httpx.Response(200, json=[])
                if p == "/session/status":
                    return httpx.Response(200, json={"RS1": {"status": "idle"}})
                return httpx.Response(404)

            from topoone.plugins.runner.executors import opencode as oc
            transport = httpx.MockTransport(handler)
            real = httpx.AsyncClient

            def patched(*a, **kw):
                kw["transport"] = transport
                return real(*a, **kw)

            ex = rmod.RemoteAgentExecutor(
                id="remote-test", agent_url="http://fake-remote",
                git_remote=shared, timeout=60)
            tree = CodingTaskTree.from_dict({"roots": [_node(id="R1", files=["x.py"])]})
            ctx = {"root": root, "branch": "arch/R1", "baseCommit": base,
                   "project": "proj-x"}
            with mock.patch.object(oc.httpx, "AsyncClient", side_effect=patched):
                r = await ex.execute(tree.roots[0], ctx)
            self.assertTrue(r.success, r.error)
            self.assertEqual(r.metadata.get("remote"), True)
            self.assertEqual(r.metadata.get("branch"), "arch/R1")
            # 工程目录已同步到共享远端任务分支
            cur = sp.run(["git", "branch", "--show-current"], cwd=root,
                         capture_output=True, text=True).stdout.strip()
            self.assertEqual(cur, "arch/R1")
