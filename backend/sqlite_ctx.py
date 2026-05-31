"""SQLite 上下文管理 - 多数据库架构 (主库/知识库/会话库/项目库)"""

import sqlite3
import json
import os
import hashlib
import threading
from collections import OrderedDict
from datetime import datetime
from typing import Optional


class SQLiteContext:
    """SQLite 数据库上下文（线程安全）"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = threading.Lock()
        self._connect()

    def _connect(self):
        """建立数据库连接（线程安全）"""
        with self._lock:
            if self._conn is None:
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
        """执行 SQL — 写操作自动提交，读操作不提交"""
        cursor = self.conn.execute(sql, params)
        # 仅对写操作提交事务，避免 SELECT 等读操作触发无意义的 commit
        upper_sql = sql.strip().upper()
        if upper_sql.startswith(('INSERT', 'UPDATE', 'DELETE', 'ALTER', 'CREATE', 'DROP', 'REPLACE')):
            self.conn.commit()
        elif upper_sql == 'COMMIT':
            self.conn.commit()
        return cursor

    def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        """查询所有结果（不提交）"""
        cursor = self.conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        """查询单条结果（不提交）"""
        cursor = self.conn.execute(sql, params)
        row = cursor.fetchone()
        return dict(row) if row else None

    def executemany(self, sql: str, params_list):
        """批量执行 SQL（用于批量插入）"""
        self.conn.executemany(sql, params_list)

    def commit(self):
        """提交事务（用于 executemany 等不自动提交的场景）"""
        try:
            self.conn.commit()
        except sqlite3.OperationalError as e:
            if "cannot commit" not in str(e):
                raise

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
        "group" TEXT DEFAULT '',
        favorite INTEGER DEFAULT 0,
        pinned INTEGER DEFAULT 0,
        sort_order INTEGER DEFAULT 0,
        last_sync TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    -- 分析任务表 (配置持久化)
    CREATE TABLE IF NOT EXISTS analysis_tasks (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        type TEXT NOT NULL CHECK(type IN ('ast', 'call-chain', 'dependency', 'dataflow', 'full')),
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
        agent_id TEXT,
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
    CREATE INDEX IF NOT EXISTS idx_analysis_tasks_project ON analysis_tasks(project_id);
    CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks(status);

    -- 任务配置变更历史
    CREATE TABLE IF NOT EXISTS task_config_history (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        config_version INTEGER NOT NULL,
        name TEXT,
        scope TEXT,
        scopes TEXT,
        extensions TEXT,
        exclude_dirs TEXT,
        report_types TEXT,
        pattern_type TEXT,
        pattern TEXT,
        changed_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_config_history_task ON task_config_history(task_id);

    -- 分析任务运行记录 (一次运行一条)
    CREATE TABLE IF NOT EXISTS analysis_task_runs (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        run_number INTEGER NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('running', 'done', 'error', 'cancelled')),
        progress INTEGER DEFAULT 0,
        total INTEGER DEFAULT 100,
        current INTEGER DEFAULT 0,
        error TEXT,
        started_at TEXT DEFAULT (datetime('now')),
        finished_at TEXT,
        duration_ms INTEGER,
        snapshot_scope TEXT,
        snapshot_scopes TEXT,
        snapshot_extensions TEXT,
        snapshot_exclude_dirs TEXT,
        snapshot_report_types TEXT,
        FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_task_runs_task ON analysis_task_runs(task_id);
    CREATE INDEX IF NOT EXISTS idx_task_runs_status ON analysis_task_runs(status);

    -- 分析报告表 (关联到运行记录)
    CREATE TABLE IF NOT EXISTS analysis_reports (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        run_id TEXT,
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

    -- LLM Prompt 模板表
    CREATE TABLE IF NOT EXISTS llm_prompt_templates (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        mode TEXT NOT NULL CHECK(mode IN ('chat', 'tools', 'structured')),
        module_type TEXT CHECK(module_type IN ('project_resource', 'project_analysis', 'knowledge_base', 'ai_assistant')),
        category TEXT DEFAULT 'general',
        is_builtin INTEGER DEFAULT 0,
        system_prompt TEXT,
        user_prompt_template TEXT,
        tools_json TEXT,
        tool_strategy TEXT DEFAULT 'auto',
        output_schema_json TEXT,
        output_example TEXT,
        variables_json TEXT,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_llm_templates_mode ON llm_prompt_templates(mode);
    CREATE INDEX IF NOT EXISTS idx_llm_templates_module ON llm_prompt_templates(module_type);

    -- LLM 调用日志表
    CREATE TABLE IF NOT EXISTS llm_call_logs (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        request_id TEXT NOT NULL,
        model_id TEXT,
        provider TEXT,
        model_name TEXT,
        mode TEXT NOT NULL,
        template_id TEXT,
        messages_json TEXT,
        response_content TEXT,
        tool_calls_json TEXT,
        token_prompt INTEGER,
        token_completion INTEGER,
        token_total INTEGER,
        latency_ms INTEGER,
        status TEXT CHECK(status IN ('success', 'error', 'aborted')),
        error_message TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_llm_logs_session ON llm_call_logs(session_id);
    CREATE INDEX IF NOT EXISTS idx_llm_logs_created ON llm_call_logs(created_at);

    -- 报告/分析交互日志（记录每次 LLM 调用的上下文、pipeline 步骤等）
    CREATE TABLE IF NOT EXISTS report_interaction_log (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        request_id TEXT,
        provider TEXT,
        model_name TEXT,
        mode TEXT,
        status TEXT,
        latency_ms INTEGER,
        meta_json TEXT,          -- 包含 template_id, pipeline_step, community_id 等上下文
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_report_log_created ON report_interaction_log(created_at);
    CREATE INDEX IF NOT EXISTS idx_report_log_request ON report_interaction_log(request_id);

    -- 代码索引消息 (报告 tab 右侧面板对话历史)
    CREATE TABLE IF NOT EXISTS code_index_messages (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        message_type TEXT NOT NULL CHECK(message_type IN ('node', 'edge', 'community', 'ai-explain')),
        content TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_code_index_project ON code_index_messages(project_id);
    CREATE INDEX IF NOT EXISTS idx_code_index_task ON code_index_messages(task_id);

    -- 用户全局节点样式设置
    CREATE TABLE IF NOT EXISTS user_node_styles (
        id TEXT PRIMARY KEY,
        symbol_type TEXT NOT NULL,
        shape TEXT NOT NULL,
        fill_color TEXT NOT NULL,
        stroke_color TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_user_node_styles_type ON user_node_styles(symbol_type);

    -- 分组树（支持父子层级，最多4层 depth 0-3）
    CREATE TABLE IF NOT EXISTS project_groups (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        parent_id TEXT DEFAULT NULL REFERENCES project_groups(id) ON DELETE CASCADE,
        depth INTEGER DEFAULT 0 CHECK(depth >= 0 AND depth <= 3),
        sort_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_project_groups_parent ON project_groups(parent_id);

    -- 项目-分组 M:N 关联
    CREATE TABLE IF NOT EXISTS project_group_map (
        project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
        group_id TEXT NOT NULL REFERENCES project_groups(id) ON DELETE CASCADE,
        PRIMARY KEY (project_id, group_id)
    );
    CREATE INDEX IF NOT EXISTS idx_project_group_map_group ON project_group_map(group_id);
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
    -- 废弃旧表 (v1 coder 会话)
    DROP TABLE IF EXISTS coder_sessions;
    DROP TABLE IF EXISTS chat_messages;

    -- 统一 LLM 会话表 (v2 — 支持 4 模块类型)
    CREATE TABLE IF NOT EXISTS llm_sessions (
        id TEXT PRIMARY KEY,
        module_type TEXT NOT NULL CHECK(module_type IN (
            'project_resource',   -- 项目资源：源码→伪码解析
            'project_analysis',   -- 项目分析：社区图/调用图/数据流图分析
            'knowledge_base',     -- 知识库：文档梳理/解析/问答
            'ai_assistant'        -- AI 助手：Agent 式会话交互
        )),
        project_id TEXT,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived')),
        metadata TEXT,            -- JSON: 模块专用扩展字段
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_llm_sessions_module ON llm_sessions(module_type);
    CREATE INDEX IF NOT EXISTS idx_llm_sessions_project ON llm_sessions(project_id);

    -- 统一 LLM 消息表
    CREATE TABLE IF NOT EXISTS llm_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
        content TEXT NOT NULL,
        token_count INTEGER,
        metadata TEXT,            -- JSON: tool_call / tool_result / structured_output 等
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (session_id) REFERENCES llm_sessions(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_llm_messages_session ON llm_messages(session_id);

    -- 分析报告会话表 (项目/任务/报告 三级隔离)
    CREATE TABLE IF NOT EXISTS analysis_sessions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        report_id TEXT,
        session_id TEXT NOT NULL,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (session_id) REFERENCES llm_sessions(id) ON DELETE CASCADE,
        FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE,
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_analysis_sessions_project ON analysis_sessions(project_id);
    CREATE INDEX IF NOT EXISTS idx_analysis_sessions_task ON analysis_sessions(task_id);
    CREATE INDEX IF NOT EXISTS idx_analysis_sessions_report ON analysis_sessions(report_id);
"""

