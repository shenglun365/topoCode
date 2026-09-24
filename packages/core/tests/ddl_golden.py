"""DDL golden 快照（pre-MS5 提取, MS5-V0 冻结）。

冻结契约：db/schema/* 五常量与本文件对应 golden 逐字节全等（test_db_schema_parity.py）。
修改 DDL 的正确流程：改 schema/*.py → 同步本 golden → 迁移块评审。
"""

GOLDEN_MAIN_DB_TABLES_SQL = MAIN_DB_TABLES_SQL = """
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
        import_mode TEXT DEFAULT 'static' CHECK(import_mode IN ('static', 'git-local', 'git-remote')),
        remote_url TEXT DEFAULT '',
        local_repo_path TEXT DEFAULT '',
        source_cache_dir TEXT DEFAULT '',
        current_version_id TEXT DEFAULT '',
        db_size_bytes INTEGER DEFAULT 0,
        source_size_bytes INTEGER DEFAULT 0,
        storage_checked_at TEXT,
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
    CREATE INDEX IF NOT EXISTS idx_analysis_tasks_created ON analysis_tasks(created_at);

    -- 基线视图：项目对外唯一生效视图（外部调用方零任务感知；任务显式挂载才对外可见）
    CREATE TABLE IF NOT EXISTS project_views (
        project_id TEXT PRIMARY KEY,
        version INTEGER NOT NULL DEFAULT 1,
        baseline_version_id TEXT DEFAULT '',
        overlap_warned INTEGER NOT NULL DEFAULT 0,
        published_at TEXT,
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE TABLE IF NOT EXISTS view_mounts (
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL,
        mounted_files INTEGER NOT NULL DEFAULT 0,
        mounted_at TEXT DEFAULT (datetime('now')),
        PRIMARY KEY (project_id, task_id)
    );

    -- 基线视图变更记录(挂载/卸载审计；任务名为操作时快照，现状经 LEFT JOIN 判定)
    CREATE TABLE IF NOT EXISTS view_change_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        action TEXT NOT NULL,
        task_id TEXT NOT NULL,
        task_name TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_view_log ON view_change_log(project_id, id);

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
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    -- Agent 配置表
    CREATE TABLE IF NOT EXISTS agent_configs (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        type TEXT NOT NULL DEFAULT 'generic' CHECK(type IN ('qwen-code', 'cline', 'opencode', 'custom', 'generic')),
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

    -- agent_executions — 外部 Agent 执行记录（与 agent_configs 关联）
    CREATE TABLE IF NOT EXISTS agent_executions (
        id TEXT PRIMARY KEY,
        agent_config_id TEXT NOT NULL,
        task_id TEXT,
        status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued', 'running', 'completed', 'failed', 'cancelled', 'timed_out')),
        args TEXT NOT NULL DEFAULT '',
        env TEXT,
        command TEXT,
        stdout_path TEXT,
        stderr_path TEXT,
        exit_code INTEGER,
        error TEXT,
        progress REAL DEFAULT 0,
        meta TEXT,
        started_at TEXT,
        finished_at TEXT,
        duration_ms INTEGER,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (agent_config_id) REFERENCES agent_configs(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_agent_exec_agent ON agent_executions(agent_config_id);
    CREATE INDEX IF NOT EXISTS idx_agent_exec_task ON agent_executions(task_id);
    CREATE INDEX IF NOT EXISTS idx_agent_exec_status ON agent_executions(status);

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

    -- 应用配置表 (key-value, 用于导入过滤等系统级配置)
    CREATE TABLE IF NOT EXISTS app_config (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL,
        updated_at TEXT DEFAULT (datetime('now'))
    );


    -- ============================================
    -- agent_instructions — 用户自定义 Agent 指令（预留）
    -- ============================================
    CREATE TABLE IF NOT EXISTS agent_instructions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        text TEXT NOT NULL,
        scope TEXT DEFAULT 'all',
        priority TEXT DEFAULT 'append',
        enabled INTEGER DEFAULT 1,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    -- ============================================
    -- project_git_info — 项目 Git 元信息
    -- ============================================
    CREATE TABLE IF NOT EXISTS project_git_info (
        project_id TEXT PRIMARY KEY,
        remote_url TEXT,
        current_branch TEXT,
        current_commit TEXT,
        latest_tag TEXT,
        tags TEXT,
        branches TEXT,
        recent_commits TEXT,
        detected_at TEXT,
        manually_edited INTEGER DEFAULT 0,
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    );

    -- ============================================
    -- doc_project_map — doc_id → project_id 映射（加速文档查找，避免遍历所有项目库）
    -- ============================================
    CREATE TABLE IF NOT EXISTS doc_project_map (
        doc_id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        task_id TEXT NOT NULL
    );

    -- ============================================
    -- project_versions — KB 版本基线注册表（只向前，不向后）
    -- 每个 KB 更新产生一个新的基线版本；对比仅在基线之间进行。
    -- ============================================
    CREATE TABLE IF NOT EXISTS project_versions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        parent_version_id TEXT,
        label TEXT DEFAULT '',
        branch TEXT DEFAULT '',
        head TEXT DEFAULT '',
        change_type TEXT DEFAULT 'minor' CHECK(change_type IN ('minor', 'major')),
        file_count INTEGER DEFAULT 0,
        added_count INTEGER DEFAULT 0,
        modified_count INTEGER DEFAULT 0,
        deleted_count INTEGER DEFAULT 0,
        is_baseline INTEGER DEFAULT 0,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_project_versions_project ON project_versions(project_id, created_at DESC);

    -- ============================================
    -- project_version_files — 版本间文件级 delta (A/M/D)
    -- ============================================
    CREATE TABLE IF NOT EXISTS project_version_files (
        id TEXT PRIMARY KEY,
        version_id TEXT NOT NULL,
        project_id TEXT NOT NULL,
        change_type TEXT NOT NULL CHECK(change_type IN ('A', 'M', 'D')),
        file_path TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (version_id) REFERENCES project_versions(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_pvf_version ON project_version_files(version_id);
    CREATE INDEX IF NOT EXISTS idx_pvf_project ON project_version_files(project_id, change_type);

    -- ============================================
    -- project_update_requests — architect 发起的"待更新"标记
    -- (repo_url + branch + head)，由 KB 界面确认后执行
    -- ============================================
    CREATE TABLE IF NOT EXISTS project_update_requests (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        source TEXT DEFAULT 'architect' CHECK(source IN ('architect', 'kb')),
        repo_url TEXT DEFAULT '',
        local_repo_path TEXT DEFAULT '',
        branch TEXT DEFAULT '',
        head TEXT DEFAULT '',
        status TEXT DEFAULT 'pending' CHECK(status IN ('pending', 'confirmed', 'done', 'cancelled')),
        method TEXT DEFAULT '',
        result_version_id TEXT,
        note TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
    );
    CREATE INDEX IF NOT EXISTS idx_pur_project ON project_update_requests(project_id, status);
"""

