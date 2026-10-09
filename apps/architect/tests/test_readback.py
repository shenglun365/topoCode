"""解读回环(D4, 意图空间一期)测试: 挡位开启判定 + 规则校验 + 指令注入。

裁决(2026-10-09): 规则可判自动裁决/偏差人工终裁; high-stakes 默认开,
task.readback 显式覆盖; 零 runner 协议改动(指令段+input_required 校验附注)。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone_app_architect.agent.execution.readback import (
    READBACK_INSTRUCTION, readback_enabled, render_verdict, verdict_of)


def test_readback_enabled_gear_and_override():
    """挡位默认: high-stakes 开/其余关; readback 字段显式覆盖。"""
    assert readback_enabled({"safetyClass": "high-stakes"}) is True
    assert readback_enabled({"safetyClass": "mutating"}) is False
    assert readback_enabled({"safetyClass": "readonly"}) is False
    assert readback_enabled({}) is False
    # 显式覆盖(挡位之上)
    assert readback_enabled({"safetyClass": "mutating", "readback": "on"}) is True
    assert readback_enabled({"safetyClass": "high-stakes", "readback": "off"}) is False
    assert readback_enabled({"safetyClass": "high-stakes", "readback": "ON"}) is True


def test_verdict_path_reconciliation():
    """坐标对账: 界内(相等/前缀/父目录)通过, 疑似越界如实列出。"""
    rb = ("目标: 重建资产。涉及 src/core/a.ts 与 src/core/sub/b.vue, "
          "另将修改 lib/util.py")
    v = verdict_of(rb, ["src/core/a.ts", "src/core/sub/"], ["资产计数 > 0 的验收要点"])
    assert "src/core/a.ts" in v["paths"]
    assert v["outScope"] == ["lib/util.py"]          # 不在边界 → 疑似越界
    assert v["pass"] is False or v["missingAcceptance"] == []
    # 全界内: 前缀匹配(目录边界/父路径)均算
    v2 = verdict_of("改 src/core/sub/b.vue 即可", ["src/core/"], [])
    assert v2["outScope"] == [] and v2["pass"] is True


def test_verdict_acceptance_coverage():
    """验收呼应: 条目关键词过半出现算覆盖; 未呼应如实列出(粗规则信号)。"""
    acc = ["arch_semantic_assets 计数大于零", "构建命令 build 通过"]
    covered = ("我的理解: 重建语义资产, 确保 arch_semantic_assets 计数大于零, "
               "涉及 src/core/a.ts")
    v = verdict_of(covered, ["src/core/a.ts"], acc)
    assert "构建命令 build 通过" in v["missingAcceptance"]
    both = covered + "; 并保证构建命令 build 通过"
    v2 = verdict_of(both, ["src/core/a.ts"], acc)
    assert v2["missingAcceptance"] == [] and v2["pass"] is True


def test_render_verdict_pass_and_signals():
    v = {"paths": ["src/a.ts"], "outScope": [], "acceptanceTotal": 2,
         "missingAcceptance": [], "pass": True}
    md = render_verdict(v)
    assert "解读校验" in md and "✅" in md and "放行" in md
    v2 = {"paths": ["src/a.ts", "lib/x.py"], "outScope": ["lib/x.py"],
          "acceptanceTotal": 1, "missingAcceptance": ["构建通过"], "pass": False}
    md2 = render_verdict(v2)
    assert "疑似越界" in md2 and "未呼应" in md2 and "纠偏" in md2


def test_confirm_injects_readback_for_high_stakes(arch_env, tmp_path, monkeypatch):
    """dispatch 集成: high-stakes 任务 confirm 后指令含「开工前解读」段;
    mutating 不含(挡位默认关)。"""
    from topoone_app_architect import store
    from topoone_app_architect.agent.execution import exec_bridge as eb
    root = tmp_path / "proj"
    root.mkdir()
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "rb", "meta": {"root": str(root)}})
    conv = store.ConversationsStore.get(conv_row["id"])
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

    t1 = eb.propose_task(conv, "高风险任务", "x",
                         {"executorType": "cline-sdk"}, safety_class="high-stakes")
    assert eb.confirm_task(t1["id"])["ok"]
    assert "开工前解读" in captured["implement"][-1]["instruction"]

    conv2 = store.ConversationsStore.create({
        "projectId": "", "title": "rb2", "meta": {"root": str(root)}})
    t2 = eb.propose_task(store.ConversationsStore.get(conv2["id"]), "普通任务", "y",
                         {"executorType": "cline-sdk"})
    assert eb.confirm_task(t2["id"])["ok"]
    assert "开工前解读" not in captured["implement"][-1]["instruction"]
    # 手动开关(显式覆盖挡位): saved 任务开启后 confirm 注入
    conv3 = store.ConversationsStore.create({
        "projectId": "", "title": "rb3", "meta": {"root": str(root)}})
    t3 = eb.propose_task(store.ConversationsStore.get(conv3["id"]), "手动开启", "z",
                         {"executorType": "cline-sdk"})
    from topoone_app_architect.agent.execution.dispatch import task_set_readback
    assert task_set_readback(t3["id"], True) is not None
    assert eb.confirm_task(t3["id"])["ok"]
    assert "开工前解读" in captured["implement"][-1]["instruction"]


def test_input_required_runs_readback_verdict(monkeypatch):
    """exec_bridge 集成: 开启任务首个 input_required → 落卡含校验附注 +
    progress.readbackDone 标记(后续问询不重复校验)。"""
    from topoone_app_architect.agent.execution import exec_bridge as eb

    appended = []
    progress_seen = {}
    task = {"id": "t1", "title": "任务", "status": "running",
            "safetyClass": "high-stakes", "progress": {}}

    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: dict(task, progress=progress_seen.get("p", {})))
    monkeypatch.setattr(eb.store.TasksStore, "update", lambda tid, d: None)
    monkeypatch.setattr(eb.store.TasksStore, "set_progress",
                        lambda tid, p: progress_seen.update({"p": p}))
    monkeypatch.setattr(eb, "_append",
                        lambda *a, **k: appended.append(a))
    monkeypatch.setattr(eb, "_publish_task", lambda *a, **k: None)
    monkeypatch.setattr(eb, "task_status_card", lambda *a, **k: None)
    monkeypatch.setattr(eb, "_resolve_boundary_files",
                        lambda rid, root, project: ["src/core/a.ts"])
    monkeypatch.setattr(eb, "_conv_root_pair", lambda cid: ("/r", "p1"))

    ctx = {"convId": "c1", "taskId": "t1", "jobId": "j1",
           "rid": "r1", "pid": "p1", "agent": "executor"}
    monkeypatch.setattr(
        eb.store.RequirementsStore, "spec_active",
        staticmethod(lambda rid: {"snapshot": {
            "acceptance": ["arch_semantic_assets 计数大于零"]}}))

    eb._handle_task_event(
        {"kind": "input_required",
         "text": "目标: 重建语义资产, arch_semantic_assets 计数大于零。涉及 src/core/a.ts"},
        ctx)
    content = appended[-1][2]
    assert "解读校验" in content and "边界对账" in content
    assert progress_seen["p"].get("readbackDone") is True

    # 第二次问询(readbackDone 已标) → 不再附校验
    appended.clear()
    eb._handle_task_event({"kind": "input_required", "text": "还有疑问…"}, ctx)
    assert "解读校验" not in appended[-1][2]
