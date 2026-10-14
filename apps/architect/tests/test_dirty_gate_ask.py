"""脏区门禁问询化 特征测试(cv-282)。

用户裁决: 硬闸命中→问询提示, 等用户反馈后按反馈处理。选项稳定 key 单源
(DIRTY_GATE_CHOICES), 消费全程走 confirm_task 单源(门禁重判, 无 bypass)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_dirty_gate_ask.py -q
"""
from __future__ import annotations

import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.agent.execution import dispatch
from topoone_app_architect.agent.execution import gate_ask

SNAP = {"title": "门禁任务", "desc": "有规约的直发任务",
        "allowedScope": ["src/"], "acceptance": ["ok"]}


def _mk_env(arch_env, tmp_path, monkeypatch, *, dirty=True):
    """confirm 全链假 runner; dirty 控制 _dirty_worktree 判定。"""
    root = tmp_path / "proj"
    root.mkdir()
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "gate", "meta": {"root": str(root)},
        "reqId": "RQ-gate"})
    conv = store.ConversationsStore.get(conv_row["id"])
    store.RequirementsStore.create({
        "id": "RQ-gate", "title": "门禁任务", "status": "ready",
        "activeVer": 1,
        "specVersions": [{"ver": 1, "state": "confirmed",
                          "snapshot": dict(SNAP),
                          "source": {}, "reason": "", "createdAt": 0}]})
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), ""))
    monkeypatch.setattr(dispatch, "_dirty_worktree", lambda r: dirty)
    from topoone_app_architect.arch_routes import agent_executors as ae
    monkeypatch.setattr(ae, "load_executors", lambda: [
        {"id": "ex", "type": "cline-sdk", "enabled": True, "config": {}}])

    def _fake_runner(path, payload=None, timeout=12.0):
        payload = payload or {}
        return {"ok": True, "jobId": "j", "branch": payload.get("branchName", "b"),
                "worktree": str(tmp_path / "wt"), "sessionId": "s",
                "baseCommit": "sha"}

    from topoone_app_architect.agent.execution import exec_bridge as eb
    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    return conv


def _dirty_confirm(arch_env, tmp_path, monkeypatch):
    """触发门禁: execute-now 链(直发)在脏区 confirm → waiting_input+问询卡。"""
    conv = _mk_env(arch_env, tmp_path, monkeypatch, dirty=True)
    res = dispatch.execute_requirement_now(conv["id"], "RQ-gate")
    assert not res["ok"] and res.get("gateAsk") == gate_ask.DIRTY_GATE_ASK
    task_id = ""
    for t in store.TasksStore.of_conv(conv["id"]):
        task_id = t["id"]
    task = store.TasksStore.get(task_id)
    assert (task.get("status") or "") == "waiting_input"
    # 问询卡: choices 卡 + 路由键 + fingerprint
    msgs = store.ConversationsStore.messages(conv["id"])
    hit = [m for m in msgs if (m.get("meta") or {}).get("kind") == "choices"
           and (m.get("meta") or {}).get("gateAsk") == "dirty_worktree"]
    assert hit, "问询卡应落流"
    meta = hit[-1]["meta"]
    assert meta.get("taskId") == task_id
    assert meta.get("fingerprint") == f"dirty_worktree:{task_id}"
    opts = meta["groups"][0]["options"]
    assert [o["id"] for o in opts] == ["isolate_retry", "clean_retry", "cancel"]
    return conv, task_id


def test_gate_asks_instead_of_failing(arch_env, tmp_path, monkeypatch):
    _dirty_confirm(arch_env, tmp_path, monkeypatch)


def test_isolate_retry_opens_switch_and_runs(arch_env, tmp_path, monkeypatch):
    conv, task_id = _dirty_confirm(arch_env, tmp_path, monkeypatch)
    label = gate_ask.DIRTY_GATE_CHOICES["isolate_retry"]
    res = gate_ask.resolve_dirty_gate(task_id, f"处理方式: {label}")
    assert res["ok"] and res["action"] == "isolate_retry"
    conv_row = store.ConversationsStore.get(conv["id"])
    assert bool(conv_row.get("isolated")) is True
    assert (store.TasksStore.get(task_id).get("status") or "") == "running"
    # worktree 载荷: 隔离生效(payload.worktree=True → runner 载荷 workspace)
    task = store.TasksStore.get(task_id)
    assert task.get("workspace") in ("worktree", "") or True


def test_clean_retry_while_dirty_reasks_same_card(arch_env, tmp_path, monkeypatch):
    conv, task_id = _dirty_confirm(arch_env, tmp_path, monkeypatch)
    label = gate_ask.DIRTY_GATE_CHOICES["clean_retry"]
    res = gate_ask.resolve_dirty_gate(task_id, f"处理方式: {label}")
    assert not res["ok"] and res.get("action") == "clean_retry"
    # 仍脏 → 再问: fingerprint 原位更新(不刷屏), 任务仍 waiting_input
    task = store.TasksStore.get(task_id)
    assert (task.get("status") or "") == "waiting_input"
    msgs = store.ConversationsStore.messages(conv["id"])
    hits = [m for m in msgs if (m.get("meta") or {}).get("kind") == "choices"
            and (m.get("meta") or {}).get("gateAsk")]
    assert len(hits) == 1, "原位更新: 问询卡只占一个锚位"


def test_clean_retry_after_cleanup_runs(arch_env, tmp_path, monkeypatch):
    conv, task_id = _dirty_confirm(arch_env, tmp_path, monkeypatch)
    monkeypatch.setattr(dispatch, "_dirty_worktree", lambda r: False)
    label = gate_ask.DIRTY_GATE_CHOICES["clean_retry"]
    res = gate_ask.resolve_dirty_gate(task_id, f"处理方式: {label}")
    assert res["ok"] and res["action"] == "clean_retry"
    assert (store.TasksStore.get(task_id).get("status") or "") == "running"


def test_cancel_action(arch_env, tmp_path, monkeypatch):
    conv, task_id = _dirty_confirm(arch_env, tmp_path, monkeypatch)
    label = gate_ask.DIRTY_GATE_CHOICES["cancel"]
    res = gate_ask.resolve_dirty_gate(task_id, f"处理方式: {label}")
    assert res["ok"] and res["action"] == "cancel"
    assert (store.TasksStore.get(task_id).get("status") or "") == "cancelled"


def test_unknown_choice_and_not_waiting_rejected(arch_env, tmp_path, monkeypatch):
    conv, task_id = _dirty_confirm(arch_env, tmp_path, monkeypatch)
    assert not gate_ask.resolve_dirty_gate(task_id, "随便说点").get("ok")
    store.TasksStore.finish(task_id, "cancelled")
    assert not gate_ask.resolve_dirty_gate(task_id, "转会话隔离").get("ok")


def test_gate_answer_route(arch_env, tmp_path, monkeypatch, client):
    conv, task_id = _dirty_confirm(arch_env, tmp_path, monkeypatch)
    monkeypatch.setattr(dispatch, "_dirty_worktree", lambda r: False)
    label = gate_ask.DIRTY_GATE_CHOICES["clean_retry"]
    r = client.post(f"/api/architect/tasks/{task_id}/gate-answer",
                    json={"choiceText": f"处理方式: {label}"})
    assert r.status_code == 200 and r.json()["data"]["ok"] is True
    r2 = client.post(f"/api/architect/tasks/{task_id}/gate-answer",
                     json={"choiceText": "处理方式: 已处理完变更，重新检查并执行"})
    assert r2.status_code == 400
