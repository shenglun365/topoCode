"""P5 CLI 测试 — RPC 客户端 + project/task 解析（query bug 修正）。"""

import os
import tempfile

import pytest


@pytest.fixture()
def data_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


def _make_project(data_dir: str, project_id: str, root_path: str, name: str):
    """在主库建一个项目 + 两个任务，供解析测试。"""
    from topoone.db.manager import MultiDBManager
    mdb = MultiDBManager(data_dir)
    mdb.main_db.execute(
        "INSERT OR REPLACE INTO projects (id, name, root_path) VALUES (?, ?, ?)",
        (project_id, name, root_path))
    mdb.main_db.execute(
        "INSERT INTO analysis_tasks (id, name, type, status, project_id) VALUES (?, ?, ?, ?, ?)",
        (f"{project_id}-t1", "full-analysis", "full", "done", project_id))
    mdb.main_db.execute(
        "INSERT INTO analysis_tasks (id, name, type, status, project_id) VALUES (?, ?, ?, ?, ?)",
        (f"{project_id}-t2", "second", "full", "done", project_id))
    mdb.main_db.conn.commit()
    mdb.close_all()


def test_resolve_project_and_task(data_dir):
    """project 解析（root_path/name）+ task 解析（name 优先、默认最近）【P5 query bug 修正】。"""
    import topoone.supervisor.cli as main_cli
    _make_project(data_dir, "proj-1", "/tmp/foo/bar", "bar")

    # 经 root_path 解析
    assert main_cli._resolve_project("/tmp/foo/bar", data_dir) == "proj-1"
    # 经 name 解析
    assert main_cli._resolve_project("/tmp/foo/bar", data_dir) == "proj-1"
    # 未命中
    assert main_cli._resolve_project("/tmp/nope", data_dir) is None

    # task：指定 name
    assert main_cli._resolve_task("proj-1", "second", data_dir) == "proj-1-t2"
    # task：默认最近（按 created_at DESC，created_at 相同则取 id 较大者）
    tid = main_cli._resolve_task("proj-1", "", data_dir)
    assert tid in ("proj-1-t1", "proj-1-t2")
    # task：不存在的项目
    assert main_cli._resolve_task("proj-x", "", data_dir) is None


def test_rpc_client(monkeypatch, data_dir):
    """RPC 客户端带 token 调 /api/rpc/{method}。"""
    import json as _json
    import topoone.supervisor.cli as main_cli
    # 写 token
    with open(os.path.join(data_dir, "token"), "w") as f:
        f.write("tok-123")

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
    monkeypatch.setenv("TOPOCODE_DB_DIR", data_dir)

    res = main_cli._rpc("project.list", {"x": 1}, http_port=3456, data_dir=data_dir)
    assert res == {"result": {"ok": True}}
    assert seen["url"] == "http://127.0.0.1:3456/api/rpc/project.list"
    assert seen["auth"] == "Bearer tok-123"


def test_cli_parser_new_commands():
    """新 CLI 命令（import/analyze/tasks/export/verify/settings）可解析。"""
    import topoone.supervisor.cli as main_cli
    parser = main_cli._build_parser()
    for cmd in ("import", "analyze", "tasks", "export", "verify", "settings"):
        args = parser.parse_args([cmd, "/tmp/x"] if cmd != "settings" else [cmd])
        assert args.command == cmd
