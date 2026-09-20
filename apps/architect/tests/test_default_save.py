"""卡片默认保存(2026-09-20 产品裁决)测试: saved 生命周期/同需求改写/忽略/存量兼容。

裁决四项: 手动触发执行 / 软删置灰 / 合并与 NEED_INPUT 门禁保留 / 存量原状。

Run: cd <repo> && python -m pytest apps/architect/tests/test_default_save.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from topoone_app_architect.arch_routes import store
from topoone_app_architect.arch_routes.store import states as ST


def _mk_conv(**kw):
    return store.ConversationsStore.create({"kind": "generic", "title": "T", **kw})


def _mk_req(conv_id):
    req = {"id": store.next_id("RQ"), "kind": "user-story", "status": "ready",
           "title": "需求A", "priority": "P1", "activeVer": 1,
           "specVersions": [{"ver": 1, "state": "confirmed",
                             "snapshot": {"title": "需求A", "desc": "d",
                                          "designMd": "方案", "allowedScope": ["src/"],
                                          "forbiddenScope": [], "acceptance": ["ok"],
                                          "functionalScope": [], "assessmentSummary": "",
                                          "estMin": 10},
                             "source": {}, "reason": "t", "createdAt": 0}],
           "ownerConv": conv_id, "projectId": "", "updatedAt": 0, "createdAt": 0}
    store.RequirementsStore.create(req)
    store.ConversationsStore.update(conv_id, {"reqId": req["id"]})
    return req["id"]


def test_propose_creates_saved_and_card_text(arch_env):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv()
    r = eb.propose_task(conv, "任务一", "目标: X", executor_hint={"executorType": "cline-sdk"})
    assert r.get("id") and r["status"] == ST.TASK_SAVED
    assert r.get("ok") is True and not r.get("revised")
    msgs = store.ConversationsStore.messages(conv["id"])
    card = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_card"]
    assert card and "任务已保存" in card[-1]["content"]
    assert "开始执行" in card[-1]["content"]


def test_same_req_propose_rewrites_saved_card(arch_env):
    """对话补充 → agent 重复 task.propose 改写同需求 saved 卡(不产生重复卡)。"""
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv()
    rid = _mk_req(conv["id"])
    r1 = eb.propose_task(conv, "任务一", "目标: 初始方案",
                         executor_hint={"executorType": "cline-sdk"})
    r2 = eb.propose_task(conv, "任务一(修订)", "目标: 按对话补充更新后的方案",
                         executor_hint={"executorType": "cline-sdk"})
    assert r2.get("revised") is True and r2["id"] == r1["id"]
    tasks = store.TasksStore.of_conv(conv["id"])
    assert len([t for t in tasks if t.get("reqId") == rid]) == 1   # 无重复卡
    t = store.TasksStore.get(r1["id"])
    assert "对话补充" in t["instruction"] and "初始方案" not in t["instruction"]
    msgs = store.ConversationsStore.messages(conv["id"])
    cards = [m for m in msgs if (m.get("meta") or {}).get("kind") == "task_card"]
    assert any("任务卡已修订" in m["content"] for m in cards)


def test_different_req_creates_new_card(arch_env):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv()
    _mk_req(conv["id"])
    eb.propose_task(conv, "任务一", "x", executor_hint={"executorType": "cline-sdk"})
    store.ConversationsStore.update(conv["id"], {"reqId": ""})   # 无需求 → 不改写
    r2 = eb.propose_task(conv, "任务二", "y", executor_hint={"executorType": "cline-sdk"})
    assert not r2.get("revised")
    assert len(store.TasksStore.of_conv(conv["id"])) == 2        # 多卡并存


def test_ignore_task_semantics(arch_env):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv()
    r = eb.propose_task(conv, "T", "x", executor_hint={"executorType": "cline-sdk"})
    tid = r["id"]
    # saved → ignored ✓ + 回执卡
    res = eb.ignore_task(tid)
    assert res["ok"] and res["task"]["status"] == ST.TASK_IGNORED
    msgs = store.ConversationsStore.messages(conv["id"])
    assert any((m.get("meta") or {}).get("kind") == "task_ignored" for m in msgs)
    # 再忽略 → 409
    res2 = eb.ignore_task(tid)
    assert not res2["ok"] and res2.get("code") == 409
    # 忽略后同需求重新建卡 ✓
    rid = _mk_req(conv["id"])
    r2 = eb.propose_task(conv, "重提", "z", executor_hint={"executorType": "cline-sdk"})
    assert r2.get("id") and r2["status"] == ST.TASK_SAVED


def test_confirm_saved_starts_execution(arch_env, tmp_path, monkeypatch):
    """手动触发: confirm(saved) → running(原确认语义)。"""
    from topoone_app_architect.arch_routes import exec_bridge as eb
    root = tmp_path / "p"; root.mkdir()
    conv = _mk_conv(projectId="proj-ds", meta={"root": str(root)})
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-ds"))
    monkeypatch.setattr(eb, "_resolve_boundary_files", lambda *a, **k: [])
    monkeypatch.setattr(eb, "_check_mutex", lambda *a, **k: None)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)
    seen = {}

    def _fake_runner(path, payload=None, timeout=12.0):
        seen["path"] = path
        if path == "/api/implement":
            return {"ok": True, "jobId": "j-ds", "branch": "task/ds",
                    "worktree": str(tmp_path / "wt"), "sessionId": "s",
                    "baseCommit": "sha-ds"}
        return {"ok": True}

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    r = eb.propose_task(conv, "T", "目标: X", executor_hint={"executorType": "cline-sdk"})
    res = eb.confirm_task(r["id"])
    assert res["ok"], res
    assert store.TasksStore.get(r["id"])["status"] == ST.TASK_RUNNING
    assert seen["path"] == "/api/implement"


def test_task_input_on_saved_guides(arch_env):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    conv = _mk_conv()
    r = eb.propose_task(conv, "T", "x", executor_hint={"executorType": "cline-sdk"})
    res = eb.task_input(r["id"], "快点做")
    assert not res["ok"] and "开始执行" in str(res.get("error"))


def test_legacy_pending_confirm_still_confirmable(arch_env, tmp_path, monkeypatch):
    """存量原状: 直建 pending_confirm 行仍走确认门。"""
    from topoone_app_architect.arch_routes import exec_bridge as eb
    root = tmp_path / "p"; root.mkdir()
    conv = _mk_conv(projectId="proj-lg", meta={"root": str(root)})
    monkeypatch.setattr(
        "topoone_app_architect.arch_routes.execution.conv_root_project",
        lambda c: (str(root), "proj-lg"))
    monkeypatch.setattr(eb, "_resolve_boundary_files", lambda *a, **k: [])
    monkeypatch.setattr(eb, "_check_mutex", lambda *a, **k: None)
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)

    def _fake_runner(path, payload=None, timeout=12.0):
        if path == "/api/implement":
            return {"ok": True, "jobId": "j-lg", "branch": "task/lg",
                    "worktree": str(tmp_path / "wt2"), "sessionId": "s",
                    "baseCommit": "sha-lg"}
        return {"ok": True}

    monkeypatch.setattr(eb, "_runner", _fake_runner)
    t = store.TasksStore.create({
        "conversationId": conv["id"], "title": "存量卡", "instruction": "x",
        "status": ST.TASK_PENDING_CONFIRM, "executorType": "opencode"})
    assert eb.confirm_task(t["id"])["ok"]
    assert store.TasksStore.get(t["id"])["status"] == ST.TASK_RUNNING


def test_requirement_ignore_rest(arch_env):
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    conv = _mk_conv()
    rid = _mk_req(conv["id"])
    client = TestClient(build_app(data_dir=os.environ["ARCH_DATA_DIR"]))
    r1 = client.post(f"/api/architect/requirements/{rid}/ignore").json()
    assert r1.get("code") == 0 and r1["data"]["ignored"] is True
    assert (store.RequirementsStore.get(rid) or {}).get("status") == "ignored"
    # 幂等
    r2 = client.post(f"/api/architect/requirements/{rid}/ignore").json()
    assert r2.get("code") == 0
    msgs = store.ConversationsStore.messages(conv["id"])
    assert any("需求已忽略" in (m.get("content") or "") for m in msgs)
