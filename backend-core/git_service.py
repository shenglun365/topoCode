"""git_service.py — KB git 导入/更新服务。

负责 KB 侧与 git 仓库交互的底层操作：
  - clone (git-local / git-remote 导入)
  - fetch / pull (同分支前进)
  - worktree add (切分支 / 多工作区，保留多份代码)
  - rev-parse (解析 head)
  - 分支/标签列表

设计约束（KB 版本基线语义）：
  - KB 只向前，不向后；每次更新清空缓存代码后按新 (branch, head) 拉取。
  - 更新方式由用户选择：'pull'（前进现有工作树）或 'worktree'（新工作树）。
  - 对比只在 KB 基线之间进行，本模块不提供 git ancestry diff。
"""

import logging
import os
import subprocess
import shutil
from typing import List, Optional

logger = logging.getLogger(__name__)


class GitError(Exception):
    """git 操作失败"""


def _run_git(cwd: str, *args: str, timeout: int = 300) -> str:
    """在 cwd 下执行 git 命令，返回 stdout（去尾换行）。"""
    cmd = ["git"] + list(args)
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise GitError(f"git {' '.join(args)} timed out after {timeout}s")
    except FileNotFoundError:
        raise GitError("git executable not found")
    if proc.returncode != 0:
        raise GitError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def is_git_repo(path: str) -> bool:
    return bool(path) and os.path.isdir(os.path.join(path, ".git"))


def rev_parse(path: str, ref: str = "HEAD", timeout: int = 60) -> str:
    """解析 ref 为完整 commit hash。"""
    return _run_git(path, "rev-parse", ref, timeout=timeout)


def current_branch(path: str) -> str:
    """当前分支名；detached head 时返回 HEAD 短哈希。"""
    try:
        return _run_git(path, "rev-parse", "--abbrev-ref", "HEAD", timeout=30)
    except GitError:
        return ""


def list_branches(path: str, limit: int = 50) -> List[str]:
    """本地+远端分支列表。"""
    try:
        raw = _run_git(path, "branch", "-a", "--format=%(refname:short)", timeout=30)
    except GitError:
        return []
    out = [b for b in raw.split("\n") if b]
    return out[:limit]


def list_tags(path: str, limit: int = 50) -> List[str]:
    try:
        raw = _run_git(path, "tag", "--sort=-creatordate", timeout=30)
    except GitError:
        return []
    out = [t for t in raw.split("\n") if t]
    return out[:limit]


def recent_commits(path: str, limit: int = 10) -> List[dict]:
    try:
        raw = _run_git(path, "log", "--format=%H|%s|%aI", "-n", str(limit), timeout=60)
    except GitError:
        return []
    commits = []
    for line in raw.split("\n"):
        parts = line.split("|", 2)
        if len(parts) == 3:
            commits.append({
                "hash": parts[0],
                "short": parts[0][:8],
                "message": parts[1],
                "date": parts[2],
            })
    return commits


def clone(source: str, dest: str, branch: Optional[str] = None,
          head: Optional[str] = None, timeout: int = 1800) -> str:
    """克隆仓库到 dest。

    - branch 指定时 clone 该分支；head 指定时 clone 后 checkout 该提交。
    - 返回最终解析出的 head commit。
    """
    if os.path.exists(dest):
        shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    cmd = ["clone"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [source, dest]
    _run_git(os.getcwd(), *cmd, timeout=timeout)
    if head:
        _run_git(dest, "checkout", head, timeout=timeout)
    return rev_parse(dest, "HEAD", timeout=timeout)


def fetch(path: str, timeout: int = 900) -> None:
    """拉取远端引用（不动工作树）。"""
    _run_git(path, "fetch", "--prune", timeout=timeout)


def pull(path: str, branch: Optional[str] = None, timeout: int = 900) -> str:
    """同分支前进：fetch + checkout/merge。

    branch 给出时先切到该分支（本地不存在则从 origin 建立跟踪分支），再拉。
    返回最终 head commit。
    """
    fetch(path, timeout=timeout)
    if branch:
        try:
            _run_git(path, "checkout", branch, timeout=timeout)
        except GitError:
            _run_git(path, "checkout", "-b", branch, f"origin/{branch}", timeout=timeout)
        _run_git(path, "pull", "--ff-only", timeout=timeout)
    else:
        _run_git(path, "pull", "--ff-only", timeout=timeout)
    return rev_parse(path, "HEAD", timeout=timeout)


def worktree(path: str, branch: str, new_dir: str, head: Optional[str] = None,
             timeout: int = 900) -> str:
    """为 branch/head 创建/切换到独立工作树。

    - 目标分支在 path 仓库中不存在时，从 origin/<branch> 新建。
    - 返回目标工作树解析出的 head commit。
    """
    if os.path.exists(new_dir):
        shutil.rmtree(new_dir, ignore_errors=True)
    os.makedirs(os.path.dirname(new_dir), exist_ok=True)
    fetch(path, timeout=timeout)
    try:
        if head:
            _run_git(path, "worktree", "add", "--detach", new_dir, head, timeout=timeout)
        else:
            _run_git(path, "worktree", "add", new_dir, branch, timeout=timeout)
    except GitError:
        _run_git(path, "worktree", "add", new_dir, f"origin/{branch}", timeout=timeout)
    return rev_parse(new_dir, "HEAD", timeout=timeout)


def remote_url(path: str) -> str:
    try:
        return _run_git(path, "remote", "get-url", "origin", timeout=30)
    except GitError:
        return ""


def checkout_ref(path: str, branch: Optional[str], head: Optional[str],
                 method: str = "pull", timeout: int = 900) -> str:
    """按用户选择的方式把 path 仓库推进到 (branch, head)。

    method:
      - 'pull'     同分支前进（或切分支后 pull），清空脏改动（KB 缓存只读镜像）。
      - 'worktree' 由调用方改用 worktree()，本函数不处理。
    返回最终 head。
    """
    if method == "pull":
        # KB 缓存目录是只读镜像，丢弃本地改动
        _run_git(path, "reset", "--hard", "HEAD", timeout=timeout)
        _run_git(path, "clean", "-fd", timeout=timeout)
        resolved = pull(path, branch=branch, timeout=timeout)
        if head and resolved != head:
            _run_git(path, "checkout", head, timeout=timeout)
            resolved = rev_parse(path, "HEAD", timeout=timeout)
        return resolved
    raise GitError(f"unknown method: {method}")
