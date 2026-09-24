"""chat REST 核心路径套件（MS1 §4.3）——LLM 打桩于 requests.post 接缝，零真实 HTTP。

打桩策略：legacy 路径的 `_llm_round` 是 send_chat_message 闭包内的同步函数
（chat.py:707），不可 monkeypatch——真实接缝是模块内 `import requests` 后的
`_req.post`（chat.py:749）。SSE 事件格式见 chat.py:951-964。
"""
import json
import threading

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from topoone import config, service_common as common
from topoone.db.manager import MultiDBManager


@pytest.fixture
def chat_env(tmp_path):
    multi_db = MultiDBManager(str(tmp_path / "chatdata"))
    from topoone_app_chat.web_tools import WebToolExecutor
    from topoone_app_chat.chat_tables import ensure_chat_tables

    common.set_globals(multi_db, port=3483, executor=WebToolExecutor(multi_db))
    ensure_chat_tables(multi_db)
    yield multi_db
    common.multi_db = None
    common.web_tool_executor = None
    multi_db.close_all()


@pytest.fixture
def client(chat_env):
    from topoone_app_chat.chat import router as chat_router

    app = FastAPI()
    app.include_router(chat_router)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": "chat-service"}

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def _create_session(client, **kw):
    body = {"title": "新对话", **kw}
    r = client.post("/api/chat/sessions", json=body)
    assert r.status_code == 200, r.text
    return r.json()


def _sse(text):
    events = []
    for block in text.split("\n\n"):
        if not block.strip():
            continue
        ev = {}
        for line in block.split("\n"):
            if line.startswith("event: "):
                ev["event"] = line[7:].strip()
            elif line.startswith("data: "):
                ev["data"] = json.loads(line[6:])
        events.append(ev)
    return events


class _FakeLLMResp:
    """requests.post 打桩：流式 chat.completions + 非流式 auto-title 双形态。"""

    status_code = 200
    text = ""

    def __init__(self, rounds):
        # rounds: list of delta-list；每轮一次 HTTP 调用
        self._rounds = rounds
        self._lock = threading.Lock()

    def iter_lines(self):
        with self._lock:
            deltas = self._rounds.pop(0) if self._rounds else []
        for d in deltas:
            yield f'data: {json.dumps({"choices": [{"delta": d}]})}'.encode("utf-8")
        yield b"data: [DONE]"

    def json(self):
        return {"choices": [{"message": {"content": "自动标题词"}}], "usage": {}}

    def close(self):
        pass


@pytest.fixture
def no_auto_title(monkeypatch):
    import topoone_app_chat.chat as chat_mod
    monkeypatch.setattr(chat_mod, "_do_auto_title", lambda *a, **k: None)


# ── P0: 会话生命周期 ──

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_session_crud_cycle(client, chat_env):
    created = _create_session(client, title="t1", projectId="p1", modelId="m1")
    sid = created["id"]
    assert sid.startswith("chat_") and created["modelId"] == "m1"
    assert created["activeSkills"], "默认 skills 应注入"

    lst = client.get("/api/chat/sessions").json()["sessions"]
    assert any(s["id"] == sid for s in lst)

    one = client.get(f"/api/chat/sessions/{sid}").json()
    assert one["title"] == "t1"
    assert one["messages"] and one["messages"][0]["role"] == "system"  # 系统提示注入

    assert client.put(f"/api/chat/sessions/{sid}",
                      json={"title": "t2", "status": "archived"}).json()["ok"] is True
    assert client.get(f"/api/chat/sessions/{sid}").json()["title"] == "t2"

    assert client.delete(f"/api/chat/sessions/{sid}").json()["ok"] is True
    assert client.get(f"/api/chat/sessions/{sid}").status_code == 404


def test_session_not_found(client, chat_env):
    assert client.get("/api/chat/sessions/chat-nope").status_code == 404


# ── P0: 消息发送（stream=False 持久化通道，无 LLM）──

