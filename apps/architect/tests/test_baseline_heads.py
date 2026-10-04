"""数据主权自管基线管理面测试: rev 清单 / 任意两 head 组件文件 diff。

Run: cd <repo> && python -m pytest apps/architect/tests/test_baseline_heads.py -q
"""
import os
import sys
import tempfile
import unittest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.ctx as C  # noqa: E402
from topoone_app_architect.store.graph import ComponentStore, GraphStore  # noqa: E402


def _node(rel, name, start=1):
    return {"id": f"cache:{rel}::{name}::{start}", "kind": "function",
            "name": name, "qualified_name": name, "file_path": rel,
            "language": "python", "start_line": start, "end_line": start + 3,
            "start_column": 0, "end_column": 0, "signature": "", "docstring": "",
            "return_type": "", "is_exported": True}


def _file(rel):
    return {"id": f"file:{rel}", "kind": "file", "name": os.path.basename(rel),
            "qualified_name": rel, "file_path": rel, "language": "",
            "start_line": 0, "end_line": 0, "start_column": 0, "end_column": 0,
            "signature": "", "docstring": "", "return_type": "", "is_exported": False}


class TestBaselineHeads(unittest.TestCase):
    PID = "proj-heads-x"
    REV_A = "baseline:aaa111"
    REV_B = "baseline:bbb222"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        C.setup(data_dir=self._tmp.name)
        # rev A: a.py + 组件 ca
        GraphStore.replace_rev(self.PID, self.REV_A,
                               [_node("a.py", "fa"), _file("a.py")], [])
        ComponentStore.replace_rev(self.PID, self.REV_A,
                                   [{"id": "ca", "name": "A域", "owns": ["a.py"],
                                     "summary": "", "source": "community"}],
                                   [{"childId": "ca", "parentId": "", "level": 0}])
        # rev B: a.py + b.py + 组件 ca(owns 扩) + cb
        GraphStore.replace_rev(self.PID, self.REV_B,
                               [_node("a.py", "fa"), _node("b.py", "fb"),
                                _file("a.py"), _file("b.py")], [])
        ComponentStore.replace_rev(self.PID, self.REV_B,
                                   [{"id": "ca", "name": "A域", "owns": ["a.py", "b.py"],
                                     "summary": "", "source": "community"},
                                    {"id": "cb", "name": "B域", "owns": ["b.py"],
                                     "summary": "", "source": "community"}],
                                   [{"childId": "ca", "parentId": "", "level": 0},
                                    {"childId": "cb", "parentId": "", "level": 0}])

    def tearDown(self):
        self._tmp.cleanup()

    def test_rev_list(self):
        rows = GraphStore.rev_list(self.PID)
        revs = {r["rev"] for r in rows}
        self.assertEqual(revs, {self.REV_A, self.REV_B})
        b = next(r for r in rows if r["rev"] == self.REV_B)
        self.assertEqual(b["nodes"], 4)
        self.assertEqual(b["files"], 2)
        self.assertIn("updatedAt", b)

    def test_baseline_diff_two_heads(self):
        from topoone_app_architect.sem.symbols import baseline_diff  # noqa: F401 (import sanity)
        ma = {c["id"]: c for c in ComponentStore.list_rev(self.PID, self.REV_A)}
        mb = {c["id"]: c for c in ComponentStore.list_rev(self.PID, self.REV_B)}
        added = sorted(mb.keys() - ma.keys())
        removed = sorted(ma.keys() - mb.keys())
        self.assertEqual(added, ["cb"])
        self.assertEqual(removed, [])
        owns_changed = [i for i in ma.keys() & mb.keys()
                        if set(ma[i]["owns"]) != set(mb[i]["owns"])]
        self.assertEqual(owns_changed, ["ca"])
        fa = set(GraphStore.files(self.PID, self.REV_A))
        fb = set(GraphStore.files(self.PID, self.REV_B))
        self.assertEqual(sorted(fb - fa), ["b.py"])
        self.assertEqual(sorted(fa - fb), [])

    def test_heads_endpoint_shape(self):
        """端点形状: baselines 清单 isCurrent 标记 + baseline-diff counts。"""
        # 直接测 engine 端点函数(不经 HTTP)
        import asyncio
        from topoone_app_architect.sem import engine
        C.set_project(self.PID)
        try:
            res = asyncio.run(engine.api_baselines(project=self.PID))
            body = res.body if hasattr(res, "body") else res
            import json as _json
            d = _json.loads(body)["data"] if isinstance(body, bytes) else body["data"]
            self.assertEqual(len(d["baselines"]), 2)
            marks = [b["isCurrent"] for b in d["baselines"]]
            self.assertEqual(marks.count(True), 0)   # 无锚 → 全 False(合法)
            r2 = asyncio.run(engine.api_baseline_diff(
                {"project": self.PID, "headA": "aaa111", "headB": "bbb222"}))
            body2 = r2.body if hasattr(r2, "body") else r2
            d2 = _json.loads(body2)["data"] if isinstance(body2, bytes) else body2["data"]
            self.assertEqual(d2["components"]["counts"]["added"], 1)
            self.assertEqual(d2["components"]["counts"]["ownsChanged"], 1)
            self.assertEqual(d2["files"]["added"], ["b.py"])
        finally:
            C.reset_project(C._project_var.get() and C.set_project(None))


if __name__ == "__main__":
    unittest.main()
