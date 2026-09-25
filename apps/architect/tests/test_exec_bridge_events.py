"""exec_bridge v2 事件面测试（cline 流式 kind + /approve 指令解析）。

Run: cd <repo> && python -m pytest apps/architect/tests/test_exec_bridge_events.py -q
"""
from __future__ import annotations

import os
import sys
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from topoone_app_architect.agent.execution import exec_bridge as eb


def _ctx():
    return {"convId": "c1", "taskId": "t1", "jobId": "j1",
            "rid": "r1", "pid": "p1", "agent": "executor"}


def _task(progress=None):
    return {"id": "t1", "title": "任务", "status": "running",
            "branch": "exec/x", "progress": progress or {}}


def test_text_event_becomes_progress_not_message(monkeypatch):
    """text 流式片段 → 进度预览, 不落会话消息（防刷屏）。"""
    appended = []
    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: _task())
    monkeypatch.setattr(eb.store.TasksStore, "set_progress", lambda tid, p: None)
    monkeypatch.setattr(eb, "_append", lambda *a, **k: appended.append(a))
    monkeypatch.setattr(eb, "_publish_progress", lambda *a, **k: None)
    eb._handle_task_event({"kind": "text", "text": "正在分析代码…"}, _ctx())
    assert appended == []


def test_tool_event_updates_progress(monkeypatch):
    seen = {}
    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: _task())
    monkeypatch.setattr(eb.store.TasksStore, "set_progress",
                        lambda tid, p: seen.update(p))
    monkeypatch.setattr(eb, "_publish_progress", lambda c, t, p: seen.update(p))
    monkeypatch.setattr(eb, "_append", lambda *a, **k: None)
    eb._handle_task_event({"kind": "tool", "text": "▶ editor",
                           "toolName": "editor"}, _ctx())
    assert seen.get("lastTool") == "editor"


def test_approval_request_lands_actionable_message(monkeypatch):
    """审批请求 → 可操作消息（meta 携 jobId/requestId）。"""
    captured = {}

    def fake_append(conv_id, role, content, msg_meta=None, **kw):
        captured["meta"] = msg_meta
        captured["content"] = content

    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: _task())
    monkeypatch.setattr(eb, "_append", fake_append)
    eb._handle_task_event({"kind": "approval_request",
                           "text": "工具 editor 等待确认",
                           "requestId": "apr-9", "toolName": "editor"}, _ctx())
    assert captured["meta"]["kind"] == "task_approval"
    assert captured["meta"]["approvalRequestId"] == "apr-9"
    assert "apr-9" in captured["content"]


def test_notice_and_turn_outcome_are_silent(monkeypatch):
    appended = []
    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: _task())
    monkeypatch.setattr(eb, "_append", lambda *a, **k: appended.append(a))
    monkeypatch.setattr(eb, "_publish_progress", lambda *a, **k: None)
    eb._handle_task_event({"kind": "notice", "text": "compaction"}, _ctx())
    eb._handle_task_event({"kind": "turn_outcome", "text": "done",
                           "status": "done"}, _ctx())
    assert appended == []


def test_task_input_approve_command(monkeypatch):
    """/approve {id} → runner approval 端点（非回合输入）。"""
    calls = {}

    def fake_runner(path, payload=None, timeout=12.0):
        calls["path"], calls["payload"] = path, payload
        return {"ok": True}

    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: {
        "id": "t1", "status": "running", "runnerJobId": "j1",
        "conversationId": "c1", "title": "任务"})
    monkeypatch.setattr(eb, "_runner", fake_runner)
    monkeypatch.setattr(eb, "_append", lambda *a, **k: None)
    r = eb.task_input("t1", "/approve apr-3")
    assert r["ok"] is True and r.get("approval") is True
    assert "/api/implement/j1/approval" in calls["path"]
    assert calls["payload"] == {"requestId": "apr-3", "approved": True,
                                "reason": "approved"}


def test_task_input_deny_with_reason(monkeypatch):
    calls = {}

    def fake_runner(path, payload=None, timeout=12.0):
        calls["payload"] = payload
        return {"ok": True}

    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: {
        "id": "t1", "status": "running", "runnerJobId": "j1",
        "conversationId": "c1", "title": "任务"})
    monkeypatch.setattr(eb, "_runner", fake_runner)
    monkeypatch.setattr(eb, "_append", lambda *a, **k: None)
    r = eb.task_input("t1", "/deny apr-3 越界文件")
    assert r["ok"] is True
    assert calls["payload"]["approved"] is False
    assert calls["payload"]["reason"] == "越界文件"


def test_verify_event_feedback(monkeypatch):
    """V5: verify 事件 → 进度留痕; FAIL/C 落 task_verify 消息, PASS 不落流。"""
    seen, appended = {}, []
    monkeypatch.setattr(eb.store.TasksStore, "get", lambda tid: _task(progress=seen))
    monkeypatch.setattr(eb.store.TasksStore, "set_progress",
                        lambda tid, p: seen.update(p))
    monkeypatch.setattr(eb, "_publish_progress", lambda c, t, p: seen.update(p))
    def fake_append(conv_id, role, content, msg_meta=None, **kw):
        appended.append(msg_meta or {})
    monkeypatch.setattr(eb, "_append", fake_append)

    eb._handle_task_event({"kind": "verify",
                           "text": "验收: B——test ✅ PASS [config] 5ms",
                           "overall": "B",
                           "test": {"verdict": "PASS", "reason": ""}}, _ctx())
    assert seen.get("verifyOverall") == "B"
    assert seen.get("verify_test") == {"verdict": "PASS", "reason": ""}
    assert appended == []                                    # PASS 不落流

    eb._handle_task_event({"kind": "verify",
                           "text": "验收: B——test ❌ FAIL [config]",
                           "overall": "B",
                           "test": {"verdict": "FAIL", "reason": "TEST_FAILED"}}, _ctx())
    assert appended and appended[-1].get("kind") == "task_verify"
    assert seen["verify_test"]["verdict"] == "FAIL"
