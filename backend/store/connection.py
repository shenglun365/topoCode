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
        self._lock = threading.Lock()

    def connect(self) -> sqlite3.Connection:
        """获取连接（懒加载 + 线程安全）"""
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
                    self._conn = sqlite3.connect(
                        self.db_path,
                        check_same_thread=False,  # 多线程共享
                    )
                    self._conn.row_factory = sqlite3.Row
                    self._init_pragmas()
        return self._conn

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
    多数据库管理器

    - 主库 (topoone.db): 任务元数据
    - 项目库 ({project_id}.db): 分析数据
    - LRU 缓存最多 MAX_DB_CONNECTIONS 个项目库连接
    """

    def __init__(self, db_dir: str = DB_DIR):
        self.db_dir = db_dir
        os.makedirs(db_dir, exist_ok=True)
        self._main_db: Optional[SQLiteContext] = None
        self._cache: OrderedDict[str, SQLiteContext] = OrderedDict()
        self._lock = threading.Lock()

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
        获取项目库连接，LRU 缓存 + 自动回收

        Args:
            project_id: 项目 ID

        Returns:
            SQLiteContext 实例
        """
        with self._lock:
            # 命中缓存 → 移到末尾（最常用）
            if project_id in self._cache:
                self._cache.move_to_end(project_id)
                return self._cache[project_id]

            # 缓存满 → 回收最久未用
            while len(self._cache) >= MAX_DB_CONNECTIONS:
                oldest_id, oldest_db = self._cache.popitem(last=False)
                oldest_db.close()

            # 创建新连接
            path = os.path.join(self.db_dir, f"{project_id}.db")
            db = SQLiteContext(path)
            db.conn
            schema.init_project_schema(db)
            self._cache[project_id] = db
            return db

    def close_all(self):
        """关闭所有连接"""
        if self._main_db:
            self._main_db.close()
            self._main_db = None
        with self._lock:
            for db in self._cache.values():
                db.close()
            self._cache.clear()
