"""Verify kernel (topoone) modules import without errors; engine service (M03) importable."""

import sys
import os

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend-core"))


class TestCoreImports:
    def test_import_config(self):
        from topoone import config
        assert hasattr(config, "MAX_AST_NODES")

    def test_import_rpc_ids(self):
        from topoone.rpc import rpc_ids
        assert hasattr(rpc_ids, "get_rpc_id")

    def test_import_sqlite_ctx(self):
        from topoone.db import manager as sqlite_ctx
        assert hasattr(sqlite_ctx, "SQLiteContext")

    def test_import_logging_config(self):
        from topoone import logging_config
        assert hasattr(logging_config, "setup_logging")

    def test_import_data_layer(self):
        from topoone.db import data_layer
        assert hasattr(data_layer, "WriteQueue")
        assert hasattr(data_layer, "CacheStore")
        assert hasattr(data_layer, "DuckDBReader")

    def test_import_messaging(self):
        from topoone.messaging import bus
        assert hasattr(bus, "MessageBus")

    def test_import_engine_service(self):
        import topoone.engine.service as engine_service
        from topoone.engine.service import _common
        assert hasattr(engine_service, "register_project_methods")
        assert hasattr(engine_service, "register_all_engine_methods")
        assert hasattr(_common, "_ensure_topocode_dirs_in_gitignore")
