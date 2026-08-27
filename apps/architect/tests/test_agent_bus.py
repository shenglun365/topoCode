"""agent_bus P3.1 测试：AgentBusStore 队列语义 + broker 端点(publish/messages/WS) + 分发。

Run: cd <repo> && python -m pytest apps/architect/tests/test_agent_bus.py -q
"""
import os
import sys

_repo = os.path.join(os.path.dirname(__file__), "..", "..", "..")
sys.path.insert(0, _repo)

import topoone_app_architect.arch_routes.ctx as C
import topoone_app_architect.arch_routes.store as store


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


class TestAgentBusStore:
    def test_create_pending_mark_delivered(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        store.AgentBusStore.create({
            "id": "bus-1", "src": "plan", "dst": "runner",
            "topic": "execution.handoff", "payload": {"reqId": "RQ-1"},
            "status": "pending", "createdAt": 1, "updatedAt": 1,
        })
        assert store.AgentBusStore.count_pending() == 1
        p = store.AgentBusStore.pending()
        assert p[0]["id"] == "bus-1"
        assert p[0]["payload"] == {"reqId": "RQ-1"}  # JSON 解码
        store.AgentBusStore.mark("bus-1", status="delivered")
        assert store.AgentBusStore.count_pending() == 0
        assert store.AgentBusStore.get("bus-1")["status"] == "delivered"

    def test_list_filters(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        rows = [
            ("bus-0", "runner", "execution.handoff", "pending"),
            ("bus-1", "monitor", "execution.progress", "delivered"),
            ("bus-2", "runner", "execution.progress", "pending"),
        ]
        for i, (mid, to, topic, status) in enumerate(rows):
            store.AgentBusStore.create({
                "id": mid, "src": "x", "dst": to, "topic": topic,
                "payload": {}, "status": status, "createdAt": i + 1, "updatedAt": i + 1,
            })
        assert len(store.AgentBusStore.list(dst="runner")) == 2
        assert len(store.AgentBusStore.list(topic="execution.progress")) == 2
        assert len(store.AgentBusStore.list(status="pending")) == 2
        assert len(store.AgentBusStore.list(dst="runner", status="pending")) == 2
        assert len(store.AgentBusStore.list(limit=1)) == 1


class TestBrokerEndpoints:
    def _client(self, tmp_path, monkeypatch):
        from fastapi.testclient import TestClient
        from topoone_app_architect import agent_bus
        _setup(tmp_path, monkeypatch)
        # 慢轮询(60s)避免测试期间分发循环把 pending 标 delivered 干扰断言
        app = agent_bus.build_app(data_dir=str(tmp_path / "arch"), poll_interval=60.0)
        return TestClient(app)

    def test_health(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            r = client.get("/health")
            assert r.status_code == 200
            assert r.json()["service"] == "agent-bus"

    def test_publish_and_query(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            r = client.post("/api/agent-bus/publish", json={
                "from": "plan", "to": "runner", "topic": "execution.handoff",
                "payload": {"reqId": "RQ-9"},
            })
            assert r.status_code == 200
            body = r.json()
            assert body["code"] == 0
            assert body["data"]["id"]
            rows = client.get("/api/agent-bus/messages",
                              params={"topic": "execution.handoff"}).json()["data"]
            assert any(m["topic"] == "execution.handoff"
                       and m["payload"]["reqId"] == "RQ-9" for m in rows)

    def test_publish_requires_topic(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            r = client.post("/api/agent-bus/publish", json={"from": "x", "to": "y"})
            assert r.status_code == 400

    def test_ws_push_on_publish(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        with client:
            with client.websocket_connect("/ws/agent-bus") as ws:
                client.post("/api/agent-bus/publish", json={
                    "from": "plan", "to": "monitor", "topic": "execution.progress",
                    "payload": {"step": 1},
                })
                msg = ws.receive_json()
                assert msg["type"] == "message"
                assert msg["message"]["topic"] == "execution.progress"


class TestDispatch:
    def test_route_and_marks_delivered(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        from topoone_app_architect import agent_bus
        store.AgentBusStore.create({
            "id": "bus-d1", "src": "plan", "dst": "runner",
            "topic": "execution.handoff", "payload": {}, "status": "pending",
            "createdAt": 1, "updatedAt": 1,
        })
        msg = store.AgentBusStore.pending()[0]
        out = agent_bus._route_and_mark(msg)
        assert out["status"] == "delivered"
        assert store.AgentBusStore.count_pending() == 0