def test_send_message_stream_false_persists(client, chat_env):
    sid = _create_session(client)["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages",
                    json={"content": "你好", "stream": False})
    assert r.status_code == 200 and r.json()["ok"] is True

    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert msgs["total"] == 1
    assert msgs["messages"][0]["role"] == "user"
    assert msgs["messages"][0]["content"] == "你好"


def test_send_message_session_missing_404(client, chat_env):
    r = client.post("/api/chat/sessions/chat-nope/messages",
                    json={"content": "x", "stream": False})
    assert r.status_code == 404


def test_send_message_limit_400(client, chat_env):
    """SESSION_MAX_MESSAGES（默认 200）触顶 → 业务 400（chat.py:574）。"""
    sid = _create_session(client)["id"]
    sdb = chat_env.chat_db
    now = "2026-01-01T00:00:00"
    for i in range(config.SESSION_MAX_MESSAGES):
        sdb.execute(
            "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, ?, ?, '{}', ?)",
            (f"msg-{i:04d}", sid, "user" if i % 2 == 0 else "assistant", f"m{i}", now),
        )
    sdb.commit()

    r = client.post(f"/api/chat/sessions/{sid}/messages",
                    json={"content": "x", "stream": False})
    assert r.status_code == 400 and "上限" in r.json()["detail"]


# ── P0: SSE 流式（requests.post 打桩）──

