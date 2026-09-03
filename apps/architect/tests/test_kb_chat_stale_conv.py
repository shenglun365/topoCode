"""KB 对话 WS：陈旧 conversationId 自愈降级测试。

浏览器 tab 内存保留的 chatConvId 可能指向已不存在的会话（服务重启/数据目录
迁移/多实例并存导致库漂移）。后端查不到时必须降级新建会话继续
（payload.messages 为全量历史，零丢失；done 事件回传新 id，前端自动跟进），
而非报 "conversation not found" 后 return——那会让该 tab 之后每条消息永远失败。

注：测试走 llm.sync 降级通道（流式 rid=None），该路径不发 chat_start，
首个事件即 chunk/done——与活体流式路径(有 chat_start)事件序不同，断言以
终态 done + 落库为准。

Run: cd <repo> && python -m pytest apps/architect/tests/test_kb_chat_stale_conv.py -q
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


def _client(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    C.setup(data_dir=data)
    # LLM 通道确定性降级：流式不可用(None) → llm.sync(run_tools_loop) 直返固定文案。
    # 本测试只关注会话自愈链路，不触发网络。
    monkeypatch.setattr(req_agent, "llm_chat_start", lambda *a, **k: None)
    monkeypatch.setattr(req_agent, "run_tools_loop", lambda *a, **k: {"content": "ok-reply"})
    return TestClient(build_app(data_dir=data))


def _recv_until(ws, *types):
    """收事件直到命中给定类型，返回 (事件, 已收类型列表)。"""
    seen = []
    while True:
        ev = ws.receive_json()
        seen.append(ev["type"])
        if ev["type"] in types:
            return ev, seen


def test_stale_conversation_falls_back_to_fresh(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            ws.send_json({"type": "chat", "kind": "asset", "title": "t",
                          "conversationId": "cv-stale-id",
                          "messages": [{"role": "user", "content": "hi"}]})
            done, seen = _recv_until(ws, "done", "error")
            # 回归断言：不再报 "conversation not found"，正常收尾
            assert done["type"] == "done", (seen, done)
            assert "conversation not found" not in str(seen)
            # 进度反馈：降级路径必须先推 status(sync) 相变事件(此前全程零反馈)
            assert "status" in seen, seen
            new_id = done.get("conversationId") or ""
            assert new_id and new_id != "cv-stale-id"
            # 新会话已落库，用户/助手消息均持久化
            assert store.ConversationsStore.get(new_id) is not None
            roles = [m["role"] for m in store.ConversationsStore.messages(new_id)]
            assert "user" in roles and "assistant" in roles


def test_existing_conversation_reused(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)
    with client:
        with client.websocket_connect(WS_PATH) as ws:
            conv = store.ConversationsStore.create({
                "kind": "asset", "projectId": "", "reqId": "",
                "title": "seed", "status": "active", "meta": {"title": "seed"},
            })
            ws.send_json({"type": "chat", "kind": "asset", "title": "t",
                          "conversationId": conv["id"],
                          "messages": [{"role": "user", "content": "hi"}]})
            done, seen = _recv_until(ws, "done", "error")
            assert done["type"] == "done", (seen, done)
            # 存活会话照常复用，不新建
            assert done.get("conversationId") == conv["id"]
