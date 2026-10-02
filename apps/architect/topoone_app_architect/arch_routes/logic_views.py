"""逻辑视图 API：语义资产的「逻辑分析」分组数据源。

逻辑资产 = 视图类型存在（跨文件跨组件的业务逻辑链条，非提取产出的资产行）：
- 提取时勾选逻辑(模式1)：extract_logic 作业 LLM 归纳链条存为视图(source=extract)；
- 手动新建(模式2)：选核心实现资产 → analyze 作业沿调用依赖拓展成员 + LLM 概括。
"""
from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Request

from ..common import err, ok
from .semantic_assets import project_id_for

router = APIRouter()


@router.get("/kb/semantic/logic-views")
async def api_logic_views_list(root: Optional[str] = None, project: Optional[str] = None):
    """逻辑视图列表（updated_at 倒序；成员解析为轻量行供列表/图谱入口）。"""
    from ..store import LogicViewsStore
    pid = project_id_for(root, project)
    if not pid:
        return ok({"views": []})
    return ok({"views": LogicViewsStore.list(pid)})


@router.post("/kb/semantic/logic-views")
async def api_logic_views_create(request: Request = None):
    """手动新建：{name, coreIds, memberIds?, root?, project?}——成员初始=核心，分析后拓展。"""
    from ..store import LogicViewsStore
    body = await request.json() if request else {}
    pid = project_id_for(body.get("root"), body.get("project"))
    if not pid:
        return err(400, "缺少项目")
    name = (body.get("name") or "").strip()
    core_ids = body.get("coreIds") or []
    if not name:
        return err(400, "缺少视图名称")
    if not core_ids:
        return err(400, "缺少核心实现资产")
    view = LogicViewsStore.create(pid, name, core_ids, body.get("memberIds") or None,
                                  source="manual")
    return ok(view)


@router.put("/kb/semantic/logic-views/{view_id}")
async def api_logic_views_update(view_id: str, request: Request = None):
    """改名/成员编辑：{name?, coreIds?, memberIds?}。"""
    from ..store import LogicViewsStore
    body = await request.json() if request else {}
    from ..store.logic_views import fingerprint_of
    view = LogicViewsStore.get(view_id)
    if not view:
        return err(404, "视图不存在")
    import json as _json
    data: dict = {}
    if body.get("name") is not None:
        data["name"] = str(body["name"]).strip()[:80]
    if body.get("coreIds") is not None:
        data["coreIds"] = _json.dumps(body["coreIds"] or [], ensure_ascii=False)
    if body.get("memberIds") is not None:
        data["memberIds"] = _json.dumps(body["memberIds"] or [], ensure_ascii=False)
    if "name" in data or "memberIds" in data:
        members = body.get("memberIds") if body.get("memberIds") is not None \
            else _json.loads(view.get("memberIds") or "[]")
        name = data.get("name") or view.get("name") or ""
        data["fingerprint"] = fingerprint_of(name, members)
    return ok(LogicViewsStore.update(view_id, data))


@router.delete("/kb/semantic/logic-views/{view_id}")
async def api_logic_views_delete(view_id: str):
    from ..store import LogicViewsStore
    if not LogicViewsStore.delete(view_id):
        return err(404, "视图不存在")
    return ok({"deleted": view_id})


@router.post("/kb/semantic/logic-views/{view_id}/analyze")
async def api_logic_views_analyze(view_id: str, request: Request = None):
    """分析作业提交：{expand?: 'core'|'1'|'2'|'all'(默认), modelId?, root?, project?}。

    核心(种子)实现资产沿调用依赖边拓展为成员全集 + LLM 概括；不拓展=仅重新概括。
    """
    from ..sem import job_runner
    from ..sem.paths import resolve_root
    from ..store import LogicViewsStore
    body = await request.json() if request else {}
    view = LogicViewsStore.get(view_id)
    if not view:
        return err(404, "视图不存在")
    rid = (resolve_root(body.get("root") or "", body.get("project")) or "").strip()
    if not rid:
        return err(400, "项目 root 解析失败")
    from ..sem.paths import project_id_for
    r = job_runner.start_job(
        project_id_for(rid, body.get("project")), "analyze_logic",
        scope={"viewId": view_id, "expand": body.get("expand") or "all",
               "root": rid, "project": body.get("project"),
               "modelId": body.get("modelId") or None},
        llm=True)
    return ok(r)


@router.post("/kb/semantic/logic-views/{view_id}/explain")
async def api_logic_views_explain(view_id: str, request: Request = None):
    """AI 详细语义讲解(B3 统一入任务中心：提交 explain_logic 作业并等待完成)。

    Body: {force?, modelId?, root?, project?}。缓存命中(指纹一致)作业内秒回；
    成员资产变化 → 指纹失效自动重生成；force 强制。排队/运行任务中心可见。
    """
    body = await request.json() if request else {}
    from ..sem.engine import wait_llm_job
    return await wait_llm_job("explain_logic", {
        "viewId": view_id, "force": bool(body.get("force")),
        "modelId": body.get("modelId") or "",
        "root": body.get("root"), "project": body.get("project")},
        body.get("root"), body.get("project"))


@router.post("/kb/semantic/logic-views/graph-outline")
async def api_logic_graph_outline(request: Request = None):
    """图谱范围提纲(零 LLM 秒回)：核心(选中优先+中心度 top≤8) × 1/2/3 跳邻域。

    Body: {assetIds(显示范围), preferCores?(选中节点置顶), root?, project?}。
    """
    import asyncio as _aio
    body = await request.json() if request else {}
    from ..store import SemanticAssetsStore
    from ..sem.logic_extract import graph_outline
    ids = list(dict.fromkeys([i for i in (body.get("assetIds") or []) if i]))
    if not ids:
        return ok({"cores": []})

    def _run():
        rows = [SemanticAssetsStore.get(i) for i in ids]
        assets = [r for r in rows if r and r.get("status") == "active"]
        return graph_outline(assets, body.get("preferCores") or [])
    return ok({"cores": await _aio.to_thread(_run)})


@router.post("/kb/semantic/logic-views/induce-scope")
async def api_logic_induce_scope(request: Request = None):
    """图谱范围逻辑解析(B3 统一排队)：提交 induce_scope 作业并等待完成。

    Body: {groups: [{coreId, hops, memberIds}], root?, project?, modelId?}。
    """
    body = await request.json() if request else {}
    from ..sem.engine import wait_llm_job
    groups = body.get("groups") or []
    if not groups:
        return err(400, "缺少解析分组")
    for g in groups:
        if not (g.get("memberIds") or []):
            return err(400, "分组缺少成员")
    return await wait_llm_job("induce_scope", {
        "groups": groups, "root": body.get("root"), "project": body.get("project"),
        "modelId": body.get("modelId") or ""},
        body.get("root"), body.get("project"), timeout_s=600)
