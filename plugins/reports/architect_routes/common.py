"""Shared helpers for architect API routes."""
from datetime import datetime, timezone
from fastapi.responses import JSONResponse


def _ts() -> int:
    return int(datetime.now(timezone.utc).timestamp() * 1000)


def _id(prefix: str) -> str:
    return f"{prefix}-{_ts()}"


def ok(data=None):
    return {"code": 0, "message": "ok", "data": data}


def err(code: int, msg: str):
    return JSONResponse(status_code=400, content={"code": code, "message": msg, "data": None})


def build_architecture_model():
    return {
        "components": [
            {"id": "c-order", "name": "订单服务", "kind": "service", "desc": "订单生命周期管理", "lang": "Go", "change": "modified", "responsibilities": ["订单创建", "状态流转"], "owns": ["Order"], "dependsOn": ["c-inventory", "c-payment"]},
            {"id": "c-inventory", "name": "库存服务", "kind": "service", "desc": "库存预扣与释放", "lang": "Go", "change": "same", "responsibilities": ["库存预扣", "超时释放"], "owns": ["Inventory"], "dependsOn": []},
            {"id": "c-payment", "name": "支付服务", "kind": "service", "desc": "支付处理", "lang": "Go", "change": "same", "responsibilities": ["支付请求", "回调处理"], "owns": ["Payment"], "dependsOn": []},
            {"id": "c-outbox", "name": "Outbox 服务", "kind": "infra", "desc": "可靠事件投递", "lang": "Go", "change": "added", "responsibilities": ["事件持久化", "消息投递"], "owns": ["Outbox"], "dependsOn": []},
            {"id": "c-gateway", "name": "API 网关", "kind": "gateway", "desc": "统一入口", "lang": "Go", "change": "same", "responsibilities": ["路由", "鉴权"], "owns": [], "dependsOn": ["c-order"]},
        ],
        "erTables": [],
        "ormMappings": [],
        "entityClasses": [],
        "executionFlows": [],
        "dataFlows": [],
    }

