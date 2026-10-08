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

    -- 已废弃(2610 规约定型): 三层规约面退役, 表留存仅历史数据迁移兼容
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

    CREATE TABLE IF NOT EXISTS arch_exec_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        job_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        kind TEXT NOT NULL,
        text TEXT DEFAULT '',               -- 截断 2000(防大行)
        extra TEXT,                         -- JSON: 其余事件字段
        ts INTEGER NOT NULL,
        UNIQUE(job_id, seq)                 -- 泵 seq 去重双保险
    );
    CREATE INDEX IF NOT EXISTS idx_exec_events_job ON arch_exec_events(job_id, seq);

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
        kind TEXT DEFAULT 'generic',        -- requirement | asset | unit-test | generic
        project_id TEXT DEFAULT '',
        req_id TEXT DEFAULT '',
        title TEXT DEFAULT '',
        status TEXT DEFAULT 'active',       -- 生命周期: active | archived(不可逆)
        work_state TEXT DEFAULT 'architect', -- 工作相位: architect(常态) | running(外调作业执行中)
        parent_conv_id TEXT DEFAULT '',       -- 主会话 id(coding 子会话 → 主会话; 主会话为空)
        executor_id TEXT DEFAULT '',          -- coding 执行器绑定(一次绑定不可换; 换=克隆)
        session_ref TEXT DEFAULT '',          -- 执行器原生会话引用(opencode session id 等; 子会话复活用)
        review_state TEXT DEFAULT 'read',   -- 查看状态: read | unread | awaiting_reply | error
        analysis_mode TEXT DEFAULT 'strict', -- 分析挡位: strict(需求分析→规约→任务) | quick(直出任务卡)
        flow_state TEXT DEFAULT '',          -- 流程相位缓存(governance/flow.py 派生物化; 事件驱动迁移)
        flow_state_at INTEGER DEFAULT 0,     -- 相位迁移时间(审计锚)
        roles TEXT,                         -- JSON: 角色集 [architect(恒), ...外调角色id]
        tags TEXT,                          -- JSON: {modules:[], groups:[]} 会话分类(会话中心)
        summary TEXT DEFAULT '',            -- 会话摘要
        meta TEXT,                          -- JSON: 作业账本 jobs[] 等
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_convs_kind ON arch_conversations(kind, project_id);

    -- 备案文档(P1 会话中心)：会话派生的总结性文档(需求快照/开发简报/笔记)，
    -- 非流程实体——随时生成、随时增删(裁决2)。
    CREATE TABLE IF NOT EXISTS arch_docs (
        id TEXT PRIMARY KEY,
        schema_version INTEGER DEFAULT 1,  -- K1 格式版本化(登记: docs/architect/kb-schema-versions.md)
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
        schema_version INTEGER DEFAULT 1,  -- K1 格式版本化(登记: docs/architect/kb-schema-versions.md)
        conversation_id TEXT DEFAULT '',
        project_id TEXT DEFAULT '',
        type TEXT DEFAULT 'note',          -- tool_call | artifact | decision | session_summary | execution_report | execution_brief | analysis | error | error_pattern | note
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

    -- A6.2 Item 投影: 执行器事件流的非落消息类型(工具轨迹/文件变更/通知)持久化
    -- (运行时流表, 非知识资产——不在 kb-schema-versions 登记范围)
    CREATE TABLE IF NOT EXISTS arch_stream_items (
        id TEXT PRIMARY KEY,
        conversation_id TEXT DEFAULT '',
        project_id TEXT DEFAULT '',
        task_id TEXT DEFAULT '',
        job_id TEXT DEFAULT '',
        type TEXT DEFAULT 'event',          -- item 类型(开放注册制: agent/execution/items.py)
        status TEXT DEFAULT '',
        text TEXT DEFAULT '',
        payload TEXT,                       -- JSON: files/requestId 等扩展载荷
        seq INTEGER,                        -- runner 事件 seq(可缺)
        created_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_stream_items_conv
        ON arch_stream_items(conversation_id, task_id, created_at);

    -- v2 重构(统一会话): coding subagent 任务(替代 conv.meta.jobs 账本+规约执行门禁)。
    -- 单流模型: 任务回执以消息(agent=executor_type)落统一流, 此表只管生命周期。
    CREATE TABLE IF NOT EXISTS arch_tasks (
        id TEXT PRIMARY KEY,
        conversation_id TEXT NOT NULL,
        project_id TEXT DEFAULT '',
        req_id TEXT DEFAULT '',
        title TEXT DEFAULT '',
        instruction TEXT DEFAULT '',        -- 下发快照全文(含工作环境/允许范围)
        status TEXT DEFAULT 'pending_confirm', -- pending_confirm|running|waiting_input|done|failed|cancelled
        executor_type TEXT DEFAULT 'opencode', -- cline | opencode | codex
        executor_id TEXT DEFAULT '',
        runner_job_id TEXT DEFAULT '',      -- runner ImplementJob id
        session_ref TEXT DEFAULT '',        -- 执行器原生会话引用(复活)
        spec_ver INTEGER DEFAULT 0,         -- 绑定的规约版本(建卡时固化; 0=无规约)
        worktree TEXT DEFAULT '',
        branch TEXT DEFAULT '',
        progress TEXT,                      -- JSON: {toolCount, msgCount, at}
        result_md TEXT DEFAULT '',          -- 终态产出摘要(done 时)
        safety_class TEXT DEFAULT 'mutating', -- 安全等级: readonly|mutating|high-stakes(互斥/worktree/门禁)
        work_tags TEXT,                     -- JSON: 开放工作类型标签(不设枚举, 仅影响提示)
        dismissed_at INTEGER DEFAULT 0,     -- 回执已阅(reviewing 消化出口, 0=未处理)
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        finished_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_tasks_conv ON arch_tasks(conversation_id, project_id);

    -- 需求跟踪台账(会话中心左栏): 工作条目六维度——谁创建/内容/待谁操作/操作类型/
    -- 结果/当前状态; 分类与操作类型为可配置字典(collab config tracking.*)非固化枚举。
    -- 主会话+子会话双 ID: 精确跟踪需求在主线与其 coding 子会话中的执行。
    -- (运行时台账, 非知识资产——不进 kb-schema-versions 登记, 同 arch_tasks 先例)
    CREATE TABLE IF NOT EXISTS arch_assets (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',        -- 项目域(空=全局)
        kind TEXT DEFAULT 'skill',         -- skill | requirement | todo | plan | data_asset | analysis(v2-todo P1 五类预留)
        name TEXT DEFAULT '',
        description TEXT DEFAULT '',
        payload TEXT DEFAULT '{}',         -- kind 专属: skill={route_hint, child_registry[], instructions_md, enabled}
        enabled INTEGER DEFAULT 1,
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        UNIQUE(project_id, kind, name)
    );

    CREATE TABLE IF NOT EXISTS arch_tracking_items (
        id TEXT PRIMARY KEY,
        category TEXT DEFAULT '',           -- 开放分类标签: 需求|方案|任务|回执|决策|异常|…(字典)
        title TEXT DEFAULT '',
        content TEXT DEFAULT '',            -- 创建的内容(正文/摘要)
        action_type TEXT DEFAULT '',        -- 操作类型: 编码|设计|分析|决策|…(字典)
        creator_role TEXT DEFAULT '',       -- user | architect | coding
        creator_id TEXT DEFAULT '',         -- 执行器实例 id(creator_role=coding 时)
        assignee_role TEXT DEFAULT '',      -- 待操作角色(空=无待办)
        assignee_id TEXT DEFAULT '',
        state TEXT DEFAULT 'done',          -- running|waiting|done|failed|cancelled
        waiting_for TEXT DEFAULT '',        -- state=waiting 时的目标角色
        result TEXT DEFAULT '',             -- 操作结果摘要(终态回填)
        result_state TEXT DEFAULT '',       -- ok | failed | cancelled
        valid INTEGER DEFAULT 1,            -- 有效性(人工作废=0)
        main_conversation_id TEXT DEFAULT '',  -- 主会话(需求主线)
        conversation_id TEXT DEFAULT '',    -- 直接(子)会话
        ref_type TEXT DEFAULT '',           -- 溯源: requirement|task|unit|…
        ref_id TEXT DEFAULT '',
        project_id TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_tracking_conv
        ON arch_tracking_items(main_conversation_id, project_id);
    CREATE INDEX IF NOT EXISTS idx_arch_tracking_ref
        ON arch_tracking_items(ref_type, ref_id);

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

    -- 语义作业(批1-3)：统一异步任务表(项目库, 多实例按项目隔离)。收编原三套
    -- daemon 的进程内 _jobs 状态(重启失忆)——持久化+恢复对账+取消协作。
    CREATE TABLE IF NOT EXISTS arch_semantic_jobs (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        kind TEXT DEFAULT '',               -- extract_delta | extract_unowned | enhance_desc | extract_impl | enhance_semantic | extract_logic | analyze_logic | gen_component_view
        scope TEXT DEFAULT '{}',            -- JSON: {type: project|component|file|asset, keys: []}
        state TEXT DEFAULT 'queued',        -- queued | running | done | failed | cancelled | lost
        progress TEXT DEFAULT '{}',         -- JSON: {total, done, current, batch}
        stages TEXT DEFAULT '[]',           -- JSON: 级联阶段(如 ["impl","logic"])
        stage_index INTEGER DEFAULT 0,
        result TEXT DEFAULT '{}',           -- JSON: {saved, skipped, errors[], summary}
        llm INTEGER DEFAULT 0,              -- LLM 类任务(全局限并发闸门)
        cancel_requested INTEGER DEFAULT 0, -- 协作式取消标记(handler 轮询)
        created_by TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0,
        started_at INTEGER DEFAULT 0,
        finished_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_jobs_state ON arch_semantic_jobs(project_id, state);

    -- 组件级聚合视图缓存(批3)：LLM 归并产物的持久缓存(虚拟节点内容，可清除重生成)。
    -- 组成关系不落此表——成员为运行时动态解析(需求 3-C)。
    CREATE TABLE IF NOT EXISTS arch_component_views (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        component_id TEXT DEFAULT '',
        rev TEXT DEFAULT 'workspace',
        facets TEXT DEFAULT '{}',           -- JSON: 4 面(capability/interface_facet/control_logic/data_ownership)
        members TEXT DEFAULT '[]',          -- JSON: 生成时的成员资产 id 快照(溯源)
        status TEXT DEFAULT 'active',       -- active | stale
        model_id TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0,
        generated_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_compview ON arch_component_views(project_id, component_id, rev);

    -- 需求草稿(批B)：非会话模式的 AI 辅助需求文本编辑载体；终产物=需求卡(发布到会话)。
    -- last_proposed_md：AI 处理产物(未采纳也保留，仅 UI 参考，不进下轮上下文)。
    CREATE TABLE IF NOT EXISTS arch_req_drafts (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        title TEXT DEFAULT '',
        content_md TEXT DEFAULT '',            -- 正文(md；可含 mermaid/plantuml/dot 块与 agent 指令标记块)
        last_proposed_md TEXT DEFAULT '',      -- 最近一轮 AI 产物(未采纳参考；采纳时拷入 content_md 并清空)
        last_proposed_at INTEGER DEFAULT 0,
        status TEXT DEFAULT 'editing',         -- editing | archived(已发布只读)
        parent_id TEXT DEFAULT '',             -- 续写溯源(归档草稿的副本)
        published_conv_id TEXT DEFAULT '',     -- 发布目标会话
        published_req_id TEXT DEFAULT '',      -- 产出的需求卡
        tags TEXT DEFAULT '[]',                -- JSON: ["tag",...] 自定义标签(泛化分类)
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_reqdrafts ON arch_req_drafts(project_id, status, updated_at);

    CREATE TABLE IF NOT EXISTS arch_symbol_notes (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        symbol_key TEXT DEFAULT '',            -- 符号 qualified_name(链路跟踪符号卡 AI 解读缓存)
        note TEXT DEFAULT '',
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_symnotes ON arch_symbol_notes(project_id, symbol_key);

    CREATE TABLE IF NOT EXISTS arch_logic_views (
        id TEXT PRIMARY KEY,
        project_id TEXT DEFAULT '',
        name TEXT DEFAULT '',                 -- 视图名(业务逻辑链名)
        core_ids TEXT DEFAULT '[]',           -- 核心(种子)实现资产 id JSON——分析起点非范围
        member_ids TEXT DEFAULT '[]',         -- 成员全集(核心+agent 拓展) JSON
        summary TEXT DEFAULT '',              -- LLM 文字概括
        source TEXT DEFAULT 'manual',         -- extract(提取归纳) | manual(手动新建)
        fingerprint TEXT DEFAULT '',          -- 成员集指纹(name+sorted members，upsert 判重)
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_arch_logicviews ON arch_logic_views(project_id, updated_at);

    CREATE TABLE IF NOT EXISTS arch_semantic_assets (
        id TEXT PRIMARY KEY,
        schema_version INTEGER DEFAULT 1,  -- K1 格式版本化(登记: docs/architect/kb-schema-versions.md)
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
        rev TEXT DEFAULT '',                -- 锚点视角(批1-1): baseline:<kbVersion> | head:<sha> | workspace | ''(legacy)
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

    -- ── architect 自有图谱基线(数据主权批A) ──────────────────────────────
    -- KB 转纯算力服务(parseFileAst/communityFromGraph)，分析结果按项目+rev
    -- 落 architect 库；rev 沿用锚点前缀 baseline:<commit> | head:<sha> |
    -- workspace(与 arch_semantic_assets.rev 同族，底座判定 LIKE 'baseline:%'
    -- 天然兼容，存量 baseline:<kbVersion> 行不受影响)。
    CREATE TABLE IF NOT EXISTS arch_graph_node (
        project_id TEXT NOT NULL,
        rev TEXT NOT NULL DEFAULT '',
        id TEXT NOT NULL,                   -- cache:file::name::line(_norm_cache_symbol 规则, 与 codegraph 同构模型)
        kind TEXT DEFAULT '',
        name TEXT DEFAULT '',
        qualified_name TEXT DEFAULT '',
        file_path TEXT DEFAULT '',
        language TEXT DEFAULT '',
        start_line INTEGER DEFAULT 0,
        end_line INTEGER DEFAULT 0,
        start_column INTEGER DEFAULT 0,
        end_column INTEGER DEFAULT 0,
        signature TEXT DEFAULT '',
        docstring TEXT DEFAULT '',
        return_type TEXT DEFAULT '',
        is_exported INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        PRIMARY KEY (project_id, rev, id)
    );
    CREATE INDEX IF NOT EXISTS idx_ag_node_file ON arch_graph_node(project_id, rev, file_path);
    CREATE INDEX IF NOT EXISTS idx_ag_node_name ON arch_graph_node(project_id, rev, name);

    CREATE TABLE IF NOT EXISTS arch_graph_edge (
        project_id TEXT NOT NULL,
        rev TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL,               -- 节点 id 或符号名(跨文件未解析时, 消费方 name_of 兼容)
        target TEXT NOT NULL,
        kind TEXT NOT NULL,                 -- calls | contains | imports | references | extends | instantiates | implements
        line INTEGER DEFAULT 0,
        col INTEGER DEFAULT 0,
        -- PK 不含 line: KB make_edge_id(src,tgt,kind) 同对节点合并为 1 条
        -- (用户裁决: 与 KB 完全一致, 不自加策略)。
        PRIMARY KEY (project_id, rev, source, target, kind)
    );
    CREATE INDEX IF NOT EXISTS idx_ag_edge_source ON arch_graph_edge(project_id, rev, source);
    CREATE INDEX IF NOT EXISTS idx_ag_edge_target ON arch_graph_edge(project_id, rev, target);

    -- 组件(批B 社区分组结果承载；批A 建表)。最小消费形状 {id,name,owns,parentId}
    -- 直配 sem/catalog 接缝(catalog 切 arch_only 后五消费方零改动)。
    CREATE TABLE IF NOT EXISTS arch_components (
        project_id TEXT NOT NULL,
        rev TEXT NOT NULL DEFAULT '',
        id TEXT NOT NULL,
        name TEXT DEFAULT '',
        summary TEXT DEFAULT '',
        owns TEXT DEFAULT '[]',             -- JSON: 相对路径[]
        source TEXT DEFAULT 'community',    -- community | manual
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        PRIMARY KEY (project_id, rev, id)
    );
    CREATE INDEX IF NOT EXISTS idx_ag_comp ON arch_components(project_id, rev);

    CREATE TABLE IF NOT EXISTS arch_component_hierarchy (
        project_id TEXT NOT NULL,
        rev TEXT NOT NULL DEFAULT '',
        child_id TEXT NOT NULL,
        parent_id TEXT DEFAULT '',          -- '' = 顶层
        level INTEGER DEFAULT 0,
        PRIMARY KEY (project_id, rev, child_id)
    );

    CREATE TABLE IF NOT EXISTS arch_component_naming (
        project_id TEXT NOT NULL,
        rev TEXT NOT NULL DEFAULT '',
        component_id TEXT NOT NULL,
        name TEXT DEFAULT '',
        summary TEXT DEFAULT '',
        model_id TEXT DEFAULT '',
        status TEXT DEFAULT 'active',       -- active | stale(owns/rev 变化后)
        fingerprint TEXT DEFAULT '',        -- 生成时 owns 集指纹(变更判定)
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        PRIMARY KEY (project_id, rev, component_id)
    );

    CREATE TABLE IF NOT EXISTS arch_graph_partitions (
        project_id TEXT NOT NULL,
        head TEXT NOT NULL DEFAULT '',      -- 提案时的 git HEAD
        idx INTEGER NOT NULL,               -- 分区序号
        files TEXT DEFAULT '[]',            -- 文件相对路径 JSON 数组
        langs TEXT DEFAULT '[]',            -- 语言构成 JSON 数组
        est_symbols INTEGER DEFAULT 0,      -- 预估符号数
        reason TEXT DEFAULT '',             -- 拆分原因(连通分量/目录装箱/语言合并)
        state TEXT DEFAULT 'proposed',      -- proposed|confirmed|running|done|error|skipped
        created_at INTEGER DEFAULT 0,
        updated_at INTEGER DEFAULT 0,
        PRIMARY KEY (project_id, head, idx)
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
        schema_version INTEGER DEFAULT 1,  -- K1 格式版本化(登记: docs/architect/kb-schema-versions.md)
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
    # 环节十一: arch_tasks 兼主库路由(无项目上下文写入主库)——基点快照列两库都补
    _add_cols(db, "arch_tasks", [
        # cv-201: 执行形态 inplace(就地) | worktree(隔离)——merge/finish 守卫
        # 依据; 缺省 ''=旧任务(未知), 走原 git 流不短路
        ("workspace", "TEXT DEFAULT ''"),
        ("base_commit", "TEXT DEFAULT ''"),
        ("merged_at", "INTEGER DEFAULT 0"),
        ("merged_head", "TEXT DEFAULT ''"),
    ])
    # 流程相位缓存 + 任务安全等级(无项目上下文写主库 → 两库同补, 幂等)
    _add_cols(db, "arch_conversations", [
        ("flow_state", "TEXT DEFAULT ''"),
        ("flow_state_at", "INTEGER DEFAULT 0"),
    ])
    _add_cols(db, "arch_tasks", [
        ("safety_class", "TEXT DEFAULT 'mutating'"),
        ("work_tags", "TEXT"),
        ("dismissed_at", "INTEGER DEFAULT 0"),
    ])
    # 环节十四: 需求任务计划列(需求表无 project_id, 主库/项目库双补)
    _add_cols(db, "arch_requirements", [
        ("task_plan", "TEXT"),
    ])
    # 环节十四: 需求任务计划(JSON, [{seq,title,instruction,taskId,status}])——
    # 需求表无 project_id 列, 主库/项目库路由双补
    _add_cols(db, "arch_requirements", [
        ("task_plan", "TEXT"),
    ])


# 已退役表(重整裁决: 清除旧数据, 不做兼容)
_DROPPED_TABLES = ("arch_bus_messages", "arch_session_roles",
                   "arch_name_tombstones", "arch_user_overlays")   # 批6 裁决删除(墓碑死池/overlay 假重放机制)


def _drop_retired_tables(db) -> None:
    for t in _DROPPED_TABLES:
        db.execute(f"DROP TABLE IF EXISTS {t}")


def _rebuild_legacy_arch_assets(db) -> None:
    """arch_assets 两代同名旧表兜底(须在各库 DDL executescript 前调用)。

    旧 schema(id/conversation_id/title/content/meta…)残留时 CREATE TABLE
    IF NOT EXISTS 永不生效, 新代码 ORDER BY name 直接崩(no such column)。
    空旧表 → DROP(随后 DDL 按新结构重建); 非空旧表 → 幂等补列保数据可读。"""
    try:
        cols = {r["name"] for r in db.fetchall("PRAGMA table_info(arch_assets)")}
    except Exception:  # noqa: BLE001 — 无表/无权限: 交给后续 DDL
        return
    if not cols or "name" in cols:
        return
    try:
        row = db.fetchone("SELECT COUNT(*) FROM arch_assets")
        cnt = row[0] if row else 0
    except Exception:  # noqa: BLE001
        cnt = 0
    if cnt == 0:
        db.execute("DROP TABLE arch_assets")
    else:
        _add_cols(db, "arch_assets", [
            ("name", "TEXT DEFAULT ''"),
            ("description", "TEXT DEFAULT ''"),
            ("payload", "TEXT DEFAULT '{}'"),
            ("enabled", "INTEGER DEFAULT 1"),
        ])


def architect_db_migrations(db) -> None:
    """architect 主库增量迁移(旧库补列/补表)。幂等: 已存在跳过。"""
    _rebuild_legacy_arch_assets(db)
    db.executescript(ARCH_MAIN_TABLES_SQL)
    _drop_retired_tables(db)
    _main_migrations(db)


# ── 项目库迁移(旧项目库升级兜底，幂等) ─────────────────────────

def _migrate_edge_line_pk(db) -> None:
    """arch_graph_edge PK 撤 line(回 KB make_edge_id 口径: 同对节点 1 条边)。

    SQLite 不能改 PK → 检测 PK 含 line 则重建表迁数据(OR IGNORE 合并)。幂等。"""
    cols = {r[1]: r for r in db.execute("PRAGMA table_info(arch_graph_edge)").fetchall()}
    if not cols:
        return
    pk_cols = [r[1] for r in sorted(
        (r for r in cols.values() if r[5]), key=lambda r: r[5])]
    if "line" not in pk_cols:
        return  # 已是目标 PK
    db.executescript("""
CREATE TABLE arch_graph_edge_new (
    project_id TEXT NOT NULL,
    rev TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL,
    target TEXT NOT NULL,
    kind TEXT NOT NULL,
    line INTEGER DEFAULT 0,
    col INTEGER DEFAULT 0,
    PRIMARY KEY (project_id, rev, source, target, kind)
);
INSERT OR IGNORE INTO arch_graph_edge_new
    SELECT project_id, rev, source, target, kind, line, col FROM arch_graph_edge;
DROP TABLE arch_graph_edge;
ALTER TABLE arch_graph_edge_new RENAME TO arch_graph_edge;
CREATE INDEX IF NOT EXISTS idx_ag_edge_source ON arch_graph_edge(project_id, rev, source);
CREATE INDEX IF NOT EXISTS idx_ag_edge_target ON arch_graph_edge(project_id, rev, target);
""")
    db.commit()


def _migrate_lifecycle_v2(db) -> None:
    """生命周期重构迁移(一次性, 幂等; 新鲜库各列默认即新模型, 无行可迁)。

    - RQ: 首次(无 spec_versions) → 由存量 analysis/status 初始化 v1 版本
      (analyzed/pool → confirmed+ready; raw → draft; cancelled/done 保持); 登记所有权。
    - 会话: kind=execution 旧执行会话删除(含消息); roles 空 → 由 role_id 推导;
      work_state 空 → architect; 旧 status=running → active(相位由作业账本推导)。
    """
    import json as _json
    now = int(__import__("time").time() * 1000)
    # ── RQ → spec v1 ──
    try:
        rows = db.fetchall(
            "SELECT id, title, desc, analysis, status, source_conversation_id, updated_at "
            "FROM arch_requirements WHERE spec_versions IS NULL")
    except Exception:
        rows = []
    for r in rows:
        try:
            a = _json.loads(r["analysis"]) if r["analysis"] else {}
        except Exception:
            a = {}
        if not isinstance(a, dict):
            a = {}
        old_status = (r["status"] or "").lower()
        confirmed = old_status in ("analyzed",) or old_status == "ready"
        snap = {
            "title": r["title"] or "", "desc": r["desc"] or "",
            "functionalScope": a.get("functionalScope") or [],
            "designMd": a.get("designMd") or str(a.get("implementationPath") or ""),
            "allowedScope": a.get("allowedScope") or [],
            "forbiddenScope": a.get("forbiddenScope") or [],
            "acceptance": a.get("acceptance") or [],
            "assessmentSummary": str(a.get("assessmentSummary") or ""),
            "estMin": a.get("estMin") or 0,
        }
        v1 = {"ver": 1,
              "state": "confirmed" if confirmed else "draft",
              "snapshot": snap,
              "source": {"convId": r["source_conversation_id"] or "", "actor": "migration"},
              "reason": "存量规约迁移初始化", "createdAt": r["updated_at"] or now}
        new_status = "ready" if confirmed else ("cancelled" if old_status == "cancelled" else "draft")
        db.execute(
            "UPDATE arch_requirements SET spec_versions=?, active_ver=1, status=?, "
            "owner_conv=COALESCE(NULLIF(?,''), '') WHERE id=?",
            (_json.dumps([v1], ensure_ascii=False), new_status,
             r["source_conversation_id"] or "", r["id"]))
    if rows:
        db.commit()
    # ── 会话: 删旧执行会话 + roles/work_state 初始化 ──
    try:
        db.execute(
            "DELETE FROM arch_conversation_messages WHERE conversation_id IN "
            "(SELECT id FROM arch_conversations WHERE kind='execution')")
        db.execute("DELETE FROM arch_conversations WHERE kind='execution'")
    except Exception:
        pass
    try:
        legacy_roles = db.fetchall(
            "SELECT id, role_id FROM arch_conversations WHERE roles IS NULL")
    except Exception:
        legacy_roles = []
    for r in legacy_roles:
        rid = r.get("role_id") or ""
        roles = [rid] if rid and rid != "architect" else ["architect"]
        db.execute("UPDATE arch_conversations SET roles=?, work_state='architect' WHERE id=?",
                   (_json.dumps(roles, ensure_ascii=False), r["id"]))
    try:
        db.execute("UPDATE arch_conversations SET status='active' WHERE status='running'")
    except Exception:
        pass
    if legacy_roles:
        db.commit()


def _project_migrations(db) -> None:
    # 草稿 tags(概念泛化分类; ≤64B/个): 联想备选由行聚合
    _add_cols(db, "arch_req_drafts", [("tags", "TEXT DEFAULT '[]'")])
    # 会话模型 v3: coding 子会话归属 + 执行器一次绑定 + 执行器会话引用
    _add_cols(db, "arch_conversations", [
        ("parent_conv_id", "TEXT DEFAULT ''"),
        ("executor_id", "TEXT DEFAULT ''"),
        ("session_ref", "TEXT DEFAULT ''"),
        ("executor_model", "TEXT DEFAULT ''"),
    ])
    try:   # 索引须在补列之后创建(旧库表已存在, 建表段不带新列)
        db.execute("CREATE INDEX IF NOT EXISTS idx_arch_convs_parent "
                   "ON arch_conversations(parent_conv_id)")
    except Exception:  # noqa: BLE001
        pass
    try:   # 角色目录退役: roles 列旧绑定数据清洗(新模型绑定面=executor_id)
        db.execute("UPDATE arch_conversations SET roles = '[\"architect\"]' "
                   "WHERE roles IS NOT NULL AND roles != '[\"architect\"]'")
    except Exception:  # noqa: BLE001
        pass
    _drop_retired_tables(db)
    # M0 冻结: 语义资产作废态（标准变更 → 整体作废，行保留可溯源；plan-C-M0 §6.4）
    _add_cols(db, "arch_semantic_assets", [
        ("voided_reason", "TEXT DEFAULT ''"),
        ("voided_at", "INTEGER DEFAULT 0"),
        ("voided_by", "TEXT DEFAULT ''"),
        ("voided_framework_version", "INTEGER DEFAULT 0"),
        ("stale_by_framework", "INTEGER DEFAULT 0"),
        # WS8 提升通道: 全局桶行记录来源项目
        ("origin_project_id", "TEXT DEFAULT ''"),
        # 锚点视角(批1-1): baseline:<kbVersion> | head:<sha> | workspace | ''(legacy)
        ("rev", "TEXT DEFAULT ''"),
    ])
    # 索引须在补列之后创建(存量表 rev 靠 _add_cols 补齐，DDL 段建索引会失败)
    db.execute("CREATE INDEX IF NOT EXISTS idx_arch_semantic_rev "
               "ON arch_semantic_assets(project_id, rev)")
    _add_cols(db, "arch_naming_conventions", [
        ("origin_project_id", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_capability_proposals", [
        ("origin_project_id", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_requirements", [
        ("asset_invalidated", "INTEGER DEFAULT 0"),
        ("asset_invalidated_at", "INTEGER DEFAULT 0"),
        ("spec_versions", "TEXT"),
        ("active_ver", "INTEGER DEFAULT 0"),
        ("done_mark", "INTEGER DEFAULT 0"),
        ("done_at", "INTEGER DEFAULT 0"),
        ("owner_conv", "TEXT DEFAULT ''"),
        ("source_type", "TEXT DEFAULT ''"),
        ("source_conversation_id", "TEXT DEFAULT ''"),
        ("created_at", "INTEGER DEFAULT 0"),
        ("task_plan", "TEXT"),
    ])
    _add_cols(db, "arch_conversations", [
        ("tags", "TEXT"),
        ("summary", "TEXT DEFAULT ''"),
        ("review_state", "TEXT DEFAULT 'read'"),
        ("roles", "TEXT"),
        ("work_state", "TEXT DEFAULT 'architect'"),
        ("analysis_mode", "TEXT DEFAULT 'strict'"),
        # cv-190: 需求澄清挡位 auto(有缺口才问) | forced(先澄清后落卡)
        ("clarify_mode", "TEXT DEFAULT 'auto'"),
        # cv-202: worktree 隔离模式(0=就地缺省 | 1=显式要求隔离执行)
        ("isolated", "INTEGER DEFAULT 0"),
        # 流程相位缓存(governance/flow.py derive-on-write; 事件驱动迁移, 可重建)
        ("flow_state", "TEXT DEFAULT ''"),
        ("flow_state_at", "INTEGER DEFAULT 0"),
    ])
    # v2 统一会话: 消息 agent 标注(''=architect 外循环; cline/opencode/codex=subagent)
    _add_cols(db, "arch_conversation_messages", [
        ("agent", "TEXT DEFAULT ''"),
    ])
    _add_cols(db, "arch_tasks", [
        # cv-201: 执行形态 inplace(就地) | worktree(隔离)——merge/finish 守卫
        # 依据; 缺省 ''=旧任务(未知), 走原 git 流不短路
        ("workspace", "TEXT DEFAULT ''"),
        ("spec_ver", "INTEGER DEFAULT 0"),
        # 环节十一: 任务分支基点 commit(交接边界快照)——里程碑比对/合并入口
        # precheck(主目录是否前移)的数据源
        ("base_commit", "TEXT DEFAULT ''"),
        # 环节十五: 本地 PR 语义——合并门禁终态(merged_at>0 = 已合并关闭)
        ("merged_at", "INTEGER DEFAULT 0"),
        ("merged_head", "TEXT DEFAULT ''"),
        # V1 验收门禁: 任务级 P0 显式配置(verify.py 发现链最高权威)
        ("verify_config", "TEXT"),
        # 任务安全等级三值轴(互斥/worktree/门禁) + 开放工作类型标签 + 回执已阅
        ("safety_class", "TEXT DEFAULT 'mutating'"),
        ("work_tags", "TEXT"),
        ("dismissed_at", "INTEGER DEFAULT 0"),
    ])
    _migrate_lifecycle_v2(db)
    _migrate_edge_line_pk(db)
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
        # 锚点视角(批1-1): baseline:<kbVersion> | head:<sha> | workspace | ''(legacy)
        ("rev", "TEXT DEFAULT ''"),
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
    _add_cols(db, "arch_logic_views", [
        ("detail", "TEXT DEFAULT ''"),      # AI 详细语义讲解(Markdown, 手动触发缓存)
        ("detail_fp", "TEXT DEFAULT ''"),   # 讲解指纹(成员资产 srcHash 聚合)——成员变化即失效
    ])


def init_architect_db(db) -> None:
    """初始化 architect 主库。db 为打开 architect.db 的 SQLiteContext。

    主库 = 全局表 + arch_projects 注册表 + 全局 id 序列，同时容纳项目表作为
    「未绑定项目」的默认桶(无项目上下文时的读写落点)。
    """
    _rebuild_legacy_arch_assets(db)
    db.executescript(ARCH_MAIN_TABLES_SQL + "\n" + ARCH_PROJECT_TABLES_SQL)
    _main_migrations(db)
    _project_migrations(db)


def init_architect_project_db(db) -> None:
    """初始化 architect 项目库(architect/<pid>/arch.db)。幂等。"""
    _rebuild_legacy_arch_assets(db)
    db.executescript(ARCH_PROJECT_TABLES_SQL)
    _project_migrations(db)
