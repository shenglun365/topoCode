"""M04: llm 服务 — mock provider 下 llm.chat 流式 + session CRUD（临时 data_dir）。"""

import asyncio
import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))),
    "backend-core",
))


@pytest.fixture()
def data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _register(data_dir):
    from topoone.db.manager import MultiDBManager
    from topoone.rpc.service_app import MethodServer
    from topoone.llm.__main__ import register_methods

    multi_db = MultiDBManager(data_dir)
    srv = MethodServer(pub_port=None)
    register_methods(srv, multi_db)
    return multi_db, srv


def _add_model(multi_db):
    multi_db.main_db.execute(
        "INSERT INTO model_configs (id, name, provider, model, url) VALUES (?, ?, ?, ?, ?)",
        ("mock-model", "Mock", "ollama", "mock-llm", "http://127.0.0.1:11434"),
    )
    multi_db.main_db.commit()


class _MockProvider:
    def chat_stream(self, model, messages, chunk_queue, tools, mode, max_tokens=None):
        chunk_queue.put("Hello")
        chunk_queue.put(" world")
        chunk_queue.put({"type": "done", "content": "Hello world"})
        return {"prompt_tokens": 1, "completion_tokens": 2}


def test_session_crud(data_dir):
    multi_db, srv = _register(data_dir)
    try:
        created = srv.methods["session.create"](module_type="project_resource", title="t1")
        sid = created["id"]
        assert created["status"] == "active"

        listed = srv.methods["session.list"]()["sessions"]
        assert any(s["id"] == sid for s in listed)

        add = srv.methods["session.addMessage"](session_id=sid, role="user", content="hi")
        assert add.get("id")

        msgs = srv.methods["session.getMessages"](session_id=sid)["messages"]
        assert [m["content"] for m in msgs if m["role"] == "user"] == ["hi"]

        assert srv.methods["session.delete"](session_id=sid)["success"] is True
        listed2 = srv.methods["session.list"]()["sessions"]
        assert not any(s["id"] == sid for s in listed2)
    finally:
        multi_db.close_all()


def test_llm_chat_streaming_with_mock_provider(data_dir, monkeypatch):
    multi_db, srv = _register(data_dir)
    try:
        import topoone.llm.service as svc_mod
        monkeypatch.setattr(svc_mod, "get_provider", lambda name: _MockProvider())
        _add_model(multi_db)

        created = srv.methods["session.create"](module_type="project_resource", title="stream")
        sid = created["id"]

        async def drive():
            res = await srv.methods["llm.chat"](
                session_id=sid, model_id="mock-model",
                messages=[{"role": "user", "content": "hi"}],
            )
            assert res["status"] == "streaming" and res["requestId"]
            deadline = time.time() + 15
            assistant = []
            while time.time() < deadline:
                msgs = srv.methods["session.getMessages"](session_id=sid)["messages"]
                assistant = [m for m in msgs if m["role"] == "assistant"]
                if assistant:
                    break
                await asyncio.sleep(0.1)
            return assistant

        assistant = asyncio.run(drive())
        assert assistant, "assistant message not persisted after streaming"
        assert assistant[0]["content"] == "Hello world"
    finally:
        multi_db.close_all()


def test_llm_chat_validations(data_dir):
    multi_db, srv = _register(data_dir)
    try:
        with pytest.raises(ValueError):
            asyncio.run(srv.methods["llm.chat"](model_id="mock-model",
                                                messages=[{"role": "user", "content": "hi"}]))
        _add_model(multi_db)
        sid = srv.methods["session.create"](module_type="project_resource")["id"]
        with pytest.raises(ValueError, match="Model not found"):
            asyncio.run(srv.methods["llm.chat"](session_id=sid, model_id="nope",
                                                messages=[{"role": "user", "content": "hi"}]))
    finally:
        multi_db.close_all()
