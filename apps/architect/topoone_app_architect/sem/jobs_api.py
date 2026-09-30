"""语义作业统一 API（批1-3/1-5）：浮窗任务中心的数据源。

start 由各业务端点自行提交（sync-extract / unowned / enhance-desc 等），
此处提供 统一列表 / 单作业取消 / 状态详情。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import Request

from ..common import err, ok
from . import router
from .paths import project_id_for


@router.get("/kb/semantic/jobs")
async def api_jobs_list(root: Optional[str] = None, project: Optional[str] = None,
                        state: str = "", limit: int = 50):
    """作业列表（浮窗 + 历史）。"""
    from . import job_runner
    pid = project_id_for(root, project)
    if not pid:
        return ok({"jobs": []})
    jobs = await asyncio.to_thread(job_runner.list_jobs, pid, state, limit)
    return ok({"jobs": jobs})


@router.post("/kb/semantic/jobs/{job_id}/cancel")
async def api_jobs_cancel(job_id: str, root: Optional[str] = None,
                          project: Optional[str] = None):
    from . import job_runner
    pid = project_id_for(root, project)
    if not pid:
        return err(400, "缺少项目")
    return ok(await asyncio.to_thread(job_runner.cancel_job, pid, job_id))


@router.get("/kb/semantic/jobs/{job_id}")
async def api_jobs_get(job_id: str):
    from ..store.jobs import SemanticJobsStore
    job = SemanticJobsStore.get(job_id)
    if not job:
        return err(404, "作业不存在")
    return ok(job)


@router.post("/kb/semantic/extract-impl")
async def api_extract_impl(request: Request = None):
    """结构化提取作业提交（批2-4）：{rev?, keys?(组件id[]), files?, base?}。

    档位：无 keys/files=全量变化量(工作区) 或全量目录(baseline)；
    keys=单/多组件(owns 展开)；files=显式清单。无 LLM。
    """
    from .structural_extract import start_extract_impl
    body = await request.json() if request else {}
    root = body.get("root")
    project = body.get("project")
    r = await asyncio.to_thread(
        start_extract_impl, root, project,
        rev=body.get("rev") or "workspace",
        keys=body.get("keys") or None,
        files=body.get("files") or None,
        base=body.get("base") or "HEAD")
    return ok(r)
