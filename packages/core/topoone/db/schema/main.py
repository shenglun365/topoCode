"""MAIN_DB_TABLES_SQL（MS5-V0 自 db/manager.py 外置；内容与原内联块逐字节一致）。

冻结契约：与 tests/ddl_golden.py 的 golden 快照全等（test_db_schema_parity.py）。
"""

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
