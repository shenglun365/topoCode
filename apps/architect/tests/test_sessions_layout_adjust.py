"""会话中心布局调整回归——/units 跨会话列示(scope=all 跨全库) + 大纲标题语义缩略端点降级。

Run: cd <repo> && python -m pytest apps/architect/tests/test_sessions_layout_adjust.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect import store  # noqa: E402


def _setup_env(tmp_path, monkeypatch):
    import topoone_app_architect.ctx as C
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


def test_units_cross_session_scope_all(tmp_path, monkeypatch):
    """/units 缺省 convId + scope=all: 跨库(主库+项目库)汇总, 条目带 conversationId。"""
    _setup_env(tmp_path, monkeypatch)
    c1 = store.ConversationsStore.create({"title": "会话一", "projectId": "pj-a"})
    c2 = store.ConversationsStore.create({"title": "会话二", "projectId": "pj-b"})
    # 分别落在不同项目库 + 主库各一条
    store.ContextUnitsStore.create({"conversationId": c1["id"], "projectId": "pj-a",
                                    "type": "execution_report", "title": "回执一", "content": "x"})
    store.ContextUnitsStore.create({"conversationId": c2["id"], "projectId": "pj-b",
                                    "type": "analysis", "title": "分析二", "content": "y"})
    store.ContextUnitsStore.create({"type": "note", "title": "主库笔记", "content": "z"})
    with _mk_app() as client:
        res = client.get("/api/architect/units?scope=all&limit=200")
        assert res.status_code == 200
        rows = res.json()["data"]["units"]
        titles = {r["title"] for r in rows}
        assert {"回执一", "分析二", "主库笔记"} <= titles
        conv_ids = {r["conversationId"] for r in rows if r["title"] in ("回执一", "分析二")}
        assert conv_ids == {c1["id"], c2["id"]}
        # createdAt 倒序(跨库归并重排)
        ts = [r.get("createdAt") or 0 for r in rows]
        assert ts == sorted(ts, reverse=True)
        # q 检索路径(scope=all)
        res2 = client.get("/api/architect/units?scope=all&q=回执")
        rows2 = res2.json()["data"]["units"]
        assert [r["title"] for r in rows2] == ["回执一"]


def test_units_single_conv_still_works(tmp_path, monkeypatch):
    """/units?convId= 既有口径回归: 会话过滤 + 未知会话 404。"""
    _setup_env(tmp_path, monkeypatch)
    c1 = store.ConversationsStore.create({"title": "会话一", "projectId": "pj-a"})
    c2 = store.ConversationsStore.create({"title": "会话二", "projectId": "pj-a"})
    store.ContextUnitsStore.create({"conversationId": c1["id"], "projectId": "pj-a",
                                    "type": "artifact", "title": "产物一", "content": "x"})
    store.ContextUnitsStore.create({"conversationId": c2["id"], "projectId": "pj-a",
                                    "type": "artifact", "title": "产物二", "content": "y"})
    with _mk_app() as client:
        rows = client.get(f"/api/architect/units?convId={c1['id']}").json()["data"]["units"]
        assert [r["title"] for r in rows] == ["产物一"]
        assert client.get("/api/architect/units?convId=cv-nope").status_code == 404


def test_outline_abbreviate_degrades_without_llm(tmp_path, monkeypatch):
    """大纲标题缩略端点: LLM 未配置/失败 → 截断降级 + degraded 标注; 形状与上限。"""
    _setup_env(tmp_path, monkeypatch)
    long_text = "请帮我分析一下支付模块在网关重试策略下的超时问题并给出修复建议"
    with _mk_app() as client:
        res = client.post("/api/architect/sessions/outline/abbreviate",
                          json={"items": [{"id": "m-1", "text": long_text},
                                          {"id": "m-2", "text": "短输入"},
                                          {"id": "m-3", "text": "   "}]})
        assert res.status_code == 200
        data = res.json()["data"]
        by_id = {it["id"]: it for it in data["items"]}
        # 降级路径(测试环境无模型): 截断 + degraded
        assert by_id["m-1"]["short"] == long_text[:16]
        assert by_id["m-1"]["degraded"] is True
        assert by_id["m-2"]["degraded"] is True
        assert data["degraded"] is True
        # 空白输入: 不走 LLM, short 为空串
        assert by_id["m-3"]["short"] == ""


def test_outline_abbreviate_rejects_bad_body(tmp_path, monkeypatch):
    _setup_env(tmp_path, monkeypatch)
    with _mk_app() as client:
        assert client.post("/api/architect/sessions/outline/abbreviate",
                           json={"items": "oops"}).status_code == 400
