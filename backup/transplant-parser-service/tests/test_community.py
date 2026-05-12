"""
Community Analysis 单元测试
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from transplant.sqlite_store.connection import MultiDBManager
from transplant.sqlite_store.analysis_store import AnalysisStore
from transplant.community_analysis import analyze_communities


class TestCommunityAnalysis(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.multi_db = MultiDBManager(self.tmpdir)
        self.project_db = self.multi_db.get_project_db("test-proj")
        self.store = AnalysisStore(self.project_db)

    def tearDown(self):
        self.multi_db.close_all()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_edges(self):
        result = analyze_communities("task-001", self.store, "CALL", min_node_cnt=2)
        self.assertEqual(result["community_count"], 0)

    def test_simple_communities(self):
        # 构建一个简单的调用图: A→B, B→C, D→E
        edges = [
            {"task_id": "task-001", "symbol_node_type": "call_relation",
             "caller_file_id": 1, "caller_func_name": "A",
             "callee_name": "B", "callee_file_id": 1},
            {"task_id": "task-001", "symbol_node_type": "call_relation",
             "caller_file_id": 1, "caller_func_name": "B",
             "callee_name": "C", "callee_file_id": 1},
            {"task_id": "task-001", "symbol_node_type": "call_relation",
             "caller_file_id": 2, "caller_func_name": "D",
             "callee_name": "E", "callee_file_id": 2},
        ]
        self.store.bulk_insert_graph_nodes(edges)

        result = analyze_communities("task-001", self.store, "CALL", min_node_cnt=2)
        self.assertGreater(result["community_count"], 0)

        # 验证社区数据已保存
        communities = self.store.get_communities("task-001", "CALL")
        self.assertGreater(len(communities), 0)
        self.assertEqual(communities[0]["edge_type"], "CALL")

    def test_best_community(self):
        edges = [
            {"task_id": "task-001", "symbol_node_type": "call_relation",
             "caller_file_id": 1, "caller_func_name": "A",
             "callee_name": "B", "callee_file_id": 1},
        ]
        self.store.bulk_insert_graph_nodes(edges)
        analyze_communities("task-001", self.store, "CALL", min_node_cnt=2)

        best = self.store.get_best_community("task-001", "CALL")
        self.assertIsNotNone(best)
        self.assertIn("comm_id", best)
        self.assertIn("quality_score", best)


if __name__ == "__main__":
    unittest.main()
