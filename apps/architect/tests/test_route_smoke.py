"""HTTP 层路由冒烟测试（兜住"拆分后签名失真"类回归）。

背景：sem/engine.py T2 拆分曾漏 `from fastapi import Request`，
__future__ annotations 下注解变字符串，FastAPI 把 `request` 当查询参数
→ 所有 POST 端点 422（Python 直调测试全绿仍漏）。本文件从 HTTP 层兜底：
  1. 任何路由的 dependant.query_params 不得含名为 request 的参数；
  2. POST /kb/semantic/* 端点空请求体必须非 422（签名失真即 422）；
  3. 关键静态路由先于动态 {asset_id}（参数感知序抽查）。
状态码断言只排除 422/404 —— 400/500 表示路由已正确命中（业务层失败可接受）。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from topoone_app_architect.arch_routes import router as arch_router


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(arch_router)
    return TestClient(app, raise_server_exceptions=False)


def test_no_request_query_param_anywhere():
    """bug 类兜底：request 被当查询参数 = 签名失真（如漏 import Request）。"""
    bad = []
    for r in arch_router.routes:
        dep = getattr(r, "dependant", None)
        if dep is None:
            continue
        for q in dep.query_params:
            if q.name == "request":
                bad.append(f"{getattr(r, 'methods', '')} {r.path}")
    assert not bad, f"以下端点把 request 当查询参数(签名失真): {bad}"


def test_kb_semantic_post_endpoints_not_422():
    client = _client()
    bad = []
    for r in arch_router.routes:
        if not hasattr(r, "methods") or "POST" not in (r.methods or set()):
            continue
        if not r.path.startswith("/api/architect/kb/semantic/"):
            continue
        resp = client.post(r.path, json={})
        if resp.status_code == 422:
            bad.append(f"{r.path} → 422 {resp.json()}")
    assert not bad, f"POST 端点签名失真(422): {bad}"


def test_static_routes_before_dynamic_asset_id():
    client = _client()
    # 静态查询路由必须命中真实 handler（而非 {asset_id} 动态路由）
    for path in ("/api/architect/kb/semantic/search?q=",
                 "/api/architect/kb/semantic/status",
                 "/api/architect/kb/semantic/graph",
                 "/api/architect/kb/semantic/mappings",
                 "/api/architect/kb/semantic/codegraph"):
        resp = client.get(path)
        assert resp.status_code != 404, f"{path} 未注册"
        body = resp.json()
        # 被 {asset_id} 吞掉时返回 "语义资产 xxx 不存在" 的 404 语义
        assert not (isinstance(body, dict) and "不存在" in str(body.get("message", ""))), \
            f"{path} 被 /kb/semantic/{{asset_id}} 遮蔽: {body}"
