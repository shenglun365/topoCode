"""信息流优化特征测试(批戊 L1/L3) — 预填双发合一/进度锚原位/卡尾分叉/中文标题。

背景: cv-240/241 实证每步 3-4 条消息(任务卡+➡️receipt 双发、英文标题、
固定话术重复、无全局进度视图)。本批: 预填状态并入计划进度锚(原位更新,
N 步计划只占 1 个锚位)、步骤卡尾精简、拆步标题中文约束。

Run: cd <repo> && python -m pytest apps/architect/tests/test_infoflow.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.collab import cards as cards_mod
from topoone_app_architect.agent.planning import task_plan as tp
from topoone_app_architect.agent.planning.task_plan import _plan_diagnosis
from topoone_app_architect import store


@pytest.fixture()
def arch(arch_env):
    return arch_env


def _mk_req(rid="RQ-IF", status="ready"):
    store.RequirementsStore.create({"id": rid, "kind": "user-story",
                                    "status": status, "title": "T",
                                    "activeVer": 1})
    return rid


# ── L3: 进度锚原位更新 ────────────────────────────────────────────────

def test_plan_anchor_upsert_single_row(arch):
    """同 requirementId 多次刷新 → 消息表仅 1 条 taskPlan 行, content 原位变。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = _mk_req()
    _tx = store.TasksStore.create({"id": "task-x", "conversationId": conv["id"],
                                   "title": "配置", "instruction": "y",
                                   "status": "saved", "executorType": "cline-sdk",
                                   "reqId": rid})
    tp._refresh_plan_anchor(conv["id"], rid, [
        {"seq": 1, "title": "初始化", "taskId": "", "status": "done"},
        {"seq": 2, "title": "配置", "taskId": "", "status": "pending"}])
    tp._refresh_plan_anchor(conv["id"], rid, [
        {"seq": 1, "title": "初始化", "taskId": "", "status": "done"},
        {"seq": 2, "title": "配置", "taskId": _tx["id"], "status": "saved"}])
    rows = [m for m in store.ConversationsStore.messages(conv["id"])
            if (m.get("meta") or "") and "taskPlan" in str(m.get("meta"))]
    assert len(rows) == 1, f"进度锚应单行原位, got {len(rows)}"
    assert "➡️ 2." in rows[0]["content"] and "✅ 1." in rows[0]["content"]


