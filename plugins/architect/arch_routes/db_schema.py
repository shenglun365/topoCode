"""Architect 工作台库 schema 与迁移 — 归 architect 自持(独立进程独占 architect.db)。

此前该 schema/迁移定义在 KB 侧 backend-core/sqlite_ctx.py；为彻底独立（源码定义权归
architect），现搬入本模块。`SQLiteContext` 连接类仍与 backend-core 共享依赖
(符合「依赖库共用」约束)，但建表/迁移只由本模块/本进程执行。
契约见 docs/architect/conventions.md §7。
"""

ARCHITECT_DB_TABLES_SQL = """
    CREATE TABLE IF NOT EXISTS arch_projects (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        desc TEXT DEFAULT '',
        root_path TEXT,                 -- execRoot
        kb_root TEXT,                   -- kbRoot
        branch TEXT DEFAULT 'main',
        baseline_id TEXT,
        baseline_commit TEXT,
        created_at INTEGER DEFAULT 0,
        active INTEGER DEFAULT 1,
        config TEXT,                    -- JSON
        mode TEXT DEFAULT 'existing',   -- existing | greenfield
        scaffold TEXT,                  -- JSON
        product_form TEXT,
        updated_at INTEGER DEFAULT 0,
        kb_project_id TEXT DEFAULT '',
        git_linked INTEGER DEFAULT 0,
        kb_source_dir TEXT DEFAULT '',
        link_verified_at INTEGER DEFAULT 0,
        pinned INTEGER DEFAULT 0,
        favorite INTEGER DEFAULT 0,
        remote_url TEXT DEFAULT '',
        default_branch TEXT DEFAULT 'main'
    );

    CREATE TABLE IF NOT EXISTS arch_requirements (
        id TEXT PRIMARY KEY,
        kind TEXT DEFAULT 'user-story',
        tier TEXT DEFAULT 'raw',            -- raw | analyzed
        status TEXT DEFAULT 'raw',
        location TEXT DEFAULT 'proposal',   -- proposal | pool
        title TEXT NOT NULL DEFAULT '',
        desc TEXT DEFAULT '',
        priority TEXT DEFAULT 'P2',
        acceptance TEXT,                    -- JSON: string[]
        analysis TEXT,                      -- JSON: RequirementAnalysis
        trace_to TEXT,                      -- JSON: string[]
        routed_by TEXT,                     -- direct | (analysis)
        suggestion TEXT,                    -- JSON
        updated_at INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_plans (
        id TEXT PRIMARY KEY,
        req_ids TEXT,                       -- JSON: string[]
        title TEXT DEFAULT '',
        approach TEXT DEFAULT '',
        changes TEXT,                       -- JSON: ChangeItem[]
        impact TEXT,                        -- JSON
        status TEXT DEFAULT 'draft',
        task_plan_id TEXT,
        base_commit TEXT,
        updated_at INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_task_trees (
        id TEXT PRIMARY KEY,
        plan_id TEXT,
        root TEXT,                          -- JSON: TaskNode
        revision INTEGER DEFAULT 0,
        history TEXT,                       -- JSON: TaskNode[] (缩略快照, 上限20)
        updated_at INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_execution_tasks (
        id TEXT PRIMARY KEY,
        plan_id TEXT,
        adapter TEXT DEFAULT 'opencode',
        model TEXT,
        req_ids TEXT,                       -- JSON: string[]
        connectivity TEXT DEFAULT 'unknown',
        status TEXT DEFAULT 'created',
        session_ids TEXT,                   -- JSON: string[]
        base_commit TEXT,
        run_count INTEGER DEFAULT 0,
        tree_revision INTEGER DEFAULT 0,
        test_ids TEXT,                      -- JSON: string[] (任务侧冗余关联)
        amendments TEXT,                    -- JSON: AppendedReq[]
        stats TEXT,                         -- JSON: TaskSessionStats
        error TEXT,
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        ended_at INTEGER,
        instance_id TEXT DEFAULT '',
        task_branch TEXT DEFAULT '',
        branch_mode TEXT DEFAULT 'auto'
    );

    CREATE TABLE IF NOT EXISTS arch_agent_sessions (
        id TEXT PRIMARY KEY,
        task_id TEXT,
        adapter TEXT DEFAULT 'opencode',
        status TEXT DEFAULT 'idle',
        keep_context INTEGER DEFAULT 1,
        artifacts TEXT,                     -- JSON: string[]
        test_result TEXT,                   -- JSON
        stats TEXT,                         -- JSON: TaskSessionStats
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        instance_id TEXT DEFAULT '',
        opencode_session_id TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS arch_agent_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        time INTEGER DEFAULT 0,
        content TEXT DEFAULT '',
        tool TEXT                            -- JSON: AgentToolCall
    );
    CREATE INDEX IF NOT EXISTS idx_arch_agent_msgs_session ON arch_agent_messages(session_id);

    CREATE TABLE IF NOT EXISTS arch_unit_tests (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL DEFAULT '',
        levels TEXT,                        -- JSON: TestLevel[]
        script_path TEXT DEFAULT '',
        source TEXT DEFAULT 'manual',       -- requirement | manual | scan
        status TEXT DEFAULT 'idle',
        last_result TEXT,                   -- JSON
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_unit_test_sessions (
        id TEXT PRIMARY KEY,
        title TEXT DEFAULT '',
        channel TEXT DEFAULT 'cli',         -- agent | cli
        adapter TEXT DEFAULT 'opencode',
        test_ids TEXT,                      -- JSON: string[]
        status TEXT DEFAULT 'created',
        stats TEXT,                         -- JSON: TaskSessionStats
        default_channel TEXT DEFAULT 'cli', -- 默认执行通道
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_unit_test_messages (
        id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        role TEXT NOT NULL,
        time INTEGER DEFAULT 0,
        content TEXT DEFAULT '',
        tool TEXT                            -- JSON: AgentToolCall
    );
    CREATE INDEX IF NOT EXISTS idx_arch_ut_msgs_session ON arch_unit_test_messages(session_id);

    CREATE TABLE IF NOT EXISTS arch_conversations (
        id TEXT PRIMARY KEY,
        kind TEXT DEFAULT 'requirement',    -- requirement | design | execution | unit-test | generic
        project_id TEXT DEFAULT '',
        req_id TEXT DEFAULT '',
        title TEXT DEFAULT '',
        status TEXT DEFAULT 'active',
        meta TEXT,                          -- JSON: 自由对话上下文(范围/意图等)
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_convs_kind ON arch_conversations(kind, project_id);

    CREATE TABLE IF NOT EXISTS arch_conversation_messages (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL,
        time INTEGER DEFAULT 0,
        content TEXT DEFAULT '',
        tool TEXT,                           -- JSON: AgentToolCall
        meta TEXT                            -- JSON: intent / rejected 等
    );
    CREATE INDEX IF NOT EXISTS idx_arch_conv_msgs_conv ON arch_conversation_messages(conversation_id);

    CREATE TABLE IF NOT EXISTS arch_mcp_calls (
        id TEXT PRIMARY KEY,
        tool TEXT DEFAULT '',
        input TEXT,                         -- JSON
        output TEXT,                        -- JSON
        status TEXT DEFAULT '',
        time INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_interactions (
        id TEXT PRIMARY KEY,
        prompt TEXT DEFAULT '',
        status TEXT DEFAULT '',
        answer TEXT DEFAULT '',
        time INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_specs (
        version TEXT PRIMARY KEY,
        overrides TEXT,                     -- JSON
        explicit_rules TEXT,                -- JSON
        derived_rules TEXT,                 -- JSON
        changelog TEXT,                     -- JSON
        updated_at INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_semantic_assets (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        kind TEXT DEFAULT 'data_structure', -- data_structure | processing_flow | control_logic
        name TEXT DEFAULT '',
        desc TEXT DEFAULT '',
        detail TEXT,                        -- JSON: fields/steps/branches
        ast_refs TEXT,                      -- JSON: AstNodeRef[]
        scope_type TEXT DEFAULT '',         -- files | symbols | comm
        scope_key TEXT DEFAULT '',
        scope_comm_id TEXT DEFAULT '',
        source TEXT DEFAULT 'codegraph',    -- codegraph | live | kb
        src_hash TEXT DEFAULT '',           -- 输入指纹(增量 change 判定)
        change TEXT DEFAULT 'same',         -- same | added | modified | deleted
        status TEXT DEFAULT 'active',       -- active | stale | deleted
        meta TEXT,                          -- JSON: 附加(componentId/edgeType 等)
        anchor_hashes TEXT,                 -- JSON: {relFile: md5} 锚定文件哈希签名
        needs_update INTEGER DEFAULT 0,     -- 需更新后使用(文件已变)
        last_checked_at INTEGER DEFAULT 0,
        deleted_at INTEGER DEFAULT 0,       -- 软删时间戳
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_proj ON arch_semantic_assets(project_id, kind);
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_scope ON arch_semantic_assets(project_id, scope_type, scope_key);
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_status ON arch_semantic_assets(project_id, status);

    CREATE TABLE IF NOT EXISTS arch_ast_cache (
        project_id TEXT NOT NULL,
        file_path TEXT NOT NULL,            -- 相对路径(正斜杠)
        content_hash TEXT DEFAULT '',
        language TEXT DEFAULT '',
        symbols TEXT,                       -- JSON: node[] (file 内符号)
        imports TEXT,                       -- JSON: module[] 
        refs TEXT,                          -- JSON: [{name,kind,line}]
        source TEXT DEFAULT 'codegraph',    -- codegraph | kb | live
        parsed_at INTEGER DEFAULT 0,
        PRIMARY KEY (project_id, file_path)
    );

    CREATE TABLE IF NOT EXISTS arch_semantic_refs (
        asset_id TEXT NOT NULL,
        ref_type TEXT NOT NULL,             -- req | plan | task | test
        ref_id TEXT NOT NULL,
        role TEXT DEFAULT 'related',        -- core | related
        created_at INTEGER DEFAULT 0,
        PRIMARY KEY (asset_id, ref_type, ref_id)
    );
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_refs_asset ON arch_semantic_refs(asset_id);
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_refs_ref ON arch_semantic_refs(ref_type, ref_id);
"""