GOLDEN_KNOWLEDGE_DB_TABLES_SQL = KNOWLEDGE_DB_TABLES_SQL = """
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

GOLDEN_SESSIONS_DB_TABLES_SQL = SESSIONS_DB_TABLES_SQL = """
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

GOLDEN_CHAT_DB_TABLES_SQL = CHAT_DB_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS chat_archives (
        id TEXT PRIMARY KEY,
        session_id TEXT,
        project_id TEXT,
        title TEXT,
        content TEXT NOT NULL,
        category TEXT DEFAULT 'note',
        tags TEXT DEFAULT '',
        source TEXT DEFAULT 'manual',
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS chat_drafts (
        id TEXT PRIMARY KEY,
        title TEXT DEFAULT '',
        content TEXT DEFAULT '',
        refs TEXT DEFAULT '[]',
        status TEXT DEFAULT 'draft',
        session_id TEXT,
        message_id TEXT,
        project_id TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS doc_categories (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        parent_id TEXT REFERENCES doc_categories(id),
        sort_order INTEGER DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now'))
    );

    CREATE TABLE IF NOT EXISTS llm_sessions (
        id TEXT PRIMARY KEY,
        module_type TEXT NOT NULL CHECK(module_type IN (
            'project_resource',
            'project_analysis',
            'knowledge_base',
            'ai_assistant'
        )),
        project_id TEXT,
        title TEXT NOT NULL,
        status TEXT DEFAULT 'active' CHECK(status IN ('active', 'archived')),
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        updated_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_chat_sessions_module ON llm_sessions(module_type);
    CREATE INDEX IF NOT EXISTS idx_chat_sessions_project ON llm_sessions(project_id);

    CREATE TABLE IF NOT EXISTS llm_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system', 'tool')),
        content TEXT NOT NULL,
        token_count INTEGER,
        metadata TEXT,
        created_at TEXT DEFAULT (datetime('now'))
    );
    CREATE INDEX IF NOT EXISTS idx_chat_messages_session ON llm_messages(session_id);
"""

GOLDEN_PROJECT_DB_TABLES_SQL = PROJECT_DB_TABLES_SQL = """
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

