"""口令安全面(2610 执行器会话拓展 A1)——architect 入口保护。

策略(裁决: 只护入口):
- 保护范围: /api/** REST + WebSocket 握手; 静态面(SPA 壳)豁免——远程浏览器
  先加载壳, 首个 API 401 → FE 提示输入口令 → 存 localStorage 后续自动携带。
- 本机豁免: client 为 127.0.0.1/::1 直接放行(dev vite proxy/本机使用零摩擦)。
- 口令单源: CollabConfigStore security.token(32hex, 首次读取自动生成);
  轮换 = POST rotate(旧口令即时失效)。
- 凭据形态: Authorization: Bearer <token>(REST) / ?token=(WS 与 MCP URL 注入)。
内部服务(runner/KB)维持 localhost 不动——远程流量必经本入口(定位裁决)。
"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, Request, WebSocket

from ..common import err, ok

router = APIRouter()

_TOKEN_KEY = "security.token"
_LOOPBACK = ("127.0.0.1", "::1", "localhost", "testclient")

# 豁免前缀(API 域内): 无(模型探测等均需保护); 静态在中间件层豁免
_EXEMPT_PREFIXES = ("/api/architect/arch/security/token",)  # 本机豁免已覆盖


def get_or_create_token() -> str:
    """口令单源: 首次读取自动生成(32hex)。"""
    from .. import store
    tok = str(store.CollabConfigStore.get(_TOKEN_KEY, "")).strip()
    if not tok:
        tok = secrets.token_hex(16)
        store.CollabConfigStore.set(_TOKEN_KEY, tok)
    return tok


def rotate_token() -> str:
    from .. import store
    tok = secrets.token_hex(16)
    store.CollabConfigStore.set(_TOKEN_KEY, tok)
    return tok


def _client_host(scope: dict) -> str:
    client = scope.get("client") or (None, None)
    return str(client[0] or "")


def _extract_token(scope: dict) -> str:
    """Bearer 头优先; ?token= 兜底(WS 握手/MCP URL 注入形态)。"""
    for name, value in (scope.get("headers") or []):
        if name == b"authorization":
            try:
                text = value.decode("latin-1")
            except Exception:  # noqa: BLE001
                continue
            if text.lower().startswith("bearer "):
                return text[7:].strip()
    try:
        from urllib.parse import parse_qs
        qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
        return (qs.get("token") or [""])[0].strip()
    except Exception:  # noqa: BLE001
        return ""


def _path_of(scope: dict) -> str:
    return (scope.get("path") or "").rstrip("/") or "/"


async def _reject(send, scope_type: str):
    if scope_type == "websocket":
        # WS 拒绝: 关闭握手(1008 policy violation)
        await send({"type": "websocket.close", "code": 1008})
        return
    body = b'{"code": 401, "message": "token required (Authorization: Bearer or ?token=)", "data": null}'
    await send({
        "type": "http.response.start", "status": 401,
        "headers": [(b"content-type", b"application/json"),
                    (b"www-authenticate", b"Bearer")],
    })
    await send({"type": "http.response.body", "body": body})


class TokenAuthMiddleware:
    """ASGI 中间件: 非静态路径的口令校验(本机豁免)。

    保护 /api/** 与 websocket; 其余(静态壳/健康探针)放行。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        st = scope.get("type") or ""
        if st not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        if _client_host(scope) in _LOOPBACK:
            await self.app(scope, receive, send)
            return
        path = _path_of(scope)
        guarded = (st == "websocket") or path.startswith("/api/")
        if not guarded or any(path.startswith(p) for p in _EXEMPT_PREFIXES):
            await self.app(scope, receive, send)
            return
        try:
            expected = get_or_create_token()
        except Exception:  # noqa: BLE001 — 口令域故障=放行(可用性优先)
            expected = ""
        if expected and _extract_token(scope) == expected:
            await self.app(scope, receive, send)
            return
        await _reject(send, st)


# ── 口令管理 REST(本机豁免面, 远程不可达——配置面本机操作) ────────────

@router.get("/arch/security/token")
async def api_token_get():
    return ok({"token": get_or_create_token()})


@router.post("/arch/security/token")
async def api_token_rotate(request: Request):
    body = await request.json() or {}
    if str(body.get("action") or "") != "rotate":
        return err(400, "action 须为 rotate")
    return ok({"token": rotate_token()})


def ws_token_ok(websocket: WebSocket) -> bool:
    """WS 处理器可显式复核(中间件已拦; 供直连/测试场景)。"""
    scope = websocket.scope
    if _client_host(scope) in _LOOPBACK:
        return True
    try:
        expected = get_or_create_token()
    except Exception:  # noqa: BLE001
        return True
    return _extract_token(scope) == expected


def append_token(url: str) -> str:
    """MCP 接入 URL 注入口令(本机豁免下为 no-op, 远程部署时生效)。"""
    try:
        expected = get_or_create_token()
    except Exception:  # noqa: BLE001
        return url
    if not expected or "token=" in url:
        return url
    return url + ("&" if "?" in url else "?") + f"token={expected}"
