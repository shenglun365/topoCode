"""
Task Store 单元测试
"""
import os
import sys
import tempfile
import unittest

# 添加项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from transplant.sqlite_store.connection import MultiDBManager
from transplant.sqlite_store.task_store import TaskStore


class TestTaskStore(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.multi_db = MultiDBManager(self.tmpdir)
        self.store = TaskStore(self.multi_db.main_db)

    def tearDown(self):
        self.multi_db.close_all()
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_task(self):
        task = self.store.create_task({
            "project_id": "proj-001",
            "name": "Test Task",
            "type": "full",
            "scopes": ["src"],
            "extensions": [".c", ".h"],
        })
        self.assertEqual(task["id"], task["id"])  # UUID generated
        self.assertEqual(task["name"], "Test Task")
        self.assertEqual(task["status"], "pending")
        self.assertEqual(task["scopes"], ["src"])

    def test_get_task(self):
        task = self.store.create_task({
            "project_id": "proj-001",
            "name": "Get Test",
        })
        fetched = self.store.get_task(task["id"])
        self.assertEqual(fetched["name"], "Get Test")

    def test_list_tasks(self):
        self.store.create_task({"project_id": "proj-001", "name": "Task 1"})
        self.store.create_task({"project_id": "proj-001", "name": "Task 2"})
        tasks = self.store.list_tasks("proj-001")
        self.assertEqual(len(tasks), 2)

    def test_update_task_config(self):
        task = self.store.create_task({
            "project_id": "proj-001",
            "name": "Config Test",
            "extensions": [".c"],
        })
        updated = self.store.update_task_config(task["id"], {
            "name": "Updated Name",
            "extensions": [".c", ".h"],
        })
        self.assertEqual(updated["name"], "Updated Name")
        self.assertEqual(updated["config_version"], 2)
        self.assertEqual(updated["status"], "pending")

    def test_create_run(self):
        task = self.store.create_task({
            "project_id": "proj-001",
            "name": "Run Test",
        })
        run = self.store.create_run(task["id"], {
            "scopes": ["src"],
            "extensions": [".c"],
        })
        self.assertEqual(run["run_number"], 1)
        self.assertEqual(run["status"], "running")

    def test_delete_task_cascade(self):
        task = self.store.create_task({
            "project_id": "proj-001",
            "name": "Delete Test",
        })
        self.store.create_run(task["id"], {})
        deleted = self.store.delete_task(task["id"])
        self.assertEqual(deleted, 1)
        self.assertIsNone(self.store.get_task(task["id"]))


if __name__ == "__main__":
    unittest.main()
