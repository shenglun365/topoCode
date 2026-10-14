"""口令安全面(2610 A1/A3)——中间件校验/豁免/轮换/反代钳制。

中间件用合成 scope 直测(不经 TestClient 的 testclient 伪主机)。
"""
from __future__ import annotations

import asyncio

import pytest

from topoone_app_architect.arch_routes import security
from topoone_app_architect.arch_routes.security import (
    TokenAuthMiddleware, append_token, get_or_create_token, rotate_token)


def _scope(path="/api/architect/arch/assets", stype="http",
           host="10.1.2.3", headers=(), query=b""):
    return {"type": stype, "path": path,
            "headers": list(headers), "query_string": query,
            "client": (host, 51234)}


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"{}"})


def _run(mid, scope):
    sent = []

    async def send(msg):
        sent.append(msg)

    async def receive():
        return {}

    asyncio.run(mid(scope, receive, send))
    return sent


def test_remote_no_token_rejected(arch_env):
    sent = _run(TokenAuthMiddleware(_ok_app), _scope())
    assert sent and sent[0]["status"] == 401


def test_remote_bearer_ok_and_query_ok(arch_env):
    tok = get_or_create_token()
    mid = TokenAuthMiddleware(_ok_app)
    sent = _run(mid, _scope(headers=[(b"authorization",
                                      f"Bearer {tok}".encode())]))
    assert sent[0]["status"] == 200
    sent2 = _run(mid, _scope(query=f"token={tok}".encode()))
    assert sent2[0]["status"] == 200


def test_loopback_and_static_exempt(arch_env):
    get_or_create_token()
    mid = TokenAuthMiddleware(_ok_app)
    assert _run(mid, _scope(host="127.0.0.1"))[0]["status"] == 200
    assert _run(mid, _scope(host="::1"))[0]["status"] == 200
    # 静态壳豁免(远程也能加载 SPA 再输口令)
    assert _run(mid, _scope(path="/architect.html"))[0]["status"] == 200


def test_websocket_rejected_without_token(arch_env):
    get_or_create_token()
    sent = _run(TokenAuthMiddleware(_ok_app),
                _scope(stype="websocket", path="/ws/kb-analysis"))
    assert sent and sent[0]["type"] == "websocket.close"


def test_rotate_invalidates_old(arch_env):
    old = get_or_create_token()
    new = rotate_token()
    assert new and new != old
    mid = TokenAuthMiddleware(_ok_app)
    assert _run(mid, _scope(headers=[(b"authorization",
                                      f"Bearer {old}".encode())]))[0]["status"] == 401
    assert _run(mid, _scope(headers=[(b"authorization",
                                      f"Bearer {new}".encode())]))[0]["status"] == 200


def test_append_token(arch_env):
    tok = get_or_create_token()
    assert append_token("http://127.0.0.1:3470/mcp/mcp") == \
        f"http://127.0.0.1:3470/mcp/mcp?token={tok}"
    assert append_token(f"http://x/y?token={tok}") == f"http://x/y?token={tok}"


# ── runner 反代(A3) ─────────────────────────────────────────────────

def test_runner_proxy_path_clamp(arch_env, monkeypatch):
    import httpx
    from topoone_app_architect.arch_routes import runner_proxy as rp
    called = {}

    class _FakeResp:
        status_code = 200
        content = b'{"code":0}'

        def json(self):
            return {"code": 0}

    class _FakeClient:
        def __init__(self, timeout=None):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kw):
            called["url"] = url
            return _FakeResp()

    monkeypatch.setattr(rp.httpx, "AsyncClient", _FakeClient)

    class _Req:
        headers = {}
        method = "GET"

        async def body(self):
            return b""

    # 钳制: 非 implement 前缀 400
    bad = asyncio.run(rp.runner_proxy("../etc/passwd", _Req()))
    assert bad.status_code == 400
    # 合法前缀透传
    okr = asyncio.run(rp.runner_proxy("api/implement/running", _Req()))
    assert okr.status_code == 200
    assert called["url"].endswith("/api/implement/running")


def test_runner_proxy_unreachable_502(arch_env, monkeypatch):
    from topoone_app_architect.arch_routes import runner_proxy as rp
    monkeypatch.setenv("RUNNER_BASE_URL", "http://127.0.0.1:1")

    class _Req:
        headers = {}
        method = "GET"

        async def body(self):
            return b""

    r = asyncio.run(rp.runner_proxy("api/implement/x", _Req()))
    assert r.status_code == 502
