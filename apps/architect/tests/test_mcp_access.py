"""MCP 接入辅助(2610)——四执行器探测/一键合并写入/幂等/备份。

写入器以显式路径为参数(tmp_path), 不 mock HOME。
"""
from __future__ import annotations

import json
import os

import pytest

from topoone_app_architect.arch_routes.mcp_access import (
    SERVER_KEY, apply_access, inspect_executors)

URL = "http://127.0.0.1:3470/mcp/mcp"


@pytest.fixture(autouse=True)
def _fake_home(tmp_path, monkeypatch):
    """HOME 隔离: 探测/写入不落真实用户目录。"""
    fake = tmp_path / "home"
    fake.mkdir()
    monkeypatch.setenv("TOPOCODE_MCP_HOME", str(fake))
    return fake


def _proj(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    return str(root)


def test_inspect_shapes(tmp_path):
    rows = {r["key"]: r for r in inspect_executors(_proj(tmp_path))}
    assert set(rows) == {"cline", "opencode", "qwen-code", "codex"}
    # codex 仅全局; 其余全局+项目
    assert rows["codex"]["scopes"]["project"] is None
    assert rows["opencode"]["scopes"]["project"]["path"].endswith("opencode.json")
    assert rows["cline"]["scopes"]["project"]["path"].endswith(
        os.path.join(".cline", "mcp_settings.json"))
    assert not rows["qwen-code"]["scopes"]["global"]["configured"]


def test_apply_opencode_merge_preserves_keys(tmp_path):
    root = _proj(tmp_path)
    cfg = os.path.join(root, "opencode.json")
    open(cfg, "w", encoding="utf-8").write(json.dumps(
        {"theme": "dark", "mcp": {"other": {"type": "remote", "url": "http://x"}}}))
    r = apply_access("opencode", "project", root, URL)
    assert r["written"] is True
    data = json.load(open(cfg, encoding="utf-8"))
    assert data["theme"] == "dark"                       # 既有键保留
    assert data["mcp"]["other"]["url"] == "http://x"     # 既有 mcp 保留
    assert data["mcp"][SERVER_KEY]["type"] == "remote"
    assert os.path.isfile(cfg + ".bak")                  # 备份
    # 幂等
    r2 = apply_access("opencode", "project", root, URL)
    assert r2["written"] is False and r2["already"] is True


def test_apply_qwen_gemini_shape(tmp_path):
    root = _proj(tmp_path)
    r = apply_access("qwen-code", "project", root, URL)
    assert r["written"] is True
    data = json.load(open(os.path.join(root, ".qwen", "settings.json"),
                          encoding="utf-8"))
    assert data["mcpServers"][SERVER_KEY]["httpUrl"] == URL


def test_apply_cline_project_scope(tmp_path):
    root = _proj(tmp_path)
    r = apply_access("cline", "project", root, URL)
    assert r["written"] is True
    data = json.load(open(os.path.join(root, ".cline", "mcp_settings.json"),
                          encoding="utf-8"))
    assert data["mcpServers"][SERVER_KEY]["transportType"] == "streamableHttp"


def test_apply_codex_toml_idempotent(tmp_path):
    root = _proj(tmp_path)
    r = apply_access("codex", "global", root, URL)
    assert r["written"] is True
    text = open(r["path"], encoding="utf-8").read()
    assert "[mcp_servers.topo-architect]" in text
    assert 'command = "' in text and "TOPOCODE_DATA_DIR" in text
    r2 = apply_access("codex", "global", root, URL)
    assert r2["written"] is False and r2["already"] is True
    assert open(r2["path"], encoding="utf-8").read() == text   # 未重复追加


def test_apply_validation(tmp_path):
    root = _proj(tmp_path)
    assert "url" in apply_access("opencode", "project", root, "ftp://x")["error"]
    assert "未知执行器" in apply_access("claude", "global", root, URL)["error"]
    assert "仅 global" in apply_access("codex", "project", root, URL)["error"]


def test_bad_json_not_clobbered(tmp_path):
    """坏 JSON 不吞文件: 报错而非覆盖。"""
    root = _proj(tmp_path)
    cfg = os.path.join(root, "opencode.json")
    open(cfg, "w", encoding="utf-8").write("{not-json")
    r = apply_access("opencode", "project", root, URL)
    assert r.get("error")
    assert open(cfg, encoding="utf-8").read() == "{not-json"


# ── 技能管理面: /arch/skills 分类分组 ────────────────────────────────

def test_skills_groups(tmp_path):
    import asyncio
    from topoone_app_architect.arch_routes import assets_api
    root = str(tmp_path / "repo-skill")
    os.makedirs(root)
    pid = "proj-skills1"
    from topoone_app_architect import store
    store.ProjectsStore.create({"id": pid, "name": "s", "root_path": root,
                                "active": 1})
    # 表技能: 覆盖内置 + 纯自定义 + 禁用行
    store.ArchAssetsStore.upsert({"name": "req.assess", "kind": "skill",
                                  "description": "覆盖版", "enabled": True,
                                  "payload": {"route_hint": "评估时"}})
    store.ArchAssetsStore.upsert({"name": "my.skill", "kind": "skill",
                                  "description": "自定义", "enabled": True,
                                  "payload": {"route_hint": "自定场景"}})
    store.ArchAssetsStore.upsert({"name": "off.skill", "kind": "skill",
                                  "description": "停用", "enabled": False,
                                  "payload": {"route_hint": "x"}})
    # 开发类资产不入技能面
    store.ArchAssetsStore.upsert({"name": "req-x", "kind": "requirement",
                                  "description": "需求", "enabled": True,
                                  "payload": {}})

    r = asyncio.run(assets_api.list_skills(project=pid))["data"]
    cats = {g["category"]: g for g in r}
    assert "requirement-analysis" in cats and "quality" in cats
    assess = next(s for s in cats["requirement-analysis"]["skills"]
                  if s["name"] == "req.assess")
    assert assess["source"] == "asset" and assess["route_hint"] == "评估时"
    custom = {s["name"] for s in cats["custom"]["skills"]}
    assert custom == {"my.skill", "off.skill"}           # 需求类不入
    off = next(s for s in cats["custom"]["skills"] if s["name"] == "off.skill")
    assert off["enabled"] is False                       # 管理视角含禁用行
