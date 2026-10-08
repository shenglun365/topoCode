"""AGENTS.md 纯文件模式(2610 定型修订)——真相源/解析/缓存同步/读写/ init。

对齐 Codex/Claude Code/opencode 三家共同模式: 人治 markdown 单文件为真相,
store 为引擎缓存(章节解析回填, 坏行容错), init 初稿不盲改。
"""
from __future__ import annotations

import asyncio
import json as _j
import os

import pytest

from topoone_app_architect import store
from topoone_app_architect.arch_routes.agents_md import (
    init_agents_md, tool_agents_md_init)
from topoone_app_architect.sem import map_tools
from topoone_app_architect.sem.rules_file import (
    append_convention, ensure_rules_synced, parse_agents_md, read_agents_md,
    write_agents_md)

SAMPLE = """# AGENTS.md — demo

> 人治规约。

## 命名规约

- [naming] 服务以 XxxService 结尾
- 禁止拼音命名

## 术语表

| 术语 | 别名 | 含义 |
|---|---|---|
| 场景 | Scene, 剧本 | 一次可播放的动画编排 |
| 需求 | — | 用户价值诉求 |

## 架构约束

- 分层单向依赖
"""


@pytest.fixture()
def proj(arch_env, tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    pid = "proj-file1"
    store.ProjectsStore.create({
        "id": pid, "name": "file-fixture",
        "root_path": str(root), "active": 1})
    return {"root": str(root), "pid": pid}


# ── 解析契约 ──────────────────────────────────────────────────────────

def test_parse_sections_and_badrows():
    r = parse_agents_md(SAMPLE)
    assert r["conventions"] == [
        {"ruleText": "服务以 XxxService 结尾", "scenarios": ["naming"]},
        {"ruleText": "禁止拼音命名", "scenarios": ["general"]}]
    g = {x["term"]: x for x in r["glossary"]}
    assert g["场景"]["alias"] == ["Scene", "剧本"]
    assert g["场景"]["definition"] == "一次可播放的动画编排"
    assert g["需求"]["alias"] == []
    assert r["skipped"] == 0
    # 坏行容错
    bad = "## 命名规约\n\n正常一条\n- [x] 好的\n垃圾行"
    assert parse_agents_md(bad)["skipped"] >= 2


# ── 读写 + 乐观锁 ────────────────────────────────────────────────────

def test_write_and_conflict(proj):
    r = write_agents_md(proj["root"], SAMPLE)
    assert r["ok"] and r["hash"]
    got = read_agents_md(proj["root"])
    assert got["exists"] and got["hash"] == r["hash"]
    # 乐观锁: 错误 base_hash → 冲突
    c = write_agents_md(proj["root"], "# 改", base_hash="deadbeef")
    assert c["conflict"] is True
    # 正确 base_hash → 成功
    w = write_agents_md(proj["root"], "# 改\n", base_hash=r["hash"])
    assert w["ok"] and read_agents_md(proj["root"])["content"].startswith("# 改")


# ── 文件→缓存全量重建 ────────────────────────────────────────────────

def test_sync_rebuilds_cache(proj):
    # 预置遗留数据(不在文件中 → 应被清)
    store.NamingConventionStore.create(proj["pid"], "遗留旧规约",
                                       scenarios=["general"], source="manual")
    store.GlossaryStore.create(proj["pid"], "旧术语", definition="x")
    # 预置 pending 提案(应保留)
    store.NamingConventionStore.create(proj["pid"], "待审提案",
                                       scenarios=["general"], status="pending")
    write_agents_md(proj["root"], SAMPLE)

    r = ensure_rules_synced(proj["root"], proj["pid"], force=True)
    assert r["synced"] is True and r["conventions"] == 2 and r["glossary"] == 2
    rules = [c["ruleText"] for c in store.NamingConventionStore.list(proj["pid"])]
    assert "服务以 XxxService 结尾" in rules and "禁止拼音命名" in rules
    assert "遗留旧规约" not in rules                      # 文件为真相
    pend = store.NamingConventionStore.list(proj["pid"], status="pending")
    assert [p["ruleText"] for p in pend] == ["待审提案"]    # 提案不动
    terms = {g["term"]: g for g in store.GlossaryStore.list(proj["pid"])}
    assert "场景" in terms and "旧术语" not in terms
    assert terms["场景"]["alias"] == ["Scene", "剧本"]
    # 惰性: 无变化不重建
    r2 = ensure_rules_synced(proj["root"], proj["pid"])
    assert r2["synced"] is False
    # 无文件 → no-op
    ensure_rules_synced("/nonexistent", proj["pid"])


# ── init(/init 模式: 无文件生成初稿+迁移, 有文件只建议) ───────────────

def test_init_creates_draft_with_migration(proj):
    # 预置缓存 + .topo/rules 迁移源
    store.NamingConventionStore.create(proj["pid"], "服务 XxxService 结尾",
                                       scenarios=["naming"])
    store.GlossaryStore.create(proj["pid"], "场景", alias=["Scene"],
                               definition="动画编排")
    rules_dir = os.path.join(proj["root"], ".topo", "rules")
    os.makedirs(rules_dir)
    open(os.path.join(rules_dir, "a-style.md"), "w", encoding="utf-8").write("A 规则内容")

    r = init_agents_md(proj["root"], proj["pid"])
    assert r["ok"] and r["created"] is True
    md = open(os.path.join(proj["root"], "AGENTS.md"), encoding="utf-8").read()
    assert "## 命名规约" in md and "服务 XxxService 结尾" in md   # 缓存并入
    assert "| 场景 | Scene | 动画编排 |" in md                    # 术语表格
    assert "## 项目规则·a-style" in md and "A 规则内容" in md    # 迁移
    assert "## 架构约束" in md                                    # 模板段
    # init 后缓存与文件一致
    assert "服务 XxxService 结尾" in [c["ruleText"] for c in
                                     store.NamingConventionStore.list(proj["pid"])]

    # 已有文件 → 只建议不盲改
    md_before = md
    r2 = init_agents_md(proj["root"], proj["pid"])
    assert r2["ok"] and r2["created"] is False
    assert r2["conventions"] == 1 and r2["suggestions"]
    assert open(os.path.join(proj["root"], "AGENTS.md"),
                encoding="utf-8").read() == md_before             # 未被改
    # root 不可用
    assert init_agents_md("/nonexistent", "")["ok"] is False


# ── 采纳 append ──────────────────────────────────────────────────────

def test_append_convention(proj):
    assert append_convention(proj["root"], proj["pid"], "新规约")["written"] is False
    write_agents_md(proj["root"], SAMPLE)
    r = append_convention(proj["root"], proj["pid"], "新规约", ["naming"])
    assert r["written"] is True
    md = open(os.path.join(proj["root"], "AGENTS.md"), encoding="utf-8").read()
    assert "- [naming] 新规约" in md
    assert "新规约" in [c["ruleText"] for c in
                      store.NamingConventionStore.list(proj["pid"])]  # 缓存已刷
    # 章节缺失 → 自动建节
    write_agents_md(proj["root"], "# 无节\n")
    r2 = append_convention(proj["root"], proj["pid"], "另一条")
    assert r2["written"] is True
    assert "## 命名规约" in open(os.path.join(proj["root"], "AGENTS.md"),
                                 encoding="utf-8").read()


# ── REST(读/写/冲突 409) + 工具注册 ─────────────────────────────────

class _Req:
    def __init__(self, body): self._b = body
    async def json(self): return self._b


def test_rest_and_tool(proj):
    from topoone_app_architect.arch_routes import agents_md as am
    put = asyncio.run(am.api_agents_md_put(_Req(
        {"root": proj["root"], "content": SAMPLE, "baseHash": "",
         "project": proj["pid"]})))
    assert put["data"]["ok"]
    got = asyncio.run(am.api_agents_md_get(root=proj["root"], project=proj["pid"]))
    assert got["data"]["exists"] and "命名规约" in got["data"]["content"]
    # 乐观锁 409
    conflict = asyncio.run(am.api_agents_md_put(_Req(
        {"root": proj["root"], "content": "# x\n", "baseHash": "bad",
         "project": proj["pid"]})))
    assert conflict.status_code == 409
    # init REST
    r = asyncio.run(am.api_agents_md_init(_Req(
        {"root": proj["root"], "project": proj["pid"]})))
    assert r["data"]["created"] is False
    # 工具: agents.md.init 注册可调; 旧 agents.md.sync 已退役
    from topoone_app_architect.agent.tools.registry import architect_tools
    names = [t["name"] for t in architect_tools()]
    assert "agents.md.init" in names and "agents.md.sync" not in names
    assert tool_agents_md_init(proj["root"], proj["pid"])["ok"] is True


# ── map.rules 文件优先/缓存回退 ──────────────────────────────────────

def test_tool_rules_file_first(proj):
    write_agents_md(proj["root"], SAMPLE)
    out = map_tools.tool_rules(proj["pid"])
    assert "分层单向依赖" in out                     # 文件全文(含自由章节)
    out2 = map_tools.tool_rules("proj-nope")
    assert "无法唯一定位项目" in out2


# ── 采纳流落文件(mining accept + naming PUT 确认) ────────────────────

def test_mining_accept_appends_file(proj):
    from topoone_app_architect.agent.reflection import mining
    write_agents_md(proj["root"], SAMPLE)
    p = store.CapabilityProposalStore.create(
        proj["pid"], "convention", "服务后缀规约", "服务以 Impl 结尾",
        scenarios=["naming"])
    r = mining.decide_proposal(proj["pid"], p["id"], "accept")
    assert r["ok"] and "AGENTS.md" in r["applied"]
    md = open(os.path.join(proj["root"], "AGENTS.md"), encoding="utf-8").read()
    assert "- [naming] 服务以 Impl 结尾" in md


def test_naming_confirm_appends_file(proj):
    import asyncio
    from topoone_app_architect.arch_routes import naming as nm
    write_agents_md(proj["root"], SAMPLE)
    row = store.NamingConventionStore.create(
        proj["pid"], "服务以 Repo 结尾", scenarios=["naming"], status="pending")

    class _Req:
        def __init__(self, b): self._b = b
        async def json(self): return self._b
    r = asyncio.run(nm.api_conventions_update(
        row["id"], _Req({"root": proj["root"], "project": proj["pid"],
                            "status": "active"})))
    md = open(os.path.join(proj["root"], "AGENTS.md"), encoding="utf-8").read()
    assert "- [naming] 服务以 Repo 结尾" in md
    assert r["data"]["status"] == "active"
