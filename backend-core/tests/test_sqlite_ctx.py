"""Test sqlite_ctx module."""

import sys
import os
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sqlite_ctx import SQLiteContext


class TestSQLiteContext:
    def test_constructor_creates_db_file(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ctx = SQLiteContext(db_path)
            assert os.path.exists(db_path)
            ctx.close()
        finally:
            os.unlink(db_path)

    def test_execute_and_fetchall(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ctx = SQLiteContext(db_path)
            ctx.execute("CREATE TABLE test (id INTEGER, name TEXT)")
            ctx.execute("INSERT INTO test VALUES (?, ?)", (1, "hello"))
            rows = ctx.fetchall("SELECT * FROM test")
            assert len(rows) == 1
            assert rows[0]["name"] == "hello"
            ctx.close()
        finally:
            os.unlink(db_path)

    def test_fetchone_returns_none_for_empty(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name
        try:
            ctx = SQLiteContext(db_path)
            ctx.execute("CREATE TABLE test (id INTEGER)")
            row = ctx.fetchone("SELECT * FROM test WHERE id = ?", (999,))
            assert row is None
            ctx.close()
        finally:
            os.unlink(db_path)
