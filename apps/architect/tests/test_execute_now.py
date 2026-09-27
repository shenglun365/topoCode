"""立即执行(需求单任务直发) 特征测试(cv-281)。

用户裁决: 免 GU 计划/确认门——需求最新版直接构造单任务并立即执行;
单源复用 propose_task→confirm_task(规约全文 confirm 时自动随注入)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_execute_now.py -q
"""
from __future__ import annotations

import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.agent.execution import dispatch

SNAP = {
    "title": "直发需求",
    "desc": "把资产重建需求直发为单任务执行",
    "allowedScope": ["src/"],
    "designMd": "用现成解析管道",
    "acceptance": ["资产计数 > 0"],
}


def _mk_env(arch_env, tmp_path, monkeypatch, with_spec=True, req_id="RQ-now"):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "now", "meta": {"root": str(tmp_path)},
        "reqId": req_id if with_spec else ""})
    conv = store.ConversationsStore.get(conv_row["id"])
    if with_spec:
        store.RequirementsStore.create({
            "id": req_id, "title": "直发需求", "status": "ready",
            "analysis": {"allowedScope": ["src/"]}, "activeVer": 1,
            "specVersions": [{"ver": 1, "state": "confirmed",
                              "snapshot": dict(SNAP),
                              "source": {}, "reason": "", "createdAt": 0}]})
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path), ""))
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
    return conv, captured


def test_execute_now_happy_path(arch_env, tmp_path, monkeypatch):
    conv, captured = _mk_env(arch_env, tmp_path, monkeypatch)
    res = dispatch.execute_requirement_now(conv["id"], "RQ-now")
    assert res["ok"], res
    task = store.TasksStore.get(res["taskId"]) or {}
    assert task.get("status") == "running"
    assert task.get("reqId") == "RQ-now"
    # 单源链: confirm 载荷 instruction 含规约注入(上下文包契约), 非裸 desc
    payload = captured["implement"][-1]
    assert "把资产重建需求直发为单任务执行" in (payload.get("instruction") or "")
    assert payload.get("contextPack")
    # 任务卡落流
    msgs = store.ConversationsStore.messages(conv["id"])
    assert any((m.get("meta") or {}).get("kind") == "task_card" for m in msgs)


def test_execute_now_rejects_unbound_req(arch_env, tmp_path, monkeypatch):
    conv, _cap = _mk_env(arch_env, tmp_path, monkeypatch, with_spec=False)
    res = dispatch.execute_requirement_now(conv["id"], "RQ-now")
    assert not res["ok"] and res["error"] == "req-not-bound-to-conv"


def test_execute_now_rejects_missing_snapshot(arch_env, tmp_path, monkeypatch):
    conv, _cap = _mk_env(arch_env, tmp_path, monkeypatch, with_spec=False)
    store.ConversationsStore.update(conv["id"], {"reqId": "RQ-now"})
    res = dispatch.execute_requirement_now(conv["id"], "RQ-now")
    assert not res["ok"] and res["error"] == "spec-snapshot-missing"


def test_execute_now_rejects_active_task(arch_env, tmp_path, monkeypatch):
    conv, _cap = _mk_env(arch_env, tmp_path, monkeypatch)
    first = dispatch.execute_requirement_now(conv["id"], "RQ-now")
    assert first["ok"]
    second = dispatch.execute_requirement_now(conv["id"], "RQ-now")
    assert not second["ok"] and second["error"] == "task-active"


def test_execute_now_route(arch_env, tmp_path, monkeypatch, client):
    conv, _cap = _mk_env(arch_env, tmp_path, monkeypatch)
    r = client.post("/api/architect/requirements/RQ-now/execute-now",
                    json={"convId": conv["id"]})
    assert r.status_code == 200
    assert r.json()["data"]["ok"] is True
    r2 = client.post("/api/architect/requirements/RQ-now/execute-now",
                     json={"convId": ""})
    assert r2.status_code == 400
