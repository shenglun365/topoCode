"""CHAT_DB_TABLES_SQL（MS5-V0 自 db/manager.py 外置；内容与原内联块逐字节一致）。

冻结契约：与 tests/ddl_golden.py 的 golden 快照全等（test_db_schema_parity.py）。
"""

CHAT_DB_TABLES_SQL = """
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
