"""投喂门(/feed)与 runningRole 双读特征测试(P0 契约固化)。

锁定:
  - /feed: 主会话消息 → 活跃 coding 子会话落审计消息(meta.feedFrom) → 投递活跃作业;
    hint 消息拒转; 无活跃作业仍记录(下次 /执行 生效)
  - _running_role_of: v2 arch_tasks 优先 → 旧 meta.jobs 账本兜底 → architect 缺省
    (P3 清退旧路径时, 兜底分支删除需同步更新本测试)

Run: cd <repo> && python -m pytest apps/architect/tests/test_feed_gate.py -q
"""
import json
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


def _client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from topoone_app_architect.server import build_app
    _setup(tmp_path, monkeypatch)
    return TestClient(build_app(data_dir=str(tmp_path / "arch"))), \
        {"Authorization": "Bearer test"}


def _mk_main_with_sub(project_id=""):
    conv = store.ConversationsStore.create({"kind": "requirement", "title": "主",
                                            "projectId": project_id})
    sub = store.ConversationsStore.create({"kind": "coding", "title": "子",
                                           "projectId": project_id,
                                           "parentConvId": conv["id"]})
    store.ConversationsStore.update(conv["id"], {"meta": {"activeCodingSession": sub["id"]}})
    return conv, sub


# ── /feed 投喂门(P3 起: 投递目标 = 活跃 v2 任务, 子会话审计不变) ────────

def _mk_active_task(conv_id, status="running", executor_type="opencode"):
    return store.TasksStore.create({
        "conversationId": conv_id, "title": "T", "instruction": "x",
        "status": status, "executorType": executor_type})


def test_feed_records_sub_and_reports_no_job(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    monkeypatch.setattr(eb, "active_task_of", lambda cid: None)
    client, h = _client(tmp_path, monkeypatch)
    conv, sub = _mk_main_with_sub()
    r = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                    json={"text": "分析结论甲"}, headers=h)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["delivered"] is False and data["activeSub"] == sub["id"]
    assert "已记录" in data["summary"]
    sub_msgs = store.ConversationsStore.messages(sub["id"])
    assert len(sub_msgs) == 1
    meta = sub_msgs[0]["meta"]
    assert meta["kind"] == "feed"
    assert meta["feedFrom"]["convId"] == conv["id"]
    assert meta["feedFrom"]["delivered"] is False and meta["feedFrom"]["queued"] is False


def test_feed_delivered_and_queued_flags(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client, h = _client(tmp_path, monkeypatch)
    conv, sub = _mk_main_with_sub()
    task = _mk_active_task(conv["id"], status="running")
    monkeypatch.setattr(eb, "active_task_of", lambda cid: task)
    monkeypatch.setattr(eb, "task_input",
                        lambda tid, text: {"ok": True, "queued": True})
    r = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                    json={"text": "补充约束"}, headers=h).json()["data"]
    assert r["delivered"] is True and r["queued"] is True
    assert "已排队" in r["summary"]
    forwarded = {}
    def _input(tid, text):
        forwarded["task_id"], forwarded["text"] = tid, text
        return {"ok": True, "queued": False}
    monkeypatch.setattr(eb, "task_input", _input)
    r2 = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                     json={"text": "定向正文"}, headers=h).json()["data"]
    assert r2["delivered"] is True
    assert forwarded == {"task_id": task["id"], "text": "定向正文"}


def test_feed_hint_message_rejected(tmp_path, monkeypatch):
    client, h = _client(tmp_path, monkeypatch)
    conv, _sub = _mk_main_with_sub()
    store.ConversationsStore.append_message({
        "id": "m-hint", "conversationId": conv["id"], "role": "assistant",
        "time": 1, "content": "本地提示", "meta": json.dumps({"kind": "hint"})})
    r = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                    json={"messageId": "m-hint"}, headers=h)
    assert r.json()["code"] == 400 and "不可转发" in r.json()["message"]


def test_feed_message_not_found(tmp_path, monkeypatch):
    client, h = _client(tmp_path, monkeypatch)
    conv, _sub = _mk_main_with_sub()
    r = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                    json={"messageId": "m-ghost"}, headers=h)
    assert r.json()["code"] == 404


def test_feed_empty_text_rejected(tmp_path, monkeypatch):
    client, h = _client(tmp_path, monkeypatch)
    conv, _sub = _mk_main_with_sub()
    r = client.post(f"/api/architect/sessions/{conv['id']}/feed",
                    json={"text": "  "}, headers=h)
    assert r.json()["code"] == 400


# ── runningRole 双读(v2 任务优先 / jobs 兜底 / 缺省 architect) ─────────

def test_running_role_none_default(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import sessions as S
    conv = store.ConversationsStore.create({"kind": "generic", "title": "x"})
    rr = S._running_role_of(store.ConversationsStore.get(conv["id"]))
    assert rr["role"] == "architect" and rr["executorId"] == ""


def test_running_role_legacy_jobs_fallback(tmp_path, monkeypatch):
    """P6 单读: 旧 meta.jobs 行不再产生 runningRole(写路径已清退)。"""
    _setup(tmp_path, monkeypatch)
    from topoone_app_architect.arch_routes import sessions as S
    conv = store.ConversationsStore.create({"kind": "generic", "title": "x"})
    store.ConversationsStore.update(conv["id"], {"meta": {"jobs": [
        {"jobId": "j-live", "status": "running", "executorId": "cline",
         "progress": {"toolCount": 5}},
    ]}})
    rr = S._running_role_of(store.ConversationsStore.get(conv["id"]))
    assert rr["role"] == "architect", "存量 jobs 行不应再驱动 runningRole"


def test_running_role_v2_task_priority(tmp_path, monkeypatch):
    """arch_tasks 活跃任务优先; 任务终态后回落 jobs/缺省。"""
    from topoone_app_architect.arch_routes import exec_bridge as eb
    from topoone_app_architect.arch_routes import sessions as S
    _setup(tmp_path, monkeypatch)
    root = tmp_path / "proj"
    root.mkdir()
    conv = store.ConversationsStore.create({"kind": "requirement", "title": "T",
                                            "projectId": "proj-rr"})
    monkeypatch.setattr("topoone_app_architect.arch_routes.execution.conv_root_project",
                        lambda c: (str(root), "proj-rr"))
    monkeypatch.setattr(eb, "_runner",
                        lambda path, payload=None, timeout=12.0:
                        {"ok": True, "jobId": "job-rr", "branch": "task/rr",
                         "worktree": "/tmp/wt", "sessionId": "s-rr"})
    monkeypatch.setattr(eb, "_start_task_pump", lambda *a, **k: None)

    def _rr():
        return S._running_role_of(store.ConversationsStore.get(conv["id"]))

    task = eb.propose_task(store.ConversationsStore.get(conv["id"]), "R", "r")
    assert _rr()["role"] == "architect", "pending_confirm 不构成 running"
    assert eb.confirm_task(task["id"])["ok"]
    rr = _rr()
    assert rr["role"] == "coding" and rr["taskId"] == task["id"]
    assert rr["status"] == "running"
    eb.task_stop(task["id"])
    assert _rr()["role"] == "architect"
