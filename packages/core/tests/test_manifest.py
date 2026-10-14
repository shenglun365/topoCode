"""M01 — App Manifest 契约测试（合法解析 / 命名空间冲突 / 保留前缀 / kind=core 无端口）。"""

import textwrap

import pytest

from topoone.manifest import (
    KIND_CORE,
    KIND_SERVICE,
    ManifestError,
    discover_apps,
    load_manifest,
    validate_registry,
)


def _write_manifest(root, name: str, body: str):
    d = root / "apps" / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "manifest.toml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_load_valid_service_manifest(tmp_path):
    p = _write_manifest(
        tmp_path,
        "docs",
        """
        [app]
        name = "docs"
        kind = "service"
        python_entry = "backend-core/doc_service_app.py"
        static_dir = "plugins/reports/static"
        static_mount = ["/viewer", "/projects"]
        api_prefixes = ["/doc", "/api/community-doc"]
        rpc_namespaces = ["render", "doc"]
        port = 3481
        pub_port = 5683

        [app.env]
        FOO = "bar"
        """,
    )
    m = load_manifest(p)
    assert m.name == "docs"
    assert m.kind == KIND_SERVICE
    assert m.port == 3481
    assert m.pub_port == 5683
    assert m.service_url == "http://127.0.0.1:3481"
    assert m.static_mount == ["/viewer", "/projects"]
    assert m.api_prefixes == ["/doc", "/api/community-doc"]
    assert m.rpc_namespaces == ["render", "doc"]
    assert m.env == {"FOO": "bar"}
    assert not m.python_entry_is_module()  # 过渡期脚本路径


def test_load_valid_module_entry(tmp_path):
    p = _write_manifest(
        tmp_path,
        "chat",
        """
        [app]
        name = "chat"
        kind = "service"
        python_entry = "topoone_app_chat:main"
        port = 3483
        """,
    )
    m = load_manifest(p)
    assert m.python_entry_is_module()
    assert m.service_url == "http://127.0.0.1:3483"


def test_registry_namespace_conflict(tmp_path):
    _write_manifest(
        tmp_path,
        "a",
        """
        [app]
        name = "a"
        kind = "service"
        python_entry = "x.py"
        port = 4001
        rpc_namespaces = ["knowledge"]
        """,
    )
    _write_manifest(
        tmp_path,
        "b",
        """
        [app]
        name = "b"
        kind = "service"
        python_entry = "y.py"
        port = 4002
        rpc_namespaces = ["knowledge"]
        """,
    )
    apps = discover_apps(tmp_path)
    assert set(apps) == {"a", "b"}
    errors = validate_registry(apps)
    assert any("knowledge" in e for e in errors)


def test_registry_reserved_prefix_rejected(tmp_path):
    p = _write_manifest(
        tmp_path,
        "c",
        """
        [app]
        name = "c"
        kind = "service"
        python_entry = "z.py"
        port = 4003
        api_prefixes = ["/api/rpc"]
        """,
    )
    with pytest.raises(ManifestError, match="reserved"):
        load_manifest(p)


def test_kind_core_must_not_declare_port(tmp_path):
    p = _write_manifest(
        tmp_path,
        "workbench",
        """
        [app]
        name = "workbench"
        kind = "core"
        python_entry = ""
        port = 3459
        """,
    )
    with pytest.raises(ManifestError, match="kind=core must not declare"):
        load_manifest(p)


def test_kind_core_empty_entry_allowed(tmp_path):
    """过渡态：kind=core 且 python_entry 为空（核心进程仍自注册方法）合法。"""
    p = _write_manifest(
        tmp_path,
        "workbench",
        """
        [app]
        name = "workbench"
        kind = "core"
        python_entry = ""
        static_dir = "dist"
        static_mount = ["/app"]
        rpc_namespaces = ["knowledge"]
        """,
    )
    m = load_manifest(p)
    assert m.kind == KIND_CORE
    assert m.service_url is None
    assert validate_registry({"workbench": m}) == []


def test_registry_port_conflict_with_core_fixed_port(tmp_path):
    p = _write_manifest(
        tmp_path,
        "d",
        """
        [app]
        name = "d"
        kind = "service"
        python_entry = "w.py"
        port = 3484
        """,
    )
    m = load_manifest(p)
    errors = validate_registry({"d": m})
    assert any("llm" in e for e in errors)


def test_name_must_match_parent_dir(tmp_path):
    p = _write_manifest(
        tmp_path,
        "docs",
        """
        [app]
        name = "other"
        kind = "service"
        python_entry = "w.py"
        port = 4100
        """,
    )
    with pytest.raises(ManifestError, match="parent dir name"):
        load_manifest(p)
