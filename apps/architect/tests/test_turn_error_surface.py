"""回合错误完整可见 特征测试(cv-154 实证回归)。

锁定:
  - handle_chat 异常 → WS 层兜底: turnError 落库(刷新不失) + error 事件全文回传
  - LLM 空返回 → turnError 落库 + error 事件带失败上下文(不再只有一句「未返回内容」)

Run: cd <repo> && python -m pytest apps/architect/tests/test_turn_error_surface.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.req_agent as req_agent
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.server import build_app

WS_PATH = "/api/architect/ws/kb-analysis"


def _client(tmp_path, monkeypatch, *, llm_content="ok-reply"):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    monkeypatch.setattr(req_agent, "llm_chat_start", lambda *a, **k: None)

    def _fake_loop(msgs, **kw):
        return {"content": llm_content}

    monkeypatch.setattr(req_agent, "run_tools_loop", _fake_loop)
    return TestClient(build_app(data_dir=data))


def _recv_until(ws, *types):
    while True:
        ev = ws.receive_json()
        if ev["type"] in types:
            return ev


def _chat(ws, conv_id, content="hi"):
    ws.send_json({"type": "chat", "kind": "generic", "title": "t",
                  "conversationId": conv_id,
                  "messages": [{"role": "user", "content": content}]})


def test_handle_chat_exception_persists_turn_error(tmp_path, monkeypatch):
    """回合中途抛异常 → 不再静默: turnError 落库 + error 事件全文。"""
    from topoone_app_architect.agent import orchestrator

    def _boom(*a, **k):
        raise RuntimeError("LLM 通道不可达: connection refused")

    client = _client(tmp_path, monkeypatch)
    monkeypatch.setattr(orchestrator, "bind_session", _boom)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"])
            ev = _recv_until(ws, "error")
    assert "回合失败" in ev["message"] and "connection refused" in ev["message"]
    msgs = store.ConversationsStore.messages(conv["id"], limit=20)
    assert any((m.get("meta") or {}).get("kind") == "turnError" for m in msgs)
    assert any("connection refused" in m["content"] for m in msgs)


def test_empty_llm_return_surfaces_detail(tmp_path, monkeypatch):
    """LLM 空返回 → error 事件带上下文 + turnError 落库(可刷新恢复)。"""
    client = _client(tmp_path, monkeypatch, llm_content="")
    conv = store.ConversationsStore.create({"kind": "generic", "title": "t"})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            _chat(ws, conv["id"])
            ev = _recv_until(ws, "error")
    assert "LLM 未返回内容" in ev["message"]
    msgs = store.ConversationsStore.messages(conv["id"], limit=20)
    assert any((m.get("meta") or {}).get("kind") == "turnError" for m in msgs)
    assert any("❌" in m["content"] for m in msgs)


def test_req_chat_stream_restored(tmp_path, monkeypatch):
    """流式入口回归(cv-156): _req_chat_stream 必须真实调用 llm.chat 并透传
    requestId——函数体曾丢失导致流式通道静默停用两天。"""
    import topoone_app_architect.agent.orchestrator as orch

    captured = {}

    def _fake_start(messages, model_id=None, session_id="", max_tokens=None):
        captured["model"] = model_id
        captured["session"] = session_id
        captured["max_tokens"] = max_tokens
        return "rid-stream-1"

    monkeypatch.setattr(req_agent, "llm_chat_start", _fake_start)
    rid = orch._req_chat_stream([{"role": "user", "content": "hi"}], "model-x")
    assert rid == "rid-stream-1"
    assert captured["model"] == "model-x"
    assert captured["session"] == "arch-req-chat"
