"""PR1 双维度状态机: 生命周期(active/running/archived 不可逆) + 查看状态。"""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("ARCH_DATA_DIR", str(tmp_path))
    from topoone_app_architect.arch_routes import ctx as C
    C._db = None; C._kb = None; C._data_dir = None
    C._project_dbs.clear()
    from topoone_app_architect import server as _srv
    app = _srv.build_app(data_dir=str(tmp_path / "arch"))
    return TestClient(app)


def _auth(client):
    tok = client.get("/api/architect/health").json().get("data", {}).get("token")
    h = {"Authorization": f"Bearer {tok}"} if tok else {}
    return h


def test_lifecycle_validation_and_archive_irreversible(client):
    h = _auth(client)
    c = client.post("/api/architect/sessions", json={"kind": "generic", "title": "T"},
                    headers=h).json()["data"]
    assert c["status"] == "active" and c["reviewState"] == "read"
    assert c["roleId"] == "architect"
    # 非法旧值拒绝
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"status": "waiting"}, headers=h)
    assert r.status_code == 400
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"status": "done"}, headers=h)
    assert r.status_code == 400
    # reviewState 校验
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"reviewState": "bad"}, headers=h)
    assert r.status_code == 400
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"reviewState": "unread"}, headers=h)
    assert r.json()["data"]["reviewState"] == "unread"
    # 归档 → 不可逆
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"status": "archived"}, headers=h)
    assert r.json()["data"]["status"] == "archived"
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"status": "active"}, headers=h)
    assert r.status_code == 400
    # 归档后 reviewState 仍可更新(读标记)
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"reviewState": "read"}, headers=h)
    assert r.json()["data"]["reviewState"] == "read"


def test_legacy_status_migration(client):
    """存量单值状态迁移: waiting→awaiting_reply+active; pending→active+pendingExec。"""
    from topoone_app_architect.arch_routes import store
    store.ConversationsStore.create({"id": "cv-old1", "kind": "asset", "status": "waiting"})
    store.ConversationsStore.create({"id": "cv-old2", "kind": "execution", "status": "pending"})
    from topoone_app_architect.arch_routes.db_schema import _migrate_conversation_lifecycle
    db = store._db()
    _migrate_conversation_lifecycle(db)
    c1 = store.ConversationsStore.get("cv-old1")
    assert c1["status"] == "active" and c1["reviewState"] == "awaiting_reply"
    c2 = store.ConversationsStore.get("cv-old2")
    assert c2["status"] == "active" and c2["reviewState"] == "read"
    meta = c2.get("meta") or {}
    assert (meta.get("pendingExec") if isinstance(meta, dict) else True) is True


def test_roles_seed_and_builtin_protection(client):
    from topoone_app_architect.arch_routes import store
    roles = store.SessionRolesStore.all()
    arch = [r for r in roles if r["id"] == "architect"]
    assert arch and arch[0]["kind"] == "architect" and arch[0]["builtin"]
    # 内置角色不可删
    assert store.SessionRolesStore.delete("architect") is False
    # executor 角色可建可删
    r = store.SessionRolesStore.upsert({"id": "exec-cline", "name": "执行器·cline",
                                        "executorId": "cline"})
    assert r["id"] == "exec-cline" and r["kind"] == "executor"
    # 内置角色改绑定被忽略
    store.SessionRolesStore.upsert({"id": "architect", "name": "Architect",
                                    "executorId": "hijack", "kind": "executor"})
    assert store.SessionRolesStore.get("architect")["executorId"] == ""
    assert store.SessionRolesStore.delete("exec-cline") is True


def test_spawn_execution_session_dual_state(client):
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes.requirements import spawn_execution_session
    store.RequirementsStore.create({"id": "RQ-D1", "title": "双态测试", "desc": "d"})
    conv = spawn_execution_session({"id": "RQ-D1", "title": "双态测试",
                                    "analysis": {"acceptance": ["构建通过"]}})
    row = store.ConversationsStore.get(conv["id"])
    assert row["status"] == "active" and row["reviewState"] == "unread"
    meta = row.get("meta") or {}
    assert isinstance(meta, dict) and meta.get("pendingExec") is True



