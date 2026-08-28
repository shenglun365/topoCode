"""Architect 库 schema 与迁移 — 归 architect 自持(独立进程)。

统一 DB 布局(docs/architect/conventions.md §7):
- 主库 `architect.db`(全局表 + arch_projects 注册表 + 全局 id 序列):
  arch_projects / arch_specs / arch_mcp_calls / arch_interactions /
  arch_collab_config
- 项目库 `architect/<project_id>/arch.db`(每 architect 项目独立，
  按 arch_projects.id 定位，与 KB 项目无存量绑定):
  需求/方案/任务树/执行/会话/单测/对话/蓝图/标签/快照/语义资产/AST 缓存等。

建表/迁移只由本模块/本进程执行；`SQLiteContext` 连接类与 KB 共享依赖库。
"""

# ── 主库(全局) ─────────────────────────────────────────────────

ARCH_MAIN_TABLES_SQL = """
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

    CREATE TABLE IF NOT EXISTS arch_specs (
        version TEXT PRIMARY KEY,
        overrides TEXT,                     -- JSON
        explicit_rules TEXT,                -- JSON
        derived_rules TEXT,                 -- JSON
        changelog TEXT,                     -- JSON
        updated_at INTEGER DEFAULT 0
    );

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

    CREATE TABLE IF NOT EXISTS arch_collab_config (
        key TEXT PRIMARY KEY,
        value TEXT DEFAULT ''
    );

    -- agent_bus 持久化消息队列(全局跨 agent 总线；broker 进程轮询本表分发)。
    -- 消息类型(topic): execution.handoff / interaction.clarify / interaction.answer /
    --   plan.revise / execution.progress / execution.result / execution.amend
    -- from/to: plan | coding | runner | monitor | user | *
    CREATE TABLE IF NOT EXISTS arch_bus_messages (
        id TEXT PRIMARY KEY,
        src TEXT NOT NULL DEFAULT '',         -- 源 agent: plan | coding | runner | user | *
        dst TEXT NOT NULL DEFAULT '',         -- 目标 agent: plan | coding | runner | monitor | *
        topic TEXT NOT NULL DEFAULT '',
        payload TEXT,                         -- JSON: 消息体
        status TEXT DEFAULT 'pending',        -- pending | delivered | failed
        error TEXT,                           -- 失败原因
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_bus_status ON arch_bus_messages(status);
    CREATE INDEX IF NOT EXISTS idx_arch_bus_dst ON arch_bus_messages(dst, status);

"""

# ── 项目库(每 architect 项目一个 arch.db) ─────────────────────

