"""A2' 主 KB 对接 API 层预留（plan-C §5.4/§5.6）。

仅预留对接 API 面（status 查询 + promote 预留 501），不实现"单机→主 KB 晋升"本体。
Run: cd apps/architect && python -m pytest tests/test_mainkb.py -q
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import topoone_app_architect.ctx as C  # noqa: E402
from topoone_app_architect.arch_routes import mainkb as MK
from topoone_app_architect.store import ProjectsStore  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402


def _ctx_setup(tmp_path, monkeypatch):
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C._data_dir = None
    C._project_dbs.clear()
    C.reset_project(C._project_var.set(None))
    C.setup(data_dir=data)


def _proj(pid, kb_pid=""):
    return ProjectsStore.upsert(pid, {
        "name": "P", "rootPath": "/tmp/p", "kbProjectId": kb_pid, "active": True,
    })


def _call(coro_factory):
    out = asyncio.run(coro_factory())
    if isinstance(out, JSONResponse):
        return json.loads(out.body.decode("utf-8"))
    return out


class TestMainKbStatus:
    def test_standalone(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _proj("proj-standalone")
        res = MK.mainkb_status("proj-standalone")
        assert res["mode"] == "standalone"
        assert res["associated"] is False
        assert res["kbProjectId"] == ""
        assert res["deepLink"] == ""
        # 晋升预留位：未实现但已预留
        assert res["promotion"]["implemented"] is False
        assert res["promotion"]["reserved"] is True

    def test_mainkb(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _proj("proj-main", kb_pid="kb-123")
        res = MK.mainkb_status("proj-main")
        assert res["mode"] == "main-kb"
        assert res["associated"] is True
        assert res["kbProjectId"] == "kb-123"
        assert res["deepLink"] == "/kb/kb-123/assets"

    def test_status_endpoint_shape(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        _proj("proj-ep", kb_pid="kb-9")
        # 端点为薄封装：ok(...) 包裹 mainkb_status
        out = _call(lambda: MK.api_mainkb_status(root=None, project=None))
        # 无 root/project → pid 为空 → standalone（不报错）
        assert out["code"] == 0
        assert out["data"]["mode"] in ("standalone", "main-kb")


class TestMainKbPromoteReserved:
    def test_promote_501(self, tmp_path, monkeypatch):
        _ctx_setup(tmp_path, monkeypatch)
        out = _call(lambda: MK.api_mainkb_promote())
        assert out["code"] == 501
        assert "预留" in out["message"] or "未实现" in out["message"]


if __name__ == "__main__":
    sys.exit(__import__("pytest").main([__file__, "-q"]))
