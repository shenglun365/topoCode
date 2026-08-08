"""Architect git 域 — 只读分析副本 + 真实 git 操作。

设计(外部 git 仓库为唯一代码事实源, 角色单向):
  - 编程 agent 实例: 在工程实现目录(root_path)建 task 分支, 改动后 commit+push 外部仓库;
  - ARCHITECT:      维护自己的**只读分析副本**({data_dir}/arch/<proj>/analysis)，
                    按 task 分支 pull, 供架构快照 / 验收 diff。只读镜像, 不提交;
  - KB:             既有 git_service + version_sync(不变)。

本模块包装 backend-core/git_service, 替换 git.py 的 mock 语义(保持契约形状)。
路径解析失败/仓库不可用 → 返回空/降级(不中断 UI), 与既有 git 域一致。
"""
import os
import subprocess
from typing import Optional

from .common import _ts
from . import store

# 顶层跳过目录(与 dirs.py _SKIP 一致)。
_SKIP = {".git", ".hg", ".svn", ".idea", ".vscode", "__pycache__", ".DS_Store",
         "node_modules", "dist", "build"}


def _git(args, cwd=None, timeout: float = 60):
    """执行 git 命令, 成功返回 stdout(去尾空白), 失败返回 None。"""
    cmd = ["git"] + list(args)
    try:
        r = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None
    return r.stdout.strip() if r.returncode == 0 else None


def _data_dir() -> str:
    from . import ctx
    return ctx.default_data_dir()


def analysis_root(project: dict) -> str:
    """architect 只读分析副本目录: {data_dir}/arch/{project_id}/analysis。"""
    return os.path.join(_data_dir(), "arch", project.get("id") or "unknown", "analysis")


