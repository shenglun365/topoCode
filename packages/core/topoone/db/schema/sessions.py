"""SESSIONS_DB_TABLES_SQL（MS5-V0 自 db/manager.py 外置；内容与原内联块逐字节一致）。

冻结契约：与 tests/ddl_golden.py 的 golden 快照全等（test_db_schema_parity.py）。
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
