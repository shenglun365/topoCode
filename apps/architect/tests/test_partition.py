"""D3 大项目分区测试: 拆分算法 / PartitionStore / merge_partition / 作业分区模式。

Run: cd <repo> && python -m pytest apps/architect/tests/test_partition.py -q
"""
import json
import os
import sys
import tempfile
import unittest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C  # noqa: E402
from topoone_app_architect.sem.partition import (  # noqa: E402
    MAX_FILES_PER_TASK, _merge_same_lang, build_partitions, file_lang,
)
from topoone_app_architect.store.graph import GraphStore  # noqa: E402
from topoone_app_architect.store.partition import PartitionStore  # noqa: E402


def _mk_tree(tmp, files):
    for rel in files:
        p = os.path.join(tmp, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(f"// {rel}\nconst x = 1\n" if rel.endswith((".ts", ".js")) else "x = 1\n")


class TestPartitionAlgorithm(unittest.TestCase):
    def test_file_lang(self):
        self.assertEqual(file_lang("a/b.ts"), "typescript")
        self.assertEqual(file_lang("x.vue"), "vue")
        self.assertEqual(file_lang("y.md"), "")

    def test_small_project_single_partition(self):
        with tempfile.TemporaryDirectory() as tmp:
            _mk_tree(tmp, ["a.ts", "sub/b.ts"])
            parts, stats = build_partitions(tmp, ["a.ts", "sub/b.ts"])
            self.assertEqual(len(parts), 1)
            self.assertEqual(parts[0]["reason"], "single")
            self.assertFalse(stats.get("overflowSplit"))

    def test_disconnected_components_split_by_language(self):
        """TS 域与 PY 域无依赖边 → 独立分区(语言隔离); TS/JS 相连合并。"""
        with tempfile.TemporaryDirectory() as tmp:
            files = []
            # web 域: a.ts import ./b.js
            _mk_tree(tmp, ["web/a.ts"])
            with open(os.path.join(tmp, "web", "a.ts"), "w") as f:
                f.write("import { x } from './b'\nexport const y = x\n")
            _mk_tree(tmp, ["web/b.js"])
            # py 域: 独立
            _mk_tree(tmp, ["svc/main.py", "svc/util.py"])
            with open(os.path.join(tmp, "svc", "main.py"), "w") as f:
                f.write("from util import y\nprint(y)\n")
            files = ["web/a.ts", "web/b.js", "svc/main.py", "svc/util.py"]
            parts, stats = build_partitions(tmp, files, cap=2)
            # cap=2: web 域(2 文件)与 py 域(2 文件)各自成区(连通分量)——
            # 同语言合并只并语言集相交的, web(ts+js) 与 py 不交 → 不合并
            self.assertEqual(len(parts), 2, [p["files"] for p in parts])
            lang_sets = [set(p["langs"]) for p in parts]
            self.assertNotIn(lang_sets[0] & lang_sets[1], [{"typescript"}])

    def test_overflow_component_boxed_by_dir(self):
        """超限连通分量 → 一级目录装箱, 每箱 ≤ cap。"""
        with tempfile.TemporaryDirectory() as tmp:
            files = [f"big/m{i:03d}.py" for i in range(9)]  # cap=4 → 3 箱(3+3+3)
            _mk_tree(tmp, files)
            with open(os.path.join(tmp, "big", "m000.py"), "w") as f:
                f.write("import m001\n")  # 全连通
            parts, stats = build_partitions(tmp, files, cap=4)
            self.assertGreaterEqual(len(parts), 3)
            for p in parts:
                self.assertLessEqual(len(p["files"]), 4)
            allf = [f for p in parts for f in p["files"]]
            self.assertEqual(sorted(allf), sorted(files))

    def test_merge_same_lang(self):
        g = _merge_same_lang([["a.ts"], ["b.ts"], ["c.py"]], cap=10)
        ts = [x for x in g if x[0].endswith(".ts")]
        py = [x for x in g if x[0].endswith(".py")]
        self.assertEqual(len(ts), 1)          # ts 合并
        self.assertEqual(sorted(ts[0]), ["a.ts", "b.ts"])
        self.assertEqual(len(py), 1)          # py 独立
        self.assertEqual(len(g), 2)


class TestMergePartition(unittest.TestCase):
    PID = "proj-part-x"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        C.setup(data_dir=self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    @staticmethod
    def _node(rel, name, start=1):
        return {"id": f"cache:{rel}::{name}::{start}", "kind": "function",
                "name": name, "qualified_name": name, "file_path": rel,
                "language": "python", "start_line": start, "end_line": start + 5,
                "start_column": 0, "end_column": 0, "signature": "", "docstring": "",
                "return_type": "", "is_exported": True}

    def test_two_partitions_merge_no_overwrite(self):
        rev = "baseline:hhh"
        p1 = [self._node("pa.py", "fa"), {"id": "file:pa.py", "kind": "file",
                                          "name": "pa.py", "file_path": "pa.py"}]
        e1 = [{"source": "cache:pa.py::fa::1", "target": "file:pa.py", "kind": "contains"}]
        r1 = GraphStore.merge_partition(self.PID, rev, p1, e1, ["pa.py"])
        self.assertEqual(r1["nodes"], 2)
        p2 = [self._node("pb.py", "fb"), {"id": "file:pb.py", "kind": "file",
                                          "name": "pb.py", "file_path": "pb.py"}]
        e2 = [{"source": "cache:pb.py::fb::1", "target": "file:pb.py", "kind": "contains"},
              {"source": "cache:pb.py::fb::1", "target": "cache:pa.py::fa::1", "kind": "calls"}]
        r2 = GraphStore.merge_partition(self.PID, rev, p2, e2, ["pb.py"])
        self.assertEqual(r2["nodes"], 2)
        # p1 数据未被 p2 覆盖
        self.assertEqual(GraphStore.counts(self.PID, rev), {"nodes": 4, "edges": 3})
        # 跨分区边(fb→fa)成立(端点都存在)
        calls = GraphStore.edges(self.PID, rev, kind="calls")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["target"], "cache:pa.py::fa::1")

    def test_partition_rerun_idempotent(self):
        rev = "baseline:rr"
        p1 = [self._node("pa.py", "fa")]
        GraphStore.merge_partition(self.PID, rev, p1, [], ["pa.py"])
        # 重跑同分区: 先删后插, 不翻倍
        GraphStore.merge_partition(self.PID, rev, p1, [], ["pa.py"])
        self.assertEqual(GraphStore.counts(self.PID, rev), {"nodes": 1, "edges": 0})


class TestPartitionStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        C.setup(data_dir=self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_plan_lifecycle(self):
        pid = "proj-part-store"
        head = "abc123"
        parts = [
            {"idx": 0, "files": ["a.ts", "b.ts"], "langs": ["typescript"],
             "est_symbols": 40, "reason": "component"},
            {"idx": 1, "files": ["c.py"], "langs": ["python"],
             "est_symbols": 10, "reason": "component"},
        ]
        n = PartitionStore.replace_plan(pid, head, parts)
        self.assertEqual(n, 2)
        rows = PartitionStore.list_rev(pid, head)
        self.assertEqual([r["idx"] for r in rows], [0, 1])
        self.assertEqual(rows[0]["files"], ["a.ts", "b.ts"])   # JSON 解码
        self.assertEqual(rows[0]["state"], "proposed")
        PartitionStore.set_state(pid, head, 0, "confirmed")
        PartitionStore.set_state(pid, head, 1, "skipped")
        self.assertEqual(PartitionStore.counts_by_state(pid, head),
                         {"confirmed": 1, "skipped": 1})
        # 重新提案整版重灌
        PartitionStore.replace_plan(pid, head, parts[:1])
        self.assertEqual(len(PartitionStore.list_rev(pid, head)), 1)


if __name__ == "__main__":
    unittest.main()
