"""需求跟踪台账 routes —— 会话中心左栏「需求跟踪」读侧面 + 手动挂账/流转 + 字典。

台账写入除手动 POST 外, 由事件点自动挂账(store/tracking.py emit/sync_task):
任务生命周期/回执沉淀/需求落库/决策卡/错误提炼。
"""
from __future__ import annotations

import fastapi
from fastapi import APIRouter, Request

from .common import ok, err
from . import store
from .store import states as ST
from .store import tracking as TR

router = APIRouter()

# PATCH 可变字段白名单(其余忽略; state/waitingFor/result 是人工流转面)
_PATCH_FIELDS = ("category", "title", "content", "actionType",
                 "assigneeRole", "assigneeId", "state", "waitingFor",
                 "result", "resultState")


@router.get("/tracking/items")
async def list_items(scope: str = "", category: str = "", state: str = "",
                     assignee: str = "", q: str = "",
                     limit: int = fastapi.Query(200, alias="limit")):
    """跟踪条目清单。?scope=all 跨全库(主库+各项目库)汇总——会话中心统一视图。

    每条携带 mainConversationId + conversationId(主/子会话双 ID)与
    conversationId→会话标题由前端按会话列表映射。
    """
    cap = max(1, min(limit, 500))
    if scope == "all":
        rows = TR.TrackingItemsStore.all_across(
            category=category or "", state=state or "",
            assignee_role=assignee or "", q=q.strip() or "", limit=cap)
    else:
        rows = TR.TrackingItemsStore.all(
            category=category or "", state=state or "",
            assignee_role=assignee or "", q=q.strip() or "", limit=cap)
    return ok({"items": rows})


@router.post("/tracking/items")
async def create_item(request: Request):
    """手动挂账(面板/对话补挂): 创建者恒记 user, 其余字段按表单。"""
    data = await request.json()
    title = str(data.get("title") or "").strip()
    if not title:
        return err(400, "title 必填")
    row = TR.TrackingItemsStore.create({
        "category": str(data.get("category") or "").strip(),
        "title": title[:200],
        "content": str(data.get("content") or "")[:8000],
        "actionType": str(data.get("actionType") or "").strip(),
        "creatorRole": "user",
        "assigneeRole": str(data.get("assigneeRole") or "").strip(),
        "assigneeId": str(data.get("assigneeId") or "").strip(),
        "state": str(data.get("state") or ST.TRACK_WAITING),
        "waitingFor": str(data.get("waitingFor") or "").strip(),
        "conversationId": str(data.get("conversationId") or "").strip(),
        "projectId": str(data.get("projectId") or "").strip(),
    })
    return ok(row)


@router.patch("/tracking/items/{item_id}")
async def patch_item(item_id: str, request: Request):
    """条目流转/修正: 状态(含终态回填 result/resultState)、有效性(valid)、
    分类/操作类型改挂、待办指派调整。"""
    data = await request.json()
    patch: dict = {k: data[k] for k in _PATCH_FIELDS if k in data}
    if "valid" in data:
        patch["valid"] = bool(data["valid"])
    if not patch:
        return err(400, "无可变字段")
    row = TR.TrackingItemsStore.update(item_id, patch)
    if not row:
        return err(404, "条目不存在")
    return ok(row)


@router.delete("/tracking/items/{item_id}")
async def delete_item(item_id: str):
    """单条删除(误挂/过期条目清理; 会话删除走级联 delete_by_conversation)。"""
    if not TR.TrackingItemsStore.delete(item_id):
        return err(404, "条目不存在")
    return ok({"deleted": True, "id": item_id})


@router.get("/tracking/vocab")
async def get_vocab():
    """字典: 分类/操作类型(可配置) + 角色词汇(结构常量)。"""
    return ok({
        "categories": TR.vocab_categories(),
        "actionTypes": TR.vocab_action_types(),
        "roles": list(ST.TRACK_ROLES),
        "states": [ST.TRACK_RUNNING, ST.TRACK_WAITING, ST.TRACK_DONE,
                   ST.TRACK_FAILED, ST.TRACK_CANCELLED],
    })


@router.put("/tracking/vocab")
async def put_vocab(request: Request):
    """写字典(传 null 的域不动; 空数组拒绝——防止清空后 UI 无项可选)。"""
    data = await request.json()
    cats = data.get("categories")
    acts = data.get("actionTypes")
    for name, vals in (("categories", cats), ("actionTypes", acts)):
        if vals is not None and not (isinstance(vals, list) and [v for v in vals if str(v).strip()]):
            return err(400, f"{name} 不能为空")
    TR.vocab_save(categories=cats, action_types=acts)
    return ok({
        "categories": TR.vocab_categories(),
        "actionTypes": TR.vocab_action_types(),
    })