PROJECT_DB_TABLES_SQL = """
    -- 源码文件表 (相对路径 + MD5 哈希)
    CREATE TABLE IF NOT EXISTS source_files (
        id TEXT PRIMARY KEY,
        file_path TEXT NOT NULL UNIQUE,
        file_name TEXT,
        language TEXT,
        size INTEGER DEFAULT 0,
        content_hash TEXT,
        hashcode TEXT,
        parent_path TEXT,
        mtime REAL,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_source_files_parent ON source_files(parent_path);
    CREATE INDEX IF NOT EXISTS idx_source_files_lang ON source_files(language);

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

    -- ============================================
    -- base_node — AST 节点 (项目级通用)
    -- file_id 为 TEXT 类型，引用 source_files.id
    -- ============================================
    CREATE TABLE IF NOT EXISTS base_node (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_id TEXT NOT NULL,
        node_id TEXT NOT NULL,
        scope_node_id TEXT,
        def_node_id TEXT,
        type TEXT NOT NULL,
        name TEXT,
        op TEXT,
        refs TEXT,
        start TEXT NOT NULL,
        end TEXT NOT NULL,
        content_size INTEGER,
        FOREIGN KEY (file_id) REFERENCES source_files(id)
    );
    CREATE INDEX IF NOT EXISTS idx_base_node_file ON base_node(file_id);
    CREATE INDEX IF NOT EXISTS idx_base_node_type ON base_node(type);
    CREATE INDEX IF NOT EXISTS idx_base_node_name ON base_node(name);

    -- ============================================
    -- file_summaries — 文件摘要缓存 (项目级)
    -- ============================================
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
    CREATE INDEX IF NOT EXISTS idx_file_summaries_project ON file_summaries(project_id);
    CREATE INDEX IF NOT EXISTS idx_file_summaries_file ON file_summaries(project_id, file_path);

    -- ============================================
    -- graph_node — 符号 + 调用边 + 依赖边 (任务级)
    -- ============================================
    CREATE TABLE IF NOT EXISTS graph_node (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        symbol_node_type TEXT NOT NULL,
        file_id TEXT,
        func_name TEXT,
        class_name TEXT,
        macro_name TEXT,
        method_name TEXT,
        caller_file_id TEXT,
        caller_func_name TEXT,
        caller_node_id TEXT,
        callee_name TEXT,
        callee_file_id TEXT,
        callee_node_id TEXT,
        callee_type TEXT,
        call_site_node_id TEXT,
        call_site_file_id TEXT,
        include_path TEXT,
        is_system INTEGER DEFAULT 0,
        extra TEXT,
        FOREIGN KEY (file_id) REFERENCES source_files(id)
    );
    CREATE INDEX IF NOT EXISTS idx_graph_task ON graph_node(task_id);
    CREATE INDEX IF NOT EXISTS idx_graph_type ON graph_node(symbol_node_type);
    CREATE INDEX IF NOT EXISTS idx_graph_caller ON graph_node(task_id, caller_file_id);
    CREATE INDEX IF NOT EXISTS idx_graph_callee ON graph_node(callee_name);

    -- ============================================
    -- graph_doc — 社区分析结果 (任务级，分层)
    -- ============================================
    CREATE TABLE IF NOT EXISTS graph_doc (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        comm_lv TEXT NOT NULL,
        parent_comm_id TEXT,
        comm_id TEXT NOT NULL,
        node_list TEXT NOT NULL,
        node_count INTEGER NOT NULL,
        edge_list TEXT,
        edge_count INTEGER DEFAULT 0,
        quality_score REAL,
        description TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_graph_doc_task ON graph_doc(task_id);
    CREATE INDEX IF NOT EXISTS idx_graph_doc_type ON graph_doc(task_id, edge_type);
    CREATE INDEX IF NOT EXISTS idx_graph_doc_comm ON graph_doc(comm_id);
    CREATE INDEX IF NOT EXISTS idx_graph_doc_score ON graph_doc(task_id, edge_type, quality_score DESC);

    -- ============================================
    -- community_hierarchy — 社区层级元数据 (任务级)
    -- ============================================
    CREATE TABLE IF NOT EXISTS community_hierarchy (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        comm_lv TEXT NOT NULL,
        comm_id TEXT NOT NULL,
        parent_comm_id TEXT,
        node_count INTEGER,
        edge_count INTEGER DEFAULT 0,
        quality_score REAL,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_comm_hier_task ON community_hierarchy(task_id);
    CREATE INDEX IF NOT EXISTS idx_comm_hier_type ON community_hierarchy(task_id, edge_type);

    -- ============================================
    -- report_subdocs — 分析报告子文档 (任务级)
    -- ============================================
    CREATE TABLE IF NOT EXISTS report_subdocs (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        comm_id TEXT,
        title TEXT NOT NULL,
        content TEXT NOT NULL,
        template_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_subdoc_task ON report_subdocs(task_id);
    CREATE INDEX IF NOT EXISTS idx_subdoc_comm ON report_subdocs(comm_id);

    -- ============================================
    -- community_llm_results — 社区 LLM 分析结果 (任务级)
    -- ============================================
    CREATE TABLE IF NOT EXISTS community_llm_results (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id     TEXT    NOT NULL,
        edge_type   TEXT    NOT NULL,
        comm_lv     TEXT    NOT NULL,
        comm_id     TEXT    NOT NULL,
        name        TEXT,
        summary     TEXT,
        mermaid     TEXT,
        plantuml    TEXT,
        model_id    TEXT,
        template_id TEXT,
        name_manual TEXT,
        created_at  TEXT DEFAULT (datetime('now')),
        updated_at  TEXT DEFAULT (datetime('now')),
        UNIQUE(task_id, edge_type, comm_lv, comm_id)
    );
    CREATE INDEX IF NOT EXISTS idx_llm_res_task ON community_llm_results(task_id);
    CREATE INDEX IF NOT EXISTS idx_llm_res_type ON community_llm_results(task_id, edge_type);

    -- ============================================
    -- model_daily_usage — 模型每日用量统计
    -- ============================================
    CREATE TABLE IF NOT EXISTS model_daily_usage (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        model_id         TEXT    NOT NULL REFERENCES model_configs(id) ON DELETE CASCADE,
        date             TEXT    NOT NULL,
        request_count    INTEGER DEFAULT 0,
        prompt_tokens    INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        total_tokens     INTEGER DEFAULT 0,
        created_at       TEXT DEFAULT (datetime('now')),
        updated_at       TEXT DEFAULT (datetime('now')),
        UNIQUE(model_id, date)
    );
    CREATE INDEX IF NOT EXISTS idx_mdu_model ON model_daily_usage(model_id);
    CREATE INDEX IF NOT EXISTS idx_mdu_date  ON model_daily_usage(date);
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
            ],
            "task_config_history": [
                ("scopes", "TEXT"),
                ("pattern_type", "TEXT"),
                ("pattern", "TEXT"),
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
            "analysis_tasks_misc": [  # 通过 analysis_tasks 表执行
            ],
            "projects": [
                ("group", "TEXT DEFAULT ''"),
                ("favorite", "INTEGER DEFAULT 0"),
                ("pinned", "INTEGER DEFAULT 0"),
                ("sort_order", "INTEGER DEFAULT 0"),
                ("summary", "TEXT DEFAULT ''"),
                ("summary_generated_at", "TEXT"),
            ],
        }
        for table, columns in columns_to_add.items():
            for col_name, col_type in columns:
                try:
                    self.main_db.execute(f'ALTER TABLE {table} ADD COLUMN "{col_name}" {col_type}')
                except Exception:
                    pass  # 列已存在，忽略

        # 迁移: 创建新表（project_groups + project_group_map）
        self.main_db.conn.executescript("""
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

    def _migrate_project_db(self, project_db: SQLiteContext):
        """迁移项目库表 - 添加新字段和新表"""
        # 为 source_files 添加新字段
        columns_to_add = [
            ("file_name", "TEXT"),
            ("hashcode", "TEXT"),
            ("mtime", "REAL"),
        ]
        for col_name, col_type in columns_to_add:
            try:
                project_db.execute(f'ALTER TABLE source_files ADD COLUMN "{col_name}" {col_type}')
            except Exception:
                pass  # 列已存在，忽略

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
                    mermaid     TEXT,
                    plantuml    TEXT,
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

        project_db.conn.commit()

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
            self._migrate_project_db(project_db)
        else:
            project_db = SQLiteContext(db_path)
            self._migrate_project_db(project_db)

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
