"""符号源桥接与变更跟踪测试（P1：native 后端 + 手动基线同步）。

覆盖：
  - _resolve_core_pid：.topocode/proj-id 签名优先 / core 主库 root_path 反查 / 均无 → None
  - _open_core_conn：core project.db TEMP 同构视图（nodes/edges/contains）
  - symbol_source_state：HEAD 变化 → stale + 变更文件范围识别（不实时解析）
  - POST /kb/semantic/symbol-sync：无 core 项目 → 400；有项目 → call_kb(version.sync)
    + 跟踪 KV 记录
"""
from __future__ import annotations

import json
import os
import sqlite3
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from topoone_app_architect.arch_routes import router as arch_router
from topoone_app_architect.arch_routes.sem import symbols as _sym
from topoone_app_architect.arch_routes.sem import codegraph as _sem_codegraph


@pytest.fixture(autouse=True)
def _clean_caches(tmp_path, monkeypatch):
    from topoone_app_architect.arch_routes import ctx as C
    monkeypatch.setenv("ARCH_CODEGRAPH", "off")
    monkeypatch.setattr(_sem_codegraph, "_mode_cache", None)
    monkeypatch.setattr(_sem_codegraph, "_cli_cache", ("", 0.0))
    data = str(tmp_path / "arch")
    monkeypatch.setenv("ARCH_DATA_DIR", data)
    C._db = None
    C._kb = None
    C.setup(data_dir=data)
    _sym.invalidate_native_cache()
    yield
    _sym.invalidate_native_cache()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(arch_router)
    return TestClient(app, raise_server_exceptions=False)


def _mk_core_env(tmp_path, root: str, core_pid: str, with_db: bool = True):
    """建 core 主库(topoone.db + projects 表) + 可选 core 分析库(graph_node/edge)。"""
    data = tmp_path / "core-data"
    data.mkdir(exist_ok=True)
    db = data / "topoone.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE projects(id TEXT PRIMARY KEY, root_path TEXT NOT NULL UNIQUE)")
    c.execute("INSERT INTO projects VALUES(?,?)", (core_pid, os.path.abspath(root)))
    c.commit()
    c.close()
    if with_db:
        pdir = data / "projects" / core_pid
        pdir.mkdir(parents=True)
        pc = sqlite3.connect(pdir / "project.db")
        pc.execute("CREATE TABLE graph_node(id TEXT, kind TEXT, name TEXT, qualified_name TEXT,"
                   " file_path TEXT, start_line INT, end_line INT, start_col INT, end_col INT,"
                   " signature TEXT, docstring TEXT)")
        pc.execute("CREATE TABLE graph_edge(source_id TEXT, target_id TEXT, kind TEXT,"
                   " line INT, col INT, metadata TEXT, provenance TEXT)")
        pc.execute("INSERT INTO graph_node VALUES('c1','class','Foo','a::Foo','a.py',1,10,0,0,'','')")
        pc.execute("INSERT INTO graph_node VALUES('m1','method','bar','a::Foo::bar','a.py',2,9,2,0,'','')")
        pc.execute("INSERT INTO graph_node VALUES('f1','function','baz','a::baz','a.py',11,12,0,0,'','')")
        pc.execute("INSERT INTO graph_edge VALUES('m1','f1','calls',3,4,'','parser')")
        pc.commit()
        pc.close()
    return str(data)


def test_resolve_core_pid_signature(tmp_path, monkeypatch):
    root = tmp_path / "repo-sig"
    (root / ".topocode").mkdir(parents=True)
    (root / ".topocode" / "proj-id").write_text("proj-signature\n")
    data = _mk_core_env(tmp_path, str(root), "proj-main", with_db=False)
    monkeypatch.setenv("TOPOCODE_DB_DIR", data)
    _sym.invalidate_native_cache()
    assert _sym._resolve_core_pid(str(root)) == "proj-signature"


def test_resolve_core_pid_root_path_lookup(tmp_path, monkeypatch):
    root = tmp_path / "repo-lookup"
    root.mkdir(parents=True)
    data = _mk_core_env(tmp_path, str(root), "proj-main", with_db=False)
    monkeypatch.setenv("TOPOCODE_DB_DIR", data)
    _sym.invalidate_native_cache()
    assert _sym._resolve_core_pid(str(root)) == "proj-main"
    assert _sym._resolve_core_pid(str(tmp_path / "unknown")) is None


