"""
SQLite 连接管理

- SQLiteContext: 单个 SQLite 连接的上下文管理器
- MultiDBManager: LRU 缓存多个项目库连接 + 主库管理
"""
import os
import sqlite3
import threading
from collections import OrderedDict
from typing import Optional

from config import DB_DIR, MAIN_DB_FILE, SQLITE_PRAGMAS, MAX_DB_CONNECTIONS

from . import schema


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


class MultiDBManager:
    """
    多数据库管理器（已迁移至 sqlite_ctx.MultiDBManager，此处保留兼容层）

    - 主库 (topoone.db): 任务元数据
    - 项目库 (.topocode/data/project.db): 分析数据
    """

    def __init__(self, db_dir: str = DB_DIR):
        self.db_dir = db_dir
        os.makedirs(db_dir, exist_ok=True)
        self._main_db: Optional[SQLiteContext] = None
        self._cache: OrderedDict[str, SQLiteContext] = OrderedDict()
        self._lock = threading.RLock()

    @property
    def main_db(self) -> SQLiteContext:
        """获取主库连接，自动初始化 + 迁移"""
        if self._main_db is None:
            with self._lock:
                if self._main_db is None:
                    path = os.path.join(self.db_dir, MAIN_DB_FILE)
                    self._main_db = SQLiteContext(path)
                    self._main_db.conn
                    schema.init_main_schema(self._main_db)
        return self._main_db

    def get_project_db(self, project_id: str) -> SQLiteContext:
        """
        获取项目库连接（委托给 sqlite_ctx.MultiDBManager 使用新架构路径）
        """
        # 延迟导入避免循环依赖
        from sqlite_ctx import MultiDBManager as NewMultiDBManager
        new_mgr = NewMultiDBManager(self.db_dir)
        return new_mgr.get_project_db(project_id)

    def close_all(self):
        """关闭所有连接"""
        if self._main_db:
            self._main_db.close()
            self._main_db = None
        with self._lock:
            for db in self._cache.values():
                db.close()
            self._cache.clear()
