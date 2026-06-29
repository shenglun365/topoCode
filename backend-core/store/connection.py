"""
SQLite 连接管理

- SQLiteContext: 单个 SQLite 连接的上下文管理器
"""
import os
import sqlite3
import threading
from typing import Optional

from config import SQLITE_PRAGMAS
from data_layer.write_queue import is_write_sql


class WriteResult:
    """模拟 sqlite3.Cursor 的 lastrowid / rowcount 属性。"""

    __slots__ = ("lastrowid", "rowcount")

    def __init__(self, lastrowid=None, rowcount: int = 0):
        self.lastrowid = lastrowid
        self.rowcount = rowcount


class SQLiteContext:
    """单个 SQLite 数据库连接的上下文管理器"""

    def __init__(self, db_path: str, *,
                 label: str = "",
                 write_queue=None):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._label = label
        self._wq = write_queue

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
        """执行 SQL，返回游标。写入操作通过 WriteQueue 串行化。"""
        if self._wq and self._label and is_write_sql(sql):
            result = self._wq.execute_sync(self._label, sql, params)
            if result.get("error"):
                raise RuntimeError(
                    f"WriteQueue error on {self._label}: {result['error']}"
                )
            return WriteResult(
                lastrowid=result.get("lastrowid"),
                rowcount=result.get("rowcount", 0),
            )
        return self.conn.execute(sql, params)

    def executemany(self, sql: str, params_list):
        """批量执行 SQL"""
        return self.conn.executemany(sql, params_list)

    def commit(self):
        """提交事务。WriteQueue 模式下单句写入已自提交，此为兼容空操作。"""
        if self._wq and self._label:
            return  # WriteQueue 每个 execute() 已自动 commit
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