def test_open_core_conn_temp_views(tmp_path, monkeypatch):
    root = tmp_path / "repo-conn"
    root.mkdir(parents=True)
    data = _mk_core_env(tmp_path, str(root), "proj-conn")
    monkeypatch.setenv("TOPOCODE_DB_DIR", data)
    conn = _sym._open_core_conn("proj-conn")
    assert conn is not None
    assert conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 3
    # 1 calls 边 + 1 contains 边(class c1 包住 method m1)
    assert conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM edges_contains").fetchone()[0] == 1
    row = conn.execute("SELECT qualified_name, file_path, start_line FROM nodes WHERE id='m1'").fetchone()
    assert row == ("a::Foo::bar", "a.py", 2)


def _mk_git_repo(tmp_path, root_name: str):
    root = tmp_path / root_name
    root.mkdir()
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    def sh(*args):
        p = subprocess.run(["git", "-C", str(root)] + list(args), check=True,
                           capture_output=True, text=True, env=env)
        return p.stdout.strip()
    sh("init", "-q", "-b", "main")
    (root / "a.py").write_text("x = 1\n")
    sh("add", ".")
    sh("commit", "-q", "-m", "a")
    head_a = sh("rev-parse", "HEAD")
    (root / "a.py").write_text("x = 2\n")
    (root / "b.py").write_text("y = 1\n")
    sh("add", ".")
    sh("commit", "-q", "-m", "b")
    return str(root), head_a


def test_symbol_source_state_stale_detection(tmp_path, monkeypatch):
    root, head_a = _mk_git_repo(tmp_path, "repo-state")
    data = _mk_core_env(tmp_path, root, "proj-x", with_db=False)
    monkeypatch.setenv("TOPOCODE_DB_DIR", data)
    _sym.invalidate_native_cache()
    _sym.record_sync("proj-x", head_a)
    st = _sym.symbol_source_state(root, None)
    assert st["stale"] is True
    assert st["lastHead"] == head_a
    assert len(st["head"]) == 40 and st["head"] != head_a
    assert "a.py" in st["staleFiles"] and "b.py" in st["staleFiles"]
    # 重新同步后 fresh
    _sym.record_sync("proj-x", st["head"])
    _sym.invalidate_native_cache()
    st2 = _sym.symbol_source_state(root, None)
    assert st2["stale"] is False


def test_symbol_sync_endpoint_no_core_project(tmp_path, monkeypatch):
    root = tmp_path / "repo-unknown"
    root.mkdir()
    data = _mk_core_env(tmp_path, str(tmp_path / "elsewhere"), "proj-other", with_db=False)
    monkeypatch.setenv("TOPOCODE_DB_DIR", data)
    _sym.invalidate_native_cache()
    c = _client()
    r = c.post("/api/architect/kb/semantic/symbol-sync",
               json={"root": str(root), "project": None})
    assert r.status_code == 400
    body = r.json()
    assert body["code"] != 0


def test_symbol_sync_endpoint_initiates_pull_request(tmp_path, monkeypatch):
    """职责划分：architect 仅发起基线变更请求(knowledge.pullRequest)，执行在 KB 管理。"""
    root, _ = _mk_git_repo(tmp_path, "repo-sync")
    data = _mk_core_env(tmp_path, str(root), "proj-sync", with_db=True)
    monkeypatch.setenv("TOPOCODE_DB_DIR", data)
    _sym.invalidate_native_cache()
    from topoone_app_architect.arch_routes import kb_gateway as _kg
    calls = []
    monkeypatch.setattr(_kg, "call_kb",
                        lambda method, **p: calls.append((method, p))
                        or {"requestId": "pur-1", "status": "pending"})
    c = _client()
    r = c.post("/api/architect/kb/semantic/symbol-sync",
               json={"root": str(root), "project": None})
    assert r.status_code == 200
    body = r.json()
    assert body["data"]["requested"] is True
    assert body["data"]["corePid"] == "proj-sync"
    assert body["data"]["requestId"] == "pur-1"
    assert len(calls) == 1
    method, params = calls[0]
    assert method == "knowledge.pullRequest"
    assert params["project_id"] == "proj-sync"
    assert len(params["head"]) == 40
    # 跟踪 KV 已记录(发起请求即对齐 head)
    kv = _sym._read_state_kv("proj-sync")
    assert kv.get("lastHead") == params["head"]
