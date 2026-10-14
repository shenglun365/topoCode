"""上下文包契约(重定位 P2 核心建设)特征测试, 裁决 2026-09-26。

契约语义: 执行器输入=结构化 brief(specMd/assetRefs/constraints/acceptance),
缺规约显式 incomplete+missing(不强硬保底: 不虚构、透明降级、照常执行);
指令尾部渲染规范 markdown 段; dispatch payload 携带结构化 contextPack。
cv-257 重放判据: 绑规约的任务, 契约字段完整(执行器不再只拿一句自由文本)。
"""
from __future__ import annotations

import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.agent.execution.context_pack import (
    build_context_pack, render_context_pack_md)

SPEC_SNAPSHOT = {
    "allowedScope": ["src/"],
    "designMd": "用现成解析管道落库, 禁止新写扫描器",
    "requirementMd": "重建项目资产并刷新基线",
    "scopeOut": "不修改业务源码",
    "acceptance": ["arch_semantic_assets 计数 > 0"],
}


def _mk_spec_env(arch_env, tmp_path, monkeypatch, root, with_spec=True):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "pack", "meta": {"root": str(root)},
        "reqId": "RQ-pack" if with_spec else ""})
    conv = store.ConversationsStore.get(conv_row["id"])
    if with_spec:
        store.RequirementsStore.create({
            "id": "RQ-pack", "title": "资产重建", "status": "ready",
            "analysis": {"allowedScope": ["src/"]}, "activeVer": 1,
            "specVersions": [{"ver": 1, "state": "confirmed",
                              "snapshot": dict(SPEC_SNAPSHOT),
                              "source": {}, "reason": "", "createdAt": 0}]})
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), ""))
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex", "type": "cline-sdk", "enabled": True, "config": {}}])
    captured = {"implement": []}

    def _fake_runner(path, payload=None, timeout=12.0):
        if path == "/api/implement":
            captured["implement"].append(payload)
            return {"ok": True, "jobId": "j", "branch": payload["branchName"],
                    "worktree": str(tmp_path / "wt"), "sessionId": "s",
                    "baseCommit": "sha"}
        return {"ok": True}

    from topoone_app_architect.agent.execution import exec_bridge as eb
    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    return conv, eb, captured


def test_pack_from_spec_complete(arch_env, tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    conv, eb, _cap = _mk_spec_env(arch_env, tmp_path, monkeypatch, root)
    task = eb.propose_task(conv, "重建资产", "x",
                           {"executorType": "cline-sdk", "reqId": "RQ-pack"})
    pack = build_context_pack(store.TasksStore.get(task["id"]) or {}, conv,
                              str(root), ["src/a.ts"])
    assert not pack.get("incomplete")
    assert "禁止新写扫描器" in pack["specMd"]
    assert pack["assetRefs"]["allowedScope"] == ["src/"]
    assert pack["assetRefs"]["boundaryFiles"] == ["src/a.ts"]
    assert any("明确不做" in c for c in pack["constraints"])
    assert pack["acceptance"] == ["arch_semantic_assets 计数 > 0"]


def test_pack_free_task_transparent_degrade(arch_env, tmp_path, monkeypatch):
    """quick 直出卡(无规约) → incomplete+missing 显式标记, 不虚构。"""
    root = tmp_path / "proj"
    root.mkdir()
    conv, eb, _cap = _mk_spec_env(arch_env, tmp_path, monkeypatch, root,
                                  with_spec=False)
    task = eb.propose_task(conv, "直出卡", "x", {"executorType": "cline-sdk"})
    pack = build_context_pack(store.TasksStore.get(task["id"]) or {}, conv,
                              str(root), [])
    assert pack.get("incomplete") is True
    assert any("specMd" in m for m in pack.get("missing") or [])


def test_render_contains_contract_sections():
    pack = {"reqId": "RQ-pack",
            "specMd": "方案正文",
            "assetRefs": {"allowedScope": ["src/"], "boundaryFiles": ["src/a.ts"]},
            "constraints": ["明确不做: 不修改业务源码"],
            "acceptance": ["资产比对通过"]}
    md = render_context_pack_md(pack)
    assert "## 上下文包(执行契约)" in md
    assert "### 规约" in md and "方案正文" in md
    assert "### 约束" in md and "不修改业务源码" in md
    assert "### 验收判据" in md and "资产比对通过" in md


def test_render_incomplete_discloses_missing():
    pack = {"reqId": "", "specMd": "", "missing": ["specMd(规约目标/方案)"],
            "incomplete": True, "assetRefs": {}, "constraints": [],
            "acceptance": ["默认资产比对"]}
    md = render_context_pack_md(pack)
    assert "⚠️ 规约要素缺失" in md and "specMd" in md


def test_confirm_payload_carries_pack(arch_env, tmp_path, monkeypatch):
    """cv-257 重放判据: 绑规约任务 confirm 后, /api/implement 载荷带
    结构化 contextPack 且 instruction 含契约段(执行器不再只拿自由文本)。"""
    root = tmp_path / "proj"
    root.mkdir()
    conv, eb, captured = _mk_spec_env(arch_env, tmp_path, monkeypatch, root)
    task = eb.propose_task(conv, "重建资产", "x",
                           {"executorType": "cline-sdk", "reqId": "RQ-pack"})
    res = eb.confirm_task(task["id"])
    assert res["ok"]
    payloads = [pl for pl in captured["implement"]]
    assert payloads and payloads[-1].get("contextPack")
    pack = payloads[-1]["contextPack"]
    assert "禁止新写扫描器" in (pack.get("specMd") or "")
    assert "## 上下文包(执行契约)" in (payloads[-1].get("instruction") or "")


def test_render_three_channel_grounding():
    """C3 三通道分层: 意图/推断分节+头注, 语义别名/代码坐标措辞, 冲突约定总则。"""
    pack = {"reqId": "RQ",
            "specMd": "方案要点…", "reqMd": "用户需求原文", "designMd": "架构师方案",
            "assetRefs": {"allowedScope": ["资产A"], "boundaryFiles": ["src/a.ts"]},
            "constraints": [], "acceptance": ["x"],
            "graphNeighborhood": {"outline": "邻域摘要", "baselineStale": True}}
    md = render_context_pack_md(pack)
    assert "### 需求（用户意图）" in md and "用户需求原文" in md
    assert "### 方案（架构师推断——以代码为准）" in md and "架构师方案" in md
    assert "语义别名" in md and "代码坐标" in md
    assert "以代码为准" in md and "解读环节" in md        # 冲突约定总则
    assert "架构师推断, 以代码为准" in md                  # 图邻域头注(含过期标注)


def test_render_slim_carries_conflict_rule():
    from topoone_app_architect.agent.execution.context_pack import (
        render_context_pack_slim)
    md = render_context_pack_slim(
        {"acceptance": ["a"], "constraints": [], "assetRefs": {}}, ".topo/docs/x")
    assert "事实优先约定" in md or "以代码为准" in md
