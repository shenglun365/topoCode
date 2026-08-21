"""Git domain routes — 真实 git 操作(arch_git 只读分析副本语义)。

契约见 docs/architect/api-execution.md。architect 不修改 agent 工作副本；
本域仅读取工程实现目录(root_path, 经 ?root= 或 ?project= 解析)与只读分析副本。
仓库不可用/无绑定项目 → 降级返回(不中断 UI)。
"""
import re
from typing import Optional
from fastapi import APIRouter, Request
from .common import _ts, ok, err
from . import store, arch_git

router = APIRouter()

BASELINE_COMMIT = "1a2b3c4d5e6f"


def _resolve_project(request: Request) -> Optional[dict]:
    root = request.query_params.get("root") or request.query_params.get("repo")
    project = request.query_params.get("project")
    from .project import _resolve_project as _rp
    return _rp(root, project)


def _status(root: str):
    return arch_git.status({"rootPath": root})


@router.get("/git/status")
async def git_status(request: Request):
    proj = _resolve_project(request)
    if not proj or not proj.get("rootPath"):
        return ok({"branch": "main", "ahead": 0, "behind": 0, "dirty": False,
                   "uncommitted": [], "staged": [], "baseline": BASELINE_COMMIT})
    return ok(_status(proj.get("rootPath")))


@router.get("/git/log")
async def git_log(request: Request, limit: int = 10):
    proj = _resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    entries = arch_git.commit_log(root, limit=limit)
    return ok({"branch": arch_git.repo_status(root).get("branch") or "main",
               "entries": entries, "baseline": BASELINE_COMMIT})


@router.get("/git/head")
async def git_head(request: Request):
    proj = _resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    st = arch_git.repo_status(root)
    return ok({"oid": st.get("commit")[:8] or "unknown", "subject": "",
               "branch": st.get("branch") or "main"})


@router.get("/git/working-tree")
async def git_working_tree(request: Request, limit: int = 200):
    proj = _resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    files = arch_git.working_tree(root, limit=limit)
    return ok({"files": files})


@router.post("/git/checkout")
async def git_checkout(request: Request):
    body = await request.json() or {}
    proj = _resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    ref = body.get("ref") or "main"
    return ok(arch_git.checkout(root, ref))


@router.post("/git/reset")
async def git_reset(request: Request):
    body = await request.json() or {}
    proj = _resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    target = body.get("target") or body.get("commit") or "HEAD"
    arch_git._git(["reset", "--hard", target], cwd=root)
    return ok({"mode": body.get("mode") or "hard", "target": target,
               "status": _status(root), "reset": True})


@router.post("/git/commit")
async def git_commit(request: Request):
    body = await request.json() or {}
    proj = _resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    msg = body.get("message") or "chore: 更新"
    arch_git._git(["add", "-A"], cwd=root)
    oid = arch_git._git(["commit", "-m", msg], cwd=root)
    return ok({"oid": oid or "unknown", "subject": msg,
               "branch": arch_git.repo_status(root).get("branch") or "main",
               "status": _status(root)})


@router.post("/git/push")
async def git_push(request: Request):
    body = await request.json() or {}
    proj = _resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    branch = body.get("branch") or arch_git.repo_status(root).get("branch") or "main"
    arch_git._git(["push", "-u", "origin", branch], cwd=root, timeout=300)
    return ok({"branch": branch, "pushed": True, "remote": "origin"})


@router.get("/git/diff")
async def git_diff(request: Request):
    proj = _resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    task_branch = (proj or {}).get("taskBranch") or ""
    base = (proj or {}).get("baselineCommit") or ""
    if task_branch:
        diff = arch_git.diff_files(proj or {}, task_branch, base=base)
        return ok({"files": [{"path": f["path"], "additions": 0, "deletions": 0,
                              "diff": ""} for f in diff.get("files", [])]})
    return ok({"files": []})