"""P6 TUI 测试 — 数据层（RPC 客户端/健康探测）与可导入性。"""

import os
import subprocess
import sys
import tempfile

import pytest


@pytest.fixture()
def data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def test_tui_importable():
    """tui 包可导入（textual 已装）。"""
    code = (
        "from topoone.supervisor.tui import TopoTUI\n"
        "print('tui import OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert "OK" in r.stdout, f"import failed: {r.stderr[:500]}"


def test_tui_rpc_with_token(monkeypatch, data_dir):
    """TUI 的 _rpc 带 token 经 /api/rpc 调后端。"""
    import json as _json
    from topoone.supervisor.tui import TopoTUI

    with open(os.path.join(data_dir, "token"), "w") as f:
        f.write("tok-abc")

    seen = {}

    def fake_urlopen(req, timeout=300):
        seen["url"] = req.full_url
        seen["auth"] = req.headers.get("Authorization")
        body = _json.dumps({"result": {"ok": True}}).encode()
        class _Resp:
            status = 200
            def read(self):
                return body
            def __enter__(self):
                return self
            def __exit__(self, *a):
                return False
        return _Resp()

    import urllib.request as _ur
    monkeypatch.setattr(_ur, "urlopen", fake_urlopen)

    app = TopoTUI(data_dir, 3456)
    res = app._rpc("project.list", {"x": 1})
    assert res == {"result": {"ok": True}}
    assert seen["url"] == "http://127.0.0.1:3456/api/rpc/project.list"
    assert seen["auth"] == "Bearer tok-abc"


def test_tui_service_health_false():
    """健康探测对未监听端口返回 False。"""
    from topoone.supervisor.tui import TopoTUI
    app = TopoTUI("/tmp/nonexistent-tui", 39999)
    assert app._service_health(39999) is False


def test_tui_services_refresh(data_dir, monkeypatch):
    """服务状态刷新不抛异常（RPC 失败时优雅降级）。"""
    from topoone.supervisor.tui import TopoTUI

    def fake_health(port):
        return True

    def fake_rpc(method, params=None):
        if method == "project.list":
            return {"result": []}
        return {"result": []}

    app = TopoTUI(data_dir, 3456)
    monkeypatch.setattr(app, "_service_health", fake_health)
    monkeypatch.setattr(app, "_rpc", fake_rpc)
    # 不启动 app，仅测刷新逻辑（widget 查询需 mock）
    class _FakeWidget:
        def __init__(self, val=""):
            self._val = val
        def update(self, val):
            self._val = val
    fake_widgets = {"#services-content": _FakeWidget(), "#tasks-content": _FakeWidget(), "#log-content": _FakeWidget()}
    monkeypatch.setattr(app, "query_one", lambda sel, t=None: fake_widgets[sel])

    app._refresh_services()
    app._refresh_tasks()
    app._refresh_logs()
    assert "服务状态" in fake_widgets["#services-content"]._val
    assert "任务进度" in fake_widgets["#tasks-content"]._val
