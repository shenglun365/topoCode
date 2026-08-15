"""Tests for analysis.parseFileAst (含 implDetails 实现细节扩展)."""

import os
import sys

_HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(_HERE, ".."))
# 与 plugin_manager 运行时一致: plugins/parsers 挂入 sys.path
_PLUGINS_PARSERS = os.path.abspath(os.path.join(_HERE, "..", "..", "plugins", "parsers"))
if _PLUGINS_PARSERS not in sys.path:
    sys.path.insert(0, _PLUGINS_PARSERS)

import core_service  # noqa: E402


class _FakeServer:
    def __init__(self):
        self.methods = {}

    def register(self, name):
        def deco(fn):
            self.methods[name] = fn
            return fn
        return deco


class _FakeMultiDB:
    main_db = None


def _parse(**kwargs):
    srv = _FakeServer()
    core_service.register_project_methods(srv, _FakeMultiDB())
    return srv.methods["analysis.parseFileAst"](**kwargs)


_PY_SRC = '''
from fastapi import FastAPI

app = FastAPI()
TIMEOUT = 30


@app.get("/items/{item_id}")
def read_item(item_id: str):
    if item_id == "x":
        return "fast"
    return item_id
'''


class TestParseFileAst:
    def test_basic_symbols(self, tmp_path):
        f = tmp_path / "api.py"
        f.write_text(_PY_SRC, encoding="utf-8")
        res = _parse(file_path=str(f), language="python")
        assert "error" not in res
        names = {s["name"] for s in res["symbols"]}
        assert "read_item" in names
        assert res["language"] == "python"

    def test_no_impl_details_by_default(self, tmp_path):
        f = tmp_path / "api.py"
        f.write_text(_PY_SRC, encoding="utf-8")
        res = _parse(file_path=str(f), language="python")
        assert "implDetails" not in res

    def test_impl_details_python(self, tmp_path):
        f = tmp_path / "api.py"
        f.write_text(_PY_SRC, encoding="utf-8")
        res = _parse(file_path=str(f), language="python", implDetails=True)
        det = res["implDetails"]
        # 语句级: if 条件原文
        conds = [s["condition"] for s in det["statements"]]
        assert "item_id == \"x\"" in conds
        assert all(s["enclosing"] == "read_item" for s in det["statements"])
        # 框架路由
        assert det["routes"] == [{
            "path": "/items/{item_id}", "methods": ["GET"],
            "handler": "read_item", "framework": "fastapi",
            "line": _PY_SRC.split("\n").index('@app.get("/items/{item_id}")') + 1,
        }]
        # 常量值
        const = {c["name"]: c["value"] for c in det["constants"]}
        assert const.get("TIMEOUT") == "30"
        assert det["configKeys"] == []

    def test_impl_details_yaml(self, tmp_path):
        f = tmp_path / "config.yaml"
        f.write_text("server:\n  host: localhost\n  port: 8080\n", encoding="utf-8")
        res = _parse(file_path=str(f), implDetails=True)
        assert "error" not in res, res
        keys = {k["key"]: k["value"] for k in res["implDetails"]["configKeys"]}
        assert keys == {"server.host": "localhost", "server.port": "8080"}
        assert res["implDetails"]["statements"] == []
        assert res["implDetails"]["routes"] == []

    def test_file_not_found(self):
        res = _parse(file_path="/nonexistent/nope.py")
        assert "error" in res

    def test_unsupported_type(self, tmp_path):
        f = tmp_path / "data.xyz"
        f.write_text("x", encoding="utf-8")
        res = _parse(file_path=str(f), implDetails=True)
        assert "error" in res
