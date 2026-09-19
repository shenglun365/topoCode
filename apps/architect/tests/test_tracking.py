"""需求跟踪台账回归——六维度条目 CRUD / 主子会话双 ID / 跨库扫描 / REST / 字典 /
任务生命周期自动挂账 / 需求落库挂账。

Run: cd <repo> && python -m pytest apps/architect/tests/test_tracking.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.arch_routes import store  # noqa: E402
from topoone_app_architect.arch_routes.store import tracking as TR  # noqa: E402
from topoone_app_architect.arch_routes.store import states as ST  # noqa: E402


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


def _mk_app():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from topoone_app_architect.arch_routes import router as arch_router
    app = FastAPI()
    app.include_router(arch_router)
    return TestClient(app, raise_server_exceptions=False)


def test_crud_and_main_sub_conversation(tmp_path, monkeypatch):
    """六维度条目: 主/子会话双 ID 解析 + 项目归属从主会话推导。"""
    _setup_env(tmp_path, monkeypatch)
    main = store.ConversationsStore.create({"title": "主会话", "projectId": "pj-a"})
    sub = store.ConversationsStore.create({"title": "coding 子会话", "projectId": "pj-a",
                                           "parentConvId": main["id"]})
    row = TR.TrackingItemsStore.create({
        "category": "任务", "title": "实现支付超时修复",
        "content": "修复网关重试", "actionType": "编码",
        "creatorRole": "architect", "assigneeRole": "coding", "assigneeId": "opencode",
        "state": ST.TRACK_RUNNING,
        "conversationId": sub["id"],           # 直接发生在子会话
        "refType": "task", "refId": "task-1",
    })
    assert row["mainConversationId"] == main["id"]   # 沿 parent 上溯到主会话
    assert row["conversationId"] == sub["id"]
    assert row["projectId"] == "pj-a"                # 从主会话行推导
    got = TR.TrackingItemsStore.get(row["id"])
    assert got["category"] == "任务" and got["state"] == "running"


def test_all_across_and_filters(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    c1 = store.ConversationsStore.create({"title": "A", "projectId": "pj-a"})
    c2 = store.ConversationsStore.create({"title": "B", "projectId": "pj-b"})
    TR.emit(category="回执", title="回执一", state=ST.TRACK_DONE,
            conversation_id=c1["id"])
    TR.emit(category="决策", title="审批请求", state=ST.TRACK_WAITING,
            waiting_for="user", conversation_id=c2["id"])
    rows = TR.TrackingItemsStore.all_across()
    assert {r["category"] for r in rows} >= {"回执", "决策"}
    only_wait = TR.TrackingItemsStore.all_across(state=ST.TRACK_WAITING)
    assert [r["title"] for r in only_wait] == ["审批请求"]
    only_receipt = TR.TrackingItemsStore.all_across(category="回执")
    assert [r["title"] for r in only_receipt] == ["回执一"]


def test_task_lifecycle_sync(tmp_path, monkeypatch):
    """任务创建即挂账(waiting/等用户确认) → 状态机变化单向同步。"""
    _setup_env(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"title": "C", "projectId": "pj-a"})
    task = store.TasksStore.create({"conversationId": conv["id"],
                                    "title": "编码任务", "instruction": "做点事",
                                    "executorType": "opencode"})
    entries = TR.TrackingItemsStore.find_by_ref("task", task["id"], category="任务")
    assert len(entries) == 1
    assert entries[0]["state"] == ST.TRACK_WAITING
    assert entries[0]["waitingFor"] == "user"
    assert entries[0]["assigneeRole"] == "coding"
    # 确认 → running
    store.TasksStore.update(task["id"], {"status": ST.TASK_RUNNING})
    e = TR.TrackingItemsStore.find_by_ref("task", task["id"], category="任务")[0]
    assert e["state"] == ST.TRACK_RUNNING and not e["waitingFor"]
    # 完成
    store.TasksStore.update(task["id"], {"status": "done", "resultMd": "搞定"})
    e = TR.TrackingItemsStore.find_by_ref("task", task["id"], category="任务")[0]
    assert e["state"] == ST.TRACK_DONE and e["resultState"] == "ok"
    assert "搞定" in e["result"]
    # 台账不回写任务(单向)
    assert store.TasksStore.get(task["id"])["status"] == "done"


def test_rest_items_manual_and_vocab(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    with _mk_app() as client:
        # 手动挂账(创建者恒 user)
        res = client.post("/api/architect/tracking/items", json={
            "category": "方案", "title": "重写网关方案", "content": "设计要点…",
            "actionType": "设计", "assigneeRole": "architect"})
        assert res.status_code == 200
        row = res.json()["data"]
        assert row["creatorRole"] == "user" and row["state"] == "waiting"
        # 缺 title 拒绝
        assert client.post("/api/architect/tracking/items",
                           json={"category": "方案"}).status_code == 400
        # 清单(scope=all + 筛选)
        rows = client.get(
            "/api/architect/tracking/items?scope=all&category=方案").json()["data"]["items"]
        assert [r["title"] for r in rows] == ["重写网关方案"]
        # 流转: 标记完成 + 作废
        res = client.patch(f"/api/architect/tracking/items/{row['id']}",
                           json={"state": "done", "resultState": "ok",
                                 "result": "方案定稿", "valid": False})
        assert res.status_code == 200
        patched = res.json()["data"]
        assert patched["state"] == "done" and patched["valid"] in (0, False)
        # 字典: 默认 + 写入
        vocab = client.get("/api/architect/tracking/vocab").json()["data"]
        assert "需求" in vocab["categories"] and "编码" in vocab["actionTypes"]
        assert set(vocab["roles"]) == {"user", "architect", "coding"}
        res = client.put("/api/architect/tracking/vocab",
                         json={"categories": ["需求", "任务", "风险"]})
        assert res.status_code == 200
        assert res.json()["data"]["categories"] == ["需求", "任务", "风险"]
        # 空字典拒绝
        assert client.put("/api/architect/tracking/vocab",
                          json={"categories": []}).status_code == 400


def test_rest_delete_item(tmp_path, monkeypatch):
    """单条删除: 删除后清单不含、重复删除 404; 不影响其他条目。"""
    _setup_env(tmp_path, monkeypatch)
    with _mk_app() as client:
        r1 = client.post("/api/architect/tracking/items",
                         json={"title": "条目A"}).json()["data"]
        r2 = client.post("/api/architect/tracking/items",
                         json={"title": "条目B"}).json()["data"]
        assert client.delete(f"/api/architect/tracking/items/{r1['id']}").status_code == 200
        rows = client.get("/api/architect/tracking/items?scope=all").json()["data"]["items"]
        assert [r["id"] for r in rows] == [r2["id"]]
        # 重复删除 → 404
        assert client.delete(f"/api/architect/tracking/items/{r1['id']}").status_code == 404


def test_manual_requirement_emits_entry(tmp_path, monkeypatch):
    """手工登记需求(draft) → 自动挂「需求」条目(等待用户完善)。"""
    _setup_env(tmp_path, monkeypatch)
    with _mk_app() as client:
        res = client.post("/api/architect/requirements", json={
            "title": "手工登记的需求", "desc": "描述"})
        assert res.status_code == 200
        rid = res.json()["data"]["id"]
        rows = client.get(
            "/api/architect/tracking/items?scope=all&category=需求").json()["data"]["items"]
        assert len(rows) == 1
        assert rows[0]["refType"] == "requirement"
        assert rows[0]["refId"] == rid
        assert rows[0]["state"] == "waiting" and rows[0]["waitingFor"] == "user"
        assert rows[0]["creatorRole"] == "user"


def test_session_delete_cascades_tracking(tmp_path, monkeypatch):
    """删除会话 → 台账条目级联清除(主线 + 其子会话), 无关会话不受影响。"""
    _setup_env(tmp_path, monkeypatch)
    main = store.ConversationsStore.create({"title": "主", "projectId": "pj-a"})
    sub = store.ConversationsStore.create({"title": "子", "projectId": "pj-a",
                                           "parentConvId": main["id"]})
    other = store.ConversationsStore.create({"title": "其他", "projectId": "pj-a"})
    TR.emit(category="任务", title="主线任务", conversation_id=main["id"])
    TR.emit(category="回执", title="子会话回执", conversation_id=sub["id"])
    TR.emit(category="任务", title="别的会话条目", conversation_id=other["id"])
    with _mk_app() as client:
        assert client.delete(f"/api/architect/sessions/{main['id']}").status_code == 200
        rows = client.get("/api/architect/tracking/items?scope=all").json()["data"]["items"]
        titles = {r["title"] for r in rows}
        assert "主线任务" not in titles          # 主会话直接条目清除
        assert "子会话回执" not in titles        # 子会话条目经 main_conversation_id 清除
        assert "别的会话条目" in titles          # 无关会话不受影响
