"""焦点栈特征测试(批戊) — 工作记忆/情景记忆显式化的派生单源。

覆盖: 帧派生矩阵(实体组合→栈序)/相位兼容视图(语义逐条等价旧
derive_flow_state)/事件近窗/消解矩阵(意图×top→动作)/cv-241 复放
(「继续执行」+ 计划步骤待确认 → 就近启动, 旧架构=误导性失败)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_focus.py -q
"""
import json
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.agent.governance.focus import (
    build_focus, derive_phase, frames_from_entities, resolve_intent)
from topoone_app_architect.store import states as ST


def _t(status="pending_confirm", tid="task-1", title="T", **kw):
    row = {"id": tid, "title": title, "status": status,
           "updated_at": kw.pop("ts", 100), "finished_at": 0,
           "dismissedAt": kw.pop("dismissed", None),
           "reqId": kw.pop("reqId", ""), "req_id": ""}
    row.update(kw)
    return row


def _conv(req_id="", **kw):
    c = {"id": "cv-x", "reqId": req_id, "meta": kw.pop("meta", "{}")}
    c.update(kw)
    return c


# ── 帧派生矩阵 ────────────────────────────────────────────────────────

def test_frames_kind_matrix():
    rows = [_t("waiting_input", "t-w"),
            _t("running", "t-r"),
            _t("pending_confirm", "t-c"),
            _t("done", "t-d")]
    kinds = [f["kind"] for f in frames_from_entities(_conv(), rows)]
    assert kinds == ["task_input_wait", "task_running",
                     "task_confirm", "reviewing"]


def test_saved_state_is_confirm_frame():
    """saved(默认保存)与 pending_confirm 同属待确认帧(armed 口径一致)。"""
    kinds = [f["kind"] for f in frames_from_entities(_conv(), [_t("saved")])]
    assert kinds == ["task_confirm"]


def test_dismissed_done_no_reviewing_frame():
    rows = [_t("done", "t-d", dismissed="2026-09-22")]
    assert frames_from_entities(_conv(), rows) == []


def test_req_done_exempts_reviewing():
    """req-done 豁免(迁移语义): 需求完结 → 回执视为已消化, 相位 free。"""
    req = {"status": "done"}
    assert derive_phase(frames_from_entities(_conv(), [_t("done")], req),
                        _conv()) == ST.FLOW_FREE
    assert not [f for f in frames_from_entities(_conv(), [_t("done")], req)
                if f["kind"] == "reviewing"]


def test_spec_ready_requires_same_chain_alone():
    """spec_ready 谓词: 绑定 req + 无计划 + 无该链任务(同链互斥)。"""
    conv = _conv("RQ-1")
    req = {"id": "RQ-1", "status": "ready", "updatedAt": 50}
    # 孤 req → spec_ready 帧
    fs = frames_from_entities(conv, [], req, plan=None)
    assert [f["kind"] for f in fs] == ["spec_ready"]
    # 该链已有任务 → 互斥, 不出帧
    fs2 = frames_from_entities(conv, [_t("done", reqId="RQ-1")], req, plan=None)
    assert not [f for f in fs2 if f["kind"] == "spec_ready"]


def test_plan_step_frame_bindings():
    plan = [{"seq": 1, "title": "初始化", "taskId": "task-1", "status": "done"},
            {"seq": 2, "title": "配置", "taskId": "task-2", "status": "pending"}]
    rows = [_t("done", "task-1"), _t("saved", "task-2")]
    fs = frames_from_entities(_conv("RQ-1"), rows, {"id": "RQ-1"}, plan)
    step = [f for f in fs if f["kind"] == "plan_step_ready"]
    assert len(step) == 1 and step[0]["taskId"] == "task-2" and step[0]["idx"] == 1


# ── 相位兼容视图(旧 derive_flow_state 语义逐条等价) ──────────────────

def test_phase_priority_and_stickiness():
    _F = lambda k: {"kind": k}
    assert derive_phase([_F("task_running")], _conv()) == ST.FLOW_EXECUTING
    assert derive_phase([_F("task_input_wait")], _conv()) == ST.FLOW_EXECUTING
    assert derive_phase([_F("plan_step_ready")], _conv()) == ST.FLOW_ARMED
    assert derive_phase([_F("task_confirm"), _F("reviewing")],
                        _conv()) == ST.FLOW_ARMED       # armed > reviewing
    assert derive_phase([_F("reviewing")], _conv()) == ST.FLOW_REVIEWING
    assert derive_phase([], _conv(meta='{"specDraft": {}}')) == ST.FLOW_CLARIFYING
    assert derive_phase([], _conv()) == ST.FLOW_FREE
    # interrupted 粘滞: 无 force 不洗白
    assert derive_phase([_F("task_running")], _conv(),
                        cached=ST.FLOW_INTERRUPTED) == ST.FLOW_INTERRUPTED
    assert derive_phase([_F("task_running")], _conv(),
                        cached=ST.FLOW_INTERRUPTED, force=True) == ST.FLOW_EXECUTING


# ── 事件栈(情景记忆) ──────────────────────────────────────────────────

