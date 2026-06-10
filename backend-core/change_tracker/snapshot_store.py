"""SnapshotStore — SQLite 快照存储。

管理项目分析快照的持久化：
- 单独的 snapshots.db，与项目分析数据隔离
- 每个项目最多保留 20 个版本
- 基于文件 hash 的去重
"""

import json
import os
import sqlite3
import threading
from datetime import datetime
from typing import Optional

from .change_model import ProjectSnapshot


SNAPSHOT_DB_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_root TEXT NOT NULL,
    commit_hash TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    file_hashes TEXT NOT NULL,
    symbols TEXT,
    dependencies TEXT,
    is_analyzed INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now')),
    UNIQUE(project_root, commit_hash)
);

CREATE TABLE IF NOT EXISTS snapshot_symbols (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL,
    file_path TEXT NOT NULL,
    symbol_name TEXT NOT NULL,
    symbol_kind TEXT DEFAULT '',
    symbol_line INTEGER DEFAULT 0,
    FOREIGN KEY (snapshot_id) REFERENCES snapshots(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_snapshot_symbols_snap ON snapshot_symbols(snapshot_id);
CREATE INDEX IF NOT EXISTS idx_snapshot_symbols_name ON snapshot_symbols(symbol_name);
CREATE INDEX IF NOT EXISTS idx_snapshot_symbols_file ON snapshot_symbols(file_path);

CREATE INDEX IF NOT EXISTS idx_snapshots_project ON snapshots(project_root);
CREATE INDEX IF NOT EXISTS idx_snapshots_commit ON snapshots(project_root, commit_hash);
"""


VERSION_LIMIT = 20


class SnapshotStore:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        with self._get_conn() as conn:
            conn.executescript(SNAPSHOT_DB_TABLES_SQL)

    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def save_snapshot(self, project_root: str, snapshot: ProjectSnapshot) -> int:
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    """INSERT OR REPLACE INTO snapshots
                       (project_root, commit_hash, timestamp, file_hashes, symbols, dependencies, is_analyzed)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_root,
                        snapshot.commit_hash,
                        snapshot.timestamp.isoformat(),
                        json.dumps(snapshot.file_hashes),
                        json.dumps(snapshot.symbols) if snapshot.symbols else None,
                        json.dumps(snapshot.dependencies) if snapshot.dependencies else None,
                        1 if snapshot.is_analyzed else 0,
                    ),
                )
                row_id = cursor.lastrowid or 0
                # Write normalized symbol rows
                if snapshot.symbols and row_id:
                    self._save_symbols(conn, row_id, snapshot.symbols)
                conn.commit()
                self._enforce_limit(conn, project_root)
                return row_id
            finally:
                conn.close()

    def _save_symbols(self, conn, snapshot_id: int, symbols: dict):
        rows = []
        for file_path, sym_list in symbols.items():
            for sym in sym_list:
                rows.append((
                    snapshot_id,
                    file_path,
                    sym.get("name", ""),
                    sym.get("kind", ""),
                    sym.get("line", 0),
                ))
        if rows:
            conn.executemany(
                "INSERT OR IGNORE INTO snapshot_symbols "
                "(snapshot_id, file_path, symbol_name, symbol_kind, symbol_line) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )

    def _enforce_limit(self, conn, project_root: str):
        rows = conn.execute(
            "SELECT id FROM snapshots WHERE project_root = ? ORDER BY timestamp DESC",
            (project_root,),
        ).fetchall()
        if len(rows) > VERSION_LIMIT:
            ids_to_delete = [r["id"] for r in rows[VERSION_LIMIT:]]
            placeholders = ",".join("?" for _ in ids_to_delete)
            conn.execute(
                f"DELETE FROM snapshots WHERE id IN ({placeholders})",
                ids_to_delete,
            )
            conn.commit()

    def get_snapshot(self, project_root: str, commit_hash: str) -> Optional[ProjectSnapshot]:
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM snapshots WHERE project_root = ? AND commit_hash = ?",
                    (project_root, commit_hash),
                ).fetchone()
                return self._row_to_snapshot(row) if row else None
            finally:
                conn.close()

    def get_latest_snapshot(self, project_root: str) -> Optional[ProjectSnapshot]:
        with self._lock:
            conn = self._get_conn()
            try:
                row = conn.execute(
                    "SELECT * FROM snapshots WHERE project_root = ? ORDER BY timestamp DESC LIMIT 1",
                    (project_root,),
                ).fetchone()
                return self._row_to_snapshot(row) if row else None
            finally:
                conn.close()

    def list_snapshots(self, project_root: str, max_count: int = 20) -> list[dict]:
        with self._lock:
            conn = self._get_conn()
            try:
                rows = conn.execute(
                    "SELECT commit_hash, timestamp, is_analyzed FROM snapshots "
                    "WHERE project_root = ? ORDER BY timestamp DESC LIMIT ?",
                    (project_root, max_count),
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def delete_snapshot(self, project_root: str, commit_hash: str) -> bool:
        with self._lock:
            conn = self._get_conn()
            try:
                cursor = conn.execute(
                    "DELETE FROM snapshots WHERE project_root = ? AND commit_hash = ?",
                    (project_root, commit_hash),
                )
                conn.commit()
                return cursor.rowcount > 0
            finally:
                conn.close()

    def query_symbols(self, project_root: str, symbol_name: str = "", file_path: str = "", max_count: int = 50) -> list[dict]:
        """Query normalized snapshot_symbols table."""
        with self._lock:
            conn = self._get_conn()
            try:
                parts = ["ss.snapshot_id = s.id", "s.project_root = ?"]
                params: list = [project_root]
                if symbol_name:
                    parts.append("ss.symbol_name = ?")
                    params.append(symbol_name)
                if file_path:
                    parts.append("ss.file_path = ?")
                    params.append(file_path)
                where = " AND ".join(parts)
                rows = conn.execute(
                    f"SELECT ss.*, s.commit_hash, s.timestamp FROM snapshot_symbols ss "
                    f"JOIN snapshots s ON ss.snapshot_id = s.id "
                    f"WHERE {where} ORDER BY s.timestamp DESC LIMIT ?",
                    [*params, max_count],
                ).fetchall()
                return [dict(r) for r in rows]
            finally:
                conn.close()

    def has_file_changed(self, project_root: str, file_path: str, file_hash: str) -> bool:
        latest = self.get_latest_snapshot(project_root)
        if not latest:
            return True
        return latest.file_hashes.get(file_path) != file_hash

    def _row_to_snapshot(self, row) -> ProjectSnapshot:
        return ProjectSnapshot(
            commit_hash=row["commit_hash"],
            timestamp=datetime.fromisoformat(row["timestamp"]),
            file_hashes=json.loads(row["file_hashes"]) if row["file_hashes"] else {},
            symbols=json.loads(row["symbols"]) if row["symbols"] else {},
            dependencies=json.loads(row["dependencies"]) if row["dependencies"] else [],
            is_analyzed=bool(row["is_analyzed"]),
        )
