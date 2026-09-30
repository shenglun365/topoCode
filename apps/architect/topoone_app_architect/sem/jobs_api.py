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


@router.delete("/kb/semantic/jobs/{job_id}")
async def api_jobs_delete(job_id: str):
    """删除单条作业记录（仅终态：done/failed/cancelled/lost）。"""
    from ..store.jobs import SemanticJobsStore
    try:
        removed = await asyncio.to_thread(SemanticJobsStore.delete, job_id)
    except ValueError as e:
        return err(409, str(e))
    if not removed:
        return err(404, "作业不存在")
    return ok({"deleted": job_id})


@router.post("/kb/semantic/jobs/clear")
async def api_jobs_clear(request: Request = None):
    """清除全部已结束作业记录（终态行物理删除；进行中不受影响）。"""
    body = await request.json() if request else {}
    from ..store.jobs import SemanticJobsStore
    pid = project_id_for(body.get("root"), body.get("project"))
    if not pid:
        return err(400, "缺少项目")
    n = await asyncio.to_thread(SemanticJobsStore.clear_finished, pid)
    return ok({"cleared": n})


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


@router.post("/kb/semantic/extract-logic")
async def api_extract_logic(request: Request = None):
    """逻辑级提取作业提交（批3，需求 3-E）：{files?, rev?, modelId?, scopeKey?}。

    级联前置：范围内无实现级骨架自动先跑结构化提取(stages=impl→logic)。LLM 类。
    """
    from .logic_extract import start_extract_logic
    body = await request.json() if request else {}
    r = await asyncio.to_thread(
        start_extract_logic, body.get("root"), body.get("project"),
        rev=body.get("rev") or "workspace",
        files=body.get("files") or None,
        model_id=body.get("modelId") or None,
        scope_key=body.get("scopeKey") or "")
    return ok(r)


@router.get("/kb/semantic/logic/{asset_id}/members")
async def api_logic_members(asset_id: str):
    """逻辑链组成成员动态解析（需求 3-C：运行时取成员当前状态）。"""
    from ..store import SemanticAssetsStore
    from .logic_extract import resolve_members
    a = SemanticAssetsStore.get(asset_id)
    if not a:
        return err(404, "资产不存在")
    if (a.get("level") or "") != "logic":
        return err(400, "非逻辑级资产")
    return ok({"members": await asyncio.to_thread(resolve_members, a)})


@router.get("/kb/semantic/component-view/{component_id}")
async def api_component_view(component_id: str, root: Optional[str] = None,
                             project: Optional[str] = None,
                             rev: str = "workspace"):
    """组件聚合视图读取（缓存 active 直返；stale 带 regenerate 标记）。"""
    from .component_view import get_component_view
    r = await asyncio.to_thread(get_component_view, root, project, component_id, rev)
    return ok(r)


@router.post("/kb/semantic/component-view")
async def api_component_view_gen(request: Request = None):
    """组件聚合视图生成作业提交（批3，需求 4.1）：{keys: [组件id], rev?, modelId?}。LLM 类。"""
    from .component_view import start_gen_component_view
    body = await request.json() if request else {}
    r = await asyncio.to_thread(
        start_gen_component_view, body.get("root"), body.get("project"),
        body.get("keys") or [],
        rev=body.get("rev") or "workspace",
        model_id=body.get("modelId") or None)
    return ok(r)


@router.delete("/kb/semantic/component-view/{component_id}")
async def api_component_view_delete(component_id: str, root: Optional[str] = None,
                                    project: Optional[str] = None,
                                    rev: str = "workspace"):
    """清除组件视图缓存（需求 4.1：手动清除后可重生成）。"""
    from .component_view import clear_component_view
    r = await asyncio.to_thread(clear_component_view, root, project, component_id, rev)
    return ok(r)
