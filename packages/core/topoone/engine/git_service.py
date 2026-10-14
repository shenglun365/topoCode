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
    - 空仓库（无任何提交）时返回 ''。
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
    try:
        return rev_parse(dest, "HEAD", timeout=timeout)
    except GitError:
        return ""


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
    """为 branch/head 创建/切换到独立工作树( detached 锚定)。

    - new_dir 已存在时幂等重建：先正规注销（清注册表+目录）；注册表残骸态
      （目录被外力删除/半初始化）再 rmtree+prune 兜底 —— 否则 stale 注册
      会让后续 worktree add 永久失败。
    - head 缺省锚定本地 branch 顶端；本地分支不存在时回退 origin/<branch>。
    - 返回目标工作树解析出的 head commit。
    """
    if os.path.exists(new_dir):
        try:
            _run_git(path, "worktree", "remove", "--force", new_dir, timeout=timeout)
        except GitError:
            shutil.rmtree(new_dir, ignore_errors=True)
            _run_git(path, "worktree", "prune", timeout=timeout)
    os.makedirs(os.path.dirname(new_dir), exist_ok=True)
    fetch(path, timeout=timeout)
    # 一律 --detach：KB 镜像是只读锚定快照，detached 与 head 路径语义一致；
    # 且规避 "branch already checked out" 陷阱(同分支更新时 add 必败并残留
    # 半注册状态)。本地分支缺失时回退 origin/<branch>(-f 覆盖残骸注册)。
    try:
        _run_git(path, "worktree", "add", "--detach", new_dir,
                 head or branch, timeout=timeout)
    except GitError:
        _run_git(path, "worktree", "add", "-f", "--detach", new_dir,
                 f"origin/{branch}", timeout=timeout)
    return rev_parse(new_dir, "HEAD", timeout=timeout)


def remote_url(path: str) -> str:
    try:
        return _run_git(path, "remote", "get-url", "origin", timeout=30)
    except GitError:
        return ""


def diff_name_status(path: str, base: str, target: str,
                     timeout: int = 600) -> dict:
    """base → target 的文件级差异（A/M/D 清单）。

    --no-renames：重命名记为 A+D 一对，便于映射到「新增/删除」。
    """
    raw = _run_git(path, "diff", "--name-status", "--no-renames",
                   base, target, timeout=timeout)
    added: list = []
    modified: list = []
    deleted: list = []
    for line in raw.split("\n"):
        line = line.strip()
        if not line or "\t" not in line:
            continue
        status, _, name = line.partition("\t")
        s = status[:1].upper()
        if s == "A":
            added.append(name)
        elif s == "D":
            deleted.append(name)
        else:
            modified.append(name)
    return {"added": added, "modified": modified, "deleted": deleted}


def list_files(path: str, timeout: int = 300) -> List[str]:
    """列举 git 跟踪的文件（相对路径，POSIX 分隔符）。

    git 是文件清单的唯一事实源：嵌套 .gitignore 等忽略语义由 git 原生保证。
    """
    raw = _run_git(path, "ls-files", "-z", "--cached", timeout=timeout)
    if not raw:
        return []
    return [f for f in raw.split("\0") if f]


def status_porcelain(path: str, timeout: int = 300) -> dict:
    """工作区未提交状态 → {added, modified, deleted}。

    -uall 逐文件枚举未跟踪（?? 记 added）；R/C/T 记 modified。
    """
    raw = _run_git(path, "status", "--porcelain", "-uall", timeout=timeout)
    out = {"added": [], "modified": [], "deleted": []}
    if not raw:
        return out
    for line in raw.splitlines():
        if len(line) < 4:
            continue
        x, y, p = line[0], line[1], line[3:].strip()
        if " -> " in p:
            p = p.split(" -> ", 1)[1].strip()
        if x == "?" and y == "?":
            out["added"].append(p)
            continue
        st = x if x != " " else y
        if st == "A":
            out["added"].append(p)
        elif st == "D":
            out["deleted"].append(p)
        elif st in ("M", "R", "C", "T"):
            out["modified"].append(p)
    return out


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


def ensure_git_repo(path: str, timeout: int = 600) -> str:
    """把普通目录初始化为 git 仓库（git init + add -A + 首次提交）。

    供「独立源码目录未 git 初始化」时经用户同意后由 TopoCode 自动初始化。
    返回首次提交 hash。
    """
    if not os.path.isdir(path):
        raise GitError(f"directory not found: {path}")
    _run_git(path, "init", timeout=timeout)
    _run_git(path, "add", "-A", timeout=timeout)
    _run_git(path, "-c", "user.name=topocode", "-c", "user.email=topocode@local",
             "commit", "-m", "topocode: init baseline", timeout=timeout)
    return rev_parse(path, "HEAD", timeout=timeout)


def snapshot_baseline(worktree: str, baseline_repo: str, message: str,
                      timeout: int = 900) -> str:
    """把 worktree 当前 HEAD 的目录树快照为一个 commit，链入项目自有基线仓库。

    - baseline_repo 是项目独享的裸仓库（{镜像目录}/{project_id}/baseline.git），
      其 baseline 分支上的每个 commit 对应一次导入/更新的基线代码版本。
    - 只用 plumbing（rev-parse / commit-tree / push），不改动 worktree 的工作
      分支与工作树；commit 链以 -p 串联形成基线历史。
    - commit message 携带与上游仓库的对应关系（source#branch@head），
      同时该映射落库 project_versions.baseline_commit。
    返回基线 commit hash。
    """
    if not os.path.isdir(worktree):
        raise GitError(f"worktree not found: {worktree}")
    if not os.path.isdir(baseline_repo):
        _run_git(os.getcwd(), "init", "--bare", baseline_repo, timeout=timeout)
    tree = _run_git(worktree, "rev-parse", "HEAD^{tree}", timeout=timeout)
    args = ["-c", "user.name=topocode", "-c", "user.email=topocode@local",
            "commit-tree", tree, "-m", message]
    prev = ""
    try:
        prev = _run_git(baseline_repo, "rev-parse", "refs/heads/baseline", timeout=60)
    except GitError:
        prev = ""
    if prev:
        args = ["-c", "user.name=topocode", "-c", "user.email=topocode@local",
                "commit-tree", tree, "-p", prev, "-m", message]
    commit = _run_git(worktree, *args, timeout=timeout)
    _run_git(worktree, "push", baseline_repo,
             f"{commit}:refs/heads/baseline", "--force", timeout=timeout)
    return commit
