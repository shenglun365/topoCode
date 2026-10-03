"""自有社区组件目录测试（数据主权批B）。

覆盖：community_group 作业端到端（快照→KB 算力 mock→组件落库）、
catalog arch_only 切源（arch 优先/空目录降级/merge 并集）、源开关 KV。
"""
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from topoone_app_architect import ctx as app_ctx
from topoone_app_architect.sem import catalog
from topoone_app_architect.sem.component_group import _job_community_group
from topoone_app_architect.sem.graph_collect import record_graph_baseline
from topoone_app_architect.store.graph import ComponentStore, GraphStore


class _FakeCtx:
    """JobCtx 鸭子替身（progress 吞掉）。"""

    def __init__(self, pid):
        self._pid = pid

    pid = property(lambda self: self._pid)
    scope = property(lambda self: {})
    job = property(lambda self: {"id": "j1", "projectId": self._pid})

    def cancelled(self):
        return False

    def progress(self, **kw):
        pass


class CommunityGroupTest(unittest.TestCase):
    PID = "proj-graph-b"

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        app_ctx.setup(data_dir=self._tmp.name)
        # 预置图谱快照: 2 簇各 3 文件
        nodes, edges = [], []
        for c in range(2):
            for i in range(3):
                rel = f"pkg{c}/f{i}.py"
                nodes.append({
                    "id": f"file:{rel}", "kind": "file", "name": f"f{i}.py",
                    "qualified_name": rel, "file_path": rel, "language": "python",
                    "start_line": 0, "end_line": 0, "start_column": 0,
                    "end_column": 0, "signature": "", "docstring": "",
                    "return_type": "", "is_exported": False,
                })
                if i > 0:
                    edges.append({"source": f"file:pkg{c}/f{i}.py",
                                  "target": f"file:pkg{c}/f0.py",
                                  "kind": "imports", "line": 1, "col": 0})
        GraphStore.replace_rev(self.PID, "baseline:bee", nodes, edges)
        record_graph_baseline(self.PID, "bee")

    def tearDown(self):
        self._tmp.cleanup()

    KB_RESULT = {
        "components": [
            {"commId": "comm-uni-L0-0000", "level": "L0", "parentId": "",
             "files": ["pkg0/f0.py", "pkg0/f1.py", "pkg0/f2.py"],
             "nodeCount": 3, "fileCount": 3, "qualityScore": 0.9},
            {"commId": "comm-uni-L0-0001", "level": "L0", "parentId": "",
             "files": ["pkg1/f0.py", "pkg1/f1.py", "pkg1/f2.py"],
             "nodeCount": 3, "fileCount": 3, "qualityScore": 0.9},
        ],
        "levels": 1,
        "counts": {"unifiedComponents": 2},
    }

    def test_community_group_job_e2e(self):
        with patch("topoone_app_architect.kb_gateway.call_kb",
                   return_value=dict(self.KB_RESULT)) as mk:
            r = _job_community_group(_FakeCtx(self.PID))
        self.assertNotIn("error", r)
        self.assertEqual(r["components"], 2)
        self.assertEqual(r["rev"], "baseline:bee")
        # 落库形状
        comps = ComponentStore.list_rev(self.PID, "baseline:bee")
        self.assertEqual(len(comps), 2)
        by_id = {c["id"]: c for c in comps}
        self.assertEqual(by_id["comm-uni-L0-0000"]["owns"],
                         ["pkg0/f0.py", "pkg0/f1.py", "pkg0/f2.py"])
        self.assertEqual(by_id["comm-uni-L0-0000"]["source"], "community")
        # KB 收到的节点已精简且含 file 虚拟节点
        kw = mk.call_args[1]
        self.assertTrue(all(set(n) <= {"id", "kind", "name",
                                       "qualified_name", "file_path"}
                            for n in kw["nodes"]))
        self.assertTrue(any(n["id"] == "file:pkg0/f0.py" for n in kw["nodes"]))

    def test_job_no_anchor_error(self):
        from topoone_app_architect.store.base import _target_db
        db = _target_db("arch_settings", self.PID)
        db.execute("DELETE FROM arch_settings WHERE key = ?", (f"arch.graphBaseline.{self.PID}",))
        db.commit()
        r = _job_community_group(_FakeCtx(self.PID))
        self.assertIn("error", r)

    def test_job_empty_snapshot_error(self):
        record_graph_baseline(self.PID + "-x", "fff")
        r = _job_community_group(_FakeCtx(self.PID + "-x"))
        self.assertIn("error", r)
        self.assertIn("collect-graph", r["error"])

    # ── catalog 切源 ─────────────────────────────────────────────

    def test_catalog_arch_only_source(self):
        # 预置组件(上面作业已落库的话直接用; 这里独立落)
        ComponentStore.replace_rev(self.PID, "baseline:bee", [
            {"id": "c1", "name": "c1", "owns": ["pkg0/f0.py"], "source": "community"},
        ], [])
        catalog._cache.clear()
        cat = catalog.component_catalog(None, self.PID, force=True)
        self.assertEqual(cat["source"], "arch")
        self.assertEqual(cat["byId"]["c1"]["owns"], ["pkg0/f0.py"])
        self.assertEqual(cat["depths"]["c1"], 0)
        # owners_of 归属直通(五消费方同口径)
        self.assertEqual(catalog.owners_of("pkg0/f0.py", cat), ["c1"])

    def test_catalog_arch_empty_degrades(self):
        catalog._cache.clear()
        cat = catalog.component_catalog(None, "proj-no-components", force=True)
        self.assertEqual(cat["source"], "empty")
        self.assertIn("collect-graph", cat["note"])

    def test_catalog_source_switch_kb_mode_calls_kb(self):
        from topoone_app_architect.store.base import _target_db
        db = _target_db("arch_settings", self.PID)
        db.execute(
            "INSERT INTO arch_settings(key,value) VALUES('arch.catalogSource',?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (json.dumps({"mode": "kb"}),))
        db.commit()
        catalog._cache.clear()
        try:
            with patch("topoone_app_architect.common.build_component_catalog",
                       return_value={"components": [
                           {"id": "kbid1", "name": "k", "owns": ["x.py"]}]}), \
                 patch("topoone_app_architect.common.build_architecture_model",
                       return_value={"components": []}):
                cat = catalog.component_catalog(None, self.PID, force=True)
            self.assertEqual(cat["source"], "catalog")
            self.assertIn("kbid1", cat["byId"])
        finally:
            db.execute("DELETE FROM arch_settings WHERE key='arch.catalogSource'")
            db.commit()
            catalog._cache.clear()


if __name__ == "__main__":
    unittest.main()
