"""runner 反代(2610 执行器会话拓展 A3)——远程流量的同源入口。

远程浏览器/客户端访问执行器会话数据一律经 architect 本入口(口令保护);
目标钳制为 RUNNER_BASE_URL 的 /api/implement/**(SSRF 防护: 路径白名单,
不透传任意目标)。会话浏览器/交互 FE 走 architect 自有 REST(B2), 本面供
管理/调试与未来直连场景。
"""
from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()

logger = logging.getLogger("arch_routes.runner_proxy")

_ALLOWED_PREFIX = "/api/implement/"


def _runner_base() -> str:
    import os
    return os.environ.get("RUNNER_BASE_URL",
                          "http://127.0.0.1:3458").rstrip("/")


@router.api_route("/arch/runner-proxy/{path:path}",
                  methods=["GET", "POST"])
async def runner_proxy(path: str, request: Request):
    """受限反代: → RUNNER_BASE_URL/api/implement/<path>。"""
    sub = "/" + (path or "").lstrip("/")
    if not sub.startswith(_ALLOWED_PREFIX):
        return JSONResponse(status_code=400, content={
            "code": 400, "message": f"仅允许 {_ALLOWED_PREFIX}* 路径",
            "data": None})
    url = _runner_base() + sub
    body = await request.body()
    headers = {"content-type": request.headers.get("content-type",
                                                   "application/json")}
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.request(
                request.method, url, content=body, headers=headers)
        return JSONResponse(status_code=resp.status_code,
                            content=resp.json() if resp.content else None)
    except httpx.HTTPError as e:
        logger.warning("[runner-proxy] %s %s 失败: %s", request.method, sub, e)
        return JSONResponse(status_code=502, content={
            "code": 502, "message": f"runner 不可达: {e}", "data": None})
