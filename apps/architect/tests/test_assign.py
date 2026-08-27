"""P3.2 指派测试：assign_requirement 核心 + POST /requirements/{id}/assign 端点。

Run: cd <repo> && python -m pytest apps/architect/tests/test_assign.py -q
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
_SENTINEL = object()


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


def _make_req(req_id="rq-1", status="analyzed"):
    store.RequirementsStore.create({
        "id": req_id, "title": "T", "desc": "", "status": status,
        "location": "pool", "priority": "P1", "updatedAt": 1,
    })
    return store.RequirementsStore.get(req_id)


def _make_exec(exec_id="ex-1"):
    store.ExecutionTasksStore.create({
        "id": exec_id, "planId": "pl-1", "adapter": "opencode",
        "reqIds": ["rq-1"], "connectivity": "ok", "status": "created",
        "sessionIds": [], "baseCommit": "", "runCount": 0, "createdAt": 1,
    })


class _FakeBus:
    def __init__(self, res=None):
        self.res = res
        self.calls = []

    def publish(self, src, dst, topic, payload=None):
        self.calls.append({"src": src, "dst": dst, "topic": topic, "payload": payload or {}})
        return self.res


class TestAssignCore:
    def test_runner_assign_publishes_and_executing(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _make_req()
        _make_exec()
        import topoone_app_architect.arch_routes.execution as ex
        fake = _FakeBus({"id": "bus-1", "status": "pending"})
        monkeypatch.setattr(_BUS_PATH, lambda: fake)
        row, e = ex.assign_requirement("rq-1", "runner", exec_id="ex-1")
        assert e is None
        assert row["status"] == "executing"
        assert row["assignedTo"] == "runner"
        c = fake.calls[0]
        assert c["src"] == "architect" and c["dst"] == "runner"
        assert c["topic"] == "execution.handoff"
        assert c["payload"]["execId"] == "ex-1" and c["payload"]["reqId"] == "rq-1"

    def test_runner_falls_back_to_bound_execid(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _make_req()
        _make_exec()
        store.RequirementsStore.update("rq-1", {"execId": "ex-1"})
        import topoone_app_architect.arch_routes.execution as ex
        fake = _FakeBus({"id": "bus-1"})
        monkeypatch.setattr(_BUS_PATH, lambda: fake)
        row, e = ex.assign_requirement("rq-1", "runner")
        assert e is None
        assert fake.calls[0]["payload"]["execId"] == "ex-1"

    def test_runner_without_execid_rejected(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _make_req()
        import topoone_app_architect.arch_routes.execution as ex
        row, e = ex.assign_requirement("rq-1", "runner")
        assert row is None and e[0] == 400

    def test_runner_unknown_exec_rejected(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _make_req()
        import topoone_app_architect.arch_routes.execution as ex
        row, e = ex.assign_requirement("rq-1", "runner", exec_id="ex-404")
        assert row is None and e[0] == 400

    def test_mcp_assign(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _make_req()
        import topoone_app_architect.arch_routes.execution as ex
        fake = _FakeBus({"id": "bus-1"})
        monkeypatch.setattr(_BUS_PATH, lambda: fake)
        row, e = ex.assign_requirement("rq-1", "mcp", tool="deploy",
                                       params={"env": "staging"})
        assert e is None
        assert row["assignedTo"] == "mcp:deploy"
        assert row["status"] == "executing"
        c = fake.calls[0]
        assert c["dst"] == "mcp"
        assert c["payload"]["tool"] == "deploy"
        assert c["payload"]["params"] == {"env": "staging"}

    def test_mcp_without_tool_rejected(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _make_req()
        import topoone_app_architect.arch_routes.execution as ex
        row, e = ex.assign_requirement("rq-1", "mcp")
        assert row is None and e[0] == 400

    def test_bogus_target_rejected(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _make_req()
        import topoone_app_architect.arch_routes.execution as ex
        row, e = ex.assign_requirement("rq-1", "human")
        assert row is None and e[0] == 400

    def test_broker_down_returns_503_and_no_state_change(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        _make_req()
        _make_exec()
        import topoone_app_architect.arch_routes.execution as ex
        monkeypatch.setattr(_BUS_PATH, lambda: _FakeBus(None))
        row, e = ex.assign_requirement("rq-1", "runner", exec_id="ex-1")
        assert row is None and e[0] == 503
        assert store.RequirementsStore.get("rq-1")["status"] == "analyzed"

    def test_unknown_req(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch)
        import topoone_app_architect.arch_routes.execution as ex
        row, e = ex.assign_requirement("rq-404", "runner")
        assert row is None and e[0] == 404


class TestAssignEndpoint:
    def _client(self, tmp_path, monkeypatch, res=_SENTINEL):
        _setup(tmp_path, monkeypatch)
        fake = _FakeBus(res if res is not _SENTINEL
                        else {"id": "bus-1", "status": "pending"})
        monkeypatch.setattr(_BUS_PATH, lambda: fake)
        return TestClient(build_app(data_dir=str(tmp_path / "arch"))), fake

    def test_assign_runner_ok(self, tmp_path, monkeypatch):
        client, fake = self._client(tmp_path, monkeypatch)
        with client:
            _make_req()
            _make_exec()
            r = client.post("/api/architect/requirements/rq-1/assign",
                            json={"target": "runner", "execId": "ex-1"})
            assert r.status_code == 200
            body = r.json()
            assert body["code"] == 0
            assert body["data"]["status"] == "executing"
            assert body["data"]["assignedTo"] == "runner"
            assert fake.calls and fake.calls[0]["topic"] == "execution.handoff"

    def test_assign_mcp_ok(self, tmp_path, monkeypatch):
        client, fake = self._client(tmp_path, monkeypatch)
        with client:
            _make_req()
            r = client.post("/api/architect/requirements/rq-1/assign",
                            json={"target": "mcp", "tool": "deploy",
                                  "params": {"env": "staging"}})
            assert r.status_code == 200
            assert r.json()["data"]["assignedTo"] == "mcp:deploy"

    def test_assign_validation_error(self, tmp_path, monkeypatch):
        client, _fake = self._client(tmp_path, monkeypatch)
        with client:
            _make_req()
            r = client.post("/api/architect/requirements/rq-1/assign",
                            json={"target": "runner"})
            assert r.status_code == 400
            assert r.json()["code"] == 400

    def test_assign_broker_down_503(self, tmp_path, monkeypatch):
        client, _fake = self._client(tmp_path, monkeypatch, res=None)
        with client:
            _make_req()
            _make_exec()
            r = client.post("/api/architect/requirements/rq-1/assign",
                            json={"target": "runner", "execId": "ex-1"})
            # 代码库约定: 业务错误统一 HTTP 400，真实码在 body
            assert r.status_code == 400
            assert r.json()["code"] == 503

    def test_assign_unknown_req_404(self, tmp_path, monkeypatch):
        client, _fake = self._client(tmp_path, monkeypatch)
        with client:
            r = client.post("/api/architect/requirements/rq-404/assign",
                            json={"target": "mcp", "tool": "deploy"})
            assert r.status_code == 400
            assert r.json()["code"] == 404
