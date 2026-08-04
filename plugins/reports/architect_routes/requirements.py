"""Requirements CRUD + status machine routes."""
from fastapi import APIRouter, Request
from .common import _ts, _id, ok, err

router = APIRouter()

REQUIREMENTS = [
    {"id": "RQ-1", "kind": "user-story", "tier": "raw", "title": "用户下单全链路", "priority": "P0", "status": "raw", "desc": "用户浏览商品后可提交订单，系统校验商品可售性、创建待支付订单，支持支付与库存扣减，直至最终完成。", "acceptance": ["端到端下单链路可用"], "traceTo": ["order-service", "inventory-service", "payment-service"], "updatedAt": _ts() - 86400000 * 6, "location": "proposal"},
    {"id": "RQ-2", "kind": "fr", "tier": "raw", "title": "可靠事件投递", "priority": "P1", "status": "raw", "desc": "订单领域事件需要可靠投递到消息中间件，保证不丢不重。", "acceptance": ["事件不丢不重"], "traceTo": ["order-service", "outbox-service"], "updatedAt": _ts() - 86400000 * 5, "location": "proposal"},
    {"id": "RQ-3", "kind": "nfr", "tier": "raw", "title": "可观测性", "priority": "P2", "status": "raw", "desc": "核心链路输出 trace 与业务指标，支撑排障与容量评估。", "acceptance": ["关键链路可观测"], "traceTo": ["order-service"], "updatedAt": _ts() - 86400000 * 5, "location": "proposal"},
]


@router.get("/requirements")
async def list_requirements():
    return ok(REQUIREMENTS)


@router.post("/requirements")
async def create_requirement(request: Request):
    body = await request.json()
    req = {
        "id": _id("RQ"), "kind": body.get("kind", "user-story"), "tier": "raw",
        "location": "proposal", "title": body.get("title", ""),
        "priority": body.get("priority", "P2"), "status": "raw",
        "desc": body.get("desc", ""), "acceptance": body.get("acceptance", []),
        "traceTo": body.get("traceTo", []), "updatedAt": _ts(),
    }
    REQUIREMENTS.append(req)
    return ok(req)


@router.patch("/requirements/{req_id}")
async def patch_requirement(req_id: str, request: Request):
    body = await request.json()
    for r in REQUIREMENTS:
        if r["id"] == req_id:
            r.update(body)
            r["updatedAt"] = _ts()
            return ok(r)
    return err(404, "Requirement not found")


@router.post("/requirements/{req_id}/cancel")
async def cancel_requirement(req_id: str):
    for r in REQUIREMENTS:
        if r["id"] == req_id:
            r["status"] = "cancelled" if r["status"] != "cancelled" else "raw"
            r["updatedAt"] = _ts()
            return ok(r)
    return err(404, "Not found")


@router.post("/requirements/{req_id}/finalize")
async def finalize_requirement(req_id: str, request: Request):
    body = await request.json()
    for r in REQUIREMENTS:
        if r["id"] == req_id:
            r["tier"] = "analyzed"
            r["location"] = "pool"
            r["status"] = "analyzed"
            r["analysis"] = body.get("analysis", {})
            r["updatedAt"] = _ts()
            return ok(r)
    return err(404, "Not found")


@router.post("/requirements/{req_id}/direct")
async def direct_requirement(req_id: str, request: Request):
    body = await request.json()
    for r in REQUIREMENTS:
        if r["id"] == req_id:
            r["location"] = "pool"
            r["status"] = "analyzed"
            r["routedBy"] = "direct"
            r["suggestion"] = body.get("suggestion")
            r["updatedAt"] = _ts()
            return ok(r)
    return err(404, "Not found")


@router.post("/requirements/{req_id}/location")
async def move_requirement_location(req_id: str, request: Request):
    body = await request.json()
    for r in REQUIREMENTS:
        if r["id"] == req_id:
            r["location"] = body.get("location", r["location"])
            r["updatedAt"] = _ts()
            return ok(r)
    return err(404, "Not found")


@router.post("/requirements/merge")
async def merge_requirements(request: Request):
    return ok({"merged": True})
