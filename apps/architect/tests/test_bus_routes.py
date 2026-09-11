"""P3.3 bus 桥接路由测试：/bus/publish 代理 + /bus/needs-input 汇总 + 需求会话注入。

Run: cd <repo> && python -m pytest apps/architect/tests/test_bus_routes.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

from fastapi.testclient import TestClient

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store
from topoone_app_architect.server import build_app

_BUS_PATH = "topoone_app_architect.arch_routes.bus_client.get_bus"


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


class _FakeBus:
    def __init__(self, res=None):
        self.res = res
        self.calls = []

    def publish(self, src, dst, topic, payload=None):
        self.calls.append({"src": src, "dst": dst, "topic": topic, "payload": payload or {}})
        return self.res


def _make_req(req_id="rq-1", title="T"):
    store.RequirementsStore.create({
        "id": req_id, "title": title, "desc": "", "status": "analyzed",
        "location": "pool", "priority": "P1", "updatedAt": 1,
    })


def _make_exec(exec_id="ex-1", status="created"):
    store.ExecutionTasksStore.create({
        "id": exec_id, "planId": "pl-1", "adapter": "opencode",
        "reqIds": ["rq-1"], "connectivity": "ok", "status": status,
        "sessionIds": [], "baseCommit": "", "runCount": 0, "createdAt": 1,
    })


def _make_conv(req_id="rq-1"):
    return store.ConversationsStore.create({
        "kind": "requirement", "projectId": "", "reqId": req_id,
        "title": "conv", "status": "active", "meta": {"title": "conv"},
    })


class TestBusPublish:
    def _client(self, tmp_path, monkeypatch, res=None):
        _setup(tmp_path, monkeypatch)
        fake = _FakeBus(res)
        monkeypatch.setattr(_BUS_PATH, lambda: fake)
        return TestClient(build_app(data_dir=str(tmp_path / "arch"))), fake

    def test_publish_ok(self, tmp_path, monkeypatch):
        client, fake = self._client(tmp_path, monkeypatch, res={"id": "bus-1", "status": "pending"})
        with client:
            r = client.post("/api/architect/bus/publish", json={
                "src": "coding", "dst": "plan", "topic": "execution.amend",
                "payload": {"reqId": "rq-1", "message": "计划需修正"},
            })
            assert r.status_code == 200
            assert r.json()["code"] == 0
            assert r.json()["data"]["id"] == "bus-1"
            c = fake.calls[0]
            assert c["topic"] == "execution.amend" and c["dst"] == "plan"

    def test_publish_broker_down(self, tmp_path, monkeypatch):
        client, _fake = self._client(tmp_path, monkeypatch, res=None)
        with client:
            r = client.post("/api/architect/bus/publish", json={
                "src": "user", "dst": "plan", "topic": "interaction.answer",
                "payload": {"answer": "ok"},
            })
            assert r.json()["code"] == 503

    def test_publish_requires_topic(self, tmp_path, monkeypatch):
        client, _fake = self._client(tmp_path, monkeypatch)
        with client:
            r = client.post("/api/architect/bus/publish",
                            json={"src": "a", "dst": "b"})
            assert r.json()["code"] == 400


class TestNeedsInput:
    def _client(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        return TestClient(build_app(data_dir=str(tmp_path / "arch")))

    def test_counts_unanswered_clarify_only(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            _make_req()
            # 未回复 clarify
            store.AgentBusStore.create({
                "id": "bus-c1", "src": "coding", "dst": "user",
                "topic": "interaction.clarify",
                "payload": {"reqId": "rq-1", "message": "选哪个方案?"},
                "status": "delivered", "createdAt": 1, "updatedAt": 1,
            })
            # 已回复 clarify(不计)
            store.AgentBusStore.create({
                "id": "bus-c2", "src": "plan", "dst": "user",
                "topic": "interaction.clarify",
                "payload": {"reqId": "rq-1", "message": "旧问题"},
                "status": "delivered", "createdAt": 2, "updatedAt": 2,
            })
            store.AgentBusStore.create({
                "id": "bus-a2", "src": "user", "dst": "plan",
                "topic": "interaction.answer",
                "payload": {"replyTo": "bus-c2", "message": "已答"},
                "status": "delivered", "createdAt": 3, "updatedAt": 3,
            })
            r = client.get("/api/architect/bus/needs-input").json()["data"]
            assert r["count"] == 1, r
            assert r["items"][0]["type"] == "clarify"
            assert r["items"][0]["label"] == "选哪个方案?"

    def test_empty(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            body = client.get("/api/architect/bus/needs-input").json()["data"]
            assert body["count"] == 0 and body["items"] == []


class TestInjection:
    def _client(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        return TestClient(build_app(data_dir=str(tmp_path / "arch")))

    def test_injection_appends_to_latest_conv(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            _make_req()
            conv = _make_conv()
            r = client.post("/api/architect/requirements/rq-1/injection", json={
                "message": "任务树第 3 步依赖不成立，需调整", "src": "coding",
                "topic": "execution.amend",
            })
            assert r.status_code == 200
            body = r.json()["data"]
            assert body["conversationId"] == conv["id"]
            msgs = store.ConversationsStore.messages(conv["id"])
            assert len(msgs) == 1
            assert msgs[0]["role"] == "assistant"
            assert "执行 subagent" in msgs[0]["content"]
            assert "execution.amend" in msgs[0]["content"]
            assert "任务树第 3 步依赖不成立" in msgs[0]["content"]

    def test_injection_creates_conv_when_missing(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            _make_req()
            r = client.post("/api/architect/requirements/rq-1/injection", json={
                "message": "需要用户确认接口风格", "src": "coding",
            })
            assert r.status_code == 200
            conv_id = r.json()["data"]["conversationId"]
            assert conv_id
            msgs = store.ConversationsStore.messages(conv_id)
            assert msgs and "用户确认接口风格" in msgs[0]["content"]

    def test_injection_unknown_req(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            r = client.post("/api/architect/requirements/rq-404/injection",
                            json={"message": "x"})
            assert r.json()["code"] == 404

    def test_injection_requires_message(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            _make_req()
            r = client.post("/api/architect/requirements/rq-1/injection",
                            json={"message": "  "})
            assert r.json()["code"] == 400
