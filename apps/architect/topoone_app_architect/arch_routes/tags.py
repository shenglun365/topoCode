"""Tags domain routes (sqlite-backed).

类型标签分类法(自定义部分)：类别 group + 标签 tag，支持下线(软删除)。
后端优先承载前端 tag-store 的持久化；内置分类法由前端 + i18n 提供。
"""
from fastapi import APIRouter, Request
from .common import _ts, ok, err
from . import store

router = APIRouter()


def _tag_api(row: dict) -> dict:
    """offline int → bool(前端契约)。"""
    if row:
        row["offline"] = bool(row.get("offline"))
    return row


@router.get("/tags")
async def list_tags():
    return ok([_tag_api(r) for r in store.TagsStore.all()])


@router.get("/tags/{tag_id}")
async def get_tag(tag_id: str):
    row = store.TagsStore.get(tag_id)
    if not row:
        return err(404, "Tag not found")
    return ok(_tag_api(row))


@router.post("/tags")
async def create_tag(request: Request):
    body = await request.json()
    tag = {
        "id": store.next_id("tag"),
        "groupKey": body.get("groupKey", ""),
        "label": body.get("label", ""),
        "color": body.get("color", ""),
        "scope": body.get("scope", "custom"),
        "offline": False,
        "createdAt": _ts(),
        "updatedAt": _ts(),
    }
    if not tag["label"].strip():
        return err(400, "label is required")
    store.TagsStore.create(tag)
    return ok(_tag_api(store.TagsStore.get(tag["id"])))


@router.patch("/tags/{tag_id}")
async def patch_tag(tag_id: str, request: Request):
    body = await request.json()
    row = store.TagsStore.update(tag_id, {**body, "updatedAt": _ts()})
    if not row:
        return err(404, "Tag not found")
    return ok(_tag_api(row))


@router.post("/tags/{tag_id}/offline")
async def offline_tag(tag_id: str):
    row = store.TagsStore.update(tag_id, {"offline": True, "updatedAt": _ts()})
    if not row:
        return err(404, "Tag not found")
    return ok(_tag_api(row))