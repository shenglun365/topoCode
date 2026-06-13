"""
SQLite 连接管理

- SQLiteContext: 单个 SQLite 连接的上下文管理器
"""
import os
import sqlite3
import threading
from typing import Optional

from config import SQLITE_PRAGMAS


class SQLiteContext:
    """单个 SQLite 数据库连接的上下文管理器"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()

    def connect(self) -> sqlite3.Connection:
        """获取连接（懒加载 + 线程安全）"""
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
                    self._conn = sqlite3.connect(
                        self.db_path,
                        check_same_thread=False,
                    )
                    self._conn.row_factory = sqlite3.Row
                    self._init_pragmas()
        return self._conn

    @property
    def conn(self) -> sqlite3.Connection:
        """获取底层连接（懒加载）"""
        return self.connect()

    def _init_pragmas(self):
        """初始化 PRAGMA 设置"""
        conn = self._conn
        for key, value in SQLITE_PRAGMAS.items():
            conn.execute(f"PRAGMA {key}={value};")

    def execute(self, sql: str, params: tuple = ()):
        """执行 SQL，返回游标"""
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params_list):
        """批量执行 SQL"""
        return self.conn.executemany(sql, params_list)

    def commit(self):
        self.conn.commit()

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        self.conn
        return self

    def __exit__(self, *args):
        self.close()
