"""exec_cline 透传路由测试（transport 打桩，不起真 runner）。

Run: cd <repo> && python -m pytest apps/architect/tests/test_exec_cline_routes.py -q
"""
from __future__ import annotations

import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import FastAPI
from fastapi.testclient import TestClient

from topoone_app_architect.arch_routes import exec_cline


def _client_with_transport(recorder):
    """recorder(path, payload, timeout) → dict；注入 RunnerClient transport。"""
    exec_cline._client = exec_cline.RunnerClient(recorder)
    app = FastAPI()
    app.include_router(exec_cline.router, prefix="/api/architect")
    return TestClient(app)


def test_messages_passthrough():
    seen = {}

    def transport(path, payload=None, timeout=12.0):
        seen["path"] = path
        return {"ok": True, "messages": [{"role": "user", "content": "hi"}]}

    with _client_with_transport(transport) as c:
        r = c.get("/api/architect/exec/j1/messages").json()
    assert r["code"] == 0
    assert r["data"]["messages"][0]["content"] == "hi"
    assert "display=true" in seen["path"]


def test_checkpoints_run_count_query():
    seen = {}

    def transport(path, payload=None, timeout=12.0):
        seen["path"] = path
        return {"ok": True, "compare": {"changedFiles": []}}

    with _client_with_transport(transport) as c:
        r = c.get("/api/architect/exec/j1/checkpoints?runCount=3").json()
    assert r["code"] == 0
    assert "runCount=3" in seen["path"]


def test_restore_payload():
    seen = {}

    def transport(path, payload=None, timeout=12.0):
        seen["path"], seen["payload"] = path, payload
        return {"ok": True, "restore": {"sessionId": "s9"}}

    with _client_with_transport(transport) as c:
        r = c.post("/api/architect/exec/j1/restore",
                   json={"runCount": 2, "options": {"workspace": True}}).json()
    assert r["code"] == 0
    assert seen["payload"]["runCount"] == 2
    assert seen["payload"]["options"] == {"workspace": True}


def test_model_requires_model_id():
    def transport(path, payload=None, timeout=12.0):
        return {"ok": True}

    with _client_with_transport(transport) as c:
        r = c.post("/api/architect/exec/j1/model", json={"modelId": ""})
    assert r.status_code == 400


def test_approval_passthrough():
    seen = {}

    def transport(path, payload=None, timeout=12.0):
        seen["path"], seen["payload"] = path, payload
        return {"ok": True}

    with _client_with_transport(transport) as c:
        r = c.post("/api/architect/exec/j1/approval",
                   json={"requestId": "apr-7", "approved": False,
                         "reason": "out of boundary"}).json()
    assert r["code"] == 0
    assert seen["payload"] == {"requestId": "apr-7", "approved": False,
                               "reason": "out of boundary"}


def test_runner_error_passthrough():
    def transport(path, payload=None, timeout=12.0):
        return {"ok": False, "error": "当前执行器(fake-bare)不支持 read_messages"}

    with _client_with_transport(transport) as c:
        r = c.get("/api/architect/exec/j1/messages")
    assert r.status_code == 400
    assert "不支持" in r.json()["message"]
