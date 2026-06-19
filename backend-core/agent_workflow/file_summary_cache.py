"""
文件摘要缓存 — 写入 project_db.file_summaries，跨会话复用。

file_summaries 表结构 (sqlite_ctx.py:636):
  CREATE TABLE IF NOT EXISTS file_summaries (
      id TEXT PRIMARY KEY,
      project_id TEXT NOT NULL,
      task_id TEXT,
      file_path TEXT NOT NULL,
      summary TEXT NOT NULL,
      summary_len INTEGER DEFAULT 0,
      source TEXT DEFAULT 'llm',
      created_at TEXT DEFAULT (datetime('now')),
      updated_at TEXT DEFAULT (datetime('now'))
  );
"""

import logging
import uuid
from typing import Optional

logger = logging.getLogger(__name__)


class FileSummaryCache:
    """基于 project_db.file_summaries 的文件摘要缓存。"""

    def __init__(self, project_db, project_id: str):
        self._db = project_db
        self._pid = project_id

    def get(self, file_path: str) -> Optional[dict]:
        """返回缓存摘要 dict，或 None。"""
        row = self._db.execute(
            "SELECT summary, summary_len, created_at FROM file_summaries "
            "WHERE project_id=? AND file_path=? ORDER BY created_at DESC LIMIT 1",
            (self._pid, file_path)
        ).fetchone()
        return dict(row) if row else None

    def put(self, file_path: str, task_id: str, summary: str):
        """写入或更新文件摘要（先删旧记录，避免同文件累积多行）。"""
        summary = summary[:2000]
        self._db.execute(
            "DELETE FROM file_summaries WHERE project_id=? AND file_path=?",
            (self._pid, file_path)
        )
        self._db.execute(
            "INSERT INTO file_summaries "
            "(id, project_id, task_id, file_path, summary, summary_len, source, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'llm', datetime('now'))",
            (str(uuid.uuid4())[:16], self._pid, task_id, file_path,
             summary, len(summary))
        )
        self._db.commit()

    def get_detail(self, file_path: str) -> Optional[dict]:
        """返回单条缓存详情（含摘要内容和元信息）。"""
        row = self._db.execute(
            "SELECT summary, summary_len, created_at, source, task_id FROM file_summaries "
            "WHERE project_id=? AND file_path=? ORDER BY created_at DESC LIMIT 1",
            (self._pid, file_path)
        ).fetchone()
        return dict(row) if row else None

    def delete(self, file_path: str) -> int:
        """删除指定文件的所有缓存行，返回删除条数。"""
        self._db.execute(
            "DELETE FROM file_summaries WHERE project_id=? AND file_path=?",
            (self._pid, file_path)
        )
        self._db.commit()
        logger.info(f"[FileSummaryCache] deleted: {file_path} for project {self._pid}")
        return self._db.changes

    def delete_by_project(self):
        """删除项目下所有文件摘要。"""
        self._db.execute("DELETE FROM file_summaries WHERE project_id=?", (self._pid,))
        self._db.commit()
        logger.info(f"[FileSummaryCache] cleared for project {self._pid}")
