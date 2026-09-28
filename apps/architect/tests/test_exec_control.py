"""执行详情窗(cv-285) 特征测试: 双源统一视图模型 + 单一控制面。

方案甲(用户裁决): 任务行与直通作业同窗体(execution_detail 统一形状);
控制 pause/resume/stop/input 单面分发——任务源走 task_input 单源,
直通源走 runner 端点+JobCard 状态回写, 无并行控制通道。

Run: cd <repo> && python -m pytest apps/architect/tests/test_exec_control.py -q
"""
from __future__ import annotations

import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect import store
from topoone_app_architect.agent.execution import exec_control as ec


def _mk_task_env(arch_env, tmp_path, monkeypatch, *, status="running"):
    conv_row = store.ConversationsStore.create({
        "projectId": "", "title": "ctl", "meta": {"root": str(tmp_path)}})
    conv_id = conv_row["id"]
    task = store.TasksStore.create({
        "conversationId": conv_id, "projectId": "", "reqId": "RQ-ctl",
        "title": "控制面任务", "instruction": "做 X",
        "status": status, "executorType": "cline-sdk",
        "runnerJobId": "job-ctl-1", "specVer": 2,
        "branch": "topo/req-ctl"})
    captured = {"abort": [], "finish": [], "input": [], "client_input": [],
                "start": []}

    def _fake_runner(path, payload=None, timeout=12.0):
        if path.endswith("/abort"):
            captured["abort"].append((path, payload))
            return {"ok": True}
        if path.endswith("/finish"):
            captured["finish"].append((path, payload))
            return {"ok": True}
        if path.endswith("/input"):
            captured["input"].append((path, payload))
            return {"ok": True, "queued": False}
        return {"ok": True}

    from topoone_app_architect.agent.execution import exec_bridge as eb
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(tmp_path), ""))
    monkeypatch.setattr(eb, "_runner", _fake_runner)

    class _Snap:
        ok = True
        status = "running"
        session_id = "s-ctl"
        raw: dict = {}

    class _Client:
        def snapshot(self, job_id, since=0, timeout=12.0):
            return _Snap()

        def input(self, job_id, text, steer=False, timeout=15.0):
            captured["client_input"].append((job_id, text, steer))
            from topoone_app_architect.agent.execution.runner_client import InputResult
            return InputResult(ok=True, queued=False, delivery="steered")

        def start_implement(self, payload, timeout):
            captured["start"].append(payload)

            class _S:
                ok = True
                job_id = "job-new-1"
                error = ""
                branch = "topo/req-ctl"
                worktree = str(tmp_path / "wt")
                workspace = "inplace"
                session_id = "s-new"
                base_commit = "sha"
                raw: dict = {}

            return _S()

    monkeypatch.setattr(eb, "_client", lambda: _Client())
    return conv_id, task["id"], captured


def test_detail_task_source(arch_env, tmp_path, monkeypatch):
    conv_id, task_id, _cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    res = ec.execution_detail(conv_id, task_id=task_id)
    assert res["ok"] and res["source"] == "task"
    assert res["title"] == "控制面任务" and res["specVer"] == 2
    assert res["instruction"] == "做 X" and res["branch"] == "topo/req-ctl"
    assert res["jobId"] == "job-ctl-1" and res["runnerStatus"]


def test_detail_no_target(arch_env, tmp_path, monkeypatch):
    conv_id, _t, _c = _mk_task_env(arch_env, tmp_path, monkeypatch)
    assert not ec.execution_detail(conv_id)["ok"]
    assert not ec.execution_detail(conv_id, task_id="task-none")["ok"]


def test_control_pause_and_resume_task(arch_env, tmp_path, monkeypatch):
    conv_id, task_id, cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    res = ec.control_execution(conv_id, "pause", task_id=task_id)
    assert res["ok"] and cap["abort"], "pause=runner abort"
    res = ec.control_execution(conv_id, "resume", task_id=task_id)
    assert res["ok"] and cap["client_input"], "resume=task_input(继续) 单源"
    res = ec.control_execution(conv_id, "input", task_id=task_id,
                               text="补充: 边界文件是 src/a.ts")
    assert res["ok"] and cap["client_input"][-1][1].startswith("补充")


def test_control_stop_task_finishes_cancelled(arch_env, tmp_path, monkeypatch):
    conv_id, task_id, cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    res = ec.control_execution(conv_id, "stop", task_id=task_id)
    assert res["ok"] and cap["finish"], "stop=runner finish(保留 worktree)"
    task = store.TasksStore.get(task_id)
    assert (task.get("status") or "") == "cancelled"
    assert "停止" in str(task.get("resultMd") or "")
    # cv-285 终态幂等守卫: stop 后泵迟到的 done/failed 事件不覆写 cancelled
    from topoone_app_architect.agent.execution.exec_bridge import _handle_task_event, _task_ctx
    ctx = _task_ctx(conv_id, task_id, "job-ctl-1", "", "cline-sdk")
    _handle_task_event({"kind": "done", "text": "迟到完成", "changedFiles": []}, ctx)
    _handle_task_event({"kind": "failed", "text": "迟到失败"}, ctx)
    task = store.TasksStore.get(task_id)
    assert (task.get("status") or "") == "cancelled", "终态不覆写"