def test_plan_anchor_marks_and_tail(arch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = _mk_req()
    store.TasksStore.create({"conversationId": conv["id"], "title": "S2",
                             "instruction": "y", "status": "saved",
                             "executorType": "cline-sdk", "reqId": rid})
    tp._refresh_plan_anchor(conv["id"], rid, [
        {"seq": 1, "title": "S1", "taskId": "", "status": "done"},
        {"seq": 2, "title": "S2", "taskId": "task-1", "status": "pending"}])
    row = [m for m in store.ConversationsStore.messages(conv["id"])
           if "taskPlan" in str(m.get("meta") or "")][0]
    # 步骤态读绑定任务行(saved → ➡️), 尾注指认待确认步骤
    assert "➡️ 2." in row["content"]
    assert "已预填待确认" in row["content"]


# ── L1①: 预填不再双发 ────────────────────────────────────────────────

def test_prefill_no_standalone_receipt(arch, monkeypatch):
    """on_plan_task_done 预填后不再落「➡️ 已预填」独立消息(状态入进度锚)。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = _mk_req()
    t1 = store.TasksStore.create({"conversationId": conv["id"], "title": "S1",
                                  "instruction": "x", "status": "done",
                                  "executorType": "cline-sdk", "reqId": rid})
    save_plan_rows = [
        {"seq": 1, "title": "S1", "instruction": "x", "taskId": t1["id"],
         "status": "done"},
        {"seq": 2, "title": "S2", "instruction": "y", "taskId": "",
         "status": "pending", "depends": [1]},
    ]
    tp.save_plan(rid, save_plan_rows)
    proposed = []

    def _fake_propose(conv_, rid_, idx_, executor_hint=None):
        task = store.TasksStore.create({"conversationId": conv_["id"],
                                        "title": f"S{idx_ + 1}", "instruction": "y",
                                        "status": "saved",
                                        "executorType": "cline-sdk",
                                        "reqId": rid_})
        proposed.append(task["id"])
        plan = tp.get_plan(rid_)
        plan[idx_]["taskId"] = task["id"]
        plan[idx_]["status"] = "proposed"
        tp.save_plan(rid_, plan)
        return {"ok": True, "task": task}

    monkeypatch.setattr(tp, "propose_plan_step", _fake_propose)
    tp.on_plan_task_done(conv["id"], t1["id"])
    tail = store.ConversationsStore.messages(conv["id"])
    prefill_texts = [m for m in tail
                     if "已预填" in str(m.get("content") or "")
                     and "taskPlan" not in str(m.get("meta") or "")]
    assert prefill_texts == [], "独立「➡️ 已预填」receipt 应退役(并入进度锚)"
    assert proposed, "预填动作本身应发生"


# ── L1④: 步骤卡尾精简 ────────────────────────────────────────────────

def test_dispatch_card_tail_fork(arch, monkeypatch):
    """propose_task card_tail=plan → 卡尾精简; 缺省 full 话术保留。"""
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    from topoone_app_architect.agent.execution import dispatch as dp
    monkeypatch.setattr(dp, "_flow_recompute", lambda *a, **k: None)
    monkeypatch.setattr(dp, "_telemetry", lambda *a, **k: None)
    monkeypatch.setattr(dp, "_publish_task", lambda *a, **k: None)
    t_full = dp.propose_task(conv, "常规卡", "目标: x")
    t_plan = dp.propose_task(conv, "计划步骤卡", "目标: y", card_tail="plan")
    msgs = store.ConversationsStore.messages(conv["id"])
    by_task = {}
    for m in msgs:
        try:
            meta = json.loads(m.get("meta") or "{}")
        except (TypeError, ValueError):
            meta = m.get("meta") or {}
        if "task_card" in str(meta):
            by_task[str(meta.get("taskId") or "")] = m["content"]
    c_full = by_task.get(t_full["id"], "")
    c_plan = by_task.get(t_plan["id"], "")
    assert "可继续对话调整, 或忽略本卡" in c_full
    assert "可继续对话调整" not in c_plan and "待确认执行" in c_plan


# ── L1③: 拆步标题中文约束 ────────────────────────────────────────────

def test_split_prompt_requires_chinese_titles(arch):
    """拆步 prompt 应约束 title 简体中文(≤16 字)——cv-240 英文标题根治面。"""
    import inspect
    src = inspect.getsource(tp.split_tasks_llm)
    assert "简体中文" in src and "≤16 字" in src


# ── 三分态诊断(批戊已立项, 信息流文案面回归) ─────────────────────────

def test_plan_diagnosis_three_states(arch):
    from topoone_app_architect import store as _s
    rid = _mk_req("RQ-IF2")
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    # cv-248 I2: taskId 非空必须指向真实任务行(悬空=failed 降级语义)
    def _task(tid, status):
        return _s.TasksStore.create({"id": tid, "conversationId": conv["id"],
                                     "title": tid, "instruction": "x",
                                     "status": status,
                                     "executorType": "cline-sdk",
                                     "reqId": rid})["id"]
    _ta = _task("task-a", "done")
    _tb = _task("task-b", "saved")
    plan = [
        {"seq": 1, "title": "A", "taskId": _ta, "status": "done"},
        {"seq": 2, "title": "B", "taskId": _tb, "status": "pending"},
    ]
    d = _plan_diagnosis(plan)
    assert "待确认" in d
    _tx = _task("task-x", "failed")
    plan2 = [{"seq": 1, "title": "A", "taskId": _tx, "status": "failed"}]
    assert "重试" in _plan_diagnosis(plan2)
    _ty = _task("task-y", "done")
    plan3 = [{"seq": 1, "title": "A", "taskId": _ty, "status": "done"}]
    assert "全部完成" in _plan_diagnosis(plan3)