def test_send_message_sse_and_persist(client, chat_env, monkeypatch, no_auto_title):
    chat_env.main_db.execute(
        "INSERT INTO model_configs (id, name, provider, model, url, status) "
        "VALUES ('m1', 'stub', 'custom-local', 'stub-model', 'http://127.0.0.1:9', 'connected')"
    )
    chat_env.main_db.commit()
    monkeypatch.setattr("requests.post", lambda *a, **kw: _FakeLLMResp(
        [[{"content": "hello "}, {"content": "world"}]],
    ))

    sid = _create_session(client, modelId="m1")["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages",
                    json={"content": "打个招呼", "modelId": "m1"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    events = _sse(r.text)
    assert events, "SSE 事件不应为空"
    assert events[-1]["event"] == "done"
    assert events[-1]["data"]["content"] == "hello world"

    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
    contents = [m["content"] for m in msgs["messages"]]
    assert "hello world" in contents  # assistant 落库
    assert "打个招呼" in contents      # user 落库


def test_send_message_tool_loop_events(client, chat_env, monkeypatch, no_auto_title):
    """工具循环：round0 工具调用 → tool_call/tool_result 事件 + tool 消息落库；round1 终答。"""
    chat_env.main_db.execute(
        "INSERT INTO model_configs (id, name, provider, model, url, status) "
        "VALUES ('m1', 'stub', 'custom-local', 'stub-model', 'http://127.0.0.1:9', 'connected')"
    )
    chat_env.main_db.commit()

    tool_call_delta = [{
        "index": 0, "id": "call_1", "type": "function",
        "function": {"name": "web_list_projects", "arguments": "{}"},
    }]

    fake = _FakeLLMResp([
        [{"tool_calls": tool_call_delta}],          # round0: 要求调工具
        [{"content": "项目列表为空"}],               # round1: 终答
    ])
    monkeypatch.setattr("requests.post", lambda *a, **kw: fake)

    sid = _create_session(client, modelId="m1")["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages",
                    json={"content": "列出项目", "modelId": "m1"})
    events = _sse(r.text)
    kinds = [e["event"] for e in events]

    assert "tool_call" in kinds and "tool_result" in kinds
    tc = next(e for e in events if e["event"] == "tool_call")
    assert tc["data"]["name"] == "web_list_projects"
    assert events[-1]["event"] == "done" and events[-1]["data"]["content"] == "项目列表为空"

    # tool 消息落库（chat.py:921-925）
    rows = chat_env.chat_db.fetchall(
        "SELECT role, content FROM llm_messages WHERE session_id = ? AND role = 'tool'", (sid,))
    assert rows and "projects" in rows[0]["content"]


def test_send_message_sse_model_missing_error(client, chat_env, monkeypatch, no_auto_title):
    """model_id 无配置 → SSE error 事件（chat.py:712），非 500。"""
    sid = _create_session(client, modelId="m-gone")["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages",
                    json={"content": "x", "modelId": "m-gone"})
    assert r.status_code == 200  # HTTP 层成功，错误走 SSE error 事件
    events = _sse(r.text)
    assert events[-1]["event"] == "error" and "Model not found" in events[-1]["data"]["message"]


def test_stream_abort(client, chat_env):
    sid = _create_session(client)["id"]
    assert client.post(f"/api/chat/sessions/{sid}/stream/abort").json() == {"ok": True}


# ── P1: /compress 命令分支 ──

def test_compress_branch(client, chat_env, monkeypatch):
    """compress 流为裸 data: 行（无 event 前缀，chat.py:559-561）。"""
    import topoone_app_chat.chat as chat_mod

    async def fake_execute(self, content, session_id):
        return "压缩摘要文本"

    monkeypatch.setattr(chat_mod.SessionCompressor, "execute", fake_execute)
    sid = _create_session(client)["id"]
    r = client.post(f"/api/chat/sessions/{sid}/messages",
                    json={"content": "/compress", "modelId": ""})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    # json.dumps 默认 ensure_ascii → 中文以 \uXXXX 出现在裸 data: 行
    assert "\\u538b\\u7f29\\u6458\\u8981" in r.text  # 压缩摘要


# ── P1: models / skills / autocomplete / template-locale ──

def test_models_empty_and_update(client, chat_env):
    body = client.get("/api/models").json()
    assert body == {"models": [], "webChatDefaultModelId": None}

    chat_env.main_db.execute(
        "INSERT INTO model_configs (id, name, provider, model, url, type, is_default) "
        "VALUES ('m1', 'Stub', 'custom-local', 'stub-model', 'http://x', 'local', 1)"
    )
    chat_env.main_db.commit()

    body = client.get("/api/models").json()
    assert body["models"][0]["id"] == "m1" and body["models"][0]["badge"] == "本地"
    assert body["webChatDefaultModelId"] is None

    assert client.put("/api/models/m1", json={"extraConfig": {"top_p": 0.9}}).json()["ok"] is True
    row = chat_env.main_db.fetchone("SELECT extra_config FROM model_configs WHERE id='m1'")
    assert json.loads(row["extra_config"]) == {"top_p": 0.9}


def test_skills_registry(client):
    body = client.get("/api/skills").json()
    assert body["skills"] and body["defaults"]


def test_autocomplete_session(client, chat_env):
    created = _create_session(client, title="搜索我")
    r = client.get("/api/chat/autocomplete", params={"type": "session", "q": "搜索"})
    hits = [x for x in r.json()["results"] if x["value"] == created["id"]]
    assert hits and hits[0]["type"] == "session"

    empty = client.get("/api/chat/autocomplete", params={"type": "session", "q": ""})
    assert empty.json()["results"] == []


def test_template_locale_default(client):
    assert client.get("/api/template-locale").json() == {"locale": "zh-CN"}


# ── P1: messages 管理 ──

def test_messages_pagination_and_delete(client, chat_env):
    sid = _create_session(client)["id"]
    sdb = chat_env.chat_db
    for i in range(5):
        sdb.execute(
            "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
            "VALUES (?, ?, 'user', ?, '{}', ?)",
            (f"m-{sid}-{i}", sid, f"c{i}", f"2026-01-0{i + 1}T00:00:00"),
        )
    sdb.commit()

    page = client.get(f"/api/chat/sessions/{sid}/messages",
                      params={"limit": 2, "offset": 0}).json()
    assert page["total"] == 5 and len(page["messages"]) == 2

    r = client.delete(f"/api/chat/sessions/{sid}/messages")  # 缺 message_id
    assert r.status_code == 422

    r = client.delete(f"/api/chat/sessions/{sid}/messages",
                      params={"message_id": f"m-{sid}-0"})
    assert r.json() == {"ok": True, "deleted": 1}
    assert client.get(f"/api/chat/sessions/{sid}/messages").json()["total"] == 4


def test_message_batch_update(client, chat_env):
    sid = _create_session(client)["id"]
    sdb = chat_env.chat_db
    sdb.execute(
        "INSERT INTO llm_messages (id, session_id, role, content, metadata, created_at) "
        f"VALUES ('mm-1', '{sid}', 'user', 'old', '{{}}', '2026-01-01T00:00:00')"
    )
    sdb.commit()
    r = client.post(f"/api/chat/sessions/{sid}/messages/batch",
                    json={"messages": [{"id": "mm-1", "content": "new"}]})
    assert r.json() == {"saved": 1}
    row = sdb.fetchone("SELECT content FROM llm_messages WHERE id='mm-1'")
    assert row["content"] == "new"


# ── P1: drafts ──

def test_draft_lifecycle_and_send(client, chat_env):
    r = client.post("/api/drafts", json={"title": "便签1", "content": "内容", "refs": [{"projectId": "p1"}]})
    did = r.json()["id"]
    assert did.startswith("draft_")

    lst = client.get("/api/drafts", params={"status": "draft"}).json()
    assert any(d["id"] == did for d in lst["drafts"])

    assert client.put(f"/api/drafts/{did}",
                      json={"refs": [{"projectId": "p2"}]}).json()["ok"] is True
    one = client.get(f"/api/drafts/{did}").json()
    assert len(one["refs"]) == 2  # refs merge 去重追加（chat.py:1277-1285）

    out = client.post(f"/api/drafts/{did}/send", json={}).json()
    sid = out["sessionId"]
    assert out["ok"] is True and out["messageId"]
    assert client.get(f"/api/drafts/{did}").json()["status"] == "sent"
    assert client.post(f"/api/drafts/{did}/send", json={}).status_code == 400  # 已发送

    msgs = client.get(f"/api/chat/sessions/{sid}/messages").json()
    assert msgs["total"] == 1  # 草稿内容作为 user 消息落库

    assert client.delete(f"/api/drafts/{did}").json()["ok"] is True
    assert client.get(f"/api/drafts/{did}").status_code == 404


def test_batch_send_skips_already_sent(client, chat_env):
    ids = [client.post("/api/drafts", json={"title": f"d{i}", "content": "x"}).json()["id"]
           for i in range(2)]
    client.post(f"/api/drafts/{ids[0]}/send", json={})
    r = client.post("/api/drafts/batch-send", json={"draftIds": ids})  # 已发送的跳过不报错
    assert r.status_code == 200


# ── P1: notes（写 knowledge_db.knowledge_docs）──

def test_notes_lifecycle(client, chat_env):
    nid = client.post("/api/notes", json={"title": "N1", "content": "note body"}).json()["id"]
    assert nid.startswith("note_")

    lst = client.get("/api/notes", params={"search": "N1"}).json()
    assert lst["total"] == 1

    assert client.get(f"/api/notes/{nid}").json()["title"] == "N1"
    assert client.get("/api/notes/note-nope").status_code == 404

    assert client.put(f"/api/notes/{nid}", json={"content": "updated"}).json()["ok"] is True
    assert client.get(f"/api/notes/{nid}").json()["content"] == "updated"

    assert client.delete(f"/api/notes/{nid}").json()["ok"] is True
    assert client.get(f"/api/notes/{nid}").status_code == 404


# ── P2: archives ──

def test_archives_roundtrip(client, chat_env):
    aid = client.post("/api/chat/archives",
                      json={"title": "A1", "content": "x" * 600, "category": "note"}).json()["id"]
    lst = client.get("/api/chat/archives", params={"category": "note"}).json()
    assert lst["total"] == 1
    assert len(lst["archives"][0]["content"]) == 500  # content 截断 500（chat.py:1178）

    assert client.delete(f"/api/chat/archives/{aid}").json()["ok"] is True
    assert client.get("/api/chat/archives").json()["total"] == 0
