"""需求草稿 API（批B）：CRUD + 续写副本。

AI 处理(批D /{id}/ai)与发布(批F /{id}/publish)后续批次接入。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request

from ..common import err, ok
from .semantic_assets import project_id_for

router = APIRouter()


@router.get("/req-drafts")
async def api_req_drafts_list(root: Optional[str] = None, project: Optional[str] = None):
    """草稿列表（资产管理页右栏草稿列表数据源；updated_at 倒序）。"""
    from ..store import ReqDraftsStore
    pid = project_id_for(root, project)
    if not pid:
        return ok({"drafts": []})
    rows = ReqDraftsStore.list(pid)
    for r in rows:
        # 列表不携带正文全量（体积）；摘要取首行
        r["excerpt"] = (r.get("contentMd") or "").strip().splitlines()[0][:80] if r.get("contentMd") else ""
        r.pop("contentMd", None)
        r.pop("lastProposedMd", None)
    return ok({"drafts": rows})


@router.post("/req-drafts")
async def api_req_drafts_create(request: Request = None):
    """新建草稿：{title?, contentMd?, root?, project?}。"""
    from ..store import ReqDraftsStore
    body = await request.json() if request else {}
    pid = project_id_for(body.get("root"), body.get("project"))
    if not pid:
        return err(400, "缺少项目")
    draft = ReqDraftsStore.create(pid, body.get("title") or "", body.get("contentMd") or "")
    return ok(draft)


@router.get("/req-drafts/{draft_id}")
async def api_req_drafts_get(draft_id: str):
    from ..store import ReqDraftsStore
    draft = ReqDraftsStore.get(draft_id)
    if not draft:
        return err(404, "草稿不存在")
    return ok(draft)


@router.put("/req-drafts/{draft_id}")
async def api_req_drafts_update(draft_id: str, request: Request = None):
    """保存草稿：{title?, contentMd?}。归档态只读拒绝（续写走 copy）。"""
    from ..store import ReqDraftsStore
    body = await request.json() if request else {}
    draft = ReqDraftsStore.get(draft_id)
    if not draft:
        return err(404, "草稿不存在")
    if (draft.get("status") or "editing") == "archived":
        return err(409, "草稿已发布归档（只读）；如需修改请续写副本")
    data = {}
    if "title" in body:
        data["title"] = str(body.get("title") or "")
    if "contentMd" in body:
        data["contentMd"] = str(body.get("contentMd") or "")
    updated = ReqDraftsStore.update(draft_id, data)
    return ok(updated)


@router.delete("/req-drafts/{draft_id}")
async def api_req_drafts_delete(draft_id: str):
    from ..store import ReqDraftsStore
    if not ReqDraftsStore.delete(draft_id):
        return err(404, "草稿不存在")
    return ok({"deleted": draft_id})


@router.post("/req-drafts/{draft_id}/copy")
async def api_req_drafts_copy(draft_id: str, request: Request = None):
    """续写：复制草稿为新的 editing 副本（归档草稿继续编写的主路径）。"""
    from ..store import ReqDraftsStore
    body = await request.json() if request else {}
    copy = ReqDraftsStore.copy(draft_id, title_suffix=body.get("titleSuffix") or "")
    if not copy:
        return err(404, "草稿不存在")
    return ok(copy)
