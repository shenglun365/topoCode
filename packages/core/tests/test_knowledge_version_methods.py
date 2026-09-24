"""knowledge.* 版本同步四方法契约测试（MS1 §4.2，core 侧）。

version.py 的 knowledge.pullRequest/pendingUpdates/updateConfirm/updateCancel
是 architect ↔ KB 基线增量交互的入口（对外契约见 version.py docstring）。
测试注册面 + 委托参数透传（vss 打桩），不触发真实 git/文件系统。
"""
import pytest

from topoone.db.manager import MultiDBManager
from topoone.rpc.service_app import MethodServer
from topoone.engine.service.version import register_version_methods


@pytest.fixture
def svc(tmp_path, monkeypatch):
    import topoone.engine.version_sync_service as vss

    calls = {}
    monkeypatch.setattr(vss, "pull_request",
                        lambda db, pid, repo_url="", local_repo_path="", branch="", head="", note="":
                        (calls.setdefault("pull", (pid, repo_url, branch, head)), {"requestId": "req-1"})[1])
    monkeypatch.setattr(vss, "pending_updates",
                        lambda db, pid: (calls.setdefault("pending", pid), [{"id": "req-1"}])[1])
    monkeypatch.setattr(vss, "confirm_update",
                        lambda db, rid, method="pull": (calls.setdefault("confirm", (rid, method)), {"ok": True})[1])
    monkeypatch.setattr(vss, "cancel_update",
                        lambda db, rid: (calls.setdefault("cancel", rid), True)[1])

    multi_db = MultiDBManager(str(tmp_path / "vss"))
    server = MethodServer()
    register_version_methods(server, multi_db)

    def call(name, **params):
        return server.methods[name](**params)

    call.calls = calls
    return call


def test_pull_request_delegation(svc):
    out = svc("knowledge.pullRequest", project_id="p1", repo_url="https://x/y.git",
              branch="main", head="abc123", note="n")
    assert out == {"requestId": "req-1"}
    assert svc.calls["pull"] == ("p1", "https://x/y.git", "main", "abc123")


def test_pending_updates_delegation(svc):
    assert svc("knowledge.pendingUpdates", project_id="p2") == [{"id": "req-1"}]
    assert svc.calls["pending"] == "p2"


def test_update_confirm_method_passthrough(svc):
    assert svc("knowledge.updateConfirm", request_id="req-9", method="pull") == {"ok": True}
    assert svc.calls["confirm"] == ("req-9", "pull")


def test_update_cancel_wraps_result(svc):
    assert svc("knowledge.updateCancel", request_id="req-8") == {"cancelled": True}
    assert svc.calls["cancel"] == "req-8"
