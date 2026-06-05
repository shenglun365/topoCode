"""Tests for new pipeline functions:
- extract_graph_symbols (extract_global_symbols.py)
- extract_call_edges_from_refs (extract_call_graph.py)
- extract_dep_edges_from_imports (parse_with_queries.py)

These functions read from graph_node (via SQLiteAdapter.find_graph)
and produce reformatted records (func_name, class_name, call_relation, dependence).
"""

import sys
import os
import sqlite3
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "backend-core"))

import pytest
from sqlite_ctx import SQLiteContext
from parsers.db_adapter import SQLiteAdapter
from parsers.extract_global_symbols import extract_graph_symbols
from parsers.extract_call_graph import extract_call_edges_from_refs
from parsers.parse_with_queries import extract_dep_edges_from_imports
from store.schema import init_project_schema

TASK_ID = "test-pipeline-001"


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    ctx = SQLiteContext(db_path)
    ctx.conn.execute("PRAGMA foreign_keys=OFF")
    init_project_schema(ctx)
    yield ctx
    ctx.close()
    os.unlink(db_path)


@pytest.fixture
def adapter(db):
    return SQLiteAdapter(db, TASK_ID)


def insert_graph(db, **kw):
    kw.setdefault("task_id", TASK_ID)
    cols = ", ".join(kw)
    ph = ", ".join(["?"] * len(kw))
    db.execute(f"INSERT INTO graph_node ({cols}) VALUES ({ph})", tuple(kw.values()))


def fetchall(db, sql):
    return db.execute(sql).fetchall()


# ===============================================================
#  extract_graph_symbols
# ===============================================================

class TestExtractGraphSymbols:

    def test_no_symbols_returns_zero(self, adapter):
        assert extract_graph_symbols(adapter) == 0

    def test_function_kind_produces_func_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="hello", kind="function", scope="module",
                     start_line="1", end_line="5")
        assert extract_graph_symbols(adapter) == 1
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='func_name'")
        assert len(rows) == 1
        r = rows[0]
        assert r["func_name"] == "hello"
        assert r["file_id"] == "a.ts"
        assert r["start_line"] == "1"
        assert r["end_line"] == "5"

    def test_method_kind_produces_func_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="bar", kind="method", scope="class.Foo",
                     start_line="10", end_line="20")
        assert extract_graph_symbols(adapter) == 1
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='func_name'")
        assert len(rows) == 1
        assert rows[0]["func_name"] == "bar"

    def test_variable_kind_produces_func_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="count", kind="variable", scope="module",
                     start_line="1", end_line="1")
        assert extract_graph_symbols(adapter) == 1
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='func_name'")
        assert len(rows) == 1
        assert rows[0]["func_name"] == "count"

    def test_parameter_kind_produces_func_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="arg", kind="parameter", scope="module",
                     start_line="1", end_line="1")
        assert extract_graph_symbols(adapter) == 1
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='func_name'")
        assert len(rows) == 1
        assert rows[0]["func_name"] == "arg"

    def test_class_kind_produces_class_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="MyClass", kind="class", scope="module",
                     start_line="1", end_line="10")
        assert extract_graph_symbols(adapter) == 1
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='class_name'")
        assert len(rows) == 1
        r = rows[0]
        assert r["class_name"] == "MyClass"
        assert r["file_id"] == "a.ts"
        assert r["start_line"] == "1"
        assert r["end_line"] == "10"

    def test_interface_kind_produces_class_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="MyInterface", kind="interface", scope="module",
                     start_line="1", end_line="5")
        assert extract_graph_symbols(adapter) == 1
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='class_name'")
        assert len(rows) == 1
        assert rows[0]["class_name"] == "MyInterface"

    def test_enum_kind_produces_class_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="Color", kind="enum", scope="module",
                     start_line="1", end_line="5")
        assert extract_graph_symbols(adapter) == 1
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='class_name'")
        assert len(rows) == 1
        assert rows[0]["class_name"] == "Color"

    def test_type_alias_kind_produces_class_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="MyType", kind="type_alias", scope="module",
                     start_line="1", end_line="1")
        assert extract_graph_symbols(adapter) == 1
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='class_name'")
        assert len(rows) == 1
        assert rows[0]["class_name"] == "MyType"

    def test_ignores_unknown_kind(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="unknown", kind="other", scope="module",
                     start_line="1", end_line="1")
        assert extract_graph_symbols(adapter) == 0

    def test_ignores_symbol_without_name(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="", kind="function", scope="module",
                     start_line="1", end_line="1")
        assert extract_graph_symbols(adapter) == 0

    def test_mixed_kinds_produces_both_types(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="foo", kind="function", scope="module",
                     start_line="1", end_line="3")
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="Bar", kind="class", scope="module",
                     start_line="5", end_line="15")
        assert extract_graph_symbols(adapter) == 2
        func_rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='func_name'")
        class_rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='class_name'")
        assert len(func_rows) == 1
        assert func_rows[0]["func_name"] == "foo"
        assert len(class_rows) == 1
        assert class_rows[0]["class_name"] == "Bar"

    def test_re_run_appends_new_records(self, db, adapter):
        insert_graph(db, symbol_node_type="symbol", file_id="a.ts",
                     name="foo", kind="function", scope="module",
                     start_line="1", end_line="3")
        extract_graph_symbols(adapter)
        count_after_first = len(
            fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='func_name'")
        )
        extract_graph_symbols(adapter)
        count_after_second = len(
            fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='func_name'")
        )
        assert count_after_first == 1
        assert count_after_second == 2


# ===============================================================
#  extract_call_edges_from_refs
# ===============================================================