def _ensure_dir(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        return True
    except OSError:
        return False


# ── 工程实现目录(agent 工作副本)读取 ────────────────────────────

def repo_status(root: str) -> dict:
    """root 仓库状态(真实)。返回 { branch, commit, dirty, ahead, behind }。"""
    branch = _git(["branch", "--show-current"], cwd=root) or ""
    commit = _git(["rev-parse", "HEAD"], cwd=root) or ""
    dirty = _git(["status", "--porcelain"], cwd=root)
    if dirty is None:
        return {"branch": branch, "commit": commit, "dirty": True, "ahead": 0, "behind": 0}
    changed = bool(dirty.strip())
    ahead = behind = 0
    line = _git(["rev-list", "--left-right", "--count", "@{upstream}"], cwd=root)
    if line:
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            behind, ahead = int(parts[0]), int(parts[1])
    return {"branch": branch, "commit": commit, "dirty": changed, "ahead": ahead, "behind": behind}


def remote_url(root: str) -> str:
    return _git(["remote", "get-url", "origin"], cwd=root) or ""


def branches(root: str) -> list:
    raw = _git(["branch", "-a", "--format=%(refname:short)"], cwd=root)
    return [b for b in (raw or "").split("\n") if b][:50]


def head_commit(root: str) -> str:
    return _git(["rev-parse", "HEAD"], cwd=root) or ""


def branch_commit(root: str, ref: str) -> str:
    return _git(["rev-parse", ref], cwd=root) or ""


# ── 基线校验(api-execution.md §6 语义, 真实化) ──────────────────

def verify_baseline(root: str, base_commit: str) -> dict:
    """校验工程目录基线: head.commit === base_commit && !dirty。

    root 缺失/非 git 仓库 → { ok: False, reason }。未提交改动或基线不符都算不通过。
    """
    if not root or not os.path.isdir(root):
        return {"ok": False, "reason": "工程目录不存在"}
    st = repo_status(root)
    if not st["commit"]:
        return {"ok": False, "reason": "非 git 仓库或无法读取 HEAD"}
    if st["dirty"]:
        return {"ok": False, "reason": "工作区存在未提交改动，请先提交或清理"}
    if base_commit and st["commit"] != base_commit:
        return {"ok": False, "reason": f"HEAD({st['commit'][:8]}) 与基线({base_commit[:8]})不符"}
    return {"ok": True, "reason": "", **st}


# ── 只读分析副本 ────────────────────────────────────────────────

def ensure_analysis_copy(project: dict, repo: str = "", branch: str = "") -> dict:
    """确保项目分析副本存在并推进到目标分支。返回 { ok, root, reason, commit }。

    - 未配置仓库(repo 为空): 以工程实现目录 root_path 直接作为只读源(降级)。
    - 已配置仓库: clone 到分析副本(不存在时), 然后 fetch + checkout 目标分支。
    """
    root_path = project.get("rootPath") or ""
    repo = repo or project.get("remoteUrl") or ""
    branch = branch or project.get("defaultBranch") or "main"
    target = analysis_root(project)

    if not repo:
        # 无外部仓库 → 就地目录即"副本"(只读语义由调用方遵守)。
        return {"ok": bool(root_path and os.path.isdir(root_path)),
                "root": root_path, "reason": "" if os.path.isdir(root_path) else "工程目录不可用",
                "commit": head_commit(root_path)}

    if not _ensure_dir(os.path.dirname(target)):
        return {"ok": False, "root": "", "reason": "无法创建分析副本目录"}
    if not os.path.isdir(os.path.join(target, ".git")):
        if os.path.exists(target):
            import shutil
            shutil.rmtree(target, ignore_errors=True)
        _ensure_dir(target)
        _git(["clone", "--no-checkout", repo, target], timeout=1800)

    _git(["fetch", "--prune", "origin"], cwd=target, timeout=900)
    # 本地目标分支已存在则 checkout, 否则从 origin/<branch> 新建。
    if _git(["rev-parse", "--verify", branch], cwd=target):
        _git(["checkout", "-f", branch], cwd=target)
    else:
        _git(["checkout", "-B", branch, f"origin/{branch}"], cwd=target)
    # 只读镜像: 丢弃本地任何差异。
    _git(["reset", "--hard", "HEAD"], cwd=target)
    return {"ok": True, "root": target, "reason": "",
            "commit": head_commit(target)}


def pull_task_branch(project: dict, task_branch: str) -> dict:
    """把 agent 提交的 task 分支同步到分析副本, 返回 { ok, root, commit, files }。"""
    copy = ensure_analysis_copy(project)
    root = copy.get("root") or ""
    if not copy.get("ok") or not task_branch:
        return {"ok": False, "root": root, "commit": "", "reason": copy.get("reason") or "分支为空"}
    _git(["fetch", "--prune", "origin"], cwd=root, timeout=900)
    if _git(["rev-parse", "--verify", f"origin/{task_branch}"], cwd=root):
        _git(["checkout", "-B", task_branch, f"origin/{task_branch}"], cwd=root)
    commit = head_commit(root)
    files = []
    raw = _git(["diff", "--name-status", f"origin/{copy.get('baseBranch') or 'main'}...HEAD"], cwd=root)
    if raw is None:
        raw = _git(["diff", "--name-status", "HEAD~1"], cwd=root)
    for line in (raw or "").split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append({"status": parts[0], "path": parts[1]})
    return {"ok": True, "root": root, "commit": commit, "files": files}


def working_tree(root: str, limit: int = 200) -> list:
    """列出工作区文件(含内容预览), 契约对齐 git.py 的 /git/working-tree。"""
    if not root or not os.path.isdir(root):
        return []
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SKIP and not d.startswith(".")]
        for f in filenames:
            if f in _SKIP or f.startswith("."):
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, root)
            if rel.startswith("."):
                continue
            try:
                with open(full, "r", errors="replace") as fh:
                    content = fh.read(4000)
            except OSError:
                content = ""
            out.append({"path": rel, "content": content})
            if len(out) >= limit:
                return out
    return out


def commit_log(root: str, limit: int = 10) -> list:
    raw = _git(["log", "--format=%H|%s|%aI", "-n", str(limit)], cwd=root)
    out = []
    for line in (raw or "").split("\n"):
        parts = line.split("|", 2)
        if len(parts) == 3:
            out.append({
                "oid": parts[0][:8], "subject": parts[1],
                "date": parts[2].replace("T", " ")[:16],
            })
    return out


