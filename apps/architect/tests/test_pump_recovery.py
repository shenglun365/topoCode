"""P1 泵恢复 特征测试(服务重启丢内存泵 → 惰性核对 runner 实际态收尾)。

cv-153 实证回归锁定:
  - runner 已 done → 重放终态: 任务 done + result_md + ✅ 回执落流 + work_state 聚合
  - runner 已 failed/error → 任务 failed 原文回执
  - runner 报「作业不存在」(重启丢内存) → 显式 failed, 不悬置
  - runner 不可达 → 保持现状(不臆断)
  - 仍在执行 → 返回 repump 清单(事件循环内重挂泵)
  - confirm_task 互斥前自愈: 僵尸 running 收尾后不再阻塞确认

Run: cd <repo> && python -m pytest apps/architect/tests/test_pump_recovery.py -q
"""
import asyncio
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.arch_routes import exec_bridge as eb
from topoone_app_architect.arch_routes.sessions import _task_payload_from_markdown


def _env(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.setup(data_dir=data)


def _mk_running_task(conv_id, job="impl-x", status="running"):
    return store.TasksStore.create({
        "conversationId": conv_id, "title": "T", "instruction": "x",
        "status": status, "executorType": "opencode",
        "runnerJobId": job, "branch": "task/x"})


def _snapshot(status, events, error=""):
    return {"ok": True, "jobId": "impl-x", "status": status, "error": error,
            "branch": "task/x", "worktree": "/tmp/wt", "root": "/tmp/src",
            "sessionId": "s1", "executorId": "opencode",
            "lastActivityTs": 0.0, "events": events}


def test_recover_done_task_finalizes(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running_task(conv["id"])
    done_ev = {"seq": 2, "kind": "done",
               "text": "[[IMPLEMENT_DONE]] 完成了改动",
               "changedFiles": ["a.py", "b.py"]}
    monkeypatch.setattr(eb, "_runner",
                        lambda path, **kw: _snapshot("done", [done_ev])
                        if path.endswith("/impl-x") else None)
    monkeypatch.setattr(eb, "_acceptance_brief", lambda *a, **k: "(简报)")
    out = eb.recover_conv_tasks(conv["id"])
    assert out["finished"] == 1 and out["repump"] == []
    row = store.TasksStore.get(t["id"])
    assert row["status"] == "done"
    assert "完成了改动" in (row["resultMd"] or "")
    msgs = store.ConversationsStore.messages(conv["id"], limit=20)
    assert any((m.get("meta") or {}).get("kind") == "task_done" for m in msgs)
    assert any("✅" in m["content"] for m in msgs)


def test_recover_failed_task(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running_task(conv["id"])
    fail_ev = {"seq": 3, "kind": "failed", "text": "编译失败: xxx"}
    monkeypatch.setattr(eb, "_runner",
                        lambda path, **kw: _snapshot("failed", [fail_ev], "boom")
                        if path.endswith("/impl-x") else None)
    out = eb.recover_conv_tasks(conv["id"])
    assert out["finished"] == 1
    assert store.TasksStore.get(t["id"])["status"] == "failed"
    msgs = store.ConversationsStore.messages(conv["id"], limit=20)
    assert any("❌" in m["content"] and "编译失败" in m["content"] for m in msgs)


def test_recover_lost_job_fails_explicitly(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running_task(conv["id"])
    monkeypatch.setattr(eb, "_runner",
                        lambda path, **kw: {"ok": False, "error": "作业不存在"})
    out = eb.recover_conv_tasks(conv["id"])
    assert out["finished"] == 1
    row = store.TasksStore.get(t["id"])
    assert row["status"] == "failed"
    assert "作业已丢失" in (row["resultMd"] or "")


def test_recover_unreachable_runner_noop(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running_task(conv["id"])
    monkeypatch.setattr(eb, "_runner", lambda path, **kw: None)  # 不可达
    out = eb.recover_conv_tasks(conv["id"])
    assert out == {"finished": 0, "repump": []}
    assert store.TasksStore.get(t["id"])["status"] == "running"


def test_recover_running_returns_repump(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running_task(conv["id"])
    monkeypatch.setattr(eb, "_runner",
                        lambda path, **kw: _snapshot("running", [
                            {"seq": 1, "kind": "session_ready", "text": "ready"}]))
    out = eb.recover_conv_tasks(conv["id"])
    assert out["finished"] == 0
    assert out["repump"] == [(t["id"], "impl-x", "", "opencode")]
    assert store.TasksStore.get(t["id"])["status"] == "running"


def test_confirm_mutex_self_heals_via_recovery(tmp_path, monkeypatch):
    """僵尸 running 阻塞互斥 → confirm 先恢复(终态化)再放行。"""
    _env(tmp_path, monkeypatch)
    root = tmp_path / "proj"
    root.mkdir(exist_ok=True)
    (root / "README.md").write_text("# P\n")
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-x"))
    # 注意: 会话不绑 projectId——of_conv 按会话项目路由库, 测试任务都在默认库
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    ghost = _mk_running_task(conv["id"], job="impl-ghost")
    real = store.TasksStore.create({
        "conversationId": conv["id"], "title": "R", "instruction": "y",
        "status": "pending_confirm", "executorType": "opencode"})
    done_ev = {"seq": 2, "kind": "done", "text": "[[IMPLEMENT_DONE]] ok",
               "changedFiles": []}

    def _fake_runner(path, **kw):
        if "impl-ghost" in path:
            return _snapshot("done", [done_ev])
        return None

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    monkeypatch.setattr(eb, "_acceptance_brief", lambda *a, **k: "(简报)")
    monkeypatch.setattr(eb, "_resolve_boundary_files", lambda *a, **k: [])
    monkeypatch.setattr(eb, "_check_mutex", lambda *a, **k: None)

    captured = {}

    def _fake_run_impl(payload_path, payload, timeout=20.0):
        captured["called"] = True
        return {"ok": True, "jobId": "impl-new", "worktree": "/tmp/w2",
                "branch": "task/new", "sessionId": "s2"}

    monkeypatch.setattr(eb, "_runner",
                        lambda path, payload=None, timeout=20.0: (
                            _fake_runner(path, payload=payload, timeout=timeout)
                            if "impl-ghost" in path else _fake_run_impl(path, payload)))
    r = eb.confirm_task(real["id"])
    assert r.get("ok") is True, r
    assert store.TasksStore.get(ghost["id"])["status"] == "done"
    assert store.TasksStore.get(real["id"])["status"] == "running"


# ── P3: guard-repair 拒绝状态话术载荷(cv-153 幽灵卡回归) ─────────────

def test_markdown_payload_rejects_status_talk():
    """模型谎报的一句回执文案 → 拒绝建卡(不能当任务载荷)。"""
    r = _task_payload_from_markdown(
        "任务已启动，执行器 `opencode` 正在处理中。完成后将在本会话同步进展与结果。")
    assert r is None


def test_markdown_payload_accepts_substantive():
    """含实质内容(文件/动作)的方案文本 → 正常提取建卡。"""
    content = ("## 实施方案\n\n"
               "修改 `src/app.py` 的启动逻辑：在 main 入口增加健康检查端点，\n"
               "返回 `{'status': 'up'}`；同时补充 test_smoke.py 用例覆盖该端点。")
    r = _task_payload_from_markdown(content)
    assert r and r["title"] == "实施方案"
    assert "src/app.py" in r["instruction"]


def test_markdown_payload_status_talk_not_title():
    """状态话术行不充当标题; 剔除后无实质内容 → 拒绝。"""
    content = ("任务已启动，执行器正在处理中。\n"
               "完成后将同步进展。")
    assert _task_payload_from_markdown(content) is None


def test_messages_rest_triggers_recovery(tmp_path, monkeypatch):
    """T3 恢复扩面: 只打开会话(GET messages, 不发消息)也自愈假 running 任务。"""
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    _env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    t = _mk_running_task(conv["id"])
    done_ev = {"seq": 2, "kind": "done", "text": "[[IMPLEMENT_DONE]] ok",
               "changedFiles": []}
    monkeypatch.setattr(eb, "_runner",
                        lambda path, **kw: _snapshot("done", [done_ev])
                        if path.endswith("/impl-x") else None)
    monkeypatch.setattr(eb, "_acceptance_brief", lambda *a, **k: "(简报)")
    client = TestClient(build_app(data_dir=str(tmp_path / "arch")))
    r = client.get(f"/api/architect/sessions/{conv['id']}/messages")
    assert r.status_code == 200
    assert store.TasksStore.get(t["id"])["status"] == "done"
    msgs = store.ConversationsStore.messages(conv["id"], limit=20)
    assert any((m.get("meta") or {}).get("kind") == "task_done" for m in msgs)
