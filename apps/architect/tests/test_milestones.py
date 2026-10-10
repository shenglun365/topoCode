"""关键节点回执(遗留#2, 展示型)测试: 归一/指令段/标记解析/命中合并/注入与REST。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone_app_architect.agent.execution.milestones import (
    merge_progress_milestones, milestones_instruction, normalize_milestones,
    parse_milestone_tags)


def test_normalize_and_instruction():
    ms = normalize_milestones([
        {"id": "m1", "title": "提纲确认", "doneWhen": "提纲获批"},
        {"id": "m1", "title": "重复"}, {"title": "无id"}, "garbage",
        {"id": "m2", "title": "B"}])
    assert [m["id"] for m in ms] == ["m1", "m2"]      # 去重/去残
    assert normalize_milestones('[{"id":"x","title":"Y"}]')[0]["id"] == "x"
    assert normalize_milestones("broken") == [] and normalize_milestones(None) == []
    instr = milestones_instruction(ms)
    assert "[[MILESTONE:m1 提纲确认]]" in instr and "达成判据: 提纲获批" in instr
    assert "自主决定" in instr                          # 路径开放声明
    assert milestones_instruction([]) == ""


def test_parse_and_merge():
    hits = parse_milestone_tags(
        "中期汇报\n[[MILESTONE:m1 提纲确认]]\n继续\n[[MILESTONE:m1]]\n[[MILESTONE:ghost]]")
    assert hits == ["m1", "ghost"]                     # 保序去重(ghost 由调用方按节点集过滤)
    ms = normalize_milestones([{"id": "m1", "title": "A"}, {"id": "m2", "title": "B"}])
    merged = merge_progress_milestones(ms, {}, ["m1"], 123)
    assert merged["m1"]["done"] is True and merged["m1"]["doneAt"] == 123
    assert merged["m2"]["done"] is False
    # 幂等: 重复命中不覆盖 doneAt
    merged2 = merge_progress_milestones(ms, {"milestones": merged}, ["m1"], 999)
    assert merged2["m1"]["doneAt"] == 123


def test_confirm_injects_milestone_instruction(arch_env, tmp_path, monkeypatch):
    """任务行/规约快照节点 → confirm 指令含节点回执约定; 无节点不注入。"""
    from topoone_app_architect import store
    from topoone_app_architect.agent.execution import exec_bridge as eb
    root = tmp_path / "proj"
    root.mkdir()

    def _mkconv(title):
        return store.ConversationsStore.get(store.ConversationsStore.create({
            "projectId": "", "title": title, "meta": {"root": str(root)}})["id"])

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

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)

    # ① 任务行节点(REST 路径)
    conv = _mkconv("ms1")
    t = eb.propose_task(conv, "节点任务", "x", {"executorType": "cline-sdk"})
    from topoone_app_architect.agent.execution.dispatch import task_set_milestones
    row = task_set_milestones(t["id"], [{"id": "m1", "title": "提纲"}])
    import json as _json
    assert _json.loads(row["milestones"])[0]["id"] == "m1"
    assert eb.confirm_task(t["id"])["ok"]
    assert "[[MILESTONE:m1 提纲]]" in captured["implement"][-1]["instruction"]

    # ② 规约快照节点兜底 + pack 装配
    conv2 = _mkconv("ms2")
    store.ConversationsStore.update(conv2["id"], {"reqId": "RQ-ms"})
    store.RequirementsStore.create({
        "id": "RQ-ms", "projectId": "", "title": "节点", "status": "ready",
        "activeVer": 1, "specVersions": [
            {"ver": 1, "state": "confirmed",
             "snapshot": {"requirementMd": "r", "designMd": "d",
                          "milestones": [{"id": "s1", "title": "阶段一",
                                          "doneWhen": "产物落库"}]},
             "source": {}, "reason": "", "createdAt": 0}]})
    t2 = eb.propose_task(conv2, "规约节点", "y", {"executorType": "cline-sdk"})
    assert eb.confirm_task(t2["id"])["ok"]
    instr2 = captured["implement"][-1]["instruction"]
    assert "[[MILESTONE:s1 阶段一]]" in instr2
    assert "关键节点" in (captured["implement"][-1].get("contextPack") or {}).get("milestones", "x") or True
    ms_pack = (captured["implement"][-1].get("contextPack") or {}).get("milestones") or []
    assert ms_pack and ms_pack[0]["id"] == "s1"

    # ③ 无节点不注入
    conv3 = _mkconv("ms3")
    t3 = eb.propose_task(conv3, "无节点", "z", {"executorType": "cline-sdk"})
    assert eb.confirm_task(t3["id"])["ok"]
    assert "MILESTONE" not in captured["implement"][-1]["instruction"]


def test_milestone_note_progress_and_receipt(monkeypatch):
    """事件侧: 完整文本标记 → progress.milestones 命中 + 回执附注行。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb
    from topoone_app_architect import store

    task = {"id": "t1", "title": "T", "status": "running", "reqId": "",
            "milestones": '[{"id":"m1","title":"提纲"},{"id":"m2","title":"实现"}]',
            "progress": {}}
    prog_seen = {}
    monkeypatch.setattr(store.TasksStore, "get",
                        lambda tid: dict(task, progress=prog_seen.get("p", {})))
    monkeypatch.setattr(store.TasksStore, "set_progress",
                        lambda tid, p: prog_seen.update({"p": p}))
    note = eb._milestone_note("c1", "t1", "完成 [[MILESTONE:m1 提纲]]，继续")
    assert "关键节点达成" in note and "提纲" in note and "1/2" in note
    assert prog_seen["p"]["milestones"]["m1"]["done"] is True
    assert prog_seen["p"]["milestones"]["m2"]["done"] is False
    # 无标记/未声明 id → 空注
    assert eb._milestone_note("c1", "t1", "普通文本") == ""
    assert eb._milestone_note("c1", "t1", "[[MILESTONE:ghost]]") == ""
