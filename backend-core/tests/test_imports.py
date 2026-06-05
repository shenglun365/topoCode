"""Verify all core modules can be imported without errors."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


class TestCoreImports:
    def test_import_config(self):
        import config
        assert hasattr(config, "MAX_AST_NODES")

    def test_import_rpc_ids(self):
        import rpc_ids
        assert hasattr(rpc_ids, "get_rpc_id")

    def test_import_sqlite_ctx(self):
        import sqlite_ctx
        assert hasattr(sqlite_ctx, "SQLiteContext")

    def test_import_logging_config(self):
        import logging_config
        assert hasattr(logging_config, "setup_logging")

    def test_import_core_service(self):
        import core_service
        assert hasattr(core_service, "register_project_methods")
        assert hasattr(core_service, "GitIgnoreParser")
