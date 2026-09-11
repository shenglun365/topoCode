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