_REQ_MIGRATION_COLS = [
    ("plan_id", "TEXT"), ("exec_id", "TEXT"), ("remarks", "TEXT"),
    ("parent_id", "TEXT"), ("related_to", "TEXT"), ("merged_into", "TEXT"),
    ("preferred_asset_ids", "TEXT"),
]

_ARCH_PROJECT_MIGRATION_COLS = [
    ("kb_project_id", "TEXT DEFAULT ''"),
    ("git_linked", "INTEGER DEFAULT 0"),
    ("kb_source_dir", "TEXT DEFAULT ''"),
    ("link_verified_at", "INTEGER DEFAULT 0"),
    ("pinned", "INTEGER DEFAULT 0"),
    ("favorite", "INTEGER DEFAULT 0"),
    ("remote_url", "TEXT DEFAULT ''"),
    ("default_branch", "TEXT DEFAULT 'main'"),
]

_ARCH_EXEC_MIGRATION_COLS = [
    ("instance_id", "TEXT DEFAULT ''"),
    ("task_branch", "TEXT DEFAULT ''"),
    ("branch_mode", "TEXT DEFAULT 'auto'"),
]

_ARCH_AGENT_CONFIG_MIGRATION_COLS = [
    ("instance_mode", "TEXT DEFAULT 'managed'"),
]

