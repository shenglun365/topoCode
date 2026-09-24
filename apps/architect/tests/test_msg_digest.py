# -*- coding: utf-8 -*-
"""语境摘要(转达下发): REST /sessions/{id}/msg-digest + WS digest 透传 + 审计回执。

- REST: LLM 摘要成功(mock) / 无 LLM 确定性降级(原文截断, summarized=false) / 参数错误
- WS: attachTo 转达携带 digest → task_input 拼接「[附] 会话历史摘要」+ 回执注字数
      + digest_sent 折叠卡落库(留"给执行器发过什么"的感知)

Run: cd <repo> && python -m pytest apps/architect/tests/test_msg_digest.py -q
"""
import asyncio
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import topoone_app_architect.arch_routes.ctx as C  # noqa: E402
from topoone_app_architect.arch_routes import req_agent, store  # noqa: E402
from topoone_app_architect.arch_routes import sessions  # noqa: E402
from topoone_app_architect.arch_routes.common import _ts  # noqa: E402

from fastapi.testclient import TestClient  # noqa: E402
from topoone_app_architect.server import build_app  # noqa: E402

WS_PATH = "/api/architect/ws/kb-analysis"


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    return data


class _Req:
    def __init__(self, payload):
        self._p = payload

    async def json(self):
        return self._p


def _content(resp):
    if isinstance(resp, dict):
        return resp
    return json.loads(resp.body)


def _mk_msgs(conv_id):
    """两条带 id 的历史消息(主会话 user + assistant)。"""
    s = store.ConversationsStore
    ids = []
    for role, content in (("user", "讨论决定用方案B实现登录"),
                          ("assistant", "方案B需要 OAuth 回调地址")):
        mid = store.next_id("m")
        s.append_message({"id": mid, "conversationId": conv_id, "role": role,
                          "time": _ts(), "content": content})
        ids.append(mid)
    return ids


# ── REST /msg-digest ─────────────────────────────────────────────────

def test_msg_digest_summarized(tmp_env, monkeypatch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    ids = _mk_msgs(conv["id"])
    import topoone_app_architect.agent.reflection.repair as ad
    seen = {}

    def _fake_summarize(**kw):
        seen["material"] = kw["material"]
        seen["system"] = kw["system"]
        return {"ok": True, "output": "决定用方案B; OAuth 回调必填", "degraded": False}

    monkeypatch.setattr(ad, "summarize_task", _fake_summarize)
    r = _content(asyncio.run(sessions.msg_digest(conv["id"], _Req({"msgIds": ids}))))
    assert r["code"] == 0, r
    d = r["data"]
    assert d["digest"] == "决定用方案B; OAuth 回调必填" and d["summarized"] is True
    assert d["chars"] == len(d["digest"])
    # 素材含角色标注与选中内容
    assert "[用户] 讨论决定用方案B" in seen["material"]
    assert "[assistant]" in seen["material"]
    assert "转达摘要" in seen["system"]


def test_msg_digest_fallback_without_llm(tmp_env, monkeypatch):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    ids = _mk_msgs(conv["id"])

    def _boom(*a, **k):
        raise RuntimeError("no llm")

    monkeypatch.setattr(req_agent, "llm_sync", _boom)
    r = _content(asyncio.run(sessions.msg_digest(conv["id"], _Req({"msgIds": ids}))))
    assert r["code"] == 0
    d = r["data"]
    assert d["summarized"] is False                      # 降级标记
    assert "方案B" in d["digest"]                        # 原文兜底可用
    assert r is not None


def test_msg_digest_param_errors(tmp_env):
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    # 会话不存在 → 404
    r0 = _content(asyncio.run(sessions.msg_digest("no-such", _Req({"msgIds": ["m1"]}))))
    assert r0["code"] == 404
    # 空 msgIds → 400
    r1 = _content(asyncio.run(sessions.msg_digest(conv["id"], _Req({"msgIds": []}))))
    assert r1["code"] == 400
    # msgIds 非数组 → 400
    r2 = _content(asyncio.run(sessions.msg_digest(conv["id"], _Req({"msgIds": "bad"}))))
    assert r2["code"] == 400
    # 全部未知 id → 404
    r3 = _content(asyncio.run(sessions.msg_digest(conv["id"], _Req({"msgIds": ["m-x", "m-y"]}))))
    assert r3["code"] == 404


# ── WS: transfer 携带 digest ─────────────────────────────────────────

def _ws_client(tmp_path, monkeypatch):
    data = str(tmp_path / "ws-arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    monkeypatch.setattr(req_agent, "llm_chat_start", lambda *a, **k: None)
    monkeypatch.setattr(req_agent, "run_tools_loop", lambda msgs, **kw: {"content": "ok"})
    return TestClient(build_app(data_dir=data))


def _recv_until(ws, *types):
    seen = []
    while True:
        ev = ws.receive_json()
        seen.append(ev["type"])
        if ev["type"] in types:
            return ev, seen


def test_transfer_with_digest_and_receipt(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client = _ws_client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    task = store.TasksStore.create({
        "conversationId": conv["id"], "title": "T", "instruction": "x",
        "status": "running", "executorType": "opencode"})
    forwarded = {}

    def _fake_input(task_id, text):
        forwarded["text"] = text
        return {"ok": True, "queued": False}

    monkeypatch.setattr(eb, "task_input", _fake_input)
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            ws.send_json({"type": "chat", "kind": "generic", "title": "t",
                          "conversationId": conv["id"],
                          "messages": [{"role": "user", "content": "继续"}],
                          "attachTo": task["id"],
                          "digest": "历史摘要: 用户选了方案B"})
            done, _ = _recv_until(ws, "done")
            assert "含历史摘要" in done.get("content", ""), done
    # digest 拼接下发(附言 + 摘要段)
    assert "继续" in forwarded["text"]
    assert "[附] 会话历史摘要" in forwarded["text"]
    assert "方案B" in forwarded["text"]
    # 审计回执落库(digest_sent 折叠卡)
    msgs = store.ConversationsStore.messages(conv["id"])
    ds = [m for m in msgs if (m.get("meta") or {}).get("kind") == "digest_sent"]
    assert ds and "方案B" in ds[-1]["content"] and ds[-1]["meta"]["chars"] > 0


def test_transfer_without_digest_unchanged(tmp_path, monkeypatch):
    """不带 digest 的转达行为不变(回归: 无摘要段、无回执卡)。"""
    from topoone_app_architect.arch_routes import exec_bridge as eb
    client = _ws_client(tmp_path, monkeypatch)
    conv = store.ConversationsStore.create({"kind": "generic", "title": "T"})
    task = store.TasksStore.create({
        "conversationId": conv["id"], "title": "T", "instruction": "x",
        "status": "running", "executorType": "opencode"})
    monkeypatch.setattr(eb, "task_input",
                        lambda tid, text: {"ok": True, "queued": False})
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            ws.send_json({"type": "chat", "kind": "generic", "title": "t",
                          "conversationId": conv["id"],
                          "messages": [{"role": "user", "content": "继续"}],
                          "attachTo": task["id"]})
            done, _ = _recv_until(ws, "done")
            assert "已转达" in done.get("content", "")
            assert "含历史摘要" not in done.get("content", "")
    msgs = store.ConversationsStore.messages(conv["id"])
    assert not [m for m in msgs if (m.get("meta") or {}).get("kind") == "digest_sent"]
