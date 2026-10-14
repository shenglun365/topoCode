"""SQLite 上下文管理 - 多数据库架构 (主库/知识库/会话库/项目库)"""

import sqlite3
import json
import os
import sys
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime
from typing import Optional


logger = logging.getLogger(__name__)

from topoone.db.data_layer.write_queue import is_write_sql


class WriteResult:
    """模拟 sqlite3.Cursor 的 lastrowid / rowcount 属性。"""

    __slots__ = ("lastrowid", "rowcount")

    def __init__(self, lastrowid=None, rowcount: int = 0):
        self.lastrowid = lastrowid
        self.rowcount = rowcount


from .schema.main import MAIN_DB_TABLES_SQL
from .schema.knowledge import KNOWLEDGE_DB_TABLES_SQL
from .schema.sessions import SESSIONS_DB_TABLES_SQL
from .schema.chat import CHAT_DB_TABLES_SQL
from .schema.project import PROJECT_DB_TABLES_SQL

class SQLiteContext:
    """SQLite 数据库上下文（线程安全）"""

    def __init__(self, db_path: str, *,
                 label: str = "",
                 write_queue=None):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.RLock()
        self._label = label
        self._wq = write_queue
        self._last_connect_error = ""
        self._connect()

    def _connect(self):
        """建立数据库连接（线程安全）"""
        with self._lock:
            if self._conn is not None:
                return
            self._conn = self._try_open()
            if self._conn:
                return
            # 所有模式都失败 → 清理 WAL/SHM 文件后最后一次重试
            db_dir = os.path.dirname(self.db_path)
            db_base = os.path.basename(self.db_path)
            for ext in ("-wal", "-shm"):
                fpath = os.path.join(db_dir, db_base + ext)
                try:
                    if os.path.exists(fpath):
                        os.remove(fpath)
                        logger.warning(f"[SQLite] removed stale {fpath}")
                except Exception:
                    pass
            self._conn = self._try_open()
            if not self._conn:
                raise RuntimeError(
                    f"[SQLite] Cannot open {self.db_path} after cleanup: {self._last_connect_error}"
                )

    def _try_open(self):
        """尝试打开连接，返回 connection 或 None。"""
        import time as _time
        for mode in ("WAL", "DELETE"):
            try:
                conn = sqlite3.connect(self.db_path, check_same_thread=False, timeout=3000)
                conn.row_factory = sqlite3.Row
                conn.execute(f"PRAGMA journal_mode={mode}")
                for _pragma in [
                    "PRAGMA foreign_keys=ON",
                    "PRAGMA busy_timeout=5000",
                    "PRAGMA synchronous=NORMAL",
                    "PRAGMA cache_size=10000",
                ]:
                    try:
                        conn.execute(_pragma)
                    except Exception:
                        pass
                # 验证连接可用
                conn.execute("SELECT 1").fetchone()
                logger.info(f"[SQLite] opened {self.db_path} in {mode} mode")
                return conn
            except sqlite3.OperationalError as e:
                self._last_connect_error = str(e)
                logger.warning(
                    f"[SQLite] {mode} failed for {self.db_path}: {e}"
                )
                try:
                    conn.close()
                except Exception:
                    pass
                _time.sleep(0.1)
        return None

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._conn:
            self._connect()
        return self._conn

    # ==================== 通用查询方法 ====================

    def _reconnect(self):
        """重建连接（在 disk I/O error 后恢复用）。"""
        with self._lock:
            try:
                if self._conn:
                    self._conn.close()
            except Exception:
                pass
            self._conn = None
            self._connect()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行 SQL — 写入通过 WriteQueue 串行化；读操作直接执行。"""
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
        upper_sql = sql.strip().upper()
        is_write = upper_sql.startswith(('INSERT', 'UPDATE', 'DELETE', 'ALTER',
                                         'CREATE', 'DROP', 'REPLACE'))

        for attempt in range(3):
            try:
                with self._lock:
                    cursor = self.conn.execute(sql, params)
                if is_write or upper_sql == 'COMMIT':
                    self.conn.commit()
                return cursor
            except sqlite3.OperationalError as e:
                err_str = str(e)
                if ("disk I/O" in err_str or "abort due to ROLLBACK" in err_str) and attempt < 2:
                    logger.warning(
                        f"[SQLite] transient error on {self._label or self.db_path}, "
                        f"reconnecting (attempt {attempt+2}/3): {e}"
                    )
                    self._reconnect()
                    continue
                raise

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        """查询所有结果（读后隐含提交）"""
        cursor = self.execute(sql, params)
        result = [dict(row) for row in cursor.fetchall()]
        return result

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """查询单条结果"""
        cursor = self.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def executemany(self, sql: str, params_list):
        """批量执行 SQL — 通过 WriteQueue 串行化（有 WQ 时）；否则直连执行。"""
        if self._wq and self._label:
            items = [(sql, params, False) for params in params_list]
            self._wq.execute_batch(self._label, items)
            return
        self.conn.executemany(sql, params_list)

    def executescript(self, sql: str):
        """执行 SQL 脚本（DDL 迁移用）— 通过 WriteQueue 串行化（有 WQ 时）；否则直连。"""
        if self._wq and self._label:
            stmts = [s.strip() for s in sql.split(";") if s.strip()]
            if stmts:
                items = [(s, (), True) for s in stmts]
                self._wq.execute_batch(self._label, items)
        else:
            self.conn.executescript(sql)

    def commit(self):
        """提交事务。WriteQueue 模式下单句写入已自提交，此为兼容空操作。"""
        if self._wq and self._label:
            return
        self.conn.commit()

    def insert(self, table: str, data: dict) -> str:
        """插入数据，返回 ID"""
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        sql = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        self.execute(sql, tuple(data.values()))
        return data.get("id", "")

    def update(self, table: str, data: dict, where: str, where_params: tuple = ()) -> int:
        """更新数据，返回影响行数"""
        set_clause = ", ".join([f"{k} = ?" for k in data.keys()])
        sql = f"UPDATE {table} SET {set_clause} WHERE {where}"
        cursor = self.execute(sql, tuple(data.values()) + where_params)
        return cursor.rowcount

    def delete(self, table: str, where: str, where_params: tuple = ()) -> int:
        """删除数据，返回影响行数"""
        sql = f"DELETE FROM {table} WHERE {where}"
        cursor = self.execute(sql, where_params)
        return cursor.rowcount

    def close(self):
        """关闭连接"""
        if self._conn:
            self._conn.close()
            self._conn = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# ==================== 表初始化 SQL ====================




# chat.db — AI CHAT 专用库：
# - 持久化文档：chat_drafts（便签/草稿）、chat_archives（归档）、doc_categories
# - AI 助手会话：module_type='ai_assistant' 的 llm_sessions + llm_messages
#   （其余模块类型的会话仍在 sessions.db；由 llm_service 按 module_type/session_id 路由）



def _init_default_skills(db: SQLiteContext):
    """初始化默认 SKILL 配置"""
    default_skills = [
        {
            "id": "skill-compilation",
            "name": "编译校验",
            "description": "确保代码编译无报错",
            "category": "validation",
            "enabled": 1,
            "config": json.dumps({"enabled": True, "strict": False}),
        },
        {
            "id": "skill-unit-test",
            "name": "单元测试校验",
            "description": "确保单元测试通过",
            "category": "validation",
            "enabled": 1,
            "config": json.dumps({"enabled": True, "minCoverage": 80}),
        },
        {
            "id": "skill-runtime",
            "name": "运行时校验",
            "description": "确保代码执行无报错",
            "category": "validation",
            "enabled": 1,
            "config": json.dumps({"enabled": True}),
        },
        {
            "id": "skill-signature",
            "name": "函数签名校验",
            "description": "严格约束函数签名一致性",
            "category": "validation",
            "enabled": 0,
            "config": json.dumps({"enabled": False}),
        },
        {
            "id": "skill-dependency",
            "name": "依赖检查",
            "description": "检查依赖版本和兼容性",
            "category": "validation",
            "enabled": 0,
            "config": json.dumps({"enabled": False}),
        },
    ]

    for skill in default_skills:
        db.execute(
            "INSERT OR IGNORE INTO skill_configs (id, name, description, category, enabled, config) VALUES (?, ?, ?, ?, ?, ?)",
            (skill["id"], skill["name"], skill["description"], skill["category"], skill["enabled"], skill["config"]),
        )
    db.conn.commit()


# ==================== MultiDBManager ====================

class MultiDBManager:
    """
    多数据库管理器（全部集中于 data_dir，源码目录只留 .topocode/proj-id 签名）
    - 主库: topoone.db (项目信息 + 全局配置)
    - 知识库: knowledge.db
    - 会话库: sessions.db (非 ai_assistant 模块的 LLM 会话)
    - CHAT 库: chat.db (AI 助手会话 + 持久化文档 chat_drafts/chat_archives)
    - 项目库: projects/{project_id}/project.db (LRU 缓存)
    """

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.expanduser("~"), ".topocode")
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

        from topoone.db.data_layer.write_queue import WriteQueue
        self._write_queue = WriteQueue()
        from topoone.db.data_layer.cache_store import CacheStore
        cache_dir = os.path.join(self.data_dir, "cache")
        self._cache_store = CacheStore(cache_dir)
        from topoone.db.data_layer.duckdb_reader import DuckDBReader
        self._duckdb = DuckDBReader(self)

        # 初始化主库
        main_db_path = os.path.join(self.data_dir, "topoone.db")
        self._write_queue.register_db("main", main_db_path)
        self.main_db = SQLiteContext(main_db_path, label="main",
                                     write_queue=self._write_queue)
        self._init_main_tables()

        # 初始化知识库
        knowledge_db_path = os.path.join(self.data_dir, "knowledge.db")
        self._write_queue.register_db("knowledge", knowledge_db_path)
        self.knowledge_db = SQLiteContext(knowledge_db_path, label="knowledge",
                                          write_queue=self._write_queue)
        self._init_knowledge_tables()

        # 初始化会话库
        sessions_db_path = os.path.join(self.data_dir, "sessions.db")
        self._write_queue.register_db("sessions", sessions_db_path)
        self.sessions_db = SQLiteContext(sessions_db_path, label="sessions",
                                         write_queue=self._write_queue)
        self._init_sessions_tables()

        # 初始化 CHAT 库（AI 助手会话 + 持久化文档）
        chat_db_path = os.path.join(self.data_dir, "chat.db")
        self._write_queue.register_db("chat", chat_db_path)
        self.chat_db = SQLiteContext(chat_db_path, label="chat",
                                     write_queue=self._write_queue)
        self._init_chat_tables()

        # 项目库 LRU 缓存 (max=10)
        self._project_db_cache: OrderedDict[str, SQLiteContext] = OrderedDict()
        self._project_db_max = 100
        self._project_db_idle_timeout = 300  # 5 分钟无访问则自动关闭
        self._project_db_last_used: dict[str, float] = {}

    @property
    def write_queue(self):
        return self._write_queue

    @property
    def cache_store(self):
        return self._cache_store

    @property
    def duckdb(self):
        return self._duckdb

    def _init_main_tables(self):
        """初始化主库表"""
        self.main_db.executescript(MAIN_DB_TABLES_SQL)
        self._migrate_main_tables()

    def _migrate_main_tables(self):
        """迁移主库表 - 添加新字段"""
        # 为已有数据库添加新字段
        columns_to_add = {
            "analysis_tasks": [
                ("scope", "TEXT"),
                ("scopes", "TEXT"),
                ("extensions", "TEXT"),
                ("exclude_dirs", "TEXT"),
                ("report_types", "TEXT"),
                ("pattern_type", "TEXT"),
                ("pattern", "TEXT"),
                ("config_version", "INTEGER DEFAULT 1"),
                ("last_run_id", "TEXT"),
            ],
            "model_configs": [
                ("context_window", "INTEGER DEFAULT 8192"),
                ("max_requests_per_day", "INTEGER DEFAULT 0"),
                ("max_tokens_per_day", "INTEGER DEFAULT 0"),
                ("frequency_penalty", "REAL DEFAULT 0.0"),
                ("presence_penalty", "REAL DEFAULT 0.0"),
            ],
            "task_config_history": [
                ("scopes", "TEXT"),
                ("pattern_type", "TEXT"),
                ("pattern", "TEXT"),
            ],
            "agent_configs": [
                ("scenario", "TEXT DEFAULT ''"),
            ],
            "analysis_reports": [
                ("logs", "TEXT"),
                ("run_id", "TEXT"),
                ("total_ast_nodes", "INTEGER DEFAULT 0"),
                ("total_symbols", "INTEGER DEFAULT 0"),
                ("total_call_edges", "INTEGER DEFAULT 0"),
                ("total_dep_edges", "INTEGER DEFAULT 0"),
                ("total_communities", "INTEGER DEFAULT 0"),
                ("language_stats", "TEXT"),
                ("files_processed", "INTEGER DEFAULT 0"),
                ("skipped_files", "INTEGER DEFAULT 0"),
                ("best_call_community_id", "TEXT"),
                ("best_dep_community_id", "TEXT"),
                ("alias", "TEXT"),
                ("node_style_map", "TEXT"),
            ],
            "analysis_task_runs": [
                ("snapshot_scopes", "TEXT"),
            ],
            "project_versions": [
                ("baseline_commit", "TEXT DEFAULT ''"),
            ],
            "analysis_tasks_misc": [  # 通过 analysis_tasks 表执行
            ],
            "projects": [
                ("group", "TEXT DEFAULT ''"),
                ("favorite", "INTEGER DEFAULT 0"),
                ("pinned", "INTEGER DEFAULT 0"),
                ("sort_order", "INTEGER DEFAULT 0"),
                ("summary", "TEXT DEFAULT ''"),
                ("summary_generated_at", "TEXT"),
                ("import_mode", "TEXT DEFAULT 'static'"),
                ("remote_url", "TEXT DEFAULT ''"),
                ("local_repo_path", "TEXT DEFAULT ''"),
                ("source_cache_dir", "TEXT DEFAULT ''"),
                ("current_version_id", "TEXT DEFAULT ''"),
                ("db_size_bytes", "INTEGER DEFAULT 0"),
                ("source_size_bytes", "INTEGER DEFAULT 0"),
                ("storage_checked_at", "TEXT"),
            ],
            "view_mounts": [
                # 存量库补挂载来源(建表 DDL 已含; ALTER 无法加 CHECK, 校验在写入侧)
                ("mount_origin", "TEXT NOT NULL DEFAULT 'manual'"),
            ],
        }
        for table, columns in columns_to_add.items():
            if not columns:
                continue
            cursor = self.main_db.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cursor.fetchall()}
            for col_name, col_type in columns:
                if col_name not in existing:
                    self.main_db.execute(f'ALTER TABLE {table} ADD COLUMN "{col_name}" {col_type}')

        # 迁移: 创建新表（project_groups + project_group_map + doc_project_map）
        self.main_db.executescript("""
            CREATE TABLE IF NOT EXISTS project_groups (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                parent_id TEXT DEFAULT NULL REFERENCES project_groups(id) ON DELETE CASCADE,
                depth INTEGER DEFAULT 0 CHECK(depth >= 0 AND depth <= 3),
                sort_order INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE INDEX IF NOT EXISTS idx_project_groups_parent ON project_groups(parent_id);

            CREATE TABLE IF NOT EXISTS project_group_map (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                group_id TEXT NOT NULL REFERENCES project_groups(id) ON DELETE CASCADE,
                PRIMARY KEY (project_id, group_id)
            );
            CREATE INDEX IF NOT EXISTS idx_project_group_map_group ON project_group_map(group_id);
        """)

        # 迁移: 更新 analysis_tasks 的 type CHECK 约束(新增 'fast' 任务类型)
        # ALTER 无法改 CHECK → 整表重建(照 model_configs 先例; 全列拷贝零丢失)
        try:
            row = self.main_db.fetchone(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='analysis_tasks'"
            )
            ddl = (row.get('sql', '') if row else '') or ''
            if ddl and "'fast'" not in ddl:
                logger.info("[migrate] Old analysis_tasks type CHECK detected, migrating...")
                # 表重建须临时关闭 FK(task_config_history 等子表引用本表,
                # DROP 期间触发 FOREIGN KEY constraint failed)——SQLite 官方
                # 12 步重建流程的标准步骤; 结束后恢复(finally)。
                self.main_db.conn.execute("PRAGMA foreign_keys=OFF")
                try:
                    self.main_db.conn.executescript("""
                        DROP TABLE IF EXISTS analysis_tasks_new;
                        CREATE TABLE analysis_tasks_new (
                            id TEXT PRIMARY KEY,
                            project_id TEXT NOT NULL,
                            type TEXT NOT NULL CHECK(type IN ('ast', 'call-chain', 'dependency', 'dataflow', 'full', 'fast')),
                            name TEXT NOT NULL,
                            status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'modified', 'running', 'done', 'error', 'cancelled')),
                            progress INTEGER DEFAULT 0,
                            total INTEGER DEFAULT 100,
                            current INTEGER DEFAULT 0,
                            error TEXT,
                            result_data TEXT,
                            favorite INTEGER DEFAULT 0,
                            pinned INTEGER DEFAULT 0,
                            tags TEXT,
                            scope TEXT,
                            scopes TEXT,
                            extensions TEXT,
                            exclude_dirs TEXT,
                            report_types TEXT,
                            pattern_type TEXT,
                            pattern TEXT,
                            config_version INTEGER DEFAULT 1,
                            last_run_id TEXT,
                            created_at TEXT DEFAULT (datetime('now')),
                            updated_at TEXT DEFAULT (datetime('now')),
                            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
                        );
                        INSERT INTO analysis_tasks_new
                            (id, project_id, type, name, status, progress, total,
                             current, error, result_data, favorite, pinned, tags,
                             scope, scopes, extensions, exclude_dirs, report_types,
                             pattern_type, pattern, config_version, last_run_id,
                             created_at, updated_at)
                        SELECT
                            id, project_id, type, name, status, progress, total,
                            current, error, result_data, favorite, pinned, tags,
                            scope, scopes, extensions, exclude_dirs, report_types,
                            pattern_type, pattern, config_version, last_run_id,
                            created_at, updated_at
                        FROM analysis_tasks;
                        DROP TABLE analysis_tasks;
                        ALTER TABLE analysis_tasks_new RENAME TO analysis_tasks;
                        CREATE INDEX IF NOT EXISTS idx_analysis_tasks_project ON analysis_tasks(project_id);
                        CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks(status);
                        CREATE INDEX IF NOT EXISTS idx_analysis_tasks_created ON analysis_tasks(created_at);
                    """)
                    self.main_db.conn.commit()
                    logger.info("[migrate] analysis_tasks type CHECK updated (+fast)")
                finally:
                    try:
                        self.main_db.conn.execute("PRAGMA foreign_keys=ON")
                    except Exception:
                        pass
        except Exception as e:
            logger.error(f"[migrate] analysis_tasks CHECK migration failed: {e}")

        # 迁移: 更新 model_configs 的 provider/status CHECK 约束
        try:
            row = self.main_db.fetchone(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='model_configs'"
            )
            if row and ('openai' in row.get('sql', '') or 'online' in row.get('sql', '')):
                logger.info("[migrate] Old model_configs CHECK constraint detected, migrating...")
                self.main_db.conn.executescript("""
                    CREATE TABLE model_configs_new (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        provider TEXT NOT NULL CHECK(provider IN ('ollama', 'lm-studio', 'custom-local', 'deepseek', 'minimax-cn', 'minimax-global', 'openrouter', 'custom-cloud')),
                        model TEXT NOT NULL,
                        url TEXT NOT NULL,
                        api_key TEXT DEFAULT '',
                        type TEXT DEFAULT 'local' CHECK(type IN ('local', 'cloud')),
                        status TEXT DEFAULT 'offline' CHECK(status IN ('offline', 'connected', 'error')),
                        is_default INTEGER DEFAULT 0,
                        temperature REAL DEFAULT 0.7,
                        max_tokens INTEGER DEFAULT 16384,
                        frequency_penalty REAL DEFAULT 0.0,
                        presence_penalty REAL DEFAULT 0.0,
                        timeout INTEGER DEFAULT 300,
                        extra_config TEXT,
                        context_window INTEGER DEFAULT 8192,
                        max_requests_per_day INTEGER DEFAULT 0,
                        max_tokens_per_day INTEGER DEFAULT 0,
                        created_at TEXT DEFAULT (datetime('now')),
                        updated_at TEXT DEFAULT (datetime('now'))
                    );
                    INSERT OR IGNORE INTO model_configs_new
                        (id, name, provider, model, url, api_key, type, status,
                         is_default, temperature, max_tokens, frequency_penalty,
                         presence_penalty, timeout, extra_config,
                         created_at, updated_at,
                         context_window, max_requests_per_day, max_tokens_per_day)
                    SELECT
                        id, name, provider, model, url, api_key, type, status,
                        is_default, temperature, max_tokens, frequency_penalty,
                        presence_penalty, timeout, extra_config,
                        created_at, updated_at,
                        context_window, max_requests_per_day, max_tokens_per_day
                    FROM model_configs;
                    DROP TABLE model_configs;
                    ALTER TABLE model_configs_new RENAME TO model_configs;
                """)
                self.main_db.conn.commit()
                logger.info("[migrate] model_configs CHECK constraint updated")
        except Exception as e:
            logger.error(f"[migrate] model_configs migration failed: {e}")

        # 修复迁移可能造成的数据损坏（旧版本迁移曾使用 SELECT * 导致列错位）
        try:
            self.main_db.execute("""
                UPDATE model_configs SET timeout = 300 WHERE typeof(timeout) = 'text'
            """)
            self.main_db.execute("""
                UPDATE model_configs SET context_window = 8192 WHERE typeof(context_window) = 'text'
            """)
            self.main_db.execute("""
                UPDATE model_configs SET max_requests_per_day = 0 WHERE typeof(max_requests_per_day) = 'text'
            """)
            self.main_db.execute("""
                UPDATE model_configs SET max_tokens_per_day = 0 WHERE typeof(max_tokens_per_day) = 'text'
            """)
            self.main_db.execute("""
                UPDATE model_configs SET created_at = datetime('now') WHERE typeof(created_at) != 'text' OR created_at IS NULL
            """)
            self.main_db.execute("""
                UPDATE model_configs SET updated_at = datetime('now') WHERE typeof(updated_at) != 'text' OR updated_at IS NULL
            """)
            self.main_db.execute("""
                UPDATE model_configs SET frequency_penalty = 0.0 WHERE frequency_penalty >= 30000
            """)
            self.main_db.execute("""
                UPDATE model_configs SET presence_penalty = 0.0 WHERE typeof(presence_penalty) = 'text'
            """)
            self.main_db.execute("""
                UPDATE model_configs SET extra_config = NULL WHERE typeof(extra_config) = 'text' AND extra_config LIKE '20%T%'
            """)
            # 将旧版毫秒超时值（30000ms）转换为秒（300s）
            self.main_db.execute("""
                UPDATE model_configs SET timeout = 300 WHERE typeof(timeout) = 'integer' AND timeout >= 30000
            """)
            # 修复已有 timeout=30 记录（上一版迁移和数据修复的遗留值）
            self.main_db.execute("""
                UPDATE model_configs SET timeout = 300 WHERE timeout = 30
            """)
            self.main_db.conn.commit()
        except Exception as e:
            logger.warning(f"[migrate] model_configs data repair skipped: {e}")

        # 性能索引: 任务列表 ORDER BY created_at
        try:
            self.main_db.execute("CREATE INDEX IF NOT EXISTS idx_analysis_tasks_created ON analysis_tasks(created_at)")
        except Exception:
            pass

        self.main_db.conn.commit()
        _init_default_skills(self.main_db)

    def _init_knowledge_tables(self):
        """初始化知识库表"""
        self.knowledge_db.executescript(KNOWLEDGE_DB_TABLES_SQL)
        self.knowledge_db.conn.commit()

    def _init_sessions_tables(self):
        """初始化会话库表"""
        self.sessions_db.executescript(SESSIONS_DB_TABLES_SQL)
        self.sessions_db.conn.commit()

    def _init_chat_tables(self):
        """初始化 CHAT 库表（AI 助手会话 + 持久化文档）"""
        self.chat_db.executescript(CHAT_DB_TABLES_SQL)
        self.chat_db.conn.commit()

    def _project_db_path(self, project_id: str, project_root: str = None) -> str:
        """项目库统一中心路径: {data_dir}/projects/{project_id}/project.db。

        不再依赖源码目录 root_path —— 源码目录整体移动不影响项目库定位。
        """
        return self.project_db_path(project_id)

    def project_db_path(self, project_id: str) -> str:
        """项目库中心路径（公开方法，供 CLI / 迁移工具复用）。"""
        return os.path.join(self.data_dir, "projects", project_id, "project.db")

    def refresh_project_storage_stats(self, project_id: str) -> dict:
        """计算并回写主库 projects 表存储统计缓存列（db_size + source_size）。

        只打开目标项目库一次做 SUM；失败时保留旧缓存值（best-effort，不抛异常）。
        供 import / sync / clear-cache 后调用，避免首页逐个项目库扫描。
        """
        cached = {"db_size_bytes": 0, "source_size_bytes": 0, "storage_checked_at": ""}
        if not project_id:
            return cached
        try:
            db_path = self.project_db_path(project_id)
            db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
            source_size = 0
            project_db = self.get_project_db(project_id)
            if project_db is not None:
                row = project_db.fetchone("SELECT COALESCE(SUM(size), 0) AS s FROM source_files")
                if row:
                    source_size = row.get("s") if isinstance(row, dict) else row[0]
                    source_size = source_size or 0
            cached = {
                "db_size_bytes": db_size,
                "source_size_bytes": source_size,
                "storage_checked_at": datetime.now().isoformat(),
            }
            self.main_db.update("projects", cached, "id = ?", (project_id,))
        except Exception as e:
            logger.warning(f"[storage] refresh stats failed for {project_id}: {e}")
        return cached

    # ── 源码目录 proj-id 签名（.topocode/proj-id，仅一行 project id）──

    @staticmethod
    def signature_path(project_root: str) -> str:
        return os.path.join(project_root, ".topocode", "proj-id")

    @staticmethod
    def write_proj_signature(project_root: str, project_id: str) -> None:
        """在源码目录写 proj-id 签名文件（目录整体移动后用于快速重关联）。"""
        try:
            sig = os.path.join(project_root, ".topocode")
            os.makedirs(sig, exist_ok=True)
            with open(os.path.join(sig, "proj-id"), "w") as f:
                f.write(project_id + "\n")
        except Exception as e:
            logger.warning(f"[signature] failed to write proj-id at {project_root}: {e}")

    @staticmethod
    def read_proj_signature(project_root: str) -> str:
        """读取源码目录 proj-id 签名；不存在/不可读返回 ''。"""
        try:
            with open(os.path.join(project_root, ".topocode", "proj-id")) as f:
                return f.read().strip()
        except Exception:
            return ""

    @staticmethod
    def remove_proj_signature(project_root: str) -> None:
        """删除源码目录 proj-id 签名（best-effort）。"""
        try:
            p = os.path.join(project_root, ".topocode", "proj-id")
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass

    def init_project_db(self, project_id: str, project_root: str = None):
        """创建并初始化项目库。project_root 参数保留仅为调用兼容。"""
        db_path = self._project_db_path(project_id)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        label = f"project:{project_id}"
        self._write_queue.register_db(label, db_path)
        project_db = SQLiteContext(db_path, label=label,
                                   write_queue=self._write_queue)
        project_db.executescript(PROJECT_DB_TABLES_SQL)
        return project_db

    def _table_exists(self, project_db: SQLiteContext, table: str) -> bool:
        try:
            row = project_db.fetchone(
                "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name=?", (table,)
            )
            return row["c"] > 0 if row else False
        except Exception:
            return False

    def _migrate_project_db(self, project_db: SQLiteContext):
        """迁移项目库表 - v2 重设计: 重建 graph_node + 新增 graph_edge + file_count"""
        # 为新版 graph_node 补充字段
        try:
            cursor = project_db.execute("PRAGMA table_info(graph_node)")
            graph_cols = {row[1] for row in cursor.fetchall()}
            for col in ('kind', 'name', 'qualified_name', 'file_path', 'language',
                        'start_line', 'start_col', 'end_line', 'end_col',
                        'signature', 'visibility', 'is_exported', 'is_async', 'is_static',
                        'docstring', 'decorators', 'type_parameters'):
                if col not in graph_cols:
                    try:
                        project_db.execute(f'ALTER TABLE graph_node ADD COLUMN "{col}" TEXT')
                    except Exception:
                        pass
        except Exception:
            pass

        # 为 community_llm_results 添加新增列（兼容旧库）
        try:
            cursor = project_db.execute("PRAGMA table_info(community_llm_results)")
            llm_cols = {row[1] for row in cursor.fetchall()}
            for col in ('component_type', 'status',
                        # 命名产物来源: detail=文件摘要详细通道 / fast-agent=快速命名通道
                        ('source', "TEXT DEFAULT 'detail'")):
                if isinstance(col, tuple):
                    if col[0] not in llm_cols:
                        project_db.execute(
                            f'ALTER TABLE community_llm_results ADD COLUMN "{col[0]}" {col[1]}')
                elif col not in llm_cols:
                    project_db.execute(f'ALTER TABLE community_llm_results ADD COLUMN "{col}" TEXT')
        except Exception:
            pass


        # 迁移：graph_node_positions CHECK 扩 UNIFIED（组件统一，存量库表重建）
        try:
            row = project_db.fetchone(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='graph_node_positions'"
            )
            if row and row["sql"] and "'UNIFIED'" not in row["sql"]:
                project_db.execute("DROP INDEX IF EXISTS idx_graph_pos_active_unique")
                project_db.execute("DROP INDEX IF EXISTS idx_graph_pos_snap_unique")
                project_db.execute("ALTER TABLE graph_node_positions RENAME TO graph_node_positions_legacy")
                project_db.execute("""
                    CREATE TABLE graph_node_positions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        task_id TEXT NOT NULL,
                        edge_type TEXT NOT NULL CHECK(edge_type IN ('INCLUDE','CALL','UNIFIED','EXTERNAL_INCLUDE','EXTERNAL_CALL')),
                        drill_key TEXT NOT NULL,
                        snapshot_id TEXT,
                        layout_type TEXT NOT NULL CHECK(layout_type IN ('dagre','force')),
                        node_id TEXT NOT NULL,
                        pos_x REAL NOT NULL,
                        pos_y REAL NOT NULL,
                        updated_at TEXT DEFAULT (datetime('now'))
                    )
                """)
                project_db.execute("""
                    INSERT INTO graph_node_positions
                        (task_id, edge_type, drill_key, snapshot_id, layout_type, node_id, pos_x, pos_y, updated_at)
                    SELECT task_id, edge_type, drill_key, snapshot_id, layout_type, node_id, pos_x, pos_y, updated_at
                    FROM graph_node_positions_legacy
                """)
                project_db.execute("DROP TABLE graph_node_positions_legacy")
                project_db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_pos_active_unique ON graph_node_positions(task_id, edge_type, drill_key, layout_type, node_id) WHERE snapshot_id IS NULL")
                project_db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_pos_snap_unique ON graph_node_positions(task_id, edge_type, drill_key, snapshot_id, layout_type, node_id)")
        except Exception:
            pass

        # 迁移旧 component_analysis 数据到 community_llm_results（兼容旧库）
        # 先检查表是否存在，避免 WQ 误报 ERROR 日志
        try:
            has_ca = project_db.fetchone(
                "SELECT COUNT(*) AS c FROM sqlite_master WHERE type='table' AND name='component_analysis'"
            )["c"] > 0
        except Exception:
            has_ca = False
        if has_ca:
            try:
                project_db.execute("""
                    INSERT OR IGNORE INTO community_llm_results
                        (task_id, edge_type, comm_lv, comm_id, name, summary, component_type, status, created_at)
                    SELECT
                        task_id,
                        CASE
                            WHEN component_type='community' AND component_id LIKE 'comm-%-incl-%' THEN 'INCLUDE'
                            WHEN component_type='community' AND component_id LIKE 'comm-%-call-%' THEN 'CALL'
                            ELSE ''
                        END,
                        'L0', component_id, analyzed_name, functional_summary,
                        component_type, status, analyzed_at
                    FROM component_analysis
                """)
            except Exception:
                pass
        # 修复已迁移但 edge_type='' 的数据（component_analysis 表已不存在的旧迁移数据）
        try:
            project_db.execute("""
                UPDATE community_llm_results
                SET edge_type = 'INCLUDE'
                WHERE edge_type = '' AND component_type = 'community'
                  AND comm_id LIKE 'comm-%-incl-%'
            """)
            project_db.execute("""
                UPDATE community_llm_results
                SET edge_type = 'CALL'
                WHERE edge_type = '' AND component_type = 'community'
                  AND comm_id LIKE 'comm-%-call-%'
            """)
        except Exception:
            pass
        # 删除旧表
        try:
            project_db.execute("DROP TABLE IF EXISTS component_analysis")
        except Exception:
            pass

        # 为 graph_doc 添加 file_count 列（表不存在则跳过）
        if self._table_exists(project_db, "graph_doc"):
            try:
                cursor = project_db.execute("PRAGMA table_info(graph_doc)")
                gd_cols = {row[1] for row in cursor.fetchall()}
                if 'file_count' not in gd_cols:
                    project_db.execute("ALTER TABLE graph_doc ADD COLUMN file_count INTEGER DEFAULT 0")
                if 'metadata' not in gd_cols:
                    project_db.execute("ALTER TABLE graph_doc ADD COLUMN metadata TEXT DEFAULT '{}'")
            except Exception:
                pass

        # 为 community_hierarchy 添加 file_count 列（表不存在则跳过）
        if self._table_exists(project_db, "community_hierarchy"):
            try:
                cursor = project_db.execute("PRAGMA table_info(community_hierarchy)")
                ch_cols = {row[1] for row in cursor.fetchall()}
                if 'file_count' not in ch_cols:
                    project_db.execute("ALTER TABLE community_hierarchy ADD COLUMN file_count INTEGER DEFAULT 0")
            except Exception:
                pass

        # 新建 graph_edge 表
        try:
            project_db.execute("""
                CREATE TABLE IF NOT EXISTS graph_edge (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    provenance TEXT DEFAULT 'parser',
                    line INTEGER DEFAULT 0,
                    col INTEGER DEFAULT 0,
                    file_path TEXT DEFAULT '',
                    metadata TEXT DEFAULT '',
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            project_db.execute("CREATE INDEX IF NOT EXISTS idx_graph_edge_task ON graph_edge(task_id)")
            project_db.execute("CREATE INDEX IF NOT EXISTS idx_graph_edge_kind ON graph_edge(task_id, kind)")
        except Exception:
            pass

        # 新建 community_llm_results 表（对旧项目库兼容）
        try:
            project_db.execute("""
                CREATE TABLE IF NOT EXISTS community_llm_results (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id     TEXT    NOT NULL,
                    edge_type   TEXT    NOT NULL,
                    comm_lv     TEXT    NOT NULL,
                    comm_id     TEXT    NOT NULL,
                    name        TEXT,
                    summary     TEXT,
                    model_id    TEXT,
                    template_id TEXT,
                    name_manual TEXT,
                    created_at  TEXT DEFAULT (datetime('now')),
                    updated_at  TEXT DEFAULT (datetime('now')),
                    UNIQUE(task_id, edge_type, comm_lv, comm_id)
                )
            """)
        except Exception:
            pass

        # 新建 agent_task_history 表（对旧项目库兼容）
        try:
            project_db.execute("""
                CREATE TABLE IF NOT EXISTS agent_task_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id  TEXT    NOT NULL,
                    task_id     TEXT    NOT NULL,
                    agent_id    TEXT    NOT NULL UNIQUE,
                    action      TEXT    NOT NULL,
                    status      TEXT    NOT NULL,
                    steps       TEXT,
                    message     TEXT,
                    error       TEXT,
                    created_at  TEXT,
                    finished_at TEXT
                )
            """)
            project_db.execute("CREATE INDEX IF NOT EXISTS idx_ath_task ON agent_task_history(task_id, created_at DESC)")
        except Exception:
            pass

        # 性能索引: graph_doc JOIN + community_hierarchy ORDER BY（表不存在则跳过）
        if self._table_exists(project_db, "graph_doc"):
            try:
                project_db.execute("CREATE INDEX IF NOT EXISTS idx_graph_doc_join ON graph_doc(task_id, edge_type, comm_id)")
            except Exception:
                pass
            try:
                project_db.execute("CREATE INDEX IF NOT EXISTS idx_graph_doc_parent ON graph_doc(task_id, edge_type, parent_comm_id)")
            except Exception:
                pass
        # 深度展开索引: parent_comm_id
        if self._table_exists(project_db, "community_hierarchy"):
            try:
                project_db.execute("CREATE INDEX IF NOT EXISTS idx_comm_hier_lv ON community_hierarchy(task_id, edge_type, comm_lv, comm_id)")
            except Exception:
                pass
            try:
                project_db.execute("CREATE INDEX IF NOT EXISTS idx_comm_hier_parent ON community_hierarchy(task_id, edge_type, parent_comm_id)")
            except Exception:
                pass
        # LLM 结果排序 + 子文档排序（表不存在则跳过）
        if self._table_exists(project_db, "community_llm_results"):
            try:
                project_db.execute("CREATE INDEX IF NOT EXISTS idx_llm_res_sort ON community_llm_results(task_id, edge_type, comm_lv, comm_id)")
            except Exception:
                pass
        if self._table_exists(project_db, "report_subdocs"):
            try:
                project_db.execute("CREATE INDEX IF NOT EXISTS idx_subdoc_sort ON report_subdocs(task_id, comm_id, created_at)")
            except Exception:
                pass

        # ── KB 版本化: source_files.version_from + 历史表 + 手动组件划分（兼容旧库）──
        try:
            cursor = project_db.execute("PRAGMA table_info(source_files)")
            sf_cols = {row[1] for row in cursor.fetchall()}
            if 'version_from' not in sf_cols:
                project_db.execute("ALTER TABLE source_files ADD COLUMN version_from TEXT")
        except Exception:
            pass
        try:
            project_db.execute("""
                CREATE TABLE IF NOT EXISTS source_files_history (
                    id TEXT PRIMARY KEY,
                    file_path TEXT NOT NULL,
                    file_name TEXT,
                    language TEXT,
                    size INTEGER DEFAULT 0,
                    content_hash TEXT,
                    hashcode TEXT,
                    parent_path TEXT,
                    mtime REAL,
                    version_from TEXT,
                    version_to TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            project_db.execute("CREATE INDEX IF NOT EXISTS idx_source_files_hist_range ON source_files_history(file_path, version_from, version_to)")
            project_db.execute("CREATE INDEX IF NOT EXISTS idx_source_files_hist_vfrom ON source_files_history(version_from)")
            project_db.execute("CREATE INDEX IF NOT EXISTS idx_source_files_hist_vto ON source_files_history(version_to)")
        except Exception:
            pass
        try:
            project_db.execute("""
                CREATE TABLE IF NOT EXISTS community_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL,
                    task_id TEXT DEFAULT '',
                    edge_type TEXT DEFAULT '',
                    comm_lv TEXT DEFAULT '',
                    comm_id TEXT DEFAULT '',
                    action TEXT NOT NULL,
                    payload TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now'))
                )
            """)
            project_db.execute("CREATE INDEX IF NOT EXISTS idx_community_overrides_project ON community_overrides(project_id, comm_id)")
        except Exception:
            pass

        project_db.conn.commit()

        # ===== 去重 + 防重复索引（graph_doc + community_hierarchy）=====
        if self._table_exists(project_db, "graph_doc"):
            try:
                project_db.execute("""
                    DELETE FROM graph_doc WHERE id NOT IN (
                        SELECT MIN(id) FROM graph_doc GROUP BY task_id, edge_type, comm_id
                    )
                """)
            except Exception:
                pass
            try:
                project_db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_doc_unique ON graph_doc(task_id, edge_type, comm_id)")
            except Exception:
                pass
        if self._table_exists(project_db, "community_hierarchy"):
            try:
                project_db.execute("""
                    DELETE FROM community_hierarchy WHERE id NOT IN (
                        SELECT MIN(id) FROM community_hierarchy GROUP BY task_id, edge_type, comm_lv, comm_id
                    )
                """)
            except Exception:
                pass
            try:
                project_db.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_comm_hier_unique ON community_hierarchy(task_id, edge_type, comm_lv, comm_id)")
            except Exception:
                pass
        project_db.conn.commit()

    def source_mirror_root(self) -> str:
        """源码镜像根目录（可配置）。

        优先读主库 app_config 的 `source_mirror_root`（设置页「通用 → 导入设置」），
        未配置/无效时回退默认 `{data_dir}/source-cache`。
        """
        try:
            row = self.main_db.fetchone(
                "SELECT value FROM app_config WHERE key = ?", ("source_mirror_root",))
            v = (row or {}).get("value") if row else ""
            v = (v or "").strip()
            if v:
                os.makedirs(v, exist_ok=True)
                return v
        except Exception as e:
            logger.warning(f"[mirror] read source_mirror_root failed: {e}")
        return os.path.join(self.data_dir, "source-cache")

    def source_cache_dir_for(self, project_id: str) -> str:
        """KB 项目源码镜像目录: {镜像根目录}/{project_id}/（含 worktree/ 与 baseline.git）。"""
        return os.path.join(self.source_mirror_root(), project_id)

    def ensure_history_table(self, project_db: SQLiteContext, table: str,
                             suffix: str = "_history"):
        """确保某活表的历史表存在（δ 归档用）。

        历史表 = 活表同构(CTAS, 无约束) + version_from + version_to。
        CTAS 不保留 PK/UNIQUE，允许同一 id 在不同版本区间重复出现。
        """
        hist_table = f"{table}{suffix}"
        try:
            project_db.execute(
                f"CREATE TABLE IF NOT EXISTS {hist_table} AS SELECT * FROM {table} WHERE 1=0"
            )
            cursor = project_db.execute(f"PRAGMA table_info({hist_table})")
            cols = {row[1] for row in cursor.fetchall()}
            if 'version_from' not in cols:
                project_db.execute(f'ALTER TABLE {hist_table} ADD COLUMN version_from TEXT')
            if 'version_to' not in cols:
                project_db.execute(f'ALTER TABLE {hist_table} ADD COLUMN version_to TEXT')
            project_db.execute(f"CREATE INDEX IF NOT EXISTS idx_{hist_table}_vfrom ON {hist_table}(version_from)")
            project_db.execute(f"CREATE INDEX IF NOT EXISTS idx_{hist_table}_vto ON {hist_table}(version_to)")
            project_db.conn.commit()
            return hist_table
        except Exception as e:
            logger.warning(f"[ensure_history_table] failed for {table}: {e}")
            return hist_table

    def _evict_idle_project_dbs(self):
        """关闭超过空闲超时的项目库连接"""
        now = time.time()
        idle_keys = [
            pid for pid, last in self._project_db_last_used.items()
            if pid in self._project_db_cache and now - last > self._project_db_idle_timeout
        ]
        for pid in idle_keys:
            try:
                self._project_db_cache[pid].close()
                del self._project_db_cache[pid]
                del self._project_db_last_used[pid]
            except Exception:
                pass

    def open_project_ro(self, project_id: str) -> sqlite3.Connection:
        """C3 WAL 直读合法化（MS7-W6）：以 mode=ro 打开项目库的只读连接。

        边界规则（CONV-04 §5 只读 WAL 共享档，三约束）：
        a) 只读——URI mode=ro，写事务由 SQLite 层拒绝；
        b) 仅限同机进程；
        c) 使用方必须在 manifest 注释声明共享哪些库。
        适用范围（裁决⑤收窄）：符号兜底路径（architect symbols.py native fallback）
        与 docs viewer 查询。返回裸 sqlite3.Connection（不经 LRU 缓存，调用方自管生命周期）。
        """
        db_path = self._project_db_path(project_id)
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=3000)
        conn.row_factory = sqlite3.Row
        return conn

    def get_project_db(self, project_id: str) -> SQLiteContext:
        """
        获取项目库连接（懒加载 + LRU 缓存 + 空闲超时剔除）
        超出容量时关闭最久未用的连接；超时未用自动关闭
        """
        # 先清理过期空闲连接
        self._evict_idle_project_dbs()

        # 如果已在缓存中，移到末尾（最近使用）
        if project_id in self._project_db_cache:
            self._project_db_cache.move_to_end(project_id)
            self._project_db_last_used[project_id] = time.time()
            return self._project_db_cache[project_id]

        # 如果超出容量，只打 warning 不强制关闭（防止误关其他协程正在用的连接）
        if len(self._project_db_cache) >= self._project_db_max:
            logger.warning(
                f"[get_project_db] project DB cache size {len(self._project_db_cache)} "
                f"exceeds limit {self._project_db_max}. Idle connections will be closed by "
                f"_evict_idle_project_dbs()."
            )

        # 检查项目库文件是否存在（中心路径，与源码目录无关）
        db_path = self._project_db_path(project_id)

        if not os.path.exists(db_path):
            # 自动创建
            project_db = self.init_project_db(project_id)
            self._migrate_project_db(project_db)
        else:
            label = f"project:{project_id}"
            self._write_queue.register_db(label, db_path)
            try:
                project_db = SQLiteContext(db_path, label=label,
                                           write_queue=self._write_queue)
            except Exception as e:
                logger.error(f"[get_project_db] failed to open {db_path}: {e}")
                raise
            self._migrate_project_db(project_db)

        # 加入缓存
        self._project_db_cache[project_id] = project_db
        self._project_db_last_used[project_id] = time.time()
        return project_db

    def close_project_db(self, project_id: str):
        """关闭项目库连接，从缓存移除"""
        if project_id in self._project_db_cache:
            self._project_db_cache[project_id].close()
            del self._project_db_cache[project_id]
        self._project_db_last_used.pop(project_id, None)

    def delete_project_db(self, project_id: str):
        """关闭连接 + 删除项目库文件（中心路径 data_dir/projects/<pid>/project.db）"""
        # Force checkpoint + switch off WAL mode to release file handles (required on Windows)
        if project_id in self._project_db_cache:
            try:
                db = self._project_db_cache[project_id]
                db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                db.execute("PRAGMA journal_mode=DELETE")
            except Exception:
                pass
        self.close_project_db(project_id)

        if sys.platform == 'win32':
            time.sleep(0.1)  # Windows needs a tick to release file handles

        def _remove_with_retry(path: str, max_retries: int = 3):
            for attempt in range(max_retries):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                    return
                except PermissionError:
                    if attempt < max_retries - 1:
                        time.sleep(0.2)

        db_path = self._project_db_path(project_id)
        # Remove WAL/SHM first (they may hold locks on Windows)
        for suffix in ['-wal', '-shm']:
            _remove_with_retry(db_path + suffix)
        _remove_with_retry(db_path)
        try:
            proj_dir = os.path.dirname(db_path)
            if os.path.isdir(proj_dir) and not os.listdir(proj_dir):
                os.rmdir(proj_dir)
        except Exception:
            pass

    def close_all(self):
        """关闭所有数据库连接"""
        self.main_db.close()
        self.knowledge_db.close()
        self.sessions_db.close()
        self.chat_db.close()
        for db in self._project_db_cache.values():
            db.close()
        self._project_db_cache.clear()
        self._write_queue.shutdown()
