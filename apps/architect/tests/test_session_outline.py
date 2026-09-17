"""K3 会话大纲回归——回合对 fold + 回执卡标注 + docs H2 大纲(fence 感知) + REST。

Run: cd <repo> && python -m pytest apps/architect/tests/test_session_outline.py -q
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topoone_app_architect.arch_routes import store  # noqa: E402
from topoone_app_architect.arch_routes.sessions import _doc_outline  # noqa: E402


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


def _mk_conv_with_turns():
    from topoone_app_architect.agent.collab import cards as _cards
    conv = store.ConversationsStore.create({"title": "大纲会话", "projectId": "pj-o"})
    cid = conv["id"]

    def _add(role, text):
        # 生产同款落流路径(cards.land 唯一出口)
        _cards.land(cid, text, role=role, project_id="pj-o")

    _add("user", "请分析支付模块的超时问题")
    _add("assistant", "支付超时主要来自网关重试策略……")
    _add("assistant", "补充: 还有连接池配置问题。")
    _add("user", "那重试上限是多少?")
    _add("assistant", "默认三次，指数退避。")
    return cid


def test_outline_turn_pairs_and_cards(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from topoone_app_architect.arch_routes import router as arch_router
    _setup_env(tmp_path, monkeypatch)
    cid = _mk_conv_with_turns()
    # 回执卡单独标注(不入回合正文)
    from topoone_app_architect.agent.collab import cards as _cards
    _cards.land(cid, "任务已发起", kind="task_start", project_id="pj-o",
                taskId="tk-1")
    app = FastAPI()
    app.include_router(arch_router)
    with TestClient(app, raise_server_exceptions=False) as client:
        res = client.get(f"/api/architect/sessions/{cid}/outline")
        assert res.status_code == 200
        data = res.json()["data"]
        turns, cards = data["turns"], data["cards"]
        assert len(turns) == 2                      # 两个回合对
        assert "支付模块的超时" in turns[0]["prompt"]
        assert "网关重试策略" in turns[0]["response"]   # 首个 assistant 非空
        assert turns[0]["msgCount"] == 3            # user + 2 assistant
        assert turns[1]["prompt"] == "那重试上限是多少?"
        assert turns[1]["response"] == "默认三次，指数退避。"
        assert [c["kind"] for c in cards] == ["task_start"]
        # 卡片不打断回合计数
        assert turns[0]["msgCount"] == 3


def test_doc_outline_fence_aware():
    md = """# 标题
## 第一节
```python
## 不是标题(代码块内)
```
## 第二节
### 不收 H3
"""
    out = _doc_outline(md)
    assert [o["text"] for o in out] == ["第一节", "第二节"]


def test_docs_list_carries_outline(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from topoone_app_architect.arch_routes import router as arch_router
    _setup_env(tmp_path, monkeypatch)
    store.DocsStore.create({"conversationId": "cv-d", "title": "方案",
                            "contentMd": "## 背景\nx\n## 方案\ny"})
    app = FastAPI()
    app.include_router(arch_router)
    with TestClient(app, raise_server_exceptions=False) as client:
        docs = client.get("/api/architect/session-docs?conversation_id=cv-d").json()["data"]
        assert [o["text"] for o in docs[0]["outline"]] == ["背景", "方案"]