class TestExtractCallEdgesFromRefs:

    def test_no_refs_returns_empty_list(self, adapter):
        assert extract_call_edges_from_refs(adapter) == []

    def test_no_call_refs_returns_empty_list(self, db, adapter):
        insert_graph(db, symbol_node_type="reference", file_id="a.ts",
                     name="Foo", kind="type_ref", scope="module",
                     start_line="1", end_line="1", target="")
        assert extract_call_edges_from_refs(adapter) == []

    def test_call_ref_produces_call_relation(self, db, adapter):
        insert_graph(db, symbol_node_type="reference", file_id="a.ts",
                     name="doSomething", kind="call", scope="module",
                     start_line="10", end_line="10", target="")
        result = extract_call_edges_from_refs(adapter)
        assert len(result) == 1
        r = result[0]
        assert r["symbol_node_type"] == "call_relation"
        assert r["caller_file_id"] == "a.ts"
        assert r["caller_func_name"] == "module"
        assert r["callee_name"] == "doSomething"
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='call_relation'")
        assert len(rows) == 1
        assert rows[0]["callee_name"] == "doSomething"

    def test_multiple_call_refs(self, db, adapter):
        insert_graph(db, symbol_node_type="reference", file_id="a.ts",
                     name="foo", kind="call", scope="bar",
                     start_line="1", end_line="1", target="")
        insert_graph(db, symbol_node_type="reference", file_id="b.ts",
                     name="baz", kind="call", scope="qux",
                     start_line="5", end_line="5", target="")
        result = extract_call_edges_from_refs(adapter)
        assert len(result) == 2
        assert result[0]["callee_name"] == "foo"
        assert result[1]["callee_name"] == "baz"

    def test_mixed_refs_filters_correctly(self, db, adapter):
        insert_graph(db, symbol_node_type="reference", file_id="a.ts",
                     name="callFn", kind="call", scope="module",
                     start_line="1", end_line="1", target="")
        insert_graph(db, symbol_node_type="reference", file_id="a.ts",
                     name="SomeType", kind="type_ref", scope="module",
                     start_line="2", end_line="2", target="")
        insert_graph(db, symbol_node_type="reference", file_id="a.ts",
                     name="x", kind="ident", scope="module",
                     start_line="3", end_line="3", target="")
        result = extract_call_edges_from_refs(adapter)
        assert len(result) == 1
        assert result[0]["callee_name"] == "callFn"

    def test_caller_func_name_uses_ref_scope(self, db, adapter):
        insert_graph(db, symbol_node_type="reference", file_id="a.ts",
                     name="helper", kind="call", scope="class.MyClass.method.foo",
                     start_line="5", end_line="5", target="")
        result = extract_call_edges_from_refs(adapter)
        assert len(result) == 1
        assert result[0]["caller_func_name"] == "class.MyClass.method.foo"

    def test_persisted_call_edges_are_queryable(self, db, adapter):
        insert_graph(db, symbol_node_type="reference", file_id="a.ts",
                     name="process", kind="call", scope="main",
                     start_line="1", end_line="1", target="")
        extract_call_edges_from_refs(adapter)
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='call_relation'")
        assert len(rows) == 1
        assert rows[0]["callee_name"] == "process"
        assert rows[0]["caller_file_id"] == "a.ts"
        assert rows[0]["caller_func_name"] == "main"


# ===============================================================
#  extract_dep_edges_from_imports
# ===============================================================

class TestExtractDepEdgesFromImports:

    def test_no_imports_returns_empty_list(self, adapter):
        assert extract_dep_edges_from_imports(adapter) == []

    def test_import_produces_dependence(self, db, adapter):
        insert_graph(db, symbol_node_type="import", file_id="a.ts",
                     name="lodash", kind="import", scope="module",
                     start_line="1", end_line="1", target="")
        result = extract_dep_edges_from_imports(adapter)
        assert len(result) == 1
        r = result[0]
        assert r["symbol_node_type"] == "dependence"
        assert r["file_id"] == "a.ts"
        assert r["include_path"] == "lodash"
        assert r["is_system"] == 0

    def test_multiple_imports(self, db, adapter):
        insert_graph(db, symbol_node_type="import", file_id="a.ts",
                     name="react", kind="import", scope="module",
                     start_line="1", end_line="1", target="")
        insert_graph(db, symbol_node_type="import", file_id="a.ts",
                     name="./utils", kind="import", scope="module",
                     start_line="2", end_line="2", target="")
        insert_graph(db, symbol_node_type="import", file_id="b.ts",
                     name="fs", kind="import", scope="module",
                     start_line="1", end_line="1", target="")
        result = extract_dep_edges_from_imports(adapter)
        assert len(result) == 3

    def test_persisted_dep_edges_are_queryable(self, db, adapter):
        insert_graph(db, symbol_node_type="import", file_id="a.ts",
                     name="express", kind="import", scope="module",
                     start_line="1", end_line="1", target="")
        extract_dep_edges_from_imports(adapter)
        rows = fetchall(db, "SELECT * FROM graph_node WHERE symbol_node_type='dependence'")
        assert len(rows) == 1
        assert rows[0]["include_path"] == "express"
        assert rows[0]["file_id"] == "a.ts"
        assert rows[0]["is_system"] == 0

    def test_empty_name_creates_empty_include_path(self, db, adapter):
        insert_graph(db, symbol_node_type="import", file_id="a.ts",
                     name="", kind="import", scope="module",
                     start_line="1", end_line="1", target="")
        result = extract_dep_edges_from_imports(adapter)
        assert len(result) == 1
        assert result[0]["include_path"] == ""
