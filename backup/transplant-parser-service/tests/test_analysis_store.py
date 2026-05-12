"""
Analysis Store 单元测试
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from transplant.sqlite_store.connection import MultiDBManager
from transplant.sqlite_store.analysis_store import AnalysisStore


class TestAnalysisStore(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.multi_db = MultiDBManager(self.tmpdir)
        self.project_db = self.multi_db.get_project_db("test-proj")
        self.store = AnalysisStore(self.project_db)
        # 插入测试用源文件记录（满足外键约束）
        self.project_db.execute(
            "INSERT INTO source_files (id, file_path, file_name, language, size) "
            "VALUES (1, '/test/main.c', 'main.c', 'c', 1024)"
        )
        self.project_db.commit()

    def tearDown(self):
        self.multi_db.close_all()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_bulk_insert_nodes(self):
        nodes = [
            {"file_id": 1, "node_id": "n001", "type": "function_definition",
             "name": "main", "start": "1,0", "end": "10,0", "refs": []},
            {"file_id": 1, "node_id": "n002", "type": "call_expression",
             "name": "printf", "start": "5,4", "end": "5,20", "refs": []},
        ]
        self.store.bulk_insert_nodes(nodes)
        self.assertEqual(self.store.count_nodes(file_id=1), 2)

    def test_get_nodes_by_file(self):
        nodes = [
            {"file_id": 1, "node_id": "n001", "type": "function_definition",
             "name": "main", "start": "1,0", "end": "10,0", "refs": []},
        ]
        self.store.bulk_insert_nodes(nodes)
        result = self.store.get_nodes_by_file(1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "main")

    def test_bulk_insert_graph_nodes(self):
        nodes = [
            {"task_id": "task-001", "symbol_node_type": "function",
             "file_id": 1, "func_name": "main"},
            {"task_id": "task-001", "symbol_node_type": "call_relation",
             "caller_file_id": 1, "callee_name": "printf"},
        ]
        self.store.bulk_insert_graph_nodes(nodes)
        self.assertEqual(self.store.count_by_task_and_type("task-001"), 2)

    def test_clear_task_data(self):
        self.store.bulk_insert_graph_nodes([
            {"task_id": "task-001", "symbol_node_type": "function",
             "file_id": 1, "func_name": "main"},
        ])
        self.store.bulk_insert_communities([
            {"task_id": "task-001", "edge_type": "CALL", "comm_lv": "L0",
             "comm_id": "c1", "node_list": ["n1"], "node_count": 1},
        ])
        self.store.clear_task_data("task-001")
        self.assertEqual(self.store.count_by_task_and_type("task-001"), 0)
        self.assertEqual(self.store.count_communities("task-001"), 0)


if __name__ == "__main__":
    unittest.main()
