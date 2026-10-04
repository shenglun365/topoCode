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
        """walker 双路径提取的重复 id 不撞 UNIQUE(keep-first: 首条=完整作用域链)。"""
        dup_a = _norm_node("a.py", "alpha")
        dup_a["qualified_name"] = "mod::alpha"
        dup_b = dict(_norm_node("a.py", "alpha"))
        dup_b["qualified_name"] = "alpha"  # 同 id 不同链(通用遍历弱链)
        r = GraphStore.replace_rev(
            self.PID, "baseline:dup",
            [dup_a, dup_b, _norm_node("sub/b.py", "beta")], [])
        self.assertEqual(r["nodes"], 2)
        got = GraphStore.nodes(self.PID, "baseline:dup")
        self.assertEqual(len(got), 2)
        alpha = next(n for n in got if n["name"] == "alpha")
        self.assertEqual(alpha["qualified_name"], "mod::alpha")  # keep-first

    def test_drop_rev(self):
        GraphStore.replace_rev(self.PID, "baseline:ccc", [_norm_node("a.py", "x")], [])
        GraphStore.drop_rev(self.PID, "baseline:ccc")
        self.assertEqual(GraphStore.counts(self.PID, "baseline:ccc"), {"nodes": 0, "edges": 0})

    # ── A2: collect_snapshot 双路径 ───────────────────────────────

    def test_collect_snapshot_cross_file_refs(self):
        """D2: b.py import a 并调用 alpha → 调用边 target 解析为 a 的符号 id。"""
        from unittest.mock import patch
        from topoone_app_architect.sem import graph_collect as gc

        def fake_parse(root, rel):
            if rel == "a.py":
                return {"language": "python",
                        "symbols": [{"name": "alpha", "kind": "function",
                                     "startLine": 1, "endLine": 2,
                                     "qualifiedName": "alpha", "signature": "def alpha()"}],
                        "imports": [], "refs": []}
            return {"language": "python",
                    "symbols": [{"name": "beta", "kind": "function",
                                 "startLine": 3, "endLine": 4,
                                 "qualifiedName": "beta", "signature": "def beta()"}],
                    "imports": ["a"],
                    "refs": [{"name": "alpha", "kind": "calls", "line": 4}]}

        with patch.object(gc, "_parse_one", side_effect=fake_parse), \
             patch("topoone_app_architect.kb_gateway.call_kb",
                   side_effect=Exception("kb down")):   # 强制降级路径
            nodes, edges, stats = gc.collect_snapshot(
                self.root, self.PID, ["a.py", "sub/b.py"], "baseline:d2")
        self.assertEqual(stats["crossFileRefs"], 1)
        cross = [e for e in edges if e["kind"] == "calls"
                 and e["target"].startswith("cache:a.py::")]
        self.assertEqual(len(cross), 1)
        self.assertEqual(cross[0]["target"], "cache:a.py::alpha::1")

    def test_collect_snapshot_kb_path(self):
        from topoone_app_architect.sem import graph_collect as gc

        def fake_parse(root, rel, impl=True):
            if rel == "a.py":
                return {
                    "language": "python",
                    "symbols": [{"name": "alpha", "kind": "function",
                                 "startLine": 1, "endLine": 2,
                                 "qualifiedName": "alpha", "signature": "def alpha()"}],
                    "imports": [], "refs": [],
                }
            return {
                "language": "python",
                "symbols": [{"name": "beta", "kind": "function",
                             "startLine": 3, "endLine": 4,
                             "qualifiedName": "beta", "signature": "def beta()"}],
                "imports": ["a"],
                "refs": [{"name": "alpha", "kind": "calls", "line": 4}],
            }

        with patch.object(gc, "_parse_one", side_effect=fake_parse), \
             patch("topoone_app_architect.kb_gateway.call_kb",
                   side_effect=Exception("kb down")):   # 强制降级路径
            nodes, edges, stats = gc.collect_snapshot(
                self.root, self.PID, ["a.py", "sub/b.py"], "baseline:test")
        self.assertEqual(stats["parsed"], 2)
        self.assertEqual(stats["failed"], 0)
        names = {n["name"] for n in nodes if n["kind"] != "file"}
        self.assertEqual(names, {"alpha", "beta"})
        file_ids = {n["id"] for n in nodes if n["kind"] == "file"}
        self.assertIn("file:sub/b.py", file_ids)
        # imports 文件级边(D1: 模块说明符解析为真实 file 节点 id)
        imps = [e for e in edges if e["kind"] == "imports"]
        self.assertEqual(len(imps), 1)
        self.assertEqual(imps[0]["source"], "file:sub/b.py")
        self.assertEqual(imps[0]["target"], "file:a.py")
        self.assertEqual(stats["importsResolved"], 1)
        # ast cache 已回写(下次命中)
        cached = AstCacheStore.get(self.PID, "a.py")
        self.assertIsNotNone(cached)
        self.assertTrue(cached.get("symbols"))

    def test_collect_snapshot_cache_hit(self):
        from topoone_app_architect.sem import graph_collect as gc
        # 缓存命中是降级路径(逐文件)语义; 主路径 buildGraph 由 KB 全图直出无缓存
        with patch("topoone_app_architect.kb_gateway.call_kb",
                   side_effect=Exception("kb down")):   # 强制降级路径
            # 预置缓存(与磁盘内容 hash 一致)
            h = gc._cache_content_hash(self.root, "a.py")
            AstCacheStore.upsert(self.PID, "a.py", {
                "contentHash": h, "language": "python",
                "symbols": [_norm_node("a.py", "cached_sym")],
                "imports": [], "refs": [], "source": "kb",
            })
            nodes, edges, stats = gc.collect_snapshot(
                self.root, self.PID, ["a.py"], "baseline:test")
        self.assertEqual(stats["cached"], 1)
        self.assertEqual(stats["parsed"], 0)
        self.assertIn("cached_sym", {n["name"] for n in nodes})

    # ── A4: 基线锚自管层 ─────────────────────────────────────────

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