ARCH_PROJECT_TABLES_SQL = """
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
        updated_at INTEGER DEFAULT 0,
        plan_id TEXT,
        exec_id TEXT,
        assigned_to TEXT DEFAULT '',     -- 指派的 subagent: runner | mcp:<tool>
        remarks TEXT,
        parent_id TEXT,
        related_to TEXT,
        merged_into TEXT,
        preferred_asset_ids TEXT,
        design TEXT,                        -- JSON: 设计方案(方向2/3)
        asset_invalidated INTEGER DEFAULT 0,
        asset_invalidated_at INTEGER DEFAULT 0
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
        branch_mode TEXT DEFAULT 'auto',
        asset_invalidated INTEGER DEFAULT 0,
        runner_tree_id TEXT DEFAULT '',
        pending_rejudge TEXT DEFAULT ''
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
        updated_at INTEGER DEFAULT 0,
        asset_refs TEXT                     -- JSON: SemanticAssetRef[]
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

    CREATE TABLE IF NOT EXISTS arch_blueprints (
        id TEXT PRIMARY KEY,
        req_ids TEXT, title TEXT, description TEXT,
        model TEXT, source TEXT, status TEXT, stack TEXT,
        created_at INTEGER, updated_at INTEGER
    );

    CREATE TABLE IF NOT EXISTS arch_kb_snapshots (
        id TEXT PRIMARY KEY,
        exec_root TEXT, git_commit TEXT, baseline_version TEXT,
        model TEXT, mappings TEXT, metrics TEXT, created_at INTEGER
    );

    CREATE TABLE IF NOT EXISTS arch_tags (
        id TEXT PRIMARY KEY,
        group_key TEXT DEFAULT '', label TEXT DEFAULT '',
        color TEXT DEFAULT '', scope TEXT DEFAULT '',
        offline INTEGER DEFAULT 0, created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_staging_scans (
        id TEXT PRIMARY KEY,
        scope TEXT DEFAULT '', grade TEXT DEFAULT '',
        files TEXT, edges_changed INTEGER DEFAULT 0,
        re_explained TEXT, boundary_changed TEXT, compliance TEXT,
        created_at INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS arch_snapshot_records (
        id TEXT PRIMARY KEY,
        name TEXT DEFAULT '', version TEXT DEFAULT '',
        task_id TEXT DEFAULT '', git_branch TEXT DEFAULT '',
        git_commit TEXT DEFAULT '', model TEXT, created_at INTEGER DEFAULT 0,
        root_path TEXT DEFAULT ''
    );

    CREATE TABLE IF NOT EXISTS arch_semantic_assets (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        kind TEXT DEFAULT 'entity',          -- entity | contract | state | rule | process | decision
        level TEXT DEFAULT 'logic',          -- implementation | logic | business(抽象粒度)
        name TEXT DEFAULT '',
        desc TEXT DEFAULT '',
        pseudo TEXT DEFAULT '',             -- 关联代码伪码级说明(查询时 LLM 生成，有效生命周期内缓存)
        detail TEXT,                        -- JSON: fields/steps/branches/aggregates
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
        canonical_key TEXT DEFAULT '',      -- 稳定规范标识(scope+锚点指纹)
        renamed_from TEXT DEFAULT '',       -- 语义命名变更溯源
        name_alias TEXT,                    -- JSON: 历史语义名列表
        needs_update INTEGER DEFAULT 0,     -- 需更新后使用(文件已变)
        last_checked_at INTEGER DEFAULT 0,
        deleted_at INTEGER DEFAULT 0,       -- 软删时间戳
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        parent_id TEXT DEFAULT ''           -- H 级聚合资产的父级组合链
    );
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_proj ON arch_semantic_assets(project_id, kind);
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_scope ON arch_semantic_assets(project_id, scope_type, scope_key);
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_status ON arch_semantic_assets(project_id, status);
    CREATE INDEX IF NOT EXISTS idx_arch_semantic_canonical ON arch_semantic_assets(project_id, canonical_key);

    CREATE TABLE IF NOT EXISTS arch_ast_cache (
        project_id TEXT NOT NULL,
        file_path TEXT NOT NULL,            -- 相对路径(正斜杠)
        content_hash TEXT DEFAULT '',
        language TEXT DEFAULT '',
        symbols TEXT,                       -- JSON: node[] (file 内符号)
        imports TEXT,                       -- JSON: module[]
        refs TEXT,                          -- JSON: [{name,kind,line}]
        statements TEXT,                    -- JSON: 语句级条件 [{type,condition,startLine,endLine,enclosing}]
        routes TEXT,                        -- JSON: 框架路由 [{path,methods,handler,framework,line}]
        constants TEXT,                     -- JSON: 常量值 [{name,value,line}]
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

    CREATE TABLE IF NOT EXISTS arch_extract_tasks (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        root TEXT DEFAULT '',
        status TEXT DEFAULT 'running',     -- running | done | partial | failed
        kind TEXT DEFAULT 'semantic',      -- semantic 提取任务归类
        comp_ids TEXT,                     -- JSON: string[] 待提取组件 id
        total INTEGER DEFAULT 0,
        done INTEGER DEFAULT 0,
        progress TEXT,                     -- JSON: [{compId, status, count, error}]
        messages TEXT,                     -- JSON: [{id, role, content, time}] 同步到对话
        meta TEXT,                         -- JSON: 附加(模型/会话上下文)
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
"""

# 旧单库全量 schema(迁移脚本/兼容参考用；新库分主/项目两套)
ARCHITECT_DB_TABLES_SQL = ARCH_MAIN_TABLES_SQL + "\n" + ARCH_PROJECT_TABLES_SQL


def _add_cols(db, table: str, cols: list) -> None:
    """幂等补列: 缺失列才 ALTER。"""
    try:
        existing = {r["name"] for r in db.fetchall(f"PRAGMA table_info({table})")}
    except Exception:
        existing = set()
    for name, typ in cols:
        if name not in existing:
            try:
                db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")
            except Exception:
                pass


# ── 主库迁移(旧库升级兜底，幂等) ───────────────────────────────

