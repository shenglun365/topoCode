"""S2 任务分支协议 — branch_service 单测（真实 git 临时仓库）。"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone_app_architect.arch_routes import branch_service as bs  # noqa: E402


def _git(args, cwd):
    p = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    assert p.returncode == 0, f"git {args} failed: {p.stderr}"
    return p.stdout.strip()


class TestBranchService(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="topo-branch-")
        self.root = os.path.join(self.dir, "work")
        os.makedirs(self.root)
        _git(["init", "-q", "-b", "main", "."], self.root)
        _git(["config", "user.email", "t@t"], self.root)
        _git(["config", "user.name", "t"], self.root)
        with open(os.path.join(self.root, "a.txt"), "w") as f:
            f.write("init\n")
        _git(["add", "-A"], self.root)
        _git(["commit", "-qm", "init"], self.root)
        self.base = _git(["rev-parse", "HEAD"], self.root)
        self.project = {"id": "proj-test-branch"}

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)
        shutil.rmtree(bs.mirror_path(self.project["id"]), ignore_errors=True)

    def test_prepare_rejects_dirty(self):
        with open(os.path.join(self.root, "a.txt"), "a") as f:
            f.write("dirty\n")
        r = bs.prepare_task_branch(self.root, "arch/E1", self.base)
        self.assertFalse(r["ok"])
        self.assertIn("未提交", r["reason"])

    def test_full_protocol_land_and_diff(self):
        # 1) prepare
        r = bs.prepare_task_branch(self.root, "arch/E1", self.base)
        self.assertTrue(r["ok"], r)
        self.assertEqual(_git(["branch", "--show-current"], self.root), "arch/E1")

        # 2) 镜像
        path = bs.ensure_mirror(self.project, self.root)
        self.assertTrue(os.path.isdir(path))
        url = _git(["remote", "get-url", bs.MIRROR_REMOTE], self.root)
        self.assertEqual(url, path)

        # 3) agent 编辑（未提交脏区）
        with open(os.path.join(self.root, "new.py"), "w") as f:
            f.write("print('by agent')\n")

        # 4) 落地：commit + push
        r = bs.land_task_branch(self.project, self.root, "E1", "arch/E1", "测试任务")
        self.assertTrue(r["ok"], r)
        tip = r["commit"]
        self.assertTrue(tip.startswith(self.base[:4]) or tip != self.base)
        self.assertFalse(_git(["status", "--porcelain"], self.root))  # 干净

        # 镜像含任务分支
        mirror_tip = _git(["rev-parse", f"refs/heads/arch/E1"], path)
        self.assertEqual(mirror_tip, tip)

        # 5) 幂等：再 land 不重复提交
        r2 = bs.land_task_branch(self.project, self.root, "E1", "arch/E1", "测试任务")
        self.assertTrue(r2["ok"])
        self.assertEqual(r2["reason"], "already-landed")
        self.assertEqual(r2["commit"], tip)

        # 6) 分支 diff（验收源）
        files = bs.branch_diff(self.root, self.base)
        self.assertEqual([f["path"] for f in files], ["new.py"])

    def test_prepare_base_mismatch_tolerant(self):
        other = _git(["commit", "--allow-empty", "-qm", "x"], self.root)
        r = bs.prepare_task_branch(self.root, "arch/E2", self.base)  # base 落后于 HEAD
        self.assertTrue(r["ok"])  # 宽容：按请求 base 建分支（manual 场景）
        self.assertEqual(_git(["rev-parse", "HEAD"], self.root),
                         _git(["rev-parse", self.base], self.root))


class TestWatchAndLand(unittest.TestCase):
    """mock runner：树终态 done → watch_and_land 自动 commit+push。"""

    def test_watch_lands_on_done(self):
        import time
        from unittest import mock as _mock
        d = tempfile.mkdtemp(prefix="topo-watch-")
        try:
            root = os.path.join(d, "w")
            os.makedirs(root)
            _git(["init", "-q", "-b", "main", "."], root)
            _git(["config", "user.email", "t@t"], root)
            _git(["config", "user.name", "t"], root)
            open(os.path.join(root, "a"), "w").write("1\n")
            _git(["add", "-A"], root); _git(["commit", "-qm", "i"], root)
            base = _git(["rev-parse", "HEAD"], root)
            self.assertTrue(bs.prepare_task_branch(root, "arch/W1", base)["ok"])
            open(os.path.join(root, "b.py"), "w").write("x\n")

            fake_runner = _mock.MagicMock()
            fake_runner.get_tree.return_value = {"status": "done"}
            task = {"id": "W1", "taskBranch": "arch/W1", "title": "w",
                    "baseCommit": base}
            with _mock.patch("topoone_app_architect.arch_routes.runner_gateway.get_runner",
                             return_value=fake_runner):
                bs.watch_and_land(task, {"id": "proj-watch"}, root, "tree-x",
                                  poll_s=0.2, max_wait_s=5)
                deadline = time.time() + 5
                landed = False
                while time.time() < deadline:
                    tip = bs._git(["rev-parse", "--verify", "--quiet",
                                   "refs/heads/arch/W1"],
                                  bs.mirror_path("proj-watch"))
                    if tip:
                        landed = True
                        break
                    time.sleep(0.2)
            self.assertTrue(landed)
        finally:
            shutil.rmtree(d, ignore_errors=True)
            shutil.rmtree(bs.mirror_path("proj-watch"), ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
