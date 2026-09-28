"""PROJECT_DB_TABLES_SQL（MS5-V0 自 db/manager.py 外置；内容与原内联块逐字节一致）。

冻结契约：与 tests/ddl_golden.py 的 golden 快照全等（test_db_schema_parity.py）。
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
        version_from TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_source_files_parent ON source_files(parent_path);
    CREATE INDEX IF NOT EXISTS idx_source_files_lang ON source_files(language);
    CREATE INDEX IF NOT EXISTS idx_source_files_version_from ON source_files(version_from);

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
    -- base_node — DEPRECATED (v2 保留以兼容旧数据)
    -- ============================================

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
    -- graph_node — 符号节点 (任务级, v2 重设计)
    -- ============================================
    CREATE TABLE IF NOT EXISTS graph_node (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        kind TEXT NOT NULL,
        name TEXT NOT NULL,
        qualified_name TEXT NOT NULL DEFAULT '',
        file_path TEXT NOT NULL DEFAULT '',
        file_id TEXT DEFAULT '',
        language TEXT DEFAULT '',
        start_line INTEGER NOT NULL DEFAULT 0,
        start_col INTEGER NOT NULL DEFAULT 0,
        end_line INTEGER NOT NULL DEFAULT 0,
        end_col INTEGER NOT NULL DEFAULT 0,
        signature TEXT DEFAULT '',
        visibility TEXT DEFAULT '',
        is_exported INTEGER DEFAULT 0,
        is_async INTEGER DEFAULT 0,
        is_static INTEGER DEFAULT 0,
        docstring TEXT DEFAULT '',
        decorators TEXT DEFAULT '',
        type_parameters TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_graph_node_task ON graph_node(task_id);
    CREATE INDEX IF NOT EXISTS idx_graph_node_kind ON graph_node(task_id, kind);
    CREATE INDEX IF NOT EXISTS idx_graph_node_file ON graph_node(task_id, file_path);
    CREATE INDEX IF NOT EXISTS idx_graph_node_name ON graph_node(task_id, name);
    CREATE INDEX IF NOT EXISTS idx_graph_node_qname ON graph_node(task_id, qualified_name);
    CREATE INDEX IF NOT EXISTS idx_graph_node_id_task ON graph_node(id, task_id);

    -- ============================================
    -- graph_edge — 关系边 (任务级, v2 新增)
    -- ============================================
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
    );
    CREATE INDEX IF NOT EXISTS idx_graph_edge_task ON graph_edge(task_id);
    CREATE INDEX IF NOT EXISTS idx_graph_edge_source ON graph_edge(source_id);
    CREATE INDEX IF NOT EXISTS idx_graph_edge_target ON graph_edge(target_id);
    CREATE INDEX IF NOT EXISTS idx_graph_edge_kind ON graph_edge(task_id, kind);
    CREATE INDEX IF NOT EXISTS idx_graph_edge_task_kind_target ON graph_edge(task_id, kind, target_id);

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
        file_count INTEGER DEFAULT 0,
        edge_list TEXT,
        edge_count INTEGER DEFAULT 0,
        quality_score REAL,
        description TEXT,
        metadata TEXT DEFAULT '{}',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_graph_doc_task ON graph_doc(task_id);
    CREATE INDEX IF NOT EXISTS idx_graph_doc_type ON graph_doc(task_id, edge_type);
    CREATE INDEX IF NOT EXISTS idx_graph_doc_comm ON graph_doc(comm_id);
    CREATE INDEX IF NOT EXISTS idx_graph_doc_score ON graph_doc(task_id, edge_type, quality_score DESC);
    CREATE INDEX IF NOT EXISTS idx_graph_doc_join ON graph_doc(task_id, edge_type, comm_id);
    CREATE INDEX IF NOT EXISTS idx_graph_doc_parent ON graph_doc(task_id, edge_type, parent_comm_id);

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
        file_count INTEGER DEFAULT 0,
        edge_count INTEGER DEFAULT 0,
        quality_score REAL,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_comm_hier_task ON community_hierarchy(task_id);
    CREATE INDEX IF NOT EXISTS idx_comm_hier_type ON community_hierarchy(task_id, edge_type);
    CREATE INDEX IF NOT EXISTS idx_comm_hier_lv ON community_hierarchy(task_id, edge_type, comm_lv, comm_id);
    CREATE INDEX IF NOT EXISTS idx_comm_hier_parent ON community_hierarchy(task_id, edge_type, parent_comm_id);

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
    CREATE INDEX IF NOT EXISTS idx_subdoc_sort ON report_subdocs(task_id, comm_id, created_at);

    -- ============================================
    -- community_llm_results — 社区 LLM 分析结果 (任务级)
    -- ============================================
    CREATE TABLE IF NOT EXISTS community_llm_results (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id         TEXT    NOT NULL,
        edge_type       TEXT    NOT NULL,
        comm_lv         TEXT    NOT NULL,
        comm_id         TEXT    NOT NULL,
        name            TEXT,
        summary         TEXT,
        model_id        TEXT,
        template_id     TEXT,
        name_manual     TEXT,
        component_type  TEXT    DEFAULT 'community',
        status          TEXT    DEFAULT 'completed',
        -- 命名产物来源: detail=文件摘要详细通道 / fast-agent=快速命名通道
        source          TEXT    DEFAULT 'detail',
        created_at      TEXT    DEFAULT (datetime('now')),
        updated_at      TEXT    DEFAULT (datetime('now')),
        UNIQUE(task_id, edge_type, comm_lv, comm_id)
    );
    CREATE INDEX IF NOT EXISTS idx_llm_res_task ON community_llm_results(task_id);
    CREATE INDEX IF NOT EXISTS idx_llm_res_type ON community_llm_results(task_id, edge_type);
    CREATE INDEX IF NOT EXISTS idx_llm_res_sort ON community_llm_results(task_id, edge_type, comm_lv, comm_id);

    -- Agent 任务历史记录
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
    );
    CREATE INDEX IF NOT EXISTS idx_ath_task ON agent_task_history(task_id, created_at DESC);

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


    -- ============================================
    -- ai_sessions — AI 编码会话追踪（预留）
    -- ============================================
    CREATE TABLE IF NOT EXISTS ai_sessions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        task_id TEXT,
        tag TEXT DEFAULT '',
        started_at TEXT NOT NULL,
        ended_at TEXT,
        status TEXT DEFAULT 'active',
        file_snapshot TEXT,
        summary_markdown TEXT,
        quality_score REAL,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_ai_sessions_project ON ai_sessions(project_id, started_at DESC);

    CREATE TABLE IF NOT EXISTS ai_session_changes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        file_path TEXT NOT NULL,
        change_type TEXT NOT NULL,
        symbol_name TEXT,
        symbol_kind TEXT,
        old_signature TEXT,
        new_signature TEXT,
        old_content TEXT,
        new_content TEXT,
        FOREIGN KEY (session_id) REFERENCES ai_sessions(id)
    );
    CREATE INDEX IF NOT EXISTS idx_ai_changes_session ON ai_session_changes(session_id);

    CREATE TABLE IF NOT EXISTS ai_session_issues (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT NOT NULL,
        file_path TEXT,
        line_number INTEGER,
        issue_type TEXT NOT NULL,
        severity TEXT NOT NULL,
        title TEXT NOT NULL,
        description TEXT,
        suggestion TEXT,
        FOREIGN KEY (session_id) REFERENCES ai_sessions(id)
    );
    CREATE INDEX IF NOT EXISTS idx_ai_issues_session ON ai_session_issues(session_id, severity);

    -- ============================================
    -- arch_snapshots — 架构快照（手动触发）
    -- ============================================
    CREATE TABLE IF NOT EXISTS arch_snapshots (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        alias TEXT,
        project_id TEXT NOT NULL,
        timestamp TEXT NOT NULL,
        git_branch TEXT,
        git_commit TEXT,
        git_tag TEXT,
        community_count INTEGER,
        total_files INTEGER,
        exported INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_arch_snap_task ON arch_snapshots(task_id);

    -- ============================================
    -- arch_snapshot_communities — 快照中的社区 + 文件列表
    -- ============================================
    CREATE TABLE IF NOT EXISTS arch_snapshot_communities (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        snapshot_id TEXT NOT NULL,
        community_id TEXT NOT NULL,
        edge_type TEXT NOT NULL,
        level TEXT NOT NULL,
        name TEXT,
        summary TEXT,
        mermaid TEXT,
        plantuml TEXT,
        node_count INTEGER,
        file_count INTEGER,
        quality_score REAL,
        node_list TEXT,
        file_list TEXT,
        edge_list TEXT,
        FOREIGN KEY (snapshot_id) REFERENCES arch_snapshots(id) ON DELETE CASCADE,
        UNIQUE(snapshot_id, community_id)
    );
    CREATE INDEX IF NOT EXISTS idx_arch_scomm_snap ON arch_snapshot_communities(snapshot_id);

    -- ============================================
    -- graph_node_positions — 图节点拖拽位置
    -- ============================================
    CREATE TABLE IF NOT EXISTS graph_node_positions (
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
    );
    CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_pos_active_unique
        ON graph_node_positions(task_id, edge_type, drill_key, layout_type, node_id)
        WHERE snapshot_id IS NULL;
    CREATE UNIQUE INDEX IF NOT EXISTS idx_graph_pos_snap_unique
        ON graph_node_positions(task_id, edge_type, drill_key, snapshot_id, layout_type, node_id)
        WHERE snapshot_id IS NOT NULL;

    -- ============================================
    -- source_files_history — 过期源码文件行 (δ 归档)
    -- 活表 = 最新版本；被覆盖/删除的行移入此处，带 version_from/version_to 区间
    -- 重建版本 V: 活表(version_from<=V) UNION 历史(version_from<=V AND version_to>V)
    -- ============================================
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
    );
    CREATE INDEX IF NOT EXISTS idx_source_files_hist_range ON source_files_history(file_path, version_from, version_to);
    CREATE INDEX IF NOT EXISTS idx_source_files_hist_vfrom ON source_files_history(version_from);
    CREATE INDEX IF NOT EXISTS idx_source_files_hist_vto ON source_files_history(version_to);

    -- ============================================
    -- community_overrides — 手动组件划分/修改（预留）
    -- 优先级高于自动聚类；增量更新不覆盖用户手动划分。
    -- action: 'rename' | 'merge' | 'split' | 'reassign' | 'freeze'
    -- ============================================
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
    );
    CREATE INDEX IF NOT EXISTS idx_community_overrides_project ON community_overrides(project_id, comm_id);
"""