def test_role_switch_rules(client):
    """PR3 角色切换: 规范化门槛 + 单向锁定。"""
    from topoone_app_architect.arch_routes import store
    h = _auth(client)
    store.SessionRolesStore.upsert({"id": "exec-x", "name": "执行X", "executorId": "opencode"})
    c = client.post("/api/architect/sessions", json={"kind": "generic", "title": "切换"}, headers=h).json()["data"]
    # 未绑定需求 → 拒绝(未规范化)
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"roleId": "exec-x"}, headers=h)
    assert r.status_code == 400 and "规范化" in r.json()["message"]
    # 绑定需求但未入池 → 拒绝
    store.RequirementsStore.create({"id": "RQ-SW", "title": "t", "location": "proposal"})
    client.patch(f"/api/architect/sessions/{c['id']}", json=None, headers=h) if False else None
    store.ConversationsStore.update(c["id"], {"reqId": "RQ-SW"})
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"roleId": "exec-x"}, headers=h)
    assert r.status_code == 400
    # 入池 → 切换成功且锁定
    store.RequirementsStore.update("RQ-SW", {"location": "pool"})
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"roleId": "exec-x"}, headers=h)
    assert r.json()["data"]["roleId"] == "exec-x" and r.json()["data"]["roleLocked"]
    # 再换(即使另一角色) → 锁定拒绝
    store.SessionRolesStore.upsert({"id": "exec-y", "name": "执行Y", "executorId": "cline"})
    r = client.patch(f"/api/architect/sessions/{c['id']}", json={"roleId": "exec-y"}, headers=h)
    assert r.status_code == 400 and "锁定" in r.json()["message"]



def test_handoff_creates_locked_new_session(client, monkeypatch):
    """PR4 交接: 规范化会话 → 新会话绑目标角色(生而锁定) + 原会话指向。"""
    from topoone_app_architect.arch_routes import store
    from topoone_app_architect.arch_routes import context_registry as CR
    # dossier 需 LLM 的段落裁剪纯本地拼装, 但 root 解析可能走 KB → 打桩兜底
    monkeypatch.setattr(CR, "assemble_dossier", lambda *a, **k: "【测试交接档案】需求: X; 方案: Y")
    h = _auth(client)
    store.SessionRolesStore.upsert({"id": "exec-h", "name": "交接目标", "executorId": "opencode"})
    c = client.post("/api/architect/sessions", json={"kind": "generic", "title": "原会话"}, headers=h).json()["data"]
    # 未绑定需求 → 拒绝
    r = client.post(f"/api/architect/sessions/{c['id']}/handoff",
                    json={"targetRoleId": "exec-h"}, headers=h)
    assert r.status_code == 400
    store.RequirementsStore.create({"id": "RQ-HO", "title": "交接需求", "desc": "d", "location": "pool"})
    store.ConversationsStore.update(c["id"], {"reqId": "RQ-HO"})
    r = client.post(f"/api/architect/sessions/{c['id']}/handoff",
                    json={"targetRoleId": "exec-h", "archiveOrigin": True}, headers=h)
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    new_id = d["newConvId"]
    new_conv = store.ConversationsStore.get(new_id)
    assert new_conv["roleId"] == "exec-h" and new_conv["roleLocked"]
    assert new_conv["reqId"] == "RQ-HO" and new_conv["reviewState"] == "unread"
    msgs = store.ConversationsStore.messages(new_id)
    assert any("交接摘要" in (m.get("content") or "") for m in msgs)
    # 原会话归档 + handoffTo
    origin = store.ConversationsStore.get(c["id"])
    assert origin["status"] == "archived" and "handoffTo" in (origin.get("meta") or "")
    # 归档会话不能再交接
    r = client.post(f"/api/architect/sessions/{c['id']}/handoff",
                    json={"targetRoleId": "exec-h"}, headers=h)
    assert r.status_code == 400
    # 新会话(锁定)不能再直接 PATCH roleId
    r = client.patch(f"/api/architect/sessions/{new_id}", json={"roleId": "architect"}, headers=h)
    assert r.status_code == 400



