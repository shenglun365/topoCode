"""A7 测试：聊天流 → tAgent 代码问答(tagent_chat.chat_reply + /ws/coding-agent)。

临时 DB + TestClient + ScriptedGateway(脚本化 LLM)，零真实 HTTP/LLM。验证：
- chat_reply: LLM 返回文本 → 回答; 不可达 → None; 空 → None
- WS 流: session.create → session.message → assistant 回复(tAgent) + user 回显
- WS 降级: KB 不可达 → 无 assistant，仅 user 回显
"""
import os
import sys

import pytest

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient
from topoone_app_architect.arch_routes import ctx, kb_gateway, tagent_chat
from topoone_app_architect.server import build_app


class ScriptedGateway:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def call(self, method, timeout=None, **params):
        self.calls.append((method, params))
        if method != "llm.sync":
            return None
        if not self.script:
            return {"content": "", "mode": "chat"}
        return self.script.pop(0)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(ctx, "_db", None, raising=False)
    monkeypatch.setattr(ctx, "_data_dir", None, raising=False)
    app = build_app(data_dir=str(tmp_path / "arch"))
    return TestClient(app)


# ── tagent_chat.chat_reply 单测 ─────────────────────────────────────

def test_chat_reply_returns_answer(monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway",
                        lambda: ScriptedGateway([{"content": "订单服务负责创建/退款", "mode": "chat"}]))
    result = tagent_chat.chat_reply(question="订单服务做什么?", root="/tmp/x", project="")
    assert result == "订单服务负责创建/退款"


def test_chat_reply_unreachable_none(monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway", lambda: None)
    assert tagent_chat.chat_reply(question="x", root="", project="") is None


def test_chat_reply_empty_none(monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway",
                        lambda: ScriptedGateway([{"content": "", "mode": "chat"}]))
    assert tagent_chat.chat_reply(question="x", root="", project="") is None


def test_chat_reply_with_task_context(monkeypatch):
    # 带任务上下文时仍能回答(上下文拼入 user prompt)
    monkeypatch.setattr(kb_gateway, "get_gateway",
                        lambda: ScriptedGateway([{"content": "基于任务: 实现幂等", "mode": "chat"}]))
    result = tagent_chat.chat_reply(
        question="如何实现幂等?", root="/tmp/x", project="p1",
        task_context="执行任务: ex-1\n需求: 订单幂等")
    assert result == "基于任务: 实现幂等"


# ── WS 流 ───────────────────────────────────────────────────────────

def test_ws_chat_flow(client, monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway",
                        lambda: ScriptedGateway([{"content": "订单服务负责创建订单", "mode": "chat"}]))
    with client.websocket_connect("/api/architect/ws/coding-agent") as ws:
        ws.send_json({"type": "session.create", "exec": {"id": "ex-1", "adapter": "opencode"}, "planTitle": "方案"})
        ev = ws.receive_json()
        assert ev["type"] == "session_created", ev
        sid = ev["session"]["id"]
        # 无 opencodeSessionId(A7 不再对接 opencode)
        assert not ev["session"].get("opencodeSessionId"), ev

        ws.send_json({"type": "session.message", "sessionId": sid, "content": "订单服务做什么?"})
        # 第一个 message = assistant(tAgent 回复)；status(chat/idle) 相变事件先行，跳过
        ev1 = ws.receive_json()
        while ev1["type"] == "status":
            ev1 = ws.receive_json()
        assert ev1["type"] == "message" and ev1["role"] == "assistant", ev1
        assert ev1["content"] == "订单服务负责创建订单", ev1
        # 第二个 message = user 回显
        ev2 = ws.receive_json()
        assert ev2["type"] == "message" and ev2["role"] == "user", ev2
        assert ev2["content"] == "订单服务做什么?", ev2


def test_ws_chat_degrade_no_kb(client, monkeypatch):
    # KB 不可达 → 无 assistant 回复，仅 user 回显
    monkeypatch.setattr(kb_gateway, "get_gateway", lambda: None)
    with client.websocket_connect("/api/architect/ws/coding-agent") as ws:
        ws.send_json({"type": "session.create", "exec": {"id": "ex-1"}, "planTitle": "方案"})
        ev = ws.receive_json()
        sid = ev["session"]["id"]
        ws.send_json({"type": "session.message", "sessionId": sid, "content": "你好"})
        ev1 = ws.receive_json()
        while ev1["type"] == "status":  # 进度相变事件(chat/idle)先于消息回显，跳过
            ev1 = ws.receive_json()
        assert ev1["type"] == "message" and ev1["role"] == "user", ev1
        assert ev1["content"] == "你好", ev1


def test_ws_chat_stop(client, monkeypatch):
    monkeypatch.setattr(kb_gateway, "get_gateway", lambda: None)
    with client.websocket_connect("/api/architect/ws/coding-agent") as ws:
        ws.send_json({"type": "session.create", "exec": {"id": "ex-1"}, "planTitle": "方案"})
        ev = ws.receive_json()
        sid = ev["session"]["id"]
        ws.send_json({"type": "session.stop", "sessionId": sid})
        ev = ws.receive_json()
        assert ev["type"] == "stopped" and ev["status"] == "stopped", ev