def test_control_job_source_proxy(arch_env, tmp_path, monkeypatch):
    conv_id, _t, _c = _mk_task_env(arch_env, tmp_path, monkeypatch)
    from topoone_app_architect.agent.execution import proxy
    proxy._PROXY_JOBS[conv_id] = {"job_id": "job-px-9", "executor_type": "cline-sdk"}
    conv = store.ConversationsStore.get(conv_id)
    from topoone_app_architect.agent.execution import exec_bridge as eb
    eb._append(conv_id, "assistant", "🔗 已直通执行器",
               msg_meta={"kind": "proxy", "jobId": "job-px-9", "jobCard": 1,
                         "jobState": "running",
                         "fingerprint": proxy._job_card_fp(conv_id)})
    res = ec.execution_detail(conv_id, job_id="job-px-9")
    assert res["ok"] and res["source"] == "job"
    assert res["title"] == "编码执行器会话" and res["status"] == "running"
    r1 = ec.control_execution(conv_id, "pause", job_id="job-px-9")
    assert r1["ok"]
    assert _jobcard_state(conv_id) == "idle"
    r2 = ec.control_execution(conv_id, "input", job_id="job-px-9",
                              text="补充指引")
    assert r2["ok"] and _jobcard_state(conv_id) == "running"
    r3 = ec.control_execution(conv_id, "stop", job_id="job-px-9")
    assert r3["ok"]
    assert _jobcard_state(conv_id) == "ended"
    assert conv_id not in proxy._PROXY_JOBS, "终态清句柄"


def _jobcard_state(conv_id: str) -> str:
    for m in store.ConversationsStore.messages(conv_id, limit=20):
        meta = m.get("meta") or {}
        if meta.get("kind") == "proxy" and meta.get("jobCard"):
            return str(meta.get("jobState") or "")
    return ""


def test_control_unknown_action(arch_env, tmp_path, monkeypatch):
    conv_id, task_id, _c = _mk_task_env(arch_env, tmp_path, monkeypatch)
    assert not ec.control_execution(conv_id, "reboot", task_id=task_id)["ok"]


def test_failed_task_input_retries_with_supplement(arch_env, tmp_path, monkeypatch):
    """cv-285c 用户实证: failed 卡转达被 task-not-active 静默拒绝——
    语义修正: 附【用户补充】翻回 saved + confirm 重跑(失败分支续跑)。"""
    conv_id, task_id, _cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    store.TasksStore.finish(task_id, "failed", "炸了")
    res = ec.control_execution(conv_id, "input", task_id=task_id,
                               text="补充: 排除 node_modules 再扫描")
    assert res["ok"] and res.get("retried"), res
    task = store.TasksStore.get(task_id)
    assert (task.get("status") or "") == "running"
    assert "【用户补充(失败重试)】补充: 排除 node_modules 再扫描" in (
        task.get("instruction") or "")


def test_failed_task_resume_retries_plain(arch_env, tmp_path, monkeypatch):
    conv_id, task_id, _cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    store.TasksStore.finish(task_id, "failed", "炸了")
    res = ec.control_execution(conv_id, "resume", task_id=task_id)
    assert res["ok"] and res.get("retried")
    assert (store.TasksStore.get(task_id).get("status") or "") == "running"


def test_cancelled_task_input_rejected(arch_env, tmp_path, monkeypatch):
    conv_id, task_id, _cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    store.TasksStore.finish(task_id, "cancelled")
    res = ec.control_execution(conv_id, "input", task_id=task_id, text="x")
    assert not res["ok"] and res["error"] == "task-terminal"
    r = client_route_cancelled(arch_env, tmp_path, task_id)
    assert r.status_code == 400


def test_cancelled_task_resume_revives(arch_env, tmp_path, monkeypatch):
    """cv-285d: cancelled 卡有再执行入口——显式 resume(ST.TASK_REVIVABLE)
    经 confirm 单门复活重跑; 被动 input 仍拒绝(同词汇两动作分权)。"""
    conv_id, task_id, _cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    store.TasksStore.finish(task_id, "cancelled", "用户停止")
    res = ec.control_execution(conv_id, "resume", task_id=task_id)
    assert res["ok"] and res.get("retried"), res
    task = store.TasksStore.get(task_id)
    assert (task.get("status") or "") == "running"
    # 指令原样(无补充段)——重新执行 ≠ 补充重试
    assert "用户补充" not in str(task.get("instruction") or "")


def test_ignored_task_resume_rejected(arch_env, tmp_path, monkeypatch):
    """ignored 不在 REVIVABLE 词汇——用户主动忽略不复活。"""
    conv_id, task_id, _cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    store.TasksStore.finish(task_id, "ignored")
    res = ec.control_execution(conv_id, "resume", task_id=task_id)
    assert not res["ok"]


def test_confirm_revives_cancelled_at_dispatch_gate(arch_env, tmp_path, monkeypatch):
    """confirm 单门(唯一再执行门)直接消费 REVIVABLE 词汇。"""
    conv_id, task_id, _cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    store.TasksStore.finish(task_id, "cancelled", "用户停止")
    from topoone_app_architect.agent.execution import dispatch
    res = dispatch.confirm_task(task_id)
    assert res["ok"], res
    assert (store.TasksStore.get(task_id).get("status") or "") == "running"


def client_route_cancelled(arch_env, tmp_path, task_id):
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    c = TestClient(build_app(data_dir=arch_env))
    return c.post("/api/architect/execution/control",
                  json={"convId": "cv-1", "action": "input",
                        "taskId": task_id, "text": "x"})


def test_routes_roundtrip(arch_env, tmp_path, monkeypatch, client):
    conv_id, task_id, cap = _mk_task_env(arch_env, tmp_path, monkeypatch)
    r = client.get(f"/api/architect/execution/detail?convId={conv_id}&taskId={task_id}")
    assert r.status_code == 200 and r.json()["data"]["source"] == "task"
    r2 = client.post("/api/architect/execution/control", json={
        "convId": conv_id, "action": "pause", "taskId": task_id})
    assert r2.status_code == 200 and r2.json()["data"]["ok"] is True
    r3 = client.post("/api/architect/execution/control", json={
        "convId": conv_id, "action": "reboot", "taskId": task_id})
    assert r3.status_code == 400
