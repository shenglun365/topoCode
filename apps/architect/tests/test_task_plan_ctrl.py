"""任务计划总控(环节十四)回归: 计划生成 / 顺序下发 / done 钩子 / 汇总。

Run: cd <repo> && python -m pytest apps/architect/tests/test_task_plan_ctrl.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store


def _mk_env(arch_env, tmp_path, monkeypatch, mode="T2", split=None):
    """T2 会话(绑需求) + mock runner + mock LLM 拆步。"""
    rid = "RQ-tp"
    conv_row = store.ConversationsStore.create({
        "projectId": "proj-tp", "title": "tp",
        "meta": {"root": str(tmp_path / "p")}, "reqId": rid,
        "analysisMode": mode})
    conv = store.ConversationsStore.get(conv_row["id"])
    store.RequirementsStore.create({
        "id": rid, "title": "总需求", "status": "ready", "projectId": "proj-tp",
        "analysis": {"allowedScope": ["src/"], "requirementMd": "需求文本"},
        "activeVer": 1,
        "specVersions": [{"ver": 1, "state": "confirmed",
                          "snapshot": {"allowedScope": ["src/"], "designMd": "方案"},
                          "source": {}, "reason": "", "createdAt": 0}]})
    from topoone_app_architect.agent.execution import exec_bridge as eb
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path / "p"), "proj-tp"))
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex-tp", "type": "cline-sdk", "enabled": True, "config": {}}])
    calls = {"implement": []}

    def _fake_runner(path, payload=None, timeout=12.0):
        calls["implement"].append((path, payload))
        if path == "/api/implement":
            return {"ok": True, "jobId": f"job-{len(calls['implement'])}",
                    "branch": f"task/{len(calls['implement'])}",
                    "worktree": str(tmp_path / "wt"), "sessionId": "s",
                    "baseCommit": "sha"}
        return {"ok": True}

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    if split is not None:
        import topoone_app_architect.agent.planning.task_plan as tp
        monkeypatch.setattr(tp, "split_tasks_llm", lambda text, policy=None: split)
    from topoone_app_architect.agent.perception import commands as cmds
    return conv, cmds, eb, calls


def test_run_execute_t2_generates_plan_and_first_card(arch_env, tmp_path, monkeypatch):
    split = [{"title": "模块A", "instruction": "实现 A"}, 
             {"title": "模块B", "instruction": "实现 B"}]
    conv, cmds, eb, calls = _mk_env(arch_env, tmp_path, monkeypatch, split=split)
    res = cmds.run_execute(conv)
    assert res["ok"] and "计划" in res["receipt"]
    plan = store.RequirementsStore.get("RQ-tp")["taskPlan"]
    assert len(plan) == 2 and plan[0]["status"] == "proposed"
    assert plan[0]["taskId"] == res["task"]["id"]
    msgs = store.ConversationsStore.messages(conv["id"])
    assert any((m.get("meta") or {}).get("kind") == "taskPlan" for m in msgs)
    # 第一步卡标题带序号; 指令含计划上下文
    assert "步骤1/2" in res["task"]["title"]
    assert "任务计划: 步骤 1/2" in res["task"]["instruction"]
    # 只建了一张卡(第二步未预填)
    cards = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_card"]
    assert len(cards) == 1


def test_run_execute_t0_skips_planning(arch_env, tmp_path, monkeypatch):
    conv, cmds, eb, calls = _mk_env(arch_env, tmp_path, monkeypatch, mode="quick",
                                    split=[{"title": "A", "instruction": "a"},
                                           {"title": "B", "instruction": "b"}])
    res = cmds.run_execute(conv)
    assert res["ok"] and "计划" not in res.get("receipt", "")
    assert store.RequirementsStore.get("RQ-tp")["taskPlan"] in (None, "")
    assert "任务计划: 步骤" not in res["task"]["instruction"]


def test_done_hook_prefills_next_and_finishes(arch_env, tmp_path, monkeypatch):
    split = [{"title": "A", "instruction": "实现 A"},
             {"title": "B", "instruction": "实现 B"}]
    conv, cmds, eb, calls = _mk_env(arch_env, tmp_path, monkeypatch, split=split)
    r1 = cmds.run_execute(conv)
    t1 = r1["task"]["id"]
    # 步骤1 完成 → 自动预填步骤2
    store.TasksStore.update(t1, {"branch": "task/1"})
    store.TasksStore.finish(t1, "done", "模块 A 完成")
    eb._handle_task_event(
        {"kind": "done", "text": "A 完成 [[IMPLEMENT_DONE]]", "changedFiles": ["src/a.py"]},
        {"convId": conv["id"], "taskId": t1, "jobId": "j1", "pid": "proj-tp",
         "agent": "cline", "rid": "RQ-tp"})
    plan = store.RequirementsStore.get("RQ-tp")["taskPlan"]
    assert plan[0]["status"] == "done" and plan[0]["result"]
    assert plan[1]["status"] == "proposed" and plan[1]["taskId"]
    msgs = store.ConversationsStore.messages(conv["id"])
    assert any("已预填" in (m.get("content") or "") for m in msgs)
    # 步骤2 完成 → 汇总回执(含各步骤分支与合并提醒)
    t2 = plan[1]["taskId"]
    store.TasksStore.update(t2, {"branch": "task/2"})
    store.TasksStore.finish(t2, "done", "模块 B 完成")
    eb._handle_task_event(
        {"kind": "done", "text": "B 完成 [[IMPLEMENT_DONE]]", "changedFiles": ["src/b.py"]},
        {"convId": conv["id"], "taskId": t2, "jobId": "j2", "pid": "proj-tp",
         "agent": "cline", "rid": "RQ-tp"})
    msgs = store.ConversationsStore.messages(conv["id"])
    done = [m for m in msgs if (m.get("meta") or {}).get("kind") == "taskPlanDone"]
    assert done and "任务计划全部完成" in done[-1]["content"]
    assert "合并" in done[-1]["content"]


def test_failed_step_redispatches_on_next_execute(arch_env, tmp_path, monkeypatch):
    split = [{"title": "A", "instruction": "实现 A"},
             {"title": "B", "instruction": "实现 B"}]
    conv, cmds, eb, calls = _mk_env(arch_env, tmp_path, monkeypatch, split=split)
    r1 = cmds.run_execute(conv)
    t1 = r1["task"]["id"]
    store.TasksStore.finish(t1, "failed", "编译失败")
    eb._handle_task_event(
        {"kind": "failed", "text": "编译失败"},
        {"convId": conv["id"], "taskId": t1, "jobId": "j1", "pid": "proj-tp",
         "agent": "cline", "rid": "RQ-tp"})
    plan = store.RequirementsStore.get("RQ-tp")["taskPlan"]
    assert plan[0]["status"] == "failed"
    # 批戊: 再次 /执行 → 三分态诊断(失败态指引「重试」), 不再暗推进
    r2 = cmds.run_execute(conv)
    assert r2["ok"] is False and "重试" in r2["receipt"]
    # 重试走焦点动作执行器: recent.failed 指代 → retry_failed_step
    from topoone_app_architect.agent.governance.focus import build_focus, resolve_intent
    focus = build_focus(conv["id"])
    res = resolve_intent("retry", focus)
    assert res["action"] == "retry_failed" and res["frame"]["taskId"] == t1
    from topoone_app_architect.agent.planning.task_plan import retry_failed_step
    r3 = retry_failed_step(conv, t1)
    assert r3["ok"] and "已重发" in r3["receipt"]
    plan2 = store.RequirementsStore.get("RQ-tp")["taskPlan"]
    assert plan2[0]["status"] == "proposed" and plan2[0]["taskId"] != t1
    assert plan2[1]["status"] == "pending"


def test_finished_plan_blocks_reexecute(arch_env, tmp_path, monkeypatch):
    split = [{"title": "A", "instruction": "a"}, {"title": "B", "instruction": "b"}]
    conv, cmds, eb, calls = _mk_env(arch_env, tmp_path, monkeypatch, split=split)
    r1 = cmds.run_execute(conv)
    store.TasksStore.finish(r1["task"]["id"], "done", "A ok")
    eb._handle_task_event(
        {"kind": "done", "text": "ok [[IMPLEMENT_DONE]]", "changedFiles": []},
        {"convId": conv["id"], "taskId": r1["task"]["id"], "jobId": "j1",
         "pid": "proj-tp", "agent": "cline", "rid": "RQ-tp"})
    plan = store.RequirementsStore.get("RQ-tp")["taskPlan"]
    t2 = plan[1]["taskId"]
    store.TasksStore.finish(t2, "done", "B ok")
    eb._handle_task_event(
        {"kind": "done", "text": "ok [[IMPLEMENT_DONE]]", "changedFiles": []},
        {"convId": conv["id"], "taskId": t2, "jobId": "j2",
         "pid": "proj-tp", "agent": "cline", "rid": "RQ-tp"})
    r3 = cmds.run_execute(conv)
    assert not r3["ok"] and "全部完成" in r3["receipt"]


def test_split_cards_vocabulary_registered(arch_env):
    from topoone_app_architect.agent.collab.cards import land
    m = land("cv-x", "计划", kind="taskPlan", requirementId="RQ-1", total=2)
    assert m is None or m  # cv 不存在 → None(不炸); 关键是 kind 合法不 raise
    try:
        land("cv-x", "x", kind="bogusPlan")
        raised = False
    except ValueError:
        raised = True
    assert raised
