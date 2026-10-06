"""组件/文件级图谱 + 节点 AI 解读特征测试(资产地图「组件图谱」域)。

契约：comp_graph 节点=自管组件目录、dependsOn 边由 imports(file→file)归并、
变更计数与 asset-compare 同口径；file_graph 多组件范围取 owns 并集、imports 边
两端在范围内才保留、文件变更态对齐对比结果；node_notes/file_line_notes 走
arch_symbol_notes 缓存(force 重生成, LLM 打桩)。
"""
import os
import subprocess
import unittest

from topoone_app_architect import ctx as app_ctx
from topoone_app_architect.arch_routes.project import resolve_project
from topoone_app_architect.sem import comp_graph as cg
from topoone_app_architect.sem.graph_collect import record_graph_baseline
from topoone_app_architect.store.component import ComponentStore
from topoone_app_architect.store.graph import GraphStore


def _git(root, *args):
    subprocess.run(["git", "-C", root, *args], check=True,
                   capture_output=True, text=True)


def _commit(root, msg):
    _git(root, "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-m", msg)


def _sha(root):
    return subprocess.run(["git", "-C", root, "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()


class CompGraphTest(unittest.TestCase):

    def setUp(self):
        self._tmp = __import__("tempfile").TemporaryDirectory()
        app_ctx.setup(data_dir=self._tmp.name)
        self.root = os.path.join(self._tmp.name, "repo")
        os.makedirs(self.root)
        _git(self.root, "init", "-q", "-b", "main")
        self.PID = resolve_project(self.root, None)["id"]   # 注册真实项目行
        os.makedirs(os.path.join(self.root, "a"))
        os.makedirs(os.path.join(self.root, "b"))
        for rel in ("a/f0.py", "a/f1.py", "b/f0.py"):
            with open(os.path.join(self.root, rel), "w") as f:
                f.write(f"# {rel}\nval = 1\n")
        _commit(self.root, "c1 base")
        self.base = _sha(self.root)
        with open(os.path.join(self.root, "b/f0.py"), "w") as f:
            f.write("# b/f0 changed\nval = 2\n")
        with open(os.path.join(self.root, "a/f2.py"), "w") as f:
            f.write("# a/f2 new\nval = 3\n")
        _commit(self.root, "c2 work")
        self.head = _sha(self.root)
        rev = f"baseline:{self.head}"
        comps = [
            {"id": "comp-a", "name": "Comp A", "summary": "A 组件", "owns": ["a/f0.py", "a/f1.py", "a/f2.py"]},
            {"id": "comp-b", "name": "Comp B", "summary": "B 组件", "owns": ["b/f0.py"]},
        ]
        ComponentStore.replace_rev(self.PID, rev, comps, [])
        nodes = [{
            "id": f"cache:a/f0.py::loader::1", "kind": "function", "name": "loader",
            "qualified_name": "loader", "file_path": "a/f0.py", "language": "python",
            "start_line": 1, "end_line": 2, "start_column": 0, "end_column": 0,
            "signature": "def loader()", "docstring": "", "return_type": "", "is_exported": True,
        }]
        edges = [{"source": "file:a/f0.py", "target": "file:b/f0.py",
                  "kind": "imports", "line": 1, "col": 0}]
        GraphStore.replace_rev(self.PID, rev, nodes, edges)
        record_graph_baseline(self.PID, self.head)

    def tearDown(self):
        self._tmp.cleanup()

    def test_comp_graph_shape_and_change(self):
        res = cg.comp_graph(self.root, self.PID, base=self.base)
        ids = {n["id"] for n in res["nodes"]}
        self.assertEqual(ids, {"comp-a", "comp-b"})
        # dependsOn 由 imports(file→file) 归并: a/f0 → b/f0 跨组件 → comp-a 依赖 comp-b
        a = next(n for n in res["nodes"] if n["id"] == "comp-a")
        self.assertEqual(a["dependsOn"], ["comp-b"])
        self.assertTrue(any(e["from"] == "comp-a" and e["to"] == "comp-b" for e in res["edges"]))
        # 变更计数与对比同口径: b/f0 修改 → comp-b modified=1; a/f2 新增 → comp-a added=1
        b = next(n for n in res["nodes"] if n["id"] == "comp-b")
        self.assertEqual(b["change"]["modified"], 1)
        self.assertEqual(a["change"]["added"], 1)
        self.assertIn("b/f0.py", a if False else (b["changedFiles"].get("modified") or []))

    def test_file_graph_scope_and_edges(self):
        # 单组件范围: 只有 a/* 文件, 无跨组件边
        single = cg.file_graph(self.root, self.PID, ["comp-a"], base=self.base)
        self.assertEqual({n["path"] for n in single["nodes"]},
                         {"a/f0.py", "a/f1.py", "a/f2.py"})
        self.assertEqual(single["edges"], [])
        self.assertEqual(single["nodes"][0]["compId"], "comp-a")
        # 多组件范围: b/f0 并入, imports 边两端都在范围内 → 保留
        both = cg.file_graph(self.root, self.PID, ["comp-a", "comp-b"], base=self.base)
        self.assertEqual(len(both["nodes"]), 4)
        self.assertEqual(both["edges"], [{"from": "a/f0.py", "to": "b/f0.py"}])
        # 文件变更态
        st = {n["path"]: n["change"] for n in both["nodes"]}
        self.assertEqual(st["b/f0.py"], "modified")
        self.assertEqual(st["a/f2.py"], "added")
        self.assertEqual(st["a/f0.py"], "")

    def test_node_notes_cache_and_force(self):
        import topoone_app_architect.agent.turns.catalog as catalog
        calls = []

        def fake_call(name, msgs, **kw):
            calls.append(msgs)
            return {"content": "组件 A：负责 f0/f1/f2 三个文件的解析与加载。"}

        orig = catalog.catalog_call
        catalog.catalog_call = fake_call
        try:
            r1 = cg.node_notes(self.root, self.PID, "component", "comp-a")
            self.assertFalse(r1["cached"])
            self.assertIn("Comp A", "\n".join(m["content"] for m in calls[0]) + r1["note"] + "comp-a")
            r2 = cg.node_notes(self.root, self.PID, "component", "comp-a")
            self.assertTrue(r2["cached"])
            self.assertEqual(len(calls), 1)          # 缓存命中不再调 LLM
            r3 = cg.node_notes(self.root, self.PID, "component", "comp-a", force=True)
            self.assertFalse(r3["cached"])
            self.assertEqual(len(calls), 2)
            # 文件级
            r4 = cg.node_notes(self.root, self.PID, "file", "a/f0.py")
            self.assertFalse(r4.get("cached"))
            self.assertTrue(r4["note"])
        finally:
            catalog.catalog_call = orig

    def test_file_line_notes_filter_and_cache(self):
        import json
        import topoone_app_architect.agent.turns.catalog as catalog

        def fake_call(name, msgs, **kw):
            return {"content": json.dumps({"1": "注释行", "2": "赋值语句", "xx": "脏数据", "99": "越界"})}

        orig = catalog.catalog_call
        catalog.catalog_call = fake_call
        try:
            r1 = cg.file_line_notes(self.root, self.PID, "a/f0.py", 1, 2)
            self.assertEqual(r1["notes"], {1: "注释行", 2: "赋值语句"})   # 脏键/越界行被滤
            r2 = cg.file_line_notes(self.root, self.PID, "a/f0.py", 1, 2)
            self.assertTrue(r2["cached"])
            r3 = cg.file_line_notes(self.root, self.PID, "a/f0.py", 1, 2, force=True)
            self.assertFalse(r3["cached"])
            # 内容变化 → 新窗口键 → 重新生成
            with open(os.path.join(self.root, "a/f0.py"), "w") as f:
                f.write("# changed\nval = 9\n")
            r4 = cg.file_line_notes(self.root, self.PID, "a/f0.py", 1, 2)
            self.assertFalse(r4["cached"])
        finally:
            catalog.catalog_call = orig


if __name__ == "__main__":
    unittest.main()


class CompGraphEndpointsTest(unittest.TestCase):
    """HTTP 端点层(TestClient): comp-graph / file-graph / node-notes / file-line-notes。"""

    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        app_ctx.setup(data_dir=self._tmp.name)
        from topoone_app_architect.arch_routes.project import resolve_project
        from topoone_app_architect.store.core import ProjectsStore
        self.root = os.path.join(self._tmp.name, "repo")
        os.makedirs(self.root)
        _git(self.root, "init", "-q", "-b", "main")
        os.makedirs(os.path.join(self.root, "a"))
        with open(os.path.join(self.root, "a/f0.py"), "w") as f:
            f.write("x = 1\n")
        _commit(self.root, "c1")
        self.PID = resolve_project(self.root, None)["id"]
        self.head = _sha(self.root)
        ProjectsStore.update(self.PID, {"baselineCommit": self.head})
        ComponentStore.replace_rev(self.PID, f"baseline:{self.head}",
                                   [{"id": "comp-a", "name": "A", "owns": ["a/f0.py"]}], [])
        record_graph_baseline(self.PID, self.head)
        from fastapi.testclient import TestClient
        from topoone_app_architect.server import build_app
        self.client = TestClient(build_app(data_dir=self._tmp.name))

    def tearDown(self):
        self._tmp.cleanup()

    def test_comp_graph_endpoint(self):
        r = self.client.get(f"/api/architect/kb/semantic/comp-graph?project={self.PID}&base={self.head}")
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual([n["id"] for n in data["nodes"]], ["comp-a"])

    def test_file_graph_endpoint(self):
        r = self.client.get(
            f"/api/architect/kb/semantic/file-graph?project={self.PID}&components=comp-a&base={self.head}")
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertEqual([n["path"] for n in data["nodes"]], ["a/f0.py"])
        self.assertFalse(data["truncated"])

    def test_file_graph_truncation(self):
        """>200 文件范围截断: 渲染前 200 + truncated 标志(大范围分批查看裁决)。"""
        comps = [{"id": f"comp-{i}", "name": f"C{i}", "owns": [f"d{i}/f.py"]} for i in range(210)]
        rev = f"baseline:{self.head}"
        ComponentStore.replace_rev(self.PID, rev, comps, [])
        r = self.client.get(
            f"/api/architect/kb/semantic/file-graph?project={self.PID}&components={','.join(c['id'] for c in comps)}&base={self.head}")
        self.assertEqual(r.status_code, 200)
        data = r.json()["data"]
        self.assertTrue(data["truncated"])
        self.assertEqual(len(data["nodes"]), 200)
        self.assertEqual(data["totalFiles"], 210)

    def test_node_notes_endpoint_validation(self):
        r = self.client.get(f"/api/architect/kb/semantic/node-notes?project={self.PID}&kind=component&key=")
        self.assertEqual(r.status_code, 400)   # 缺 key → 400(错误契约)
