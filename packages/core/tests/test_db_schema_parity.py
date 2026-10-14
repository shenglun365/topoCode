"""MS5-V0 冻结契约：db/schema/* 五段 DDL 与 pre-MS5 golden 快照逐字节全等。

修改 DDL 的正确流程：改 schema/*.py → 同步 ddl_golden.py → 迁移块（_migrate_*）评审。
"""
from topoone.db.schema.main import MAIN_DB_TABLES_SQL
from topoone.db.schema.knowledge import KNOWLEDGE_DB_TABLES_SQL
from topoone.db.schema.sessions import SESSIONS_DB_TABLES_SQL
from topoone.db.schema.chat import CHAT_DB_TABLES_SQL
from topoone.db.schema.project import PROJECT_DB_TABLES_SQL

from ddl_golden import (  # 同目录 golden（pytest rootdir 插入 sys.path）
    GOLDEN_MAIN_DB_TABLES_SQL,
    GOLDEN_KNOWLEDGE_DB_TABLES_SQL,
    GOLDEN_SESSIONS_DB_TABLES_SQL,
    GOLDEN_CHAT_DB_TABLES_SQL,
    GOLDEN_PROJECT_DB_TABLES_SQL,
)


def test_main_ddl_parity():
    assert MAIN_DB_TABLES_SQL == GOLDEN_MAIN_DB_TABLES_SQL


def test_knowledge_ddl_parity():
    assert KNOWLEDGE_DB_TABLES_SQL == GOLDEN_KNOWLEDGE_DB_TABLES_SQL


def test_sessions_ddl_parity():
    assert SESSIONS_DB_TABLES_SQL == GOLDEN_SESSIONS_DB_TABLES_SQL


def test_chat_ddl_parity():
    assert CHAT_DB_TABLES_SQL == GOLDEN_CHAT_DB_TABLES_SQL


def test_project_ddl_parity():
    assert PROJECT_DB_TABLES_SQL == GOLDEN_PROJECT_DB_TABLES_SQL
