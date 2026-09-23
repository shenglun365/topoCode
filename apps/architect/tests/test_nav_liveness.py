"""导航层惰性失效守门(cv-248 阶段二) — I2: 跨层指涉读取时校验, 缺失按规则降级。

- N3 计划步骤→已删任务: 诊断/进度锚降级 failed(重试出路可达), 不静默沿用
  旧记账误判「全部完成」
- N2 clarify_pending 帧**生灭自驱**守门: 帧源=最近 assistant 回合动作 meta
  (零写点派生)——消息删除/丢失后帧自然消失。固化此语义, 防未来回归为
  持久化写点(悬空帧会吞掉后续输入为 continuation, 功能性卡死)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_nav_liveness.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.governance import focus as focus_mod
from topoone_app_architect.agent.planning.task_plan import _plan_diagnosis
from topoone_app_architect.arch_routes import store


@pytest.fixture()
def arch(arch_env):
    return arch_env


# ── N3: 计划步骤→已删任务 降级 failed ────────────────────────────────

def test_dangling_task_step_diagnosed_as_failed(arch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = store.RequirementsStore.create({"id": "RQ-DG", "kind": "user-story",
                                          "status": "ready", "title": "T",
                                          "activeVer": 1})["id"]
    plan = [
        {"seq": 1, "title": "S1", "instruction": "x", "taskId": "task-gone",
         "status": "done"},                      # 旧记账 done, 任务行已删
        {"seq": 2, "title": "S2", "instruction": "y", "taskId": "", "status": "pending"},
    ]
    store.RequirementsStore.update(rid, {"taskPlan": plan})

    out = _plan_diagnosis(_plan_of(rid))

    assert "失败步骤" in out                      # 降级 failed, 出路=重试
    assert "全部完成" not in out                  # 不误判


def test_normal_done_plan_still_completed(arch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = store.RequirementsStore.create({"id": "RQ-OK", "kind": "user-story",
                                          "status": "ready", "title": "T",
                                          "activeVer": 1})["id"]
    t = store.TasksStore.create({"conversationId": conv["id"], "title": "S1",
                                 "instruction": "x", "status": "done",
                                 "executorType": "cline-sdk", "reqId": rid})
    store.RequirementsStore.update(rid, {"taskPlan": [
        {"seq": 1, "title": "S1", "instruction": "x", "taskId": t["id"],
         "status": "done"}]})

    out = _plan_diagnosis(_plan_of(rid))

    assert "全部完成" in out                      # 回归: 真完成语义不变


def test_plan_anchor_marks_dangling_step_failed(arch):
    """进度锚视图: 悬空步骤标记 ❌(failed 语义), 非「⬚ 待就绪」误导。"""
    from topoone_app_architect.agent.planning import task_plan as tp
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = store.RequirementsStore.create({"id": "RQ-AN", "kind": "user-story",
                                          "status": "ready", "title": "T",
                                          "activeVer": 1})["id"]
    plan = [{"seq": 1, "title": "S1", "instruction": "x",
             "taskId": "task-gone", "status": "proposed"}]
    store.RequirementsStore.update(rid, {"taskPlan": plan})
    tp._refresh_plan_anchor(conv["id"], rid, plan)

    cards = store.ConversationsStore.messages(conv["id"]) or []
    body = "\n".join(str(m.get("content") or "") for m in cards
                     if "taskPlan" in str(m.get("meta") or ""))
    assert "❌" in body and "⬚" not in body


# ── N2: clarify_pending 帧生灭自驱(零写点派生) ───────────────────────

def test_clarify_frame_dies_with_action_message(arch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    cid = conv["id"]
    row = {"id": store.next_id("m"), "conversationId": cid, "role": "assistant",
           "time": __import__("time").time() * 1000, "content": "问询正文",
           "meta": json.dumps({"guAction": "clarify-first"},
                              ensure_ascii=False)}
    store.ConversationsStore.append_message(row)

    def _pending():
        return focus_mod._pending_action(store, cid,
                                         __import__("time").time() * 1000)

    def _frames():
        return focus_mod.frames_from_entities(
            store.ConversationsStore.get(cid), [], pending=_pending())

    assert any(f.get("kind") == "clarify_pending" for f in _frames())
    store.ConversationsStore.delete_message(cid, row["id"])   # 消息删除
    assert not any(f.get("kind") == "clarify_pending" for f in _frames())


def _plan_of(rid: str) -> list:
    rows = store.RequirementsStore.get(rid) or {}
    return rows.get("taskPlan") or []
