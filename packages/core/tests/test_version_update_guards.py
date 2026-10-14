"""版本更新守卫特征测试 — A·解析互斥 + B·worktree 幂等重建。

A: running/queued 解析任务存在时 sync/confirm_update 必须拒绝(混合状态
   基线防护)；pending(建而未跑)不拦。
B: git_service.worktree 对已存在目录(含注册表残骸态)可安全重建 —
   此前 rmtree 只删目录不清注册，二次 worktree add 永久失败。
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from topoone.db.manager import MultiDBManager
from topoone.engine import git_service
from topoone.engine import version_sync_service as vss


def _mk_project(md: MultiDBManager, pid: str, root: str):
    md.main_db.execute(
        "INSERT INTO projects(id, name, root_path) VALUES(?, ?, ?)",
        (pid, "test", root))
    md.main_db.conn.commit()


def _mk_task(md: MultiDBManager, pid: str, status: str, name: str = "t1"):
    md.main_db.execute(
        "INSERT INTO analysis_tasks(id, project_id, type, name, status)"
        " VALUES(?, ?, 'full', ?, ?)",
        (f"task-{status}", pid, name, status))
    md.main_db.conn.commit()


# ==================== A·解析互斥 ====================

def test_guard_blocks_running(tmp_path):
    """running 拦截。queued 亦在守卫词汇内(tasks_crud 同口径防御)，但被
    analysis_tasks CHECK 约束排除，不可插入故不测。"""
    md = MultiDBManager(data_dir=str(tmp_path))
    _mk_project(md, "p1", str(tmp_path))
    _mk_task(md, "p1", "running")
    with pytest.raises(ValueError, match="解析任务进行中"):
        vss._assert_no_running_analysis(md.main_db, "p1")


def test_guard_allows_pending_and_absent(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    _mk_project(md, "p1", str(tmp_path))
    vss._assert_no_running_analysis(md.main_db, "p1")  # 无任务
    _mk_task(md, "p1", "pending")
    vss._assert_no_running_analysis(md.main_db, "p1")  # pending 不拦


def test_sync_rejects_while_task_running(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    _mk_project(md, "p1", str(tmp_path / "src"))
    _mk_task(md, "p1", "running")
    with pytest.raises(ValueError, match="解析任务进行中"):
        vss.sync(md, "p1", force=True)


def test_confirm_update_rejects_while_task_running(tmp_path):
    md = MultiDBManager(data_dir=str(tmp_path))
    _mk_project(md, "p1", str(tmp_path / "src"))
    md.main_db.execute(
        "INSERT INTO project_update_requests(id, project_id, status)"
        " VALUES('req-1', 'p1', 'pending')")
    md.main_db.conn.commit()
    _mk_task(md, "p1", "running")
    with pytest.raises(ValueError, match="解析任务进行中"):
        vss.confirm_update(md, "req-1", method="pull")


# ==================== B·worktree 幂等重建 ====================

def _git(cwd: str, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                   cwd=cwd, check=True, capture_output=True)


def _mk_repo(base) -> str:
    up = base / "up"
    up.mkdir()
    _git(str(up), "init", "-b", "main")
    (up / "f.txt").write_text("v1")
    _git(str(up), "add", "-A")
    _git(str(up), "commit", "-m", "v1")
    repo = base / "repo"
    subprocess.run(["git", "clone", str(up), str(repo)],
                   check=True, capture_output=True)
    return str(repo)


def test_worktree_create_rebuild_and_wrecked(tmp_path):
    repo = _mk_repo(tmp_path)
    wt = str(tmp_path / "wts" / "main")

    # 首建
    git_service.worktree(repo, "main", wt)
    assert (tmp_path / "wts" / "main" / "f.txt").exists()

    # 上游前进后同路径重建(生产路径: confirm 显式携带 head) → 内容随新 head
    up = str(tmp_path / "up")
    (tmp_path / "up" / "f2.txt").write_text("v2")
    _git(up, "add", "-A")
    _git(up, "commit", "-m", "v2")
    v2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=up, check=True,
                        capture_output=True, text=True).stdout.strip()
    git_service.worktree(repo, "main", wt, head=v2)
    assert (tmp_path / "wts" / "main" / "f2.txt").exists()

    # 残骸态(目录被外力删除、注册表残留) → 仍可重建
    shutil.rmtree(wt)
    git_service.worktree(repo, "main", wt, head=v2)
    assert (tmp_path / "wts" / "main" / "f2.txt").exists()
