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
    # 规约定型(2610): AGENTS.md 只含约束性信息, 资产概览(参考性质)已裁
    assert "资产概览" not in md
    assert "本地语义资产为空" not in md


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


# ── W4 规则链(D-2 方案 A, 2610-B1): 定界/规则追加/手改保护 ─────────────

def _read(path):
    return open(path, encoding="utf-8").read()


def test_rules_dir_appended_sorted(proj_with_rules, tmp_path):
    import topoone_app_architect.arch_routes.agents_md_chain as chain
    root = proj_with_rules["root"]
    rules = tmp_path / "repo" / ".topo" / "rules"
    rules.mkdir(parents=True)
    (rules / "b-style.md").write_text("B 规则", encoding="utf-8")
    (rules / "a-naming.md").write_text("A 规则", encoding="utf-8")
    (rules / "cache.log").write_text("应被过滤", encoding="utf-8")
    r = sync_agents_md(root, proj_with_rules["pid"])
    assert r["ok"] and r["changed"] is True
    md = _read(r["path"])
    assert "topo:generated-begin:" in md and "<!-- topo:generated-end -->" in md
    assert md.index("### a-naming.md") < md.index("### b-style.md")   # 按名排序
    assert "A 规则" in md and "B 规则" in md and "应被过滤" not in md
    assert md.index("topo:generated-end") < md.index("## 项目规则")    # 生成段在前


def test_regenerate_clean_when_fingerprint_intact(proj_with_rules):
    """规约更新 → 数据驱动再生成: 指纹校验通过, 照常覆盖(非冲突)。"""
    root, pid = proj_with_rules["root"], proj_with_rules["pid"]
    assert sync_agents_md(root, pid)["changed"] is True
    store.NamingConventionStore.create(pid, "新规约条目", scenarios=["general"])
    r = sync_agents_md(root, pid)
    assert r["changed"] is True and "status" not in r        # 非冲突
    assert "新规约条目" in _read(r["path"])


def test_manual_edit_conflict_not_silently_overwritten(proj_with_rules):
    root, pid = proj_with_rules["root"], proj_with_rules["pid"]
    path = sync_agents_md(root, pid)["path"]
    md = _read(path)
    hand = md.replace("# AGENTS.md", "# AGENTS.md(手改标题)", 1)
    open(path, "w", encoding="utf-8").write(hand)
    r = sync_agents_md(root, pid)
    assert r["status"] == "manual_edit_conflict" and r["changed"] is False
    assert r["options"] == ["force_overwrite", "cancel"]
    assert "(手改标题)" in _read(path)                        # 未被覆盖
    r2 = sync_agents_md(root, pid, force=True)
    assert r2["changed"] is True
    assert "(手改标题)" not in _read(path)                    # force 后重建


def test_legacy_undelimited_file_conflicts(proj_with_rules):
    """无定界旧文件(手写/旧版生成) → 冲突; force 一次入定界形态。"""
    root, pid = proj_with_rules["root"], proj_with_rules["pid"]
    path = f"{root}/AGENTS.md"
    open(path, "w", encoding="utf-8").write("# 手写 AGENTS.md\n内容")
    r = sync_agents_md(root, pid)
    assert r["status"] == "manual_edit_conflict"
    assert sync_agents_md(root, pid, force=True)["changed"] is True
    assert "topo:generated-begin:" in _read(path)