def test_recent_events_window_and_limit(monkeypatch):
    import time as _time
    now = int(_time.time() * 1000)
    rows = [_t("done", "t-old", ts=now - 2 * 3600 * 1000),      # 窗外
            _t("done", "t-done", ts=now - 100),
            _t("failed", "t-fail", ts=now - 50)]
    from topoone_app_architect.agent.governance import focus as _f
    evs = _f._recent_events(rows, now)
    kinds = [e["kind"] for e in evs]
    assert "task_failed" in kinds and "task_done" in kinds
    assert all(e["taskId"] != "t-old" for e in evs)              # 滑窗淘汰


# ── 消解矩阵 ──────────────────────────────────────────────────────────

def test_resolve_matrix_core_paths():
    step = {"kind": "plan_step_ready", "taskId": "task-38",
            "idx": 1, "label": "步骤 2/4"}
    focus = {"stack": [step], "recent": [], "top": step}
    # cv-241 复放: 「继续执行」× 预填步骤 → 就近启动(旧=误导性失败)
    assert resolve_intent("continue", focus) == {
        "action": "confirm_task", "frame": step}
    assert resolve_intent("confirm", focus)["action"] == "confirm_task"
    # confirm 无焦点 → 回落 GU(旧行为: 无卡=普通对话)
    assert resolve_intent("confirm", {"stack": [], "recent": [],
                                      "top": None})["action"] == "fallthrough"
    # 运行占用 → 焦点态提示
    run_f = {"kind": "task_running", "taskId": "t", "label": "A 执行中"}
    assert resolve_intent("execute", {"stack": [run_f], "recent": [],
                                      "top": run_f})["action"] == "none"


# ── cv-241 端到端复放(WS 全管线) ──────────────────────────────────────

def _plan_env(tmp_path, monkeypatch):
    from tests.conftest import isolate_arch
    data = isolate_arch(tmp_path, monkeypatch)
    import topoone_app_architect.arch_routes.req_agent as req_agent
    monkeypatch.setattr(req_agent, "llm_chat_start", lambda *a, **k: None)
    monkeypatch.setattr(req_agent, "run_tools_loop",
                        lambda msgs, **kw: {"content": "ok"})
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    return TestClient(build_app(data_dir=data))


def test_cv241_continue_confirm_starts_prefilled_step(tmp_path, monkeypatch):
    """「继续执行」+ 计划步骤已预填待确认 → 就近启动该步(旧架构=误导性失败)。"""
    from topoone_app_architect import store
    from topoone_app_architect.agent.planning.task_plan import save_plan
    from topoone_app_architect.arch_routes import exec_bridge as eb
    import topoone_app_architect.arch_routes.execution as ex
    client = _plan_env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    rid = "RQ-P"
    store.RequirementsStore.create({"id": rid, "kind": "user-story",
                                    "status": "ready", "title": "T",
                                    "activeVer": 1})
    store.ConversationsStore.update(conv["id"], {"reqId": rid})
    t1 = store.TasksStore.create({"conversationId": conv["id"], "title": "S1",
                                  "instruction": "x", "status": "done",
                                  "executorType": "cline-sdk", "reqId": rid})
    t2 = store.TasksStore.create({"conversationId": conv["id"], "title": "S2",
                                  "instruction": "y", "status": "saved",
                                  "executorType": "cline-sdk", "reqId": rid})
    save_plan(rid, [
        {"seq": 1, "title": "S1", "instruction": "x", "taskId": t1["id"],
         "status": "done"},
        {"seq": 2, "title": "S2", "instruction": "y", "taskId": t2["id"],
         "status": "pending", "depends": [1]},
    ])
    root = tmp_path / "proj-cv241"
    root.mkdir(exist_ok=True)
    (root / "README.md").write_text("# P\n")
    monkeypatch.setattr(ex, "conv_root_project", lambda c: (str(root), "proj-c"))
    monkeypatch.setattr(eb, "_resolve_boundary_files", lambda *a, **k: [])
    monkeypatch.setattr(eb, "_check_mutex", lambda *a, **k: None)
    monkeypatch.setattr(eb, "_runner",
                        lambda path, payload=None, timeout=20.0: (
                            {"ok": True, "jobId": "j1", "worktree": "/w",
                             "branch": "task/x", "sessionId": "s"}
                            if path == "/api/implement" else None))
    # 修复前对照: run_execute 诊断路径不再暗推进, 而是三分态提示(含待确认)
    from topoone_app_architect.agent.planning.task_plan import (
        maybe_plan_and_propose, _plan_diagnosis)
    conv_row = store.ConversationsStore.get(conv["id"])
    diag = maybe_plan_and_propose(conv_row, rid, "目标", "T", "指令占位")
    assert diag["ok"] is False and "待确认" in diag["receipt"]

    with client:
        with client.websocket_connect("/api/architect/ws/kb-analysis") as ws:
            ws.send_json({"type": "chat", "kind": "generic", "title": "t",
                          "conversationId": conv["id"],
                          "messages": [{"role": "user", "content": "继续执行"}]})
            from tests.ws_helpers import recv_until
            ev, _ = recv_until(ws, "done")
    assert "已确认任务" in ev["content"]
    assert store.TasksStore.get(t2["id"])["status"] == "running"
