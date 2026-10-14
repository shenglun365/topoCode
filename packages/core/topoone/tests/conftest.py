"""I1 测试夹具：fake multi_db（main_db 内存库）+ 生产 schema project_db。"""

from __future__ import annotations

import sqlite3

import pytest


def _connect(path=":memory:"):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


class FakeDB:
    """sqlite3 薄包装 — 与主项目 db handle 同形（db/manager.py）：
    execute→Cursor, fetchall→list[dict], fetchone→dict|None。"""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, sql, params=()):
        return self._conn.execute(sql, params)

    def executemany(self, sql, rows):
        return self._conn.executemany(sql, rows)

    def fetchone(self, sql, params=()):
        row = self._conn.execute(sql, params).fetchone()
        return dict(row) if row else None

    def fetchall(self, sql, params=()):
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def commit(self):
        self._conn.commit()

    @property
    def raw(self) -> sqlite3.Connection:
        return self._conn


class FakeMultiDB:
    def __init__(self, data_dir: str):
        self.main_db = FakeDB(_connect())
        self.data_dir = data_dir
        self._project_dbs: dict = {}
        self.main_db.execute(
            "CREATE TABLE model_configs (id TEXT PRIMARY KEY, name TEXT, provider TEXT, "
            "url TEXT, model TEXT, api_key TEXT, is_default INTEGER, temperature REAL, "
            "max_tokens INTEGER, timeout INTEGER, extra_config TEXT)")
        self.main_db.execute(
            "CREATE TABLE projects (id TEXT PRIMARY KEY, name TEXT, root_path TEXT, summary TEXT)")
        self.main_db.execute(
            "CREATE TABLE llm_call_logs (id TEXT PRIMARY KEY, session_id TEXT, "
            "request_id TEXT, model_id TEXT, provider TEXT, model_name TEXT, mode TEXT, "
            "template_id TEXT, messages_json TEXT, response_content TEXT, "
            "tool_calls_json TEXT, token_prompt INTEGER, token_completion INTEGER, "
            "token_total INTEGER, latency_ms INTEGER, status TEXT, error_message TEXT, "
            "created_at TEXT)")
        self.main_db.execute(
            "CREATE TABLE model_daily_usage (id INTEGER PRIMARY KEY AUTOINCREMENT, "
            "model_id TEXT NOT NULL, date TEXT NOT NULL, request_count INTEGER DEFAULT 0, "
            "prompt_tokens INTEGER DEFAULT 0, completion_tokens INTEGER DEFAULT 0, "
            "total_tokens INTEGER DEFAULT 0, created_at TEXT, updated_at TEXT, "
            "UNIQUE(model_id, date))")

    def get_project_db(self, project_id: str):
        return self._project_dbs.get(project_id)


PROJECT_DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS graph_node (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, kind TEXT NOT NULL, name TEXT NOT NULL,
    qualified_name TEXT NOT NULL DEFAULT '', file_path TEXT NOT NULL DEFAULT '',
    file_id TEXT DEFAULT '', language TEXT DEFAULT '', start_line INTEGER NOT NULL DEFAULT 0,
    start_col INTEGER NOT NULL DEFAULT 0, end_line INTEGER NOT NULL DEFAULT 0,
    end_col INTEGER NOT NULL DEFAULT 0, signature TEXT DEFAULT '', visibility TEXT DEFAULT '',
    is_exported INTEGER DEFAULT 0, is_async INTEGER DEFAULT 0, is_static INTEGER DEFAULT 0,
    docstring TEXT DEFAULT '', decorators TEXT DEFAULT '', type_parameters TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS graph_edge (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, source_id TEXT NOT NULL, target_id TEXT NOT NULL,
    kind TEXT NOT NULL, provenance TEXT DEFAULT 'parser', line INTEGER DEFAULT 0,
    col INTEGER DEFAULT 0, file_path TEXT DEFAULT '', metadata TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS graph_doc (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, edge_type TEXT NOT NULL,
    comm_lv TEXT NOT NULL, parent_comm_id TEXT, comm_id TEXT NOT NULL,
    node_list TEXT NOT NULL, node_count INTEGER NOT NULL, file_count INTEGER DEFAULT 0,
    edge_list TEXT, edge_count INTEGER DEFAULT 0, quality_score REAL, description TEXT,
    metadata TEXT DEFAULT '{}', created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS community_hierarchy (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, edge_type TEXT NOT NULL,
    comm_lv TEXT NOT NULL, comm_id TEXT NOT NULL, parent_comm_id TEXT,
    node_count INTEGER, file_count INTEGER DEFAULT 0, edge_count INTEGER DEFAULT 0,
    quality_score REAL, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS community_llm_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, edge_type TEXT NOT NULL,
    comm_lv TEXT NOT NULL, comm_id TEXT NOT NULL, name TEXT, summary TEXT, model_id TEXT,
    template_id TEXT, name_manual TEXT, component_type TEXT DEFAULT 'community',
    status TEXT DEFAULT 'completed', created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now')), UNIQUE(task_id, edge_type, comm_lv, comm_id));
CREATE TABLE IF NOT EXISTS file_summaries (
    id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_id TEXT, file_path TEXT NOT NULL,
    summary TEXT NOT NULL, summary_len INTEGER DEFAULT 0, source TEXT DEFAULT 'llm',
    created_at TEXT DEFAULT (datetime('now')), updated_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS report_subdocs (
    id TEXT PRIMARY KEY, task_id TEXT NOT NULL, edge_type TEXT NOT NULL, comm_id TEXT,
    title TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT DEFAULT (datetime('now')));
CREATE TABLE IF NOT EXISTS base_node (
    node_id TEXT, file_id TEXT, kind TEXT, code TEXT, line_start INT, line_end INT);
CREATE TABLE IF NOT EXISTS dependencies (
    id TEXT PRIMARY KEY, source_file TEXT NOT NULL, target_file TEXT NOT NULL,
    dep_type TEXT, created_at TEXT DEFAULT (datetime('now')));
"""


@pytest.fixture
def data_dir(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture
def multi_db(data_dir):
    return FakeMultiDB(data_dir)


@pytest.fixture
def project_db():
    db = FakeDB(_connect())
    db.raw.executescript(PROJECT_DB_SCHEMA)
    return db
