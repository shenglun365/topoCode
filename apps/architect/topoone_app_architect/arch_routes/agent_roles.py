"""tAgent 角色注册表 REST 适配层(实现迁至 agent.cognition.roles, P1)。

GET/PUT /agent/roles；函数名经 re-export 保持存量引用可用。
"""
from typing import Any, List

from fastapi import APIRouter, Request

from .common import err, ok
from ..agent.cognition.roles import (  # noqa: F401
    DEFAULT_ROLES,
    get_roles,
    resolve_role_model,
    role_model_id,
    scenario_role,
    set_roles,
)

router = APIRouter()


@router.get("/agent/roles")
async def api_roles_get():
    return ok({"roles": get_roles()})


@router.put("/agent/roles")
async def api_roles_put(request: Request):
    body = await request.json()
    roles = body.get("roles") if isinstance(body, dict) else None
    if roles is None or not isinstance(roles, list):
        return err(400, "roles 必须是数组")
    return ok({"roles": set_roles(roles)})
