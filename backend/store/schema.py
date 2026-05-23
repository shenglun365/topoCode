"""
SQLite 建表 DDL

- init_main_schema: 初始化主库表结构
- init_project_schema: 初始化项目库表结构
- migrate_main_schema: 主库迁移（添加新字段）
"""


# ==================== 主库 DDL ====================
MAIN_SCHEMA_SQL = """
-- ============================================
-- analysis_tasks — 任务配置表
-- ============================================
CREATE TABLE IF NOT EXISTS analysis_tasks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('ast', 'call-chain', 'dependency', 'dataflow', 'full')),
    name TEXT NOT NULL,
    status TEXT DEFAULT 'pending'
        CHECK(status IN ('pending', 'modified', 'running', 'done', 'error', 'cancelled', 'stopped')),
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
    updated_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_analysis_tasks_project ON analysis_tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_analysis_tasks_status ON analysis_tasks(status);

-- ============================================
-- analysis_task_runs — 运行记录表
-- ============================================
CREATE TABLE IF NOT EXISTS analysis_task_runs (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    run_number INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('running', 'done', 'error', 'stopped')),
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

-- ============================================
-- analysis_reports — 分析报告表
-- ============================================
CREATE TABLE IF NOT EXISTS analysis_reports (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    ast_data TEXT,
    call_chain TEXT,
    dependencies TEXT,
    dataflow TEXT,
    logs TEXT,
    summary TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (task_id) REFERENCES analysis_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (run_id) REFERENCES analysis_task_runs(id)
);
CREATE INDEX IF NOT EXISTS idx_reports_task ON analysis_reports(task_id);
CREATE INDEX IF NOT EXISTS idx_reports_run ON analysis_reports(run_id);

-- ============================================
-- task_config_history — 配置历史表
-- ============================================
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
"""

# 主库迁移 SQL — 添加新字段（向后兼容）
MAIN_MIGRATION_SQL = """
-- 为 analysis_reports 添加新字段（如果不存在）
ALTER TABLE analysis_reports ADD COLUMN total_ast_nodes INTEGER DEFAULT 0;
ALTER TABLE analysis_reports ADD COLUMN total_symbols INTEGER DEFAULT 0;
ALTER TABLE analysis_reports ADD COLUMN total_call_edges INTEGER DEFAULT 0;
ALTER TABLE analysis_reports ADD COLUMN total_dep_edges INTEGER DEFAULT 0;
ALTER TABLE analysis_reports ADD COLUMN total_communities INTEGER DEFAULT 0;
ALTER TABLE analysis_reports ADD COLUMN language_stats TEXT;
ALTER TABLE analysis_reports ADD COLUMN files_processed INTEGER DEFAULT 0;
ALTER TABLE analysis_reports ADD COLUMN skipped_files INTEGER DEFAULT 0;
ALTER TABLE analysis_reports ADD COLUMN best_call_community_id TEXT;
ALTER TABLE analysis_reports ADD COLUMN best_dep_community_id TEXT;
ALTER TABLE analysis_reports ADD COLUMN alias TEXT;
ALTER TABLE analysis_reports ADD COLUMN node_style_map TEXT;
"""


# ==================== 项目库 DDL ====================
PROJECT_SCHEMA_SQL = """
-- ============================================
-- source_files — 源文件列表 (外部填充)
-- id 为 TEXT 类型，与现有系统兼容
-- ============================================
CREATE TABLE IF NOT EXISTS source_files (
    id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    file_name TEXT NOT NULL,
    language TEXT,
    size INTEGER,
    hashcode TEXT,
    mtime REAL
);
CREATE INDEX IF NOT EXISTS idx_source_files_lang ON source_files(language);
CREATE INDEX IF NOT EXISTS idx_source_files_path ON source_files(file_path);

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
-- graph_node — 符号 + 调用边 + 依赖边 (任务级)
-- file_id 为 TEXT 类型
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
"""


def init_main_schema(db):
    """初始化主库表结构"""
    db.conn.executescript(MAIN_SCHEMA_SQL)
    # auto-committed by execute()


def migrate_main_schema(db):
    """主库迁移 — 添加新字段（忽略已存在字段的错误）"""
    conn = db.conn
    for sql in MAIN_MIGRATION_SQL.strip().split(";"):
        sql = sql.strip()
        if not sql:
            continue
        try:
            conn.execute(sql)
        except Exception:
            pass  # 字段已存在，忽略
    # auto-committed by execute()


def init_project_schema(db):
    """初始化项目库表结构"""
    db.conn.executescript(PROJECT_SCHEMA_SQL)

    # 迁移: 为 community_hierarchy 添加 edge_count 列（如不存在则忽略）
    cursor = db.conn.execute("PRAGMA table_info(community_hierarchy)")
    cols = {row[1] for row in cursor.fetchall()}
    if 'edge_count' not in cols:
        db.conn.execute("ALTER TABLE community_hierarchy ADD COLUMN edge_count INTEGER DEFAULT 0")

    # 迁移: 新建 community_llm_results 表（如已存在则忽略）
    db.conn.execute("""
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
    db.conn.commit()
