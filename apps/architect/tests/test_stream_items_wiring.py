"""A6.2 切片 2 回归——流 item 持久化 + REST + /messages 读侧投影 + 泵接线。

Run: cd <repo> && python -m pytest apps/architect/tests/test_stream_items_wiring.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from test_exec_implement import _mk_v2_fixture  # noqa: E402

from topoone_app_architect.agent.execution.items import (  # noqa: E402
    item_from_card, project_event, STREAM_PERSIST_TYPES)
from topoone_app_architect.arch_routes import store  # noqa: E402


def _setup_env(tmp_path, monkeypatch):
    import topoone_app_architect.arch_routes.ctx as C
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


# ── StreamItemsStore ────────────────────────────────────────────────

def test_store_crud_and_filters(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    for i, tid in ((1, "t1"), (2, "t1"), (3, "t2")):
        store.StreamItemsStore.create({"id": f"si-{i}", "conversationId": "cv1",
                                       "projectId": "pj", "taskId": tid,
                                       "type": "tool_call", "status": "ok",
                                       "text": f"bash {i}", "payload": {"n": i},
                                       "seq": i})
    assert len(store.StreamItemsStore.for_conv("cv1")) == 3
    only_t1 = store.StreamItemsStore.for_conv("cv1", task_id="t1")
    assert {r["taskId"] for r in only_t1} == {"t1"}
    page = store.StreamItemsStore.for_conv("cv1", before_ts=only_t1[0]["createdAt"],
                                           limit=10)
    assert all(r["createdAt"] < only_t1[0]["createdAt"] for r in page)
    row = store.StreamItemsStore.for_conv("cv1")[0]
    assert row["payload"] == {"n": row["seq"]}          # JSON 解码
    store.StreamItemsStore.delete_by_conversation("cv1")
    assert store.StreamItemsStore.for_conv("cv1") == []


def test_only_persist_types_landed(tmp_path, monkeypatch):
    """仅 STREAM_PERSIST_TYPES 入流表; 落消息类(verify 等)不入。"""
    _setup_env(tmp_path, monkeypatch)
    assert set(STREAM_PERSIST_TYPES) == {"tool_call", "file_change", "notice"}
    for ev in ({"kind": "tool", "text": "✓ bash", "toolName": "bash", "seq": 1},
               {"kind": "verify", "overall": "A"},
               {"kind": "approval_request", "toolName": "w", "requestId": "r"}):
        for it_ in project_event(ev):
            if it_["type"] not in STREAM_PERSIST_TYPES:
                continue
            store.StreamItemsStore.create({"id": it_["id"], "conversationId": "cv",
                                           "type": it_["type"]})
    rows = store.StreamItemsStore.for_conv("cv")
    assert {r["type"] for r in rows} == {"tool_call"}


# ── 泵接线(done 事件 → file_change 落流表; 既有沉淀不受影响) ─────────

def test_pump_wiring_projects_tool_call(tmp_path, monkeypatch):
    conv, eb, _ = _mk_v2_fixture(tmp_path, monkeypatch)
    task = eb.propose_task(conv, "投影 E2E", "x")
    assert eb.confirm_task(task["id"])["ok"]
    # 泵 on_event 挂钩单测: 直接调 _land_stream_items(泵回调整体由 E2E 覆盖)
    eb._land_stream_items({"kind": "tool", "text": "✓ bash", "toolName": "bash",
                           "seq": 1},
                          conv["id"], task["id"], "job-v2-1",
                          conv.get("projectId") or "")
    items = store.StreamItemsStore.for_conv(conv["id"])
    assert [i["type"] for i in items] == ["tool_call"]
    assert items[0]["taskId"] == task["id"]


# ── /messages 读侧投影(item_from_card) ──────────────────────────────

def test_item_from_card_mapping():
    cases = {
        "task_card": "task", "task_start": "task_status",
        "task_approval_done": "task_status", "task_done": "turn_completed",
        "task_failed": "turn_completed", "task_input": "task_input",
        "task_input_echo": "task_input", "task_approval": "approval",
        "task_verify": "verify", "turnError": "turn_error",
        "taskPlan": "plan", "taskPlanDone": "plan", "digest_sent": "digest",
        "specCreated": "spec", "specReady": "spec",
    }
    for kind, type_ in cases.items():
        it_ = item_from_card({"kind": kind, "taskId": "t9"}, "正文", ts=5,
                             msg_id="m1")
        assert it_ and it_["type"] == type_, kind
    # 结构化字段进 payload; 非卡片返回 None
    assert item_from_card({"kind": "task_done", "taskId": "t9"}, "x")["payload"]["taskId"] == "t9"
    assert item_from_card({"kind": "task_approval", "approvalRequestId": "r1"},
                          "x")["payload"]["approvalRequestId"] == "r1"
    assert item_from_card(None, "x") is None
    assert item_from_card({"kind": "unknown"}, "x") is None
    # task_status 状态语义
    assert item_from_card({"kind": "task_start"}, "x")["status"] == "running"
    assert item_from_card({"kind": "task_failed"}, "x")["status"] == "failed"
    assert item_from_card({"kind": "taskPlanDone"}, "x")["status"] == "done"


# ── REST ────────────────────────────────────────────────────────────

def test_rest_items_and_messages_projection(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from topoone_app_architect.arch_routes import router as arch_router
    _setup_env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"title": "t", "projectId": "pj-r"})
    store.StreamItemsStore.create({"id": "si-r", "conversationId": conv["id"],
                                   "projectId": "pj-r", "taskId": "tk",
                                   "type": "tool_call", "status": "ok",
                                   "text": "bash", "seq": 1})
    from topoone_app_architect.agent.collab import cards as _cards
    _cards.land(conv["id"], "🔐 确认", kind="task_approval",
                project_id="pj-r",
                taskId="tk", approvalRequestId="rq")
    app = FastAPI()
    app.include_router(arch_router)
    with TestClient(app, raise_server_exceptions=False) as client:
        base = f"/api/architect/sessions/{conv['id']}"
        res = client.get(f"{base}/items")
        assert res.status_code == 200
        items = res.json()["data"]["items"]
        assert [i["type"] for i in items] == ["tool_call"]
        msgs = client.get(f"{base}/messages").json()["data"]["messages"]
        card = [m for m in msgs if (m.get("meta") or {}).get("kind")]
        assert card and card[0]["item"]["type"] == "approval"
        assert card[0]["item"]["payload"]["approvalRequestId"] == "rq"
        res404 = client.get("/api/architect/sessions/nope/items")
        assert res404.status_code == 404
