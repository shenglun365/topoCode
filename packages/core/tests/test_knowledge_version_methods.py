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


def test_knowledge_methods_retired(svc):
    """去基线化(2026-10 裁决): knowledge.* 四方法空壳——旧调用得明确错误非 404。"""
    r = svc("knowledge.pullRequest", projectId="proj-t")
    assert r.get("retired") is True and "去基线化" in (r.get("error") or "")
    r = svc("knowledge.pendingUpdates", projectId="proj-t")
    assert r.get("retired") is True
    r = svc("knowledge.updateConfirm", requestId="req-1")
    assert r.get("retired") is True
    r = svc("knowledge.updateCancel", requestId="req-1")
    assert r.get("retired") is True


def test_version_write_methods_retired(svc):
    """version.preview/sync/cleanup 同批退役空壳。"""
    for name in ("version.preview", "version.sync", "version.cleanup"):
        r = svc(name, projectId="proj-t")
        assert r.get("retired") is True and r.get("success") is False, name