_ARCH_AGENT_SESSION_MIGRATION_COLS = [
    ("instance_id", "TEXT DEFAULT ''"),
    ("opencode_session_id", "TEXT DEFAULT ''"),
]

_ARCH_UNIT_TEST_MIGRATION_COLS = [
    ("asset_refs", "TEXT"),                # JSON: SemanticAssetRef[]
]

_ARCH_SEMANTIC_MIGRATION_COLS = [
    ("anchor_hashes", "TEXT"),             # JSON: {relFile: md5}
    ("needs_update", "INTEGER DEFAULT 0"),
    ("last_checked_at", "INTEGER DEFAULT 0"),
    ("deleted_at", "INTEGER DEFAULT 0"),
]


def architect_db_migrations(db) -> None:
    """architect 库增量迁移(旧库补列/补表)。幂等: 已存在跳过。"""
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_blueprints (
            id TEXT PRIMARY KEY,
            req_ids TEXT, title TEXT, description TEXT,
            model TEXT, source TEXT, status TEXT, stack TEXT,
            created_at INTEGER, updated_at INTEGER
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_kb_snapshots (
            id TEXT PRIMARY KEY,
            exec_root TEXT, git_commit TEXT, baseline_version TEXT,
            model TEXT, mappings TEXT, metrics TEXT, created_at INTEGER
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_tags (
            id TEXT PRIMARY KEY,
            group_key TEXT DEFAULT '', label TEXT DEFAULT '',
            color TEXT DEFAULT '', scope TEXT DEFAULT '',
            offline INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_collab_config (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_staging_scans (
            id TEXT PRIMARY KEY,
            scope TEXT DEFAULT '', grade TEXT DEFAULT '',
            files TEXT, edges_changed INTEGER DEFAULT 0,
            re_explained TEXT, boundary_changed TEXT, compliance TEXT,
            created_at INTEGER DEFAULT 0
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_snapshot_records (
            id TEXT PRIMARY KEY,
            name TEXT DEFAULT '', version TEXT DEFAULT '',
            task_id TEXT DEFAULT '', git_branch TEXT DEFAULT '',
            git_commit TEXT DEFAULT '', model TEXT, created_at INTEGER DEFAULT 0
        )
    """)
    try:
        snap_cols = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_snapshot_records)")}
    except Exception:
        snap_cols = set()
    if "root_path" not in snap_cols:
        try:
            db.execute("ALTER TABLE arch_snapshot_records ADD COLUMN root_path TEXT DEFAULT ''")
        except Exception:
            pass
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_agent_configs (
            id TEXT PRIMARY KEY,
            adapter TEXT DEFAULT '',          -- opencode / codex / claude / ...
            name TEXT DEFAULT '',
            mode TEXT DEFAULT 'server',       -- server | cli
            host TEXT DEFAULT '',
            port INTEGER DEFAULT 0,
            username TEXT DEFAULT '',
            url TEXT DEFAULT '',              -- 探测地址(如 http://127.0.0.1:4096)
            models TEXT,                      -- JSON: 选用的模型 id 列表
            default_model TEXT DEFAULT '',
            last_status TEXT DEFAULT 'unknown', -- unknown | ok | fail
            last_detail TEXT DEFAULT '',
            last_check_at INTEGER DEFAULT 0,
            created_at INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0,
            instance_mode TEXT DEFAULT 'managed' -- managed | external
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_agent_instances (
            id TEXT PRIMARY KEY,
            project_id TEXT DEFAULT '',       -- arch_projects.id
            adapter TEXT DEFAULT 'opencode',
            host TEXT DEFAULT '127.0.0.1',    -- 实例所在主机(支持远程 IP)
            mode TEXT DEFAULT 'managed',      -- managed | external
            state TEXT DEFAULT 'idle',        -- starting | ready | busy | idle | stopped | error
            pid INTEGER DEFAULT 0,            -- managed 子进程 pid
            port INTEGER DEFAULT 0,           -- serve 端口
            work_dir TEXT DEFAULT '',         -- 工程实现目录(= arch_projects.root_path)
            repo_url TEXT DEFAULT '',         -- 外部 git 仓库(统一代码事实源)
            base_branch TEXT DEFAULT 'main',
            base_commit TEXT DEFAULT '',
            task_branch TEXT DEFAULT '',      -- 当前任务分支(arch/<task_id>)
            last_commit TEXT DEFAULT '',
            ref_count INTEGER DEFAULT 0,      -- 活跃会话引用数
            idle_until INTEGER DEFAULT 0,     -- 空闲超时回收时间戳(0=不回收)
            error TEXT DEFAULT '',
            created_at INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0
        )
    """)
    try:
        existing = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_requirements)")}
    except Exception:
        existing = set()
    for name, typ in _REQ_MIGRATION_COLS:
        if name not in existing:
            try:
                db.execute(f"ALTER TABLE arch_requirements ADD COLUMN {name} {typ}")
            except Exception:
                pass
    try:
        proj_cols = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_projects)")}
    except Exception:
        proj_cols = set()
    for name, typ in _ARCH_PROJECT_MIGRATION_COLS:
        if name not in proj_cols:
            try:
                db.execute(f"ALTER TABLE arch_projects ADD COLUMN {name} {typ}")
            except Exception:
                pass
    try:
        exec_cols = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_execution_tasks)")}
    except Exception:
        exec_cols = set()
    for name, typ in _ARCH_EXEC_MIGRATION_COLS:
        if name not in exec_cols:
            try:
                db.execute(f"ALTER TABLE arch_execution_tasks ADD COLUMN {name} {typ}")
            except Exception:
                pass
    try:
        cfg_cols = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_agent_configs)")}
    except Exception:
        cfg_cols = set()
    for name, typ in _ARCH_AGENT_CONFIG_MIGRATION_COLS:
        if name not in cfg_cols:
            try:
                db.execute(f"ALTER TABLE arch_agent_configs ADD COLUMN {name} {typ}")
            except Exception:
                pass
    try:
        sess_cols = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_agent_sessions)")}
    except Exception:
        sess_cols = set()
    for name, typ in _ARCH_AGENT_SESSION_MIGRATION_COLS:
        if name not in sess_cols:
            try:
                db.execute(f"ALTER TABLE arch_agent_sessions ADD COLUMN {name} {typ}")
            except Exception:
                pass
    # 语义资产表(旧库增量迁移兜底) + 新增列
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_semantic_assets (
            id TEXT PRIMARY KEY,
            project_id TEXT DEFAULT '',
            kind TEXT DEFAULT 'data_structure',
            name TEXT DEFAULT '',
            desc TEXT DEFAULT '',
            detail TEXT,
            ast_refs TEXT,
            scope_type TEXT DEFAULT '',
            scope_key TEXT DEFAULT '',
            scope_comm_id TEXT DEFAULT '',
            source TEXT DEFAULT 'codegraph',
            src_hash TEXT DEFAULT '',
            change TEXT DEFAULT 'same',
            status TEXT DEFAULT 'active',
            meta TEXT,
            created_at INTEGER DEFAULT 0,
            updated_at INTEGER DEFAULT 0
        )
    """)
    try:
        sem_cols = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_semantic_assets)")}
    except Exception:
        sem_cols = set()
    for name, typ in _ARCH_SEMANTIC_MIGRATION_COLS:
        if name not in sem_cols:
            try:
                db.execute(f"ALTER TABLE arch_semantic_assets ADD COLUMN {name} {typ}")
            except Exception:
                pass
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_ast_cache (
            project_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            content_hash TEXT DEFAULT '',
            language TEXT DEFAULT '',
            symbols TEXT,
            imports TEXT,
            refs TEXT,
            source TEXT DEFAULT 'codegraph',
            parsed_at INTEGER DEFAULT 0,
            PRIMARY KEY (project_id, file_path)
        )
    """)
    db.execute("""
        CREATE TABLE IF NOT EXISTS arch_semantic_refs (
            asset_id TEXT NOT NULL,
            ref_type TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            role TEXT DEFAULT 'related',
            created_at INTEGER DEFAULT 0,
            PRIMARY KEY (asset_id, ref_type, ref_id)
        )
    """)
    try:
        ut_cols = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_unit_tests)")}
    except Exception:
        ut_cols = set()
    for name, typ in _ARCH_UNIT_TEST_MIGRATION_COLS:
        if name not in ut_cols:
            try:
                db.execute(f"ALTER TABLE arch_unit_tests ADD COLUMN {name} {typ}")
            except Exception:
                pass


def init_architect_db(db) -> None:
    """初始化 architect 工作台库(架构表 + 迁移)。db 为打开 architect.db 的 SQLiteContext。"""
    db.executescript(ARCHITECT_DB_TABLES_SQL)
    architect_db_migrations(db)
    db.conn.commit()