def _main_migrations(db) -> None:
    _add_cols(db, "arch_projects", [
        ("kb_project_id", "TEXT DEFAULT ''"),
        ("git_linked", "INTEGER DEFAULT 0"),
        ("kb_source_dir", "TEXT DEFAULT ''"),
        ("link_verified_at", "INTEGER DEFAULT 0"),
        ("pinned", "INTEGER DEFAULT 0"),
        ("favorite", "INTEGER DEFAULT 0"),
        ("remote_url", "TEXT DEFAULT ''"),
        ("default_branch", "TEXT DEFAULT 'main'"),
    ])


def architect_db_migrations(db) -> None:
    """architect 主库增量迁移(旧库补列/补表)。幂等: 已存在跳过。"""
    db.executescript(ARCH_MAIN_TABLES_SQL)
    _main_migrations(db)


# ── 项目库迁移(旧项目库升级兜底，幂等) ─────────────────────────

def _project_migrations(db) -> None:
    _add_cols(db, "arch_requirements", [
        ("plan_id", "TEXT"), ("exec_id", "TEXT"), ("remarks", "TEXT"),
        ("parent_id", "TEXT"), ("related_to", "TEXT"), ("merged_into", "TEXT"),
        ("preferred_asset_ids", "TEXT"),
        ("design", "TEXT"),
        ("asset_invalidated", "INTEGER DEFAULT 0"),
        ("asset_invalidated_at", "INTEGER DEFAULT 0"),
        ("assigned_to", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_execution_tasks", [
        ("instance_id", "TEXT DEFAULT ''"),
        ("task_branch", "TEXT DEFAULT ''"),
        ("branch_mode", "TEXT DEFAULT 'auto'"),
        ("asset_invalidated", "INTEGER DEFAULT 0"),
        ("runner_tree_id", "TEXT DEFAULT ''"),
        ("pending_rejudge", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_agent_sessions", [
        ("instance_id", "TEXT DEFAULT ''"),
        ("opencode_session_id", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_unit_tests", [
        ("asset_refs", "TEXT"),
    ])
    _add_cols(db, "arch_snapshot_records", [
        ("root_path", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_semantic_assets", [
        ("pseudo", "TEXT DEFAULT ''"),
        ("anchor_hashes", "TEXT"),
        ("needs_update", "INTEGER DEFAULT 0"),
        ("last_checked_at", "INTEGER DEFAULT 0"),
        ("deleted_at", "INTEGER DEFAULT 0"),
        ("canonical_key", "TEXT DEFAULT ''"),
        ("renamed_from", "TEXT DEFAULT ''"),
        ("name_alias", "TEXT"),
        ("level", "TEXT DEFAULT 'interaction'"),
        ("parent_id", "TEXT DEFAULT ''"),
    ])
    # kind/level 规范化: 旧五类/四粒度 → 新六类/三粒度(默认 logic 粒度)。
    # rule 在新六类中是一级类别(配置化规则)，不得并入 decision。
    for old, new in (("data_structure", "entity"),
                     ("asset", "entity"),
                     ("processing_flow", "process"),
                     ("control_logic", "decision")):
        try:
            db.execute(
                "UPDATE arch_semantic_assets SET kind = ?, level = 'logic' WHERE kind = ?",
                (new, old),
            )
        except Exception:
            pass
    try:
        db.execute(
            "UPDATE arch_semantic_assets SET level = CASE level "
            "WHEN 'business' THEN 'business' WHEN 'high' THEN 'business' "
            "WHEN 'interaction' THEN 'logic' WHEN 'medium' THEN 'logic' "
            "WHEN 'algorithm' THEN 'implementation' WHEN 'low' THEN 'implementation' "
            "WHEN 'infra' THEN 'implementation' ELSE 'logic' END "
            "WHERE level IS NOT NULL AND level NOT IN ('implementation','logic','business')")
    except Exception:
        pass
    _add_cols(db, "arch_ast_cache", [
        ("statements", "TEXT"),
        ("routes", "TEXT"),
        ("constants", "TEXT"),
    ])


def init_architect_db(db) -> None:
    """初始化 architect 主库。db 为打开 architect.db 的 SQLiteContext。

    主库 = 全局表 + arch_projects 注册表 + 全局 id 序列，同时容纳项目表作为
    「未绑定项目」的默认桶(无项目上下文时的读写落点)。
    """
    db.executescript(ARCH_MAIN_TABLES_SQL + "\n" + ARCH_PROJECT_TABLES_SQL)
    _main_migrations(db)
    _project_migrations(db)


def init_architect_project_db(db) -> None:
    """初始化 architect 项目库(architect/<pid>/arch.db)。幂等。"""
    db.executescript(ARCH_PROJECT_TABLES_SQL)
    _project_migrations(db)
