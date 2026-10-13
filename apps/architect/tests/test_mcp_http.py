"""MCP HTTP 面(2610 F1): /mcp 精确可达回归——挂载双前缀修复锁。

历史缺陷: app.mount("/mcp", sub_app) 剥前缀, FastMCP 内部裸 Route /mcp
落到 /mcp/mcp; 客户端 POST /mcp → 307 → /mcp/ → 404, 直通执行器
「topo-architect: 注入失败(Error POSTing to endpoint: Not Found)」。
修复: 子应用路由提升进顶层(server.py), 端点 /mcp 精确匹配。
"""
from __future__ import annotations


def _client(tmp_path, monkeypatch):
    from tests.conftest import isolate_arch
    data = isolate_arch(tmp_path, monkeypatch)
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    # with 触发 lifespan(MCP streamable 会话任务组初始化);
    # base_url 用回环(Host 校验拒 testserver 仿冒域——SDK rebinding 防护)
    return TestClient(build_app(data_dir=data), base_url="http://127.0.0.1")


# SDK 对 localhost 绑定自动启用 DNS rebinding 防护: Host 须带端口(127.0.0.1:*)
# (真实客户端恒带 host:port, TestClient 缺省无端口 → 显式补)
_H = {"Accept": "application/json, text/event-stream",
      "Host": "127.0.0.1:8001"}

_INIT = {"jsonrpc": "2.0", "method": "initialize", "id": 1,
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "t", "version": "1"}}}


def test_mcp_endpoint_reachable_at_root_path(tmp_path, monkeypatch):
    """POST /mcp initialize 直达(修复前 307→404)。"""
    client = _client(tmp_path, monkeypatch)
    with client:
        r = client.post("/mcp", json=_INIT, headers=_H)
        assert r.status_code == 200, r.text[:200]
        body = r.text
        assert "topo-architect" in body, body[:200]


def test_mcp_endpoint_no_double_prefix_needed(tmp_path, monkeypatch):
    """/mcp/mcp 双前缀形态退役(内部实现细节不再外泄)。"""
    client = _client(tmp_path, monkeypatch)
    with client:
        r = client.post("/mcp/mcp", json=_INIT, headers=_H)
        assert r.status_code == 404, "双前缀端点应已不存在"


def test_mcp_tool_listing(tmp_path, monkeypatch):
    """initialize 后 tools/list 可见 ctx.* 与 map.*(执行器可调用面)。"""
    client = _client(tmp_path, monkeypatch)
    with client:
        r = client.post("/mcp", json=_INIT, headers=_H)
        assert r.status_code == 200
        sid = r.headers.get("mcp-session-id") or ""
        r2 = client.post("/mcp", headers={**_H, "mcp-session-id": sid},
                         json={"jsonrpc": "2.0", "method": "tools/list", "id": 2})
        assert r2.status_code == 200
        body = r2.text
        for tool in ("ctx.search", "ctx.get", "map.overview", "task.mandate",
                 "map.core"):
            assert tool in body, f"缺工具 {tool}: {body[:300]}"


def test_req_audit_log_layer(arch_env, tmp_path, monkeypatch, caplog):
    """2610 cv-15 轮询评估面: [req] 全量请求行(方法 路径?query 状态 耗时)。"""
    import logging as _logging
    client = _client(tmp_path, monkeypatch)
    with client:
        with caplog.at_level(_logging.INFO, logger="arch.req"):
            client.get("/api/architect/sessions?limit=5",
                       headers={"Host": "127.0.0.1:8001"})
    assert any("[req] GET /api/architect/sessions?limit=5" in r.message
               for r in caplog.records), \
        [r.message for r in caplog.records if "req" in r.message][:3]
