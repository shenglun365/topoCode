"""项目级 AGENTS.md 生成/维护(用户需求 2026-09-26)特征测试。

- 内容源=既有能力单源(tool_rules 规约全集 + SemanticAssetsStore 统计);
- sync 幂等: 内容无变化不动文件; 显式触发(不扩大化)。
"""
from __future__ import annotations

import os

import pytest

from topoone_app_architect import store
from topoone_app_architect.arch_routes.agents_md import tool_agents_md_sync
from topoone_app_architect.arch_routes.agents_md import (
    build_project_agents_md, sync_agents_md)


@pytest.fixture()
def proj_with_rules(arch_env, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    pid = "proj-agents1"
    store.ProjectsStore.create({
        "id": pid, "name": "agents-fixture",
        "root_path": str(root), "active": 1})
    store.NamingConventionStore.create(
        pid, "动词开头小驼峰，禁止拼音", scenarios=["general"])
    store.GlossaryStore.create(pid, "场景",
                               definition="Scene——一次可播放的动画编排")
    return {"root": str(root), "pid": pid}


def test_build_contains_rules_and_glossary(proj_with_rules):
    md = build_project_agents_md(proj_with_rules["root"], proj_with_rules["pid"])
    assert "# AGENTS.md — agents-fixture" in md
    assert "动词开头小驼峰" in md
    assert "Scene——一次可播放的动画编排" in md
    assert "## 资产概览" in md
    assert "本地语义资产为空" in md


def test_sync_writes_and_idempotent(proj_with_rules):
    root, pid = proj_with_rules["root"], proj_with_rules["pid"]
    r1 = sync_agents_md(root, pid)
    assert r1["ok"] and r1["changed"] is True
    path = os.path.join(root, "AGENTS.md")
    assert os.path.isfile(path)
    r2 = sync_agents_md(root, pid)
    assert r2["changed"] is False          # 幂等: 内容无变化不动文件
    # 规约更新 → 再 sync 内容变化
    store.NamingConventionStore.create(
        pid, "PascalCase 且带域前缀", scenarios=["general"])
    r3 = sync_agents_md(root, pid)
    assert r3["changed"] is True


def test_tool_registered_and_invocable(proj_with_rules):
    from topoone_app_architect.agent.tools.registry import architect_tools
    names = [t["name"] for t in architect_tools()]
    assert "agents.md.sync" in names
    res = tool_agents_md_sync(proj_with_rules["root"], proj_with_rules["pid"])
    assert res["ok"] and res["changed"] is True


def test_sync_refuses_missing_root(arch_env):
    res = sync_agents_md("/nonexistent/xyz", "")
    assert res["ok"] is False and "root" in res["error"]
