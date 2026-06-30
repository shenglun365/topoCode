"""
文件摘要缓存 — 写入 ingest 文件，由消费端异步入库。
"""
import logging
import os
import uuid
from typing import Optional

logger = logging.getLogger(__name__)

INGEST_DIR_RELPATH = os.path.join(".topoone", "ingest")


class FileSummaryCache:
    """基于 project_db.file_summaries 的摘要缓存。get/delete 直连 DB，put 写 ingest 文件。"""

    def __init__(self, project_db, project_id: str, project_root: str = ""):
        self._db = project_db
        self._pid = project_id
        self._project_root = project_root

    def get(self, file_path: str) -> Optional[dict]:
        row = self._db.execute(
            "SELECT summary, summary_len, created_at FROM file_summaries "
            "WHERE project_id=? AND file_path=? ORDER BY created_at DESC LIMIT 1",
            (self._pid, file_path)
        ).fetchone()
        return dict(row) if row else None

    def put(self, file_path: str, task_id: str, summary: str):
        """写入或更新文件摘要（写 ingest 文件，由消费端异步入库）。"""
        from ingest import write_ingest
        summary = summary[:2000]
        data = {
            "project_id": self._pid,
            "task_id": task_id,
            "file_path": file_path,
            "summary": summary,
            "summary_len": len(summary),
            "source": "llm",
        }
        if self._project_root:
            write_ingest(self._project_root, "file_summary", data)

    def get_detail(self, file_path: str) -> Optional[dict]:
        row = self._db.execute(
            "SELECT summary, summary_len, created_at, source, task_id FROM file_summaries "
            "WHERE project_id=? AND file_path=? ORDER BY created_at DESC LIMIT 1",
            (self._pid, file_path)
        ).fetchone()
        return dict(row) if row else None

    def delete(self, file_path: str) -> int:
        self._db.execute(
            "DELETE FROM file_summaries WHERE project_id=? AND file_path=?",
            (self._pid, file_path)
        )
        self._db.commit()
        return self._db.changes

    def delete_by_project(self):
        self._db.execute("DELETE FROM file_summaries WHERE project_id=?", (self._pid,))
        self._db.commit()
