"""Git domain routes — 真实 git 操作(arch_git 只读分析副本语义)。

基线管理页已下线(能力并入概览页), 本域仅保留仍被消费的两端点:
- /git/status: FE 可达性探针(services/backend.ts) + 概览状态
- /git/log: 资产工作区 diff 对比选择器(gitService.commitLog)
仓库不可用/无绑定项目 → 降级返回(不中断 UI)。
"""
import asyncio
from typing import Optional
from fastapi import APIRouter, Request
from ..common import ok
from . import arch_git

router = APIRouter()


def resolve_project(request: Request) -> Optional[dict]:
    root = request.query_params.get("root") or request.query_params.get("repo")
    project = request.query_params.get("project")
    from .project import resolve_project as _rp
    return _rp(root, project)


@router.get("/git/status")
async def git_status(request: Request):
    proj = resolve_project(request)
    if not proj or not proj.get("rootPath"):
        return ok({"branch": "main", "ahead": 0, "behind": 0, "dirty": False,
                   "uncommitted": [], "staged": [], "baseline": ""})
    # git spawn 同步执行会冻结事件循环(挂载探针高频)——to_thread
    status = await asyncio.to_thread(arch_git.status, {"rootPath": proj.get("rootPath")})
    return ok(status)


@router.get("/git/log")
async def git_log(request: Request, limit: int = 10):
    proj = resolve_project(request)
    root = (proj or {}).get("rootPath") or ""
    entries = arch_git.commit_log(root, limit=limit)
    return ok({"branch": arch_git.repo_status(root).get("branch") or "main",
               "entries": entries, "baseline": (proj or {}).get("baselineCommit") or ""})