def status(project: dict, root: Optional[str] = None) -> dict:
    """/git/status 契约(真实仓库)。root 缺省取工程实现目录。"""
    root = root or project.get("rootPath") or ""
    st = repo_status(root)
    baseline = (project.get("baselineCommit") or "").strip()
    return {
        "branch": st["branch"], "ahead": st["ahead"], "behind": st["behind"],
        "dirty": st["dirty"],
        "uncommitted": _porcelain(root) if st["dirty"] else [],
        "staged": [], "baseline": baseline,
    }


def _porcelain(root: str) -> list:
    raw = _git(["status", "--porcelain"], cwd=root)
    out = []
    for line in (raw or "").split("\n"):
        if len(line) > 3:
            out.append(line[3:])
    return out


def checkout(root: str, ref: str) -> dict:
    """切分支/提交(供验收后切回目标分支)。失败返回 { ok: False }。"""
    ok_ = _git(["checkout", ref], cwd=root)
    return {"branch": _git(["branch", "--show-current"], cwd=root) or ref,
            "oid": head_commit(root), "clean": ok_ is not None}


def diff_worktree(project: dict, base: str = "") -> dict:
    """工作树(含未提交)相对基线的差异。base 缺省取项目基线提交，否则取 defaultBranch/HEAD。

    返回 { filesChanged, added, modified, deleted, deletedHighRisk, files:[{path,status,additions,deletions}], byComponent }。
    byComponent: 按顶层组件(首个路径段)分组的 增删改统计。
    """
    root = project.get("rootPath") or ""
    base = (base or project.get("baselineCommit") or "").strip()
    head = head_commit(root)
    if not head:
        return {"filesChanged": 0, "added": 0, "modified": 0, "deleted": 0,
                "deletedHighRisk": False, "files": [], "byComponent": []}
    if not base:
        st = repo_status(root)
        base = st.get("branch") if st.get("branch") else head
    numstat = _git(["diff", "--numstat", base], cwd=root) or ""
    namestatus = _git(["diff", "--name-status", base], cwd=root) or ""
    add_map, del_map = {}, {}
    for line in numstat.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 3 and parts[2]:
            add_map[parts[2]] = int(parts[0]) if parts[0].isdigit() else 0
            del_map[parts[2]] = int(parts[1]) if parts[1].isdigit() else 0
    status_map = {}
    for line in namestatus.split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2:
            status_map[parts[1]] = parts[0][0]
    files = []
    for path, st_ in status_map.items():
        files.append({"path": path, "status": st_,
                      "additions": add_map.get(path, 0), "deletions": del_map.get(path, 0)})
    added_cnt = sum(1 for f in files if f["status"] == "A")
    modified_cnt = sum(1 for f in files if f["status"] == "M")
    deleted_cnt = sum(1 for f in files if f["status"] == "D")
    comp_map = {}
    for f in files:
        name = f["path"].split("/", 1)[0] if "/" in f["path"] else f["path"]
        c = comp_map.setdefault(name, {"name": name, "added": 0, "modified": 0, "deleted": 0, "files": []})
        if f["status"] == "A":
            c["added"] += 1
        elif f["status"] == "D":
            c["deleted"] += 1
        else:
            c["modified"] += 1
        c["files"].append(f["path"])
    return {"filesChanged": len(files), "added": added_cnt, "modified": modified_cnt,
            "deleted": deleted_cnt, "deletedHighRisk": deleted_cnt > 0,
            "files": files, "byComponent": list(comp_map.values())}


def diff_files(project: dict, task_branch: str, base: str = "") -> dict:
    """工程实现目录与 task 分支的差异(验收前给用户看)。"""
    root = project.get("rootPath") or ""
    base = base or project.get("baselineCommit") or project.get("defaultBranch") or "main"
    raw = _git(["diff", "--name-status", f"{base}...{task_branch}"], cwd=root)
    files = []
    for line in (raw or "").split("\n"):
        parts = line.split("\t")
        if len(parts) >= 2:
            files.append({"status": parts[0], "path": parts[1]})
    return {"filesChanged": len(files), "files": files}
