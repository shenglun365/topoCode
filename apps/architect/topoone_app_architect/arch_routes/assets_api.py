"""W6 资产 REST（2610-B1）——arch_assets 表面（D-1 表为真相源）。

管理面先行（C1 先例：REST 先行 UI 后置）；kind=skill 的 payload 校验
route_hint 非空（路由协议要求）。LLM 侧消费走 prompt skill_catalog 块。
"""
from fastapi import APIRouter, Request

from ..common import err, ok

router = APIRouter()


@router.get("/arch/assets")
async def list_assets(kind: str = "", project: str = ""):
    from .. import store
    return ok(store.ArchAssetsStore.all(kind=kind or "",
                                        project_id=project or ""))


@router.post("/arch/assets")
async def upsert_asset(request: Request):
    try:
        body = await request.json() or {}
    except Exception:  # noqa: BLE001
        return err(400, "invalid json")
    kind = str(body.get("kind") or "skill")
    if kind == "skill" and not str((body.get("payload") or {})
                                   .get("route_hint") or "").strip():
        return err(400, "skill 资产 payload.route_hint 必填(路由协议)")
    try:
        from .. import store
        return ok(store.ArchAssetsStore.upsert(body))
    except ValueError as e:
        return err(400, str(e))


@router.delete("/arch/assets/{asset_id}")
async def delete_asset(asset_id: str):
    from .. import store
    return ok({"deleted": store.ArchAssetsStore.delete(asset_id)})
