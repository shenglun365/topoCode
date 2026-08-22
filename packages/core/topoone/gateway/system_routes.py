"""Gateway 系统管理路由（P1）：supervisor 控制面代理。

- GET  /api/system/apps              → supervisor GET /apps（全部受管进程状态）
- POST /api/system/apps/{name}/restart → supervisor POST /restart/{name}（人工重启）

经 env `SUPERVISOR_ADMIN_URL` 转发到 supervisor localhost 管理端点
（仅绑定 127.0.0.1，由 `topo serve` 注入）；未配置时返回 503（如独立开发模式）。
鉴权：网关主 token（D7，auth_middleware 已校验 /api/*），转发时透传同一 token——
管理员即全权，与现有 /api 行为一致；管理端点本身仅监听 localhost。
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter()

_ADMIN_URL = os.environ.get("SUPERVISOR_ADMIN_URL", "")


def _admin_token() -> str | None:
    from topoone.gateway.gateway import _read_token
    return _read_token()


async def _proxy_admin(method: str, path: str) -> Response:
    if not _ADMIN_URL:
        return JSONResponse({"detail": "supervisor admin endpoint not available"},
                            status_code=503)
    import httpx
    token = _admin_token()
    headers = {"authorization": f"Bearer {token}"} if token else {}
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.request(method, _ADMIN_URL + path, headers=headers)
    except Exception as e:
        logger.warning(f"[gateway] supervisor admin {path} failed: {e}")
        return JSONResponse({"detail": f"supervisor admin unreachable: {e}"},
                            status_code=502)
    return Response(content=resp.content, status_code=resp.status_code,
                    media_type="application/json")


@router.get("/api/system/apps", include_in_schema=False)
async def system_apps():
    """返回全部受管进程状态（label/status/pid/restart_count/alive）。"""
    return await _proxy_admin("GET", "/apps")


@router.post("/api/system/apps/{name}/restart", include_in_schema=False)
async def system_restart(name: str):
    """人工重启指定进程（重置崩溃预算 restart_count）。"""
    return await _proxy_admin("POST", f"/restart/{name}")
