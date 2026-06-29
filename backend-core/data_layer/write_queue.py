"""
WriteQueue — 单线程 SQLite 写入序列化器

消除多线程并发写入时的 SQLITE_BUSY，保证事务顺序。

使用方式:
    from data_layer.write_queue import WriteQueue

    wq = WriteQueue()
    # 阻塞式写入（会等待写入完成）
    result = wq.execute_sync("main", "INSERT INTO t VALUES (?)", (1,))
    # result -> {"lastrowid": 1, "rowcount": 1}
    # 非阻塞写入（fire-and-forget）
    wq.execute("main", "INSERT INTO t VALUES (?)", (2,))
"""

from __future__ import annotations

import logging
import queue
import sqlite3
import threading
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_WRITE_PREFIXES = (
    "INSERT", "UPDATE", "DELETE", "CREATE", "ALTER", "DROP", "REPLACE",
)


def is_write_sql(sql: str) -> bool:
    """检测 SQL 语句是否为写操作（INSERT/UPDATE/DELETE/DDL）。"""
    stripped = sql.strip().upper()
    for prefix in _WRITE_PREFIXES:
        if stripped.startswith(prefix):
            return True
    # PRAGMA with assignment (write), but not PRAGMA queries (read)
    if stripped.startswith("PRAGMA") and "=" in stripped:
        read_keys = ("journal_mode", "cache_size", "synchronous",
                     "wal_checkpoint", "table_info", "index_list",
                     "foreign_key_list")
        if not any(k.upper() in stripped for k in read_keys):
            return True
    return False


class WriteQueue:
    """
    单一后台线程串行化所有 SQLite 写入操作。

    支持多数据库文件（按 db_label 区分连接）。

    db_label 规则:
        "main"      → topoone.db (主库)
        "sessions"  → sessions.db (会话库)
        "knowledge" → knowledge.db (知识库)
        "project:{pid}" → {project_id}.db (项目库)
    """

    def __init__(self, db_paths: dict[str, str] | None = None):
        """
        Args:
            db_paths: {label: path} 预注册的数据库路径。
                      也可后续通过 register_db() 动态添加。
        """
        self._pending: queue.Queue = queue.Queue()
        self._connections: dict[str, sqlite3.Connection] = {}
        self._db_paths: dict[str, str] = dict(db_paths or {})
        self._running = True
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="sqlite-writer",
        )
        self._thread.start()
        logger.info("[WriteQueue] writer thread started")

    # ── 公开 API ──────────────────────────────────────────────────────

    def register_db(self, label: str, path: str):
        """注册数据库路径（按需懒连接）。"""
        self._db_paths[label] = path

    def execute(self, label: str, sql: str, params: tuple = (),
                _commit: bool = True):
        """非阻塞写入。不等待结果，适用于分析/日志类写入。"""
        self._pending.put((label, sql, params, _commit, None, None))

    def execute_sync(self, label: str, sql: str, params: tuple = (),
                     _commit: bool = True, timeout: float = 30.0) -> dict:
        """
        阻塞式写入。等待写入线程完成，返回结果。

        Returns:
            {"lastrowid": int|None, "rowcount": int, "error": str|None}
        """
        ev = threading.Event()
        result: dict[str, Any] = {}
        self._pending.put((label, sql, params, _commit, ev, result))
        if not ev.wait(timeout):
            logger.error(f"[WriteQueue] timeout on {label}: {sql[:80]}")
            result["error"] = f"timeout after {timeout}s"
        return result

    def execute_batch(self, label: str,
                      items: list[tuple[str, tuple, bool]]) -> list[dict]:
        """
        批量写入（在一个事务内）。items = [(sql, params, commit), ...]

        返回每个语句的结果列表。
        """
        if not items:
            return []
        ev = threading.Event()
        results: list[dict] = []
        for _ in items:
            results.append({})
        self._pending.put(("__batch__", label, items, ev, results))
        ev.wait(timeout=60)
        return results

    def shutdown(self, timeout: float = 5.0):
        """优雅关闭写入线程。"""
        self._running = False
        self._pending.put(("__shutdown__", "", (), True, None, None))
        self._thread.join(timeout=timeout)
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()
        logger.info("[WriteQueue] shutdown complete")

    # ── 内部 ──────────────────────────────────────────────────────────

    def _get_conn(self, label: str) -> sqlite3.Connection:
        """获取或创建指定 label 的 SQLite 连接。"""
        if label not in self._connections:
            if label not in self._db_paths:
                raise ValueError(
                    f"[WriteQueue] unknown db label '{label}'. "
                    "Call register_db() first."
                )
            path = self._db_paths[label]
            conn = sqlite3.connect(path, check_same_thread=False)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.execute("PRAGMA busy_timeout=5000")
            except sqlite3.OperationalError as e:
                if "disk I/O error" in str(e) or "unable to open" in str(e).lower():
                    import os as _os
                    for ext in ("-wal", "-shm"):
                        extra = path + ext
                        if _os.path.exists(extra):
                            try:
                                _os.unlink(extra)
                                logger.warning(f"[WriteQueue] removed corrupted {extra}")
                            except Exception:
                                pass
                    conn = sqlite3.connect(path, check_same_thread=False)
                    conn.execute("PRAGMA journal_mode=WAL")
                    conn.execute("PRAGMA synchronous=NORMAL")
                    conn.execute("PRAGMA busy_timeout=5000")
                else:
                    raise
            self._connections[label] = conn
        return self._connections[label]

    def _run(self):
        """写入线程主循环。"""
        while self._running:
            try:
                task = self._pending.get(timeout=0.5)
            except queue.Empty:
                continue

            # Shutdown signal
            if task[0] == "__shutdown__":
                break

            # Batch mode
            if task[0] == "__batch__":
                _, label, items, ev, results = task
                try:
                    conn = self._get_conn(label)
                    conn.execute("BEGIN")
                    for i, (sql, params, _commit) in enumerate(items):
                        try:
                            cur = conn.execute(sql, params)
                            results[i] = {"lastrowid": cur.lastrowid,
                                          "rowcount": cur.rowcount}
                        except Exception as e:
                            results[i] = {"error": str(e)}
                            raise
                    conn.commit()
                except Exception as e:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    logger.error(
                        f"[WriteQueue] batch error on {label}: {e}"
                    )
                finally:
                    ev.set()
                continue

            # Single write
            label, sql, params, _commit, ev, result = task
            try:
                conn = self._get_conn(label)
                cur = conn.execute(sql, params)
                if _commit:
                    conn.commit()
                lastrowid = cur.lastrowid
                rowcount = cur.rowcount
                if ev:
                    result["lastrowid"] = lastrowid
                    result["rowcount"] = rowcount
            except Exception as e:
                logger.error(
                    f"[WriteQueue] error on {label}: {e} | SQL={sql[:100]}"
                )
                try:
                    conn.rollback()
                except Exception:
                    pass
                if ev:
                    result["error"] = str(e)
            finally:
                if ev:
                    ev.set()

    def __del__(self):
        try:
            self.shutdown(timeout=2)
        except Exception:
            pass
