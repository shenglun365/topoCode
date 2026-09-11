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
    -- WS6-E 审计落库: 工具调用流水(全局表, project_id 供过滤)
    CREATE TABLE IF NOT EXISTS arch_tool_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts INTEGER NOT NULL,
        tool TEXT NOT NULL,
        args_digest TEXT DEFAULT '',
        ok INTEGER DEFAULT 1,
        result_digest TEXT DEFAULT '',
        conversation_id TEXT DEFAULT '',
        req_id TEXT DEFAULT '',
        project_id TEXT DEFAULT '',
        model_id TEXT DEFAULT '',
        latency_ms REAL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_audit_ts ON arch_tool_audit(ts DESC);
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
        kind TEXT DEFAULT 'requirement',    -- requirement | design | asset | execution | unit-test | generic
        project_id TEXT DEFAULT '',
        req_id TEXT DEFAULT '',
        title TEXT DEFAULT '',
        status TEXT DEFAULT 'active',       -- 生命周期维度: active | running | archived(不可逆)
        review_state TEXT DEFAULT 'read',   -- 查看状态维度: read | unread | awaiting_reply | error
        role_id TEXT DEFAULT 'architect',   -- 执行角色(arch_session_roles.id; 新会话默认 architect)
        role_locked INTEGER DEFAULT 0,      -- 角色锁定(首次切换 executor 后=1, 再换只能交接)
        tags TEXT,                          -- JSON: {modules:[], groups:[]} 会话分类(会话中心)
        summary TEXT DEFAULT '',            -- 会话摘要(自动生成/手改；历史总结素材)
        meta TEXT,                          -- JSON: 自由对话上下文(范围/意图等)
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_convs_kind ON arch_conversations(kind, project_id);

    -- 备案文档(P1 会话中心)：会话派生的总结性文档(需求快照/开发简报/笔记)，
    -- 非流程实体——随时生成、随时增删(裁决2)。
    CREATE TABLE IF NOT EXISTS arch_docs (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        conversation_id TEXT DEFAULT '',    -- 来源会话(证据链)
        type TEXT DEFAULT 'requirement_summary',  -- requirement_summary | dev_digest | note
        title TEXT DEFAULT '',
        content_md TEXT DEFAULT '',
        refs TEXT,                          -- JSON: {execIds:[], assetVersions:{}, modules:[]}
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_docs_conv ON arch_docs(conversation_id, project_id);

    -- 上下文注册表(P2)：会话派生的可检索单元(拉取式——architect 经 ctx.* 按需提取)。
    -- 消息本体不复制(存对话消息表)，此处只留派生单元：工具轨迹/产物/决策/摘要/执行回执。
    CREATE TABLE IF NOT EXISTS arch_context_units (
        id TEXT PRIMARY KEY,
        conversation_id TEXT DEFAULT '',
        project_id TEXT DEFAULT '',
        type TEXT DEFAULT 'note',          -- tool_call | artifact | decision | session_summary | execution_report | execution_brief | note
        title TEXT DEFAULT '',
        content TEXT DEFAULT '',           -- markdown 正文
        refs TEXT,                         -- JSON: {modules:[], components:[], files:[], execIds:[], reqIds:[]}
        importance INTEGER DEFAULT 0,      -- 0 普通 / 1 高(决策/摘要/回执)
        created_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_ctx_units_conv ON arch_context_units(conversation_id, project_id);
    CREATE INDEX IF NOT EXISTS idx_arch_ctx_units_type ON arch_context_units(type, project_id);

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

    -- ── M0 冻结 schema（docs/architect-reconstruction/plan-C-M0.md §6） ──

    -- 框架配置（版本行即变更审计；每 project 至多一行 active=1）
    CREATE TABLE IF NOT EXISTS arch_framework_configs (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        config TEXT NOT NULL,               -- JSON: {axes, tiers, activeTier, acceptanceDefault, directivesDepth}
        change_kind TEXT DEFAULT 'init',    -- init | tier_switch | values_edit | custom_load
        affected_summary TEXT,              -- JSON: {voidedAssets, byKind, note}
        executed_by TEXT DEFAULT '',
        note TEXT DEFAULT '',
        active INTEGER DEFAULT 0,
        created_at INTEGER DEFAULT 0,
        UNIQUE(project_id, version)
    );
    CREATE INDEX IF NOT EXISTS idx_arch_fwcfg_active ON arch_framework_configs(project_id, active);

    -- 命名墓碑（参考池；仅服务"标准不变的代码变更"生命周期——框架作废不写墓碑 R1）
    CREATE TABLE IF NOT EXISTS arch_name_tombstones (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        file_path TEXT DEFAULT '',
        symbol TEXT DEFAULT '',
        name TEXT NOT NULL,
        source TEXT DEFAULT 'llm',          -- user | llm | rule
        reason TEXT DEFAULT 'anchor_gone',  -- anchor_gone | partial_fail | reconcile_deleted
        asset_id TEXT DEFAULT '',
        note TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_tombstone_lookup
        ON arch_name_tombstones(project_id, file_path, symbol);
    CREATE INDEX IF NOT EXISTS idx_arch_tombstone_name
        ON arch_name_tombstones(project_id, name);

    -- 用户编辑层（overlay：改名/合并/拆分/描述修订；seq 有序重放）
    CREATE TABLE IF NOT EXISTS arch_user_overlays (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        author TEXT DEFAULT '',
        op TEXT NOT NULL,                   -- rename | merge | split | edit_desc | edit_detail
        target_asset_ids TEXT NOT NULL,     -- JSON: string[]
        payload TEXT,                       -- JSON: rename{newName} / merge{intoId,targetName} / split{parts} / edit_desc{desc}
        anchor_basis TEXT,                  -- JSON: [{file,symbol}] 操作时锚点快照（重放匹配依据）
        reason TEXT DEFAULT '',
        status TEXT DEFAULT 'active',       -- active | orphaned | rolled_back
        approval_status TEXT DEFAULT '',    -- 多人留位: pending | approved | rejected
        approved_by TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0,
        applied_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_overlay_proj ON arch_user_overlays(project_id, seq);

    -- 资产命名规约（项目规约页·资产命名规约区块；scenarios NOT NULL 防全量注入 R7）
    CREATE TABLE IF NOT EXISTS arch_naming_conventions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        scope TEXT DEFAULT 'project',       -- project | component
        component_id TEXT DEFAULT '',
        applies_kinds TEXT,                 -- JSON: kind 数组（空=全部）
        rule_text TEXT NOT NULL,
        source TEXT DEFAULT 'manual',       -- induced | manual
        scenarios TEXT NOT NULL,            -- JSON: ["extract","accept","naming","general"]
        status TEXT DEFAULT 'active',       -- active | disabled | pending_review
        author TEXT DEFAULT '',
        framework_version INTEGER DEFAULT 0,
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );

CREATE TABLE IF NOT EXISTS arch_capability_proposals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    type TEXT NOT NULL,               -- convention | process | trick | skill
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    scenarios TEXT,                   -- JSON: 注入场景标签数组(extract/accept/…)
    reason TEXT,
    source_conversation_id TEXT,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | accepted | ignored
    origin_project_id TEXT DEFAULT '',  -- WS8: 全局桶行来源项目
    created_at INTEGER DEFAULT 0,
    updated_at INTEGER DEFAULT 0
);
    CREATE INDEX IF NOT EXISTS idx_arch_conv_proj ON arch_naming_conventions(project_id, status);
    CREATE INDEX IF NOT EXISTS idx_arch_conv_scenario ON arch_naming_conventions(project_id, status, scenarios);

    -- 术语表（词典，纯参考非约束）
    CREATE TABLE IF NOT EXISTS arch_glossary (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        term TEXT NOT NULL,
        alias TEXT,                         -- JSON: 别名/英文对应
        definition TEXT DEFAULT '',
        source TEXT DEFAULT 'manual',       -- doc_import | manual
        source_ref TEXT DEFAULT '',
        author TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_glossary_term ON arch_glossary(project_id, term);

    -- 契约条目（= 验收条目，plan-C-M0 §2.1）
    CREATE TABLE IF NOT EXISTS arch_contract_items (
        id TEXT PRIMARY KEY,                -- ci-{seq}
        project_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        req_id TEXT DEFAULT '',
        conv_id TEXT DEFAULT '',
        origin TEXT,                        -- JSON: {convId, messageId, quote}
        kind TEXT NOT NULL,
        level TEXT DEFAULT 'implementation',
        target TEXT,                        -- JSON: {file?, symbol?, componentId?}
        intent_only INTEGER DEFAULT 0,
        behavior TEXT,                      -- JSON: fields/steps/branches/states/transitions/relations
        z_axis TEXT,                        -- JSON: [{category,text,anchor?}]
        acceptance TEXT,                    -- JSON: {mode, criteria?, linkedTests?}
        status TEXT DEFAULT 'draft',        -- draft|confirmed|injected|verifying|accepted|rejected
        stale_by_framework INTEGER DEFAULT 0,
        version INTEGER DEFAULT 1,
        created_by TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0,
        confirmed_at INTEGER DEFAULT 0,
        injected_at INTEGER DEFAULT 0,
        verified_at INTEGER DEFAULT 0,
        UNIQUE(project_id, seq)
    );
    CREATE INDEX IF NOT EXISTS idx_arch_citem_proj ON arch_contract_items(project_id, status);

    -- 契约包（注入 runner 的单元）
    CREATE TABLE IF NOT EXISTS arch_contract_packages (
        id TEXT PRIMARY KEY,                -- cp-{seq}
        project_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        framework_snapshot TEXT NOT NULL,   -- JSON: {version, activeTier}
        item_ids TEXT NOT NULL,             -- JSON: 仅 confirmed+
        asset_refs TEXT,                    -- JSON: 语义资产 id（X 轴基线）
        component_refs TEXT,                -- JSON: Y 轴组件引用
        agents_md TEXT DEFAULT '',
        status TEXT DEFAULT 'created',      -- created | injected | superseded
        injected_to TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0,
        injected_at INTEGER DEFAULT 0,
        UNIQUE(project_id, seq)
    );

    -- 验收报告（facts 与 opinions 物理分表——事实/意见分离 R6）
    CREATE TABLE IF NOT EXISTS arch_acceptance_reports (
        id TEXT PRIMARY KEY,                -- ar-{seq}
        project_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        package_id TEXT NOT NULL,
        trigger_info TEXT,                  -- JSON: {type: runner_done|git_diff|manual, ref}（trigger 为保留字）
        extraction_profile TEXT DEFAULT 'strict',
        summary TEXT,                       -- JSON: {pass, fail, l3AwaitingHuman}
        created_at INTEGER DEFAULT 0,
        UNIQUE(project_id, seq)
    );

    CREATE TABLE IF NOT EXISTS arch_acceptance_facts (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        report_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        check_layer TEXT NOT NULL,          -- L1 | L2（check 为保留字）
        verdict TEXT NOT NULL,              -- pass | fail | partial
        evidence TEXT,                      -- JSON: {assetId?, anchors:[], detail}
        created_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_afact_report ON arch_acceptance_facts(project_id, report_id);

    CREATE TABLE IF NOT EXISTS arch_acceptance_opinions (
        id TEXT PRIMARY KEY,
        project_id TEXT NOT NULL,
        report_id TEXT NOT NULL,
        item_id TEXT NOT NULL,
        text TEXT NOT NULL,
        confidence REAL DEFAULT 0,
        model TEXT DEFAULT '',
        evidence TEXT,                      -- JSON: 同 facts 结构
        trigger_by TEXT DEFAULT '',         -- 触发用户（仅人工，无自动写入方）
        created_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_aopin_report ON arch_acceptance_opinions(project_id, report_id);
"""

# 旧单库全量 schema(迁移脚本/兼容参考用；新库分主/项目两套)
ARCHITECT_DB_TABLES_SQL = ARCH_MAIN_TABLES_SQL + "\n" + ARCH_PROJECT_TABLES_SQL


SESSION_ROLE_TABLE_SQL = """
    -- 会话执行角色(P2 角色体系): architect 系统种子唯一不可删; executor 绑执行器实例
    CREATE TABLE IF NOT EXISTS arch_session_roles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,                 -- 显示名(区别多个 executor)
        kind TEXT DEFAULT 'executor',       -- architect | executor
        executor_id TEXT DEFAULT '',        -- agent.executors 实例 id(executor 角色必填)
        model_id TEXT DEFAULT '',           -- 实例下模型参数(executor 角色)
        skills TEXT,                        -- JSON: 角色技能场景白名单
        tools TEXT,                         -- JSON: 工具调用白名单(harness/tools)
        permissions TEXT,                   -- JSON: 权限配置(写文件/执行命令/网络等)
        builtin INTEGER DEFAULT 0,          -- 系统内置(architect=1: 不可删不可改执行器)
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
"""


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


def _seed_roles(db) -> None:
    """种子 architect 角色(系统内置唯一不可删)。"""
    row = db.fetchall("SELECT id FROM arch_session_roles WHERE id = 'architect'")
    if not row:
        now = int(__import__("time").time() * 1000)
        db.execute(
            "INSERT INTO arch_session_roles (id, name, kind, builtin, created_at, updated_at) "
            "VALUES ('architect', 'Architect', 'architect', 1, ?, ?)", (now, now))
        db.commit()


def architect_db_migrations(db) -> None:
    """architect 主库增量迁移(旧库补列/补表)。幂等: 已存在跳过。"""
    db.executescript(ARCH_MAIN_TABLES_SQL)
    db.executescript(SESSION_ROLE_TABLE_SQL)
    _seed_roles(db)
    _main_migrations(db)


# ── 项目库迁移(旧项目库升级兜底，幂等) ─────────────────────────

def _migrate_conversation_lifecycle(db) -> None:
    """存量会话状态迁移(一次性, 幂等): 单值 status → 双维度。

    waiting→(active, awaiting_reply); done/pending→(active, read) —
    pending 额外打 meta.pendingExec 标记(待执行徽标); running/archived 保持。
    """
    try:
        rows = db.fetchall(
            "SELECT id, status, meta FROM arch_conversations WHERE status IN ('waiting','done','pending')")
    except Exception:
        return
    for r in rows:
        cid, st = r["id"], r["status"]
        review = "awaiting_reply" if st == "waiting" else "read"
        meta = r["meta"] or ""
        if st == "pending":
            try:
                import json as _json
                m = _json.loads(meta) if isinstance(meta, str) and meta else {}
                if isinstance(m, dict):
                    m["pendingExec"] = True
                    meta = _json.dumps(m, ensure_ascii=False)
            except Exception:
                meta = '{"pendingExec": true}'
        db.execute(
            "UPDATE arch_conversations SET status='active', review_state=?, role_id='architect', "
            "role_locked=0, meta=? WHERE id=?", (review, meta, cid))
    if rows:
        db.commit()


def _project_migrations(db) -> None:
    # M0 冻结: 语义资产作废态（标准变更 → 整体作废，行保留可溯源；plan-C-M0 §6.4）
    _add_cols(db, "arch_semantic_assets", [
        ("voided_reason", "TEXT DEFAULT ''"),
        ("voided_at", "INTEGER DEFAULT 0"),
        ("voided_by", "TEXT DEFAULT ''"),
        ("voided_framework_version", "INTEGER DEFAULT 0"),
        ("stale_by_framework", "INTEGER DEFAULT 0"),
        # WS8 提升通道: 全局桶行记录来源项目
        ("origin_project_id", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_naming_conventions", [
        ("origin_project_id", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_capability_proposals", [
        ("origin_project_id", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_requirements", [
        ("plan_id", "TEXT"), ("exec_id", "TEXT"), ("remarks", "TEXT"),
        ("parent_id", "TEXT"), ("related_to", "TEXT"), ("merged_into", "TEXT"),
        ("preferred_asset_ids", "TEXT"),
        ("design", "TEXT"),
        ("asset_invalidated", "INTEGER DEFAULT 0"),
        ("asset_invalidated_at", "INTEGER DEFAULT 0"),
        ("assigned_to", "TEXT DEFAULT ''"),
        # S5 会话中心：需求来源（资产地图对话中形成 → 提交）
        ("source_type", "TEXT DEFAULT ''"),
        ("source_conversation_id", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_conversations", [
        # P1 会话中心：分类标签 + 摘要(全量持久化、历史总结素材)
        ("tags", "TEXT"),
        ("summary", "TEXT DEFAULT ''"),
        # PR1 双维度状态机: 查看状态 + 执行角色(生命周期沿用 status 列)
        ("review_state", "TEXT DEFAULT 'read'"),
        ("role_id", "TEXT DEFAULT 'architect'"),
        ("role_locked", "INTEGER DEFAULT 0"),
    ])
    _migrate_conversation_lifecycle(db)
    _add_cols(db, "arch_unit_tests", [
        ("asset_refs", "TEXT"),
    ])
    _add_cols(db, "arch_snapshot_records", [
        ("root_path", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_semantic_assets", [
        ("pseudo", "TEXT DEFAULT ''"),
        ("line_notes", "TEXT DEFAULT ''"),
        ("node_brief", "TEXT DEFAULT ''"),
        ("edge_notes", "TEXT DEFAULT ''"),
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
    db.executescript(SESSION_ROLE_TABLE_SQL)
    _seed_roles(db)
    _main_migrations(db)
    _project_migrations(db)


def init_architect_project_db(db) -> None:
    """初始化 architect 项目库(architect/<pid>/arch.db)。幂等。"""
    db.executescript(ARCH_PROJECT_TABLES_SQL)
    _project_migrations(db)
