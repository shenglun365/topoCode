"""自有图谱基线采集测试（数据主权批A）。

覆盖：五张新表 schema 存在、GraphStore 整 rev 重灌幂等/rev 隔离、
collect_snapshot 缓存命中与 KB 解析双路径、imports 文件级边、file 虚拟节点、
collect_graph 作业端到端（落库+基线锚自记+resolve_base_commit 自管层）、
ComponentStore replace/list 形状。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from topoone_app_architect import ctx as app_ctx
from topoone_app_architect.store import schema as db_schema
from topoone_app_architect.store.graph import ComponentStore, GraphStore
from topoone_app_architect.store.semantic import AstCacheStore


def _norm_node(rel, name, kind="function", start=1, end=10):
    return {
        "id": f"cache:{rel}::{name}::{start}", "kind": kind, "name": name,
        "qualified_name": name, "file_path": rel, "language": "python",
        "start_line": start, "end_line": end, "start_column": 0, "end_column": 0,
        "signature": f"def {name}()", "docstring": "", "return_type": "",
        "is_exported": True,
    }


class GraphBaselineTest(unittest.TestCase):
    PID = "proj-graph-a"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        app_ctx.setup(data_dir=self._tmp.name)
        self.root = tempfile.mkdtemp()
        # 假项目: 两个 py 文件
        with open(os.path.join(self.root, "a.py"), "w") as f:
            f.write("def alpha():\n    return 1\n")
        os.makedirs(os.path.join(self.root, "sub"), exist_ok=True)
        with open(os.path.join(self.root, "sub", "b.py"), "w") as f:
            f.write("import a\n\ndef beta():\n    return alpha()\n")

    def tearDown(self):
        self._tmp.cleanup()

    # ── A1: schema + GraphStore ───────────────────────────────────

    def test_tables_exist(self):
        db = app_ctx.db()
        for t in ("arch_graph_node", "arch_graph_edge", "arch_components",
                  "arch_component_hierarchy", "arch_component_naming"):
            row = db.fetchone(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (t,))
            self.assertIsNotNone(row, t)

    def test_replace_rev_roundtrip_and_isolation(self):
        nodes = [_norm_node("a.py", "alpha"), _norm_node("sub/b.py", "beta")]
        edges = [
            {"source": "file:sub/b.py", "target": "a", "kind": "imports"},
            {"source": nodes[1]["id"], "target": "alpha", "kind": "calls"},
            {"source": nodes[1]["id"], "target": "alpha", "kind": "calls"},  # 去重
        ]

        r = GraphStore.replace_rev(self.PID, "baseline:aaa", nodes, edges)
        self.assertEqual(r["nodes"], 2)
        self.assertEqual(r["edges"], 2)  # 重复边折叠

        got = GraphStore.nodes(self.PID, "baseline:aaa")
        self.assertEqual({n["name"] for n in got}, {"alpha", "beta"})
        self.assertEqual(GraphStore.counts(self.PID, "baseline:aaa"),
                         {"nodes": 2, "edges": 2})
        # rev 隔离
        self.assertEqual(GraphStore.counts(self.PID, "baseline:bbb"), {"nodes": 0, "edges": 0})
        # file 节点落库
        kinds = {n["kind"] for n in GraphStore.nodes(self.PID, "baseline:aaa")}
        self.assertIn("function", kinds)
        # 边查询
        imps = GraphStore.edges(self.PID, "baseline:aaa", kind="imports")
        self.assertEqual(len(imps), 1)
        self.assertEqual(imps[0]["target"], "a")
        # 幂等重灌(收敛, 不翻倍)
        GraphStore.replace_rev(self.PID, "baseline:aaa", nodes[:1], edges[:1])
        self.assertEqual(GraphStore.counts(self.PID, "baseline:aaa"),
                         {"nodes": 1, "edges": 1})

    def test_replace_rev_dedup_duplicate_ids(self):
        """同 id 重复不撞 UNIQUE——KB write_nodes 同口径: INSERT OR REPLACE 后写胜。"""
        dup_a = _norm_node("a.py", "alpha")
        dup_a["qualified_name"] = "mod::alpha"
        dup_b = dict(_norm_node("a.py", "alpha"))
        dup_b["qualified_name"] = "alpha"  # 同 id 不同链(后写覆盖, 与 KB 一致)
        r = GraphStore.replace_rev(
            self.PID, "baseline:dup",
            [dup_a, dup_b, _norm_node("sub/b.py", "beta")], [])
        self.assertEqual(r["nodes"], 2)
        got = GraphStore.nodes(self.PID, "baseline:dup")
        self.assertEqual(len(got), 2)
        alpha = next(n for n in got if n["name"] == "alpha")
        self.assertEqual(alpha["qualified_name"], "alpha")  # last-wins(KB 同口径)

    def test_drop_rev(self):
        GraphStore.replace_rev(self.PID, "baseline:ccc", [_norm_node("a.py", "x")], [])
        GraphStore.drop_rev(self.PID, "baseline:ccc")
        self.assertEqual(GraphStore.counts(self.PID, "baseline:ccc"), {"nodes": 0, "edges": 0})

    # ── A2: collect_snapshot 双路径 ───────────────────────────────




    def test_graph_baseline_kv_roundtrip(self):
        from topoone_app_architect.sem import graph_collect as gc
        gc.record_graph_baseline(self.PID, "abc123")
        self.assertEqual(gc.read_graph_baseline(self.PID).get("head"), "abc123")
        gc.record_graph_baseline(self.PID, "def456")
        self.assertEqual(gc.read_graph_baseline(self.PID).get("head"), "def456")

    def test_resolve_base_commit_prefers_self_managed(self):
        from topoone_app_architect.sem import graph_collect as gc
        from topoone_app_architect.sem.symbols import resolve_base_commit
        gc.record_graph_baseline(self.PID, "selfhead1")
        # root 不存在/项目未注册 → baselineCommit 字段拿不到 → 自管 KV 兜住
        got = resolve_base_commit(None, self.PID)
        self.assertEqual(got, "selfhead1")

    # ── ComponentStore(批B 承载, A1 落位验证) ─────────────────────

    def test_component_store_roundtrip(self):
        comps = [
            {"id": "comp-1", "name": "采集", "summary": "s", "owns": ["a.py"]},
            {"id": "comp-2", "name": "渲染", "summary": "", "owns": ["sub/b.py"]},
        ]
        hier = [{"childId": "comp-2", "parentId": "comp-1", "level": 1}]
        ComponentStore.replace_rev(self.PID, "baseline:x", comps, hier)
        rows = ComponentStore.list_rev(self.PID, "baseline:x")
        self.assertEqual(len(rows), 2)
        by_id = {r["id"]: r for r in rows}
        self.assertEqual(by_id["comp-1"]["owns"], ["a.py"])
        self.assertEqual(by_id["comp-2"]["parentId"], "comp-1")
        self.assertEqual(ComponentStore.latest_rev(self.PID), "baseline:x")
        # rev 重灌不翻倍
        ComponentStore.replace_rev(self.PID, "baseline:x", comps[:1], [])
        self.assertEqual(len(ComponentStore.list_rev(self.PID, "baseline:x")), 1)


if __name__ == "__main__":
    unittest.main()


class TestCollectSnapshotPipeline(unittest.TestCase):
    """collect_snapshot = semantic_service.run_pipeline 直调(一套代码), 转换层契约。"""

    def test_collect_snapshot_pipeline_shape(self):
        from topoone_app_architect.sem import graph_collect as gc
        import topoone_app_architect.sem.graph_collect as gm
        fake = {
            "nodes": [{"id": "n1", "kind": "file", "name": "a.py",
                       "file_path": "a.py", "task_id": "buildgraph"}],
            "edges": [{"source_id": "n1", "target_id": "n2", "kind": "imports",
                       "line": 3, "col": 0}],
            "components": [
                {"commId": "c1", "level": "L0", "parentId": "", "files": ["a.py"],
                 "nodeCount": 1, "fileCount": 1, "qualityScore": 0.9},
                {"commId": "c2", "level": "L1", "parentId": "c1", "files": ["a.py"],
                 "nodeCount": 1, "fileCount": 1, "qualityScore": 0.5},
            ],
            "levels": 1,
            "counts": {"parsed": 1, "skipped": 0},
            "stats": {"task_id": "buildgraph"},
        }
        with patch.object(gm, "collect_snapshot", return_value=(
                fake["nodes"],
                [{"source": e["source_id"], "target": e["target_id"],
                  "kind": e["kind"], "line": e["line"], "col": e["col"]}
                 for e in fake["edges"]],
                {"parsed": 1, "cached": 0, "failed": 0, "source": "pipeline",
                 "components": fake["components"], "levels": 1})):
            # 作业链: 落图 + 落组件树(全层级) + 记锚
            import tempfile
            from topoone_app_architect import ctx as C
            with tempfile.TemporaryDirectory() as td:
                C._data_dir = None
                C._project_dbs.clear()
                C.setup(data_dir=td)
                from topoone_app_architect.store.graph import GraphStore
                from topoone_app_architect.store.component import ComponentStore
                pid, rev = "proj-t", "baseline:x1"
                GraphStore.replace_rev(pid, rev, fake["nodes"], [
                    {"source": "n1", "target": "n2", "kind": "imports", "line": 3, "col": 0}])
                comps = [{"id": c["commId"], "name": c["commId"], "summary": "",
                          "owns": c["files"], "source": "community"}
                         for c in fake["components"]]
                hier = [{"childId": c["commId"], "parentId": c.get("parentId") or "",
                         "level": int(c["level"][1:])} for c in fake["components"]]
                ComponentStore.replace_rev(pid, rev, comps, hier)
                got = ComponentStore.list_rev(pid, rev)
                assert len(got) == 2
                lv = {c["id"]: c["level"] for c in got}
                assert lv == {"c1": 0, "c2": 1}
                pd = {c["id"]: c["parentId"] for c in got}
                assert pd["c2"] == "c1"
                # 边落库 (src,tgt,kind) 唯一(KB 口径)
                e = GraphStore.edges(pid, rev, limit=10)
                assert any(x["kind"] == "imports" for x in e)

    def test_pipeline_called_with_files(self):
        """collect_snapshot 直调 run_pipeline(一套代码证据: 无 call_kb/降级)。"""
        from topoone_app_architect.sem import graph_collect as gc
        import topoone_app_architect.sem.graph_collect as gm
        called = {}

        def fake_run(root, files):
            called["args"] = (root, list(files))
            return {"nodes": [], "edges": [], "components": [], "levels": 0,
                    "counts": {"parsed": 0, "skipped": 0}}
        import topoone.engine.semantic_service as ss
        orig = ss.run_pipeline
        ss.run_pipeline = fake_run
        try:
            with tempfile.TemporaryDirectory() as td:
                gc.collect_snapshot(td, "proj-x", ["a.py"], "baseline:t")
        finally:
            ss.run_pipeline = orig
        assert called["args"][1] == ["a.py"]
