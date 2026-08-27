"""需求会话消息删除测试：已绑定正式提案的会话允许删除单条消息(统一工作台主编辑界面)。

Run: cd <repo> && python -m pytest apps/architect/tests/test_conversation_delete.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.server import build_app


def _setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.reset_req(C._req_var.set(None))
    return C.setup(data_dir=data)


def _client(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    return TestClient(build_app(data_dir=str(tmp_path / "arch")))


def _seed_bound_conv():
    """建需求 + 绑定会话(带两条消息)。返回 (conv_id, msg_ids)。"""
    store.RequirementsStore.create({
        "id": "rq-1", "title": "T", "desc": "", "status": "raw",
        "location": "proposal", "priority": "P1", "updatedAt": 1,
    })
    conv = store.ConversationsStore.create({
        "kind": "requirement", "projectId": "", "reqId": "rq-1",
        "title": "conv", "status": "active", "meta": {"title": "conv"},
    })
    store.ConversationsStore.append_message({
        "id": "m-1", "conversationId": conv["id"], "role": "user",
        "time": 1, "content": "第一问",
    })
    store.ConversationsStore.append_message({
        "id": "m-2", "conversationId": conv["id"], "role": "assistant",
        "time": 2, "content": "答复",
    })
    return conv["id"], ["m-1", "m-2"]


class TestDeleteMessage:
    def test_delete_bound_conversation_message(self, tmp_path, monkeypatch):
        client = _client(tmp_path, monkeypatch)
        with client:
            conv_id, [m1, m2] = _seed_bound_conv()
            r = client.delete(f"/api/architect/requirements/conversations/{conv_id}/messages/{m1}")
            assert r.status_code == 200
            assert r.json()["data"]["deleted"] is True
            left = [m["id"] for m in store.ConversationsStore.messages(conv_id)]
            assert left == [m2]

    def test_delete_unknown_conversation(self, tmp_path, monkeypatch):
        client = _client(tmp_path, monkeypatch)
        with client:
            r = client.delete("/api/architect/requirements/conversations/cv-x/messages/m-1")
            assert r.json()["code"] == 404

    def test_delete_unknown_message(self, tmp_path, monkeypatch):
        client = _client(tmp_path, monkeypatch)
        with client:
            conv_id, _ = _seed_bound_conv()
            r = client.delete(f"/api/architect/requirements/conversations/{conv_id}/messages/m-404")
            assert r.json()["code"] == 404