def test_conv_read_tool_includes_archived(client):
    """PR-D: conv.read 只读工具可读归档会话。"""
    from topoone_app_architect.arch_routes import req_agent as R
    from topoone_app_architect.arch_routes import store
    store.ConversationsStore.create({"id": "cv-arch1", "kind": "generic",
                                     "title": "归档读", "status": "archived"})
    store.ConversationsStore.append_message({"id": "m1", "conversationId": "cv-arch1",
                                             "role": "user", "time": 1, "content": "历史提问"})
    r = R.run_arch_tool("conv.read", {"convId": "cv-arch1"}, None, None)
    assert r.get("ok") and r["lifecycle"] == "archived"
    assert any(m["content"] == "历史提问" for m in r["messages"])


def test_tool_whitelist_contextvar(client):
    """PR-A: 角色工具白名单 contextvar 拒绝未授权工具。"""
    import asyncio
    from topoone_app_architect.arch_routes import websocket as WS
    sent = []
    class _FakeWS:
        async def send_json(self, obj):
            sent.append(obj)
    WS._TOOL_WHITELIST.set(["kb.asset.search"])

    async def _run():
        return await WS._run_tool_with_progress(
            _FakeWS(), "req-propose-x", "req.propose",
            {"title": "x", "designMd": "d"}, None, None)
    res = asyncio.run(_run())
    assert res["ok"] is False and "白名单拒绝" in res["text"]
    WS._TOOL_WHITELIST.set(None)




def test_agent_chat_reply_extra_context(client, monkeypatch):
    """PR-B: executor 会话对话直达 coding agent, 携带需求/角色/最近对话上下文。"""
    import asyncio
    from topoone_app_architect.arch_routes import websocket as WS
    captured = {}

    def fake_chat_reply(*, question, root, project, task_context="", model_id="", max_rounds=4):
        captured["question"] = question
        captured["ctx"] = task_context
        return "代码回答"

    import topoone_app_architect.arch_routes.tagent_chat as TC
    monkeypatch.setattr(TC, "chat_reply", fake_chat_reply)
    out = asyncio.run(WS._agent_chat_reply(
        {"reqId": ""}, "这个函数怎么改?",
        "会话角色: 执行A(executor)\n最近对话:\nuser: 上一轮"))
    assert out == "代码回答"
    assert captured["question"] == "这个函数怎么改?"
    assert "executor" in captured["ctx"] and "上一轮" in captured["ctx"]



def test_parse_oc_config_models():
    """opencode /config → 模型条目(local/cloud 分类)。"""
    from topoone_app_architect.arch_routes.agent_executors import _parse_oc_config
    cfg = {"provider": {
        "AMD-GPU-8200": {"options": {"baseURL": "http://192.168.1.76:8200/v1"},
                         "models": {"Qwen3.8-27B": {}, "Qwen3.6-27B": {}}},
        "siliconflow": {"options": {"baseURL": "https://api.siliconflow.cn/v1"},
                        "models": {"DeepSeek-V4": {}}},
        "no-url": {"models": {"x": {}}},
    }}
    out = _parse_oc_config(cfg)
    got = {(m["model"], m["kind"]) for m in out}
    assert ("AMD-GPU-8200/Qwen3.8-27B", "local") in got
    assert ("siliconflow/DeepSeek-V4", "cloud") in got
    assert not any(m["model"].startswith("no-url") for m in out)
    assert all(m["url"] for m in out)
