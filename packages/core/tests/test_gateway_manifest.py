"""M06: gateway manifest 驱动路由表 — 合并 / 冲突 / 端口变更 / env 覆盖 / kind=core 归 kb。

聚焦 `topoone.gateway.gateway._load_registry`：由 `apps/*/manifest.toml` 生成
服务表、RPC 路由表、反代前缀、健康探测目标、事件桥端口。
"""

import textwrap

import pytest

from topoone.gateway import gateway as gw
from topoone.manifest import ManifestError


def _write(root, name: str, body: str):
    d = root / "apps" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "manifest.toml").write_text(textwrap.dedent(body), encoding="utf-8")


def _docs_app(port=3481, pub=5683):
    return f"""
    [app]
    name = "docs"
    kind = "service"
    python_entry = "backend-core/doc_service_app.py"
    static_dir = "plugins/reports/static"
    static_mount = ["/viewer"]
    api_prefixes = ["/doc", "/code", "/api/community-doc"]
    rpc_namespaces = ["render", "doc"]
    port = {port}
    pub_port = {pub}
    health = "/health"
    """


def _chat_app(port=3483):
    return f"""
    [app]
    name = "chat"
    kind = "service"
    python_entry = "backend-core/chat_service_app.py"
    api_prefixes = ["/chat", "/api/chat"]
    rpc_namespaces = ["chat"]
    port = {port}
    health = "/health"
    """


def test_merges_core_and_app_routes(tmp_path):
    _write(tmp_path, "docs", _docs_app())
    _write(tmp_path, "chat", _chat_app())
    svc, rpc, prefixes, health, ports = gw._load_registry(str(tmp_path))

    # 核心固定服务
    assert svc["kb"] == gw._KB_URL
    assert rpc["project"] == "kb" and rpc["analysis"] == "kb"
    assert rpc["llm"] == "llm" and rpc["session"] == "llm"
    assert rpc["agent"] == "agent" and rpc["skill"] == "agent"
    # app 命名空间并入
    assert rpc["render"] == "docs" and rpc["doc"] == "docs"
    assert rpc["chat"] == "chat"
    # 服务表 / 健康目标
    assert svc["docs"] == "http://127.0.0.1:3481"
    assert svc["chat"] == "http://127.0.0.1:3483"
    assert "docs" in health and "chat" in health and "kb" in health
    # 反代前缀（含 app 声明）
    prefix_set = {p for p, _ in prefixes}
    assert {"/doc", "/code", "/api/community-doc", "/chat", "/api/chat"} <= prefix_set
    # 事件桥端口含 app pub_port
    assert 5683 in ports and 5681 in ports


def test_port_change_changes_proxy_target(tmp_path):
    _write(tmp_path, "docs", _docs_app(port=3481))
    _, _, _, _, _ = gw._load_registry(str(tmp_path))
    svc_a, *_ = gw._load_registry(str(tmp_path))
    assert svc_a["docs"] == "http://127.0.0.1:3481"

    # 改 manifest 端口 → 反代目标随之改变（验收标准 2）
    _write(tmp_path, "docs", _docs_app(port=3999))
    svc_b, *_ = gw._load_registry(str(tmp_path))
    assert svc_b["docs"] == "http://127.0.0.1:3999"


def test_rpc_namespace_conflict_between_apps_raises(tmp_path):
    _write(tmp_path, "docs", _docs_app())
    _write(tmp_path, "chat", _chat_app())
    # 第三个 app 抢占 docs 已声明的 render
    _write(tmp_path, "architect", """
        [app]
        name = "architect"
        kind = "service"
        python_entry = "backend-core/arch_service_app.py"
        api_prefixes = ["/architect"]
        rpc_namespaces = ["render"]
        port = 3470
        health = "/health"
        """)
    with pytest.raises(ManifestError):
        gw._load_registry(str(tmp_path))


def test_app_claiming_core_namespace_raises(tmp_path):
    _write(tmp_path, "docs", """
        [app]
        name = "docs"
        kind = "service"
        python_entry = "backend-core/doc_service_app.py"
        api_prefixes = ["/doc"]
        rpc_namespaces = ["project"]
        port = 3481
        health = "/health"
        """)
    with pytest.raises(ManifestError):
        gw._load_registry(str(tmp_path))


def test_env_override_wins_over_manifest(tmp_path, monkeypatch):
    _write(tmp_path, "docs", _docs_app(port=3481))
    monkeypatch.setenv("DOC_API_URL", "http://127.0.0.1:9999")
    svc, *_ = gw._load_registry(str(tmp_path))
    assert svc["docs"] == "http://127.0.0.1:9999"


def test_kind_core_routes_to_kb_not_service(tmp_path):
    _write(tmp_path, "workbench", """
        [app]
        name = "workbench"
        kind = "core"
        python_entry = ""
        static_dir = "dist"
        static_mount = ["/app"]
        rpc_namespaces = ["knowledge"]
        """)
    svc, rpc, *_ = gw._load_registry(str(tmp_path))
    # kind=core：命名空间经 kb 进程，不进入服务表
    assert rpc["knowledge"] == "kb"
    assert "workbench" not in svc


def test_prefix_targets_sorted_longest_first(tmp_path):
    _write(tmp_path, "docs", """
        [app]
        name = "docs"
        kind = "service"
        python_entry = "backend-core/doc_service_app.py"
        api_prefixes = ["/api/x", "/api/x/sub"]
        rpc_namespaces = []
        port = 3481
        health = "/health"
        """)
    _, _, prefixes, _, _ = gw._load_registry(str(tmp_path))
    ordered = [p for p, _ in prefixes]
    assert ordered.index("/api/x/sub") < ordered.index("/api/x")
