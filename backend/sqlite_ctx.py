"""SQLite 上下文管理 - 多数据库架构 (主库/知识库/会话库/项目库)"""

import sqlite3
import json
import os
import hashlib
from collections import OrderedDict
from datetime import datetime
from typing import Optional


class SQLiteContext:
    """SQLite 数据库上下文"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._connect()

    def _connect(self):
        """建立数据库连接"""
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # WAL 模式提升并发性能（多窗口共享后端时多个连接同时读写）
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        # 多窗口并发安全设置
        self._conn.execute("PRAGMA busy_timeout=5000")  # 等待锁释放 5 秒
        self._conn.execute("PRAGMA synchronous=NORMAL")  # 平衡性能和安全
        self._conn.execute("PRAGMA cache_size=10000")  # 10MB 缓存

    @property
    def conn(self) -> sqlite3.Connection:
        if not self._conn:
            self._connect()
        return self._conn

    # ==================== 通用查询方法 ====================

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        """执行 SQL 并提交"""
        cursor = self.conn.execute(sql, params)
        self.conn.commit()
        return cursor

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        """查询所有结果"""
        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """查询单条结果"""
        cursor = self.conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

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

MAIN_DB_TABLES_SQL = """
    -- 项目表
    CREATE TABLE IF NOT EXISTS projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        root_path TEXT NOT NULL UNIQUE,
        language TEXT,
        file_count INTEGER DEFAULT 0,
        status TEXT DEFAULT 'synced' CHECK(status IN ('synced', 'syncing', 'error')),
        needs_resync INTEGER DEFAULT 0,
        has_file_changes INTEGER DEFAULT 0,
        is_sample INTEGER DEFAULT 0,
        last_sync TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    -- 分析任务表
    CREATE TABLE IF NOT EXISTS analysis_tasks (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('ast', 'call-chain', 'dependency', 'dataflow', 'full')),
        name TEXT NOT NULL,
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'running', 'done', 'error', 'cancelled', 'stopped')),
        progress INTEGER DEFAULT 0,
        total INTEGER DEFAULT 100,
        current INTEGER DEFAULT 0,
        error TEXT,
        result_data TEXT,
        favorite INTEGER DEFAULT 0,
        pinned INTEGER DEFAULT 0,
        tags TEXT,
        agent_id TEXT,
        scope TEXT,
        extensions TEXT,
        exclude_dirs TEXT,
        report_types TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_analysis_tasks_project ON analysis_tasks(project_id);
    CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks(status);

    -- 分析报告表
    CREATE TABLE IF NOT EXISTS analysis_reports (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL UNIQUE,
        ast_data TEXT,
        call_chain TEXT,
        dependencies TEXT,
        dataflow TEXT,
        summary TEXT,
        logs TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE
    );

    -- 模型配置表
    CREATE TABLE IF NOT EXISTS model_configs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        provider TEXT NOT NULL CHECK(provider IN ('ollama', 'openai', 'lm-studio', 'custom')),
        model TEXT NOT NULL,
        url TEXT NOT NULL,
        api_key TEXT DEFAULT '',
        type TEXT DEFAULT 'local' CHECK(type IN ('local', 'cloud')),
        status TEXT DEFAULT 'offline' CHECK(status IN ('offline', 'online', 'error')),
        is_default INTEGER DEFAULT 0,
        temperature REAL DEFAULT 0.7,
        max_tokens INTEGER DEFAULT 4096,
        timeout INTEGER DEFAULT 30000,
        extra_config TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    -- Agent 配置表
    CREATE TABLE IF NOT EXISTS agent_configs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('qwen-code', 'cline', 'opencode', 'custom')),
        path TEXT NOT NULL,
        args TEXT DEFAULT '',
        env TEXT,
        status TEXT DEFAULT 'not-configured' CHECK(status IN ('not-configured', 'configured', 'online', 'offline', 'error')),
        version TEXT,
        is_default INTEGER DEFAULT 0,
        timeout INTEGER DEFAULT 300000,
        extra_config TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    -- SKILL 配置表
    CREATE TABLE IF NOT EXISTS skill_configs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        description TEXT,
        category TEXT,
        enabled INTEGER DEFAULT 1,
        config TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    -- 任务-模型绑定表
    CREATE TABLE IF NOT EXISTS task_model_bindings (
        id TEXT PRIMARY KEY,
        task_type TEXT NOT NULL,
        model_id TEXT NOT NULL,
        priority INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (model_id) REFERENCES model_configs(id) ON DELETE CASCADE
    );

    -- 通用上下文存储 (key-value)
    CREATE TABLE IF NOT EXISTS context_store (
        key TEXT PRIMARY KEY,
        value TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
"""

KNOWLEDGE_DB_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS knowledge_docs (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        type TEXT DEFAULT 'document' CHECK(type IN ('document', 'snippet', 'note', 'spec')),
        description TEXT,
        content TEXT,
        project_id TEXT,
        tags TEXT,
        status TEXT DEFAULT 'draft' CHECK(status IN ('draft', 'published', 'archived')),
        favorite INTEGER DEFAULT 0,
        pinned INTEGER DEFAULT 0,
        embedding_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_knowledge_docs_project ON knowledge_docs(project_id);
    CREATE INDEX IF NOT EXISTS idx_knowledge_docs_status ON knowledge_docs(status);
"""

SESSIONS_DB_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS coder_sessions (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        mode TEXT DEFAULT 'chat' CHECK(mode IN ('chat', 'design')),
        status TEXT DEFAULT 'idle' CHECK(status IN ('idle', 'running', 'done', 'error')),
        spec_data TEXT,
        agent_id TEXT,
        task_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS chat_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
        content TEXT NOT NULL,
        timestamp TEXT DEFAULT (datetime('now')),
        metadata TEXT,
        FOREIGN KEY (session_id) REFERENCES coder_sessions(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON chat_messages(session_id);
"""

PROJECT_DB_TABLES_SQL = """
    -- 源码文件表 (相对路径 + MD5 哈希)
    CREATE TABLE IF NOT EXISTS source_files (
        id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL UNIQUE,
        language TEXT,
        size INTEGER DEFAULT 0,
        content_hash TEXT,
        parent_path TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_source_files_parent ON source_files(parent_path);

    -- AST 数据表 (仅保留最新)
    CREATE TABLE IF NOT EXISTS ast_data (
        id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL UNIQUE,
        ast_json TEXT,
        version INTEGER DEFAULT 1,
        parsed_at TEXT DEFAULT (datetime('now'))
    );

    -- 依赖关系表
    CREATE TABLE IF NOT EXISTS dependencies (
        id TEXT PRIMARY KEY,
        source_file TEXT NOT NULL,
        target_file TEXT NOT NULL,
        dep_type TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_deps_source ON dependencies(source_file);

    -- 调用链表
    CREATE TABLE IF NOT EXISTS call_chains (
        id TEXT PRIMARY KEY,
        caller_file TEXT NOT NULL,
        callee_file TEXT NOT NULL,
        caller_func TEXT,
        callee_func TEXT,
        line_number INTEGER,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_call_chains_caller ON call_chains(caller_file);

    -- 组件表
    CREATE TABLE IF NOT EXISTS components (
        id TEXT PRIMARY KEY,
        component_name TEXT NOT NULL,
        component_type TEXT,
        file_paths TEXT,
        description TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- AI QA 记录表
    CREATE TABLE IF NOT EXISTS ai_qa (
        id TEXT PRIMARY KEY,
        question TEXT NOT NULL,
        answer TEXT,
        context_files TEXT,
        session_id TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );

    -- 项目级配置表
    CREATE TABLE IF NOT EXISTS project_config (
        id TEXT PRIMARY KEY,
        key TEXT NOT NULL UNIQUE,
        value TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
"""


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
    多数据库管理器
    - 主库: topoone.db (项目信息 + 全局配置)
    - 知识库: knowledge.db
    - 会话库: sessions.db
    - 项目库: {project_id}.db (LRU 缓存, max=3)
    """

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = os.path.join(os.path.expanduser("~"), ".topoone")
        self.data_dir = data_dir
        os.makedirs(self.data_dir, exist_ok=True)

        # 初始化主库
        main_db_path = os.path.join(self.data_dir, "topoone.db")
        self.main_db = SQLiteContext(main_db_path)
        self._init_main_tables()

        # 初始化知识库
        knowledge_db_path = os.path.join(self.data_dir, "knowledge.db")
        self.knowledge_db = SQLiteContext(knowledge_db_path)
        self._init_knowledge_tables()

        # 初始化会话库
        sessions_db_path = os.path.join(self.data_dir, "sessions.db")
        self.sessions_db = SQLiteContext(sessions_db_path)
        self._init_sessions_tables()

        # 项目库 LRU 缓存 (max=3)
        self._project_db_cache: OrderedDict[str, SQLiteContext] = OrderedDict()
        self._project_db_max = 3

    def _init_main_tables(self):
        """初始化主库表"""
        self.main_db.conn.executescript(MAIN_DB_TABLES_SQL)
        self._migrate_main_tables()

    def _migrate_main_tables(self):
        """迁移主库表 - 添加新字段"""
        # 为已有数据库添加新字段
        columns_to_add = {
            "analysis_tasks": [
                ("scope", "TEXT"),
                ("extensions", "TEXT"),
                ("exclude_dirs", "TEXT"),
                ("report_types", "TEXT"),
            ],
            "analysis_reports": [
                ("logs", "TEXT"),
            ],
        }
        for table, columns in columns_to_add.items():
            for col_name, col_type in columns:
                try:
                    self.main_db.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
                except Exception:
                    pass  # 列已存在，忽略
        self.main_db.conn.commit()
        _init_default_skills(self.main_db)

    def _init_knowledge_tables(self):
        """初始化知识库表"""
        self.knowledge_db.conn.executescript(KNOWLEDGE_DB_TABLES_SQL)
        self.knowledge_db.conn.commit()

    def _init_sessions_tables(self):
        """初始化会话库表"""
        self.sessions_db.conn.executescript(SESSIONS_DB_TABLES_SQL)
        self.sessions_db.conn.commit()

    def init_project_db(self, project_id: str):
        """创建并初始化项目库"""
        db_path = os.path.join(self.data_dir, f"{project_id}.db")
        project_db = SQLiteContext(db_path)
        project_db.conn.executescript(PROJECT_DB_TABLES_SQL)
        project_db.conn.commit()
        return project_db

    def get_project_db(self, project_id: str) -> SQLiteContext:
        """
        获取项目库连接（懒加载 + LRU 缓存）
        超出容量时关闭最久未用的连接
        """
        # 如果已在缓存中，移到末尾（最近使用）
        if project_id in self._project_db_cache:
            self._project_db_cache.move_to_end(project_id)
            return self._project_db_cache[project_id]

        # 如果缓存已满，关闭最久未用的连接
        if len(self._project_db_cache) >= self._project_db_max:
            oldest_id, oldest_db = self._project_db_cache.popitem(last=False)
            oldest_db.close()

        # 检查项目库文件是否存在
        db_path = os.path.join(self.data_dir, f"{project_id}.db")
        if not os.path.exists(db_path):
            # 自动创建
            project_db = self.init_project_db(project_id)
        else:
            project_db = SQLiteContext(db_path)

        # 加入缓存
        self._project_db_cache[project_id] = project_db
        return project_db

    def close_project_db(self, project_id: str):
        """关闭项目库连接，从缓存移除"""
        if project_id in self._project_db_cache:
            self._project_db_cache[project_id].close()
            del self._project_db_cache[project_id]

    def delete_project_db(self, project_id: str):
        """关闭连接 + 删除项目库文件"""
        self.close_project_db(project_id)
        db_path = os.path.join(self.data_dir, f"{project_id}.db")
        if os.path.exists(db_path):
            os.remove(db_path)
        # 也删除 -wal 和 -shm 文件
        for suffix in ['-wal', '-shm']:
            wal_path = db_path + suffix
            if os.path.exists(wal_path):
                os.remove(wal_path)

    def compute_md5(self, file_path: str) -> str:
        """计算文件的 MD5 哈希"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()

    def close_all(self):
        """关闭所有数据库连接"""
        self.main_db.close()
        self.knowledge_db.close()
        self.sessions_db.close()
        for db in self._project_db_cache.values():
            db.close()
        self._project_db_cache.clear()
