"""
verify_service.py — 文件校验（git 核心机制）。

git 是唯一事实源：
  - 变更集 = 基线 commit（project_versions.baseline_commit）→ HEAD 的
    `git diff --name-status` ∪ 工作区未提交（`git status --porcelain`，工作区态优先）。
  - 非 git 仓库 / 无基线 → 降级返回（note 标注），不报错。
"""
import logging
import os
import threading
import time
import uuid
from typing import Optional

from topoone.engine import git_service

logger = logging.getLogger(__name__)

VERIFY_STATUS_RUNNING = "running"
VERIFY_STATUS_DONE = "done"
VERIFY_STATUS_ERROR = "error"

_verify_tasks: dict[str, dict] = {}
_verify_lock = threading.Lock()

_CHANGE_KEYS = ("added", "modified", "deleted")


def _baseline_commit(main_db, project_id: str) -> str:
    """项目最近一次导入/更新快照的基线 commit（无则 ''）。"""
    try:
        row = main_db.fetchone(
            "SELECT baseline_commit FROM project_versions "
            "WHERE project_id = ? AND IFNULL(baseline_commit, '') != '' "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (project_id,),
        )
    except Exception:
        return ""
    return (row or {}).get("baseline_commit") or ""


def _verify_worker(verify_id: str, multi_db, project_id: str, publish_fn):
    t0 = time.time()
    try:
        main_db = multi_db.main_db
        project = main_db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if not project:
            raise ValueError(f"Project not found: {project_id}")

        root = project.get("root_path", "") or ""
        result = {
            "mode": "git",
            "baseline": "", "head": "", "branch": project.get("branch") or "",
            "dirty": 0,
            "added": [], "modified": [], "deleted": [], "total": 0,
            "note": "", "details": [],
        }

        if not root or not os.path.isdir(root) or not git_service.is_git_repo(root):
            result["note"] = "not-git"
        else:
            try:
                result["head"] = git_service.rev_parse(root, "HEAD", timeout=60)
            except git_service.GitError:
                result["head"] = ""
            result["branch"] = git_service.current_branch(root) or result["branch"]
            if result["head"]:
                baseline = _baseline_commit(main_db, project_id)
                committed = {"added": [], "modified": [], "deleted": []}
                if baseline:
                    result["baseline"] = baseline
                    try:
                        committed = git_service.diff_name_status(root, baseline, result["head"])
                    except git_service.GitError as e:
                        logger.warning("[Verify] %s diff failed: %s", verify_id, e)
                        result["note"] = "diff-failed"
                else:
                    result["note"] = "no-baseline"
                worktree = git_service.status_porcelain(root)
                result["dirty"] = sum(len(v) for v in worktree.values())
                # 合并：工作区态优先覆盖已提交漂移
                cat: dict[str, str] = {}
                for src in (committed, worktree):
                    for k in _CHANGE_KEYS:
                        for p in src.get(k) or []:
                            cat[p] = k
                for k in _CHANGE_KEYS:
                    result[k] = sorted(p for p, c in cat.items() if c == k)
                result["total"] = len(cat)
                result["details"] = [{"filePath": p, "status": c} for p, c in sorted(cat.items())]
            else:
                result["note"] = "no-head"

        elapsed = time.time() - t0
        _update_status(verify_id, VERIFY_STATUS_DONE, 100,
                       f"Git comparison complete: {result['total']} changed ({elapsed:.1f}s)",
                       result=result)
        publish_fn("verify", "verify.done", {
            "verifyId": verify_id,
            "projectId": project_id,
            "total": result["total"],
        })
        logger.info(f"[Verify] {verify_id} done: {project_id} total={result['total']} ({elapsed:.1f}s)")

    except Exception as e:
        logger.error(f"[Verify] {verify_id} failed: {e}", exc_info=True)
        _update_status(verify_id, VERIFY_STATUS_ERROR, 0, str(e))
        publish_fn("verify", "verify.error", {"verifyId": verify_id, "error": str(e)})


def _update_status(verify_id: str, status: str, progress: int,
                   message: str = "", result: Optional[dict] = None):
    with _verify_lock:
        if verify_id in _verify_tasks:
            _verify_tasks[verify_id].update({
                "status": status,
                "progress": progress,
                "message": message,
            })
            if result:
                _verify_tasks[verify_id]["result"] = result


def start_verify(multi_db, project_id: str, publish_fn) -> str:
    """启动文件比对后台任务，返回 verify_id"""
    verify_id = f"verify-{uuid.uuid4().hex[:12]}"
    with _verify_lock:
        _verify_tasks[verify_id] = {
            "id": verify_id,
            "status": VERIFY_STATUS_RUNNING,
            "progress": 0,
            "message": "Queued",
            "result": None,
        }
    thread = threading.Thread(
        target=_verify_worker,
        args=(verify_id, multi_db, project_id, publish_fn),
        daemon=True,
    )
    thread.start()
    return verify_id


def get_verify_status(verify_id: str) -> Optional[dict]:
    with _verify_lock:
        return _verify_tasks.get(verify_id)
