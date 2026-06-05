"""Tests for query_loader.py — QueryLoader, QuerySet, QueryMatch, CapturedNode"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from tree_sitter import Language, Parser
import tree_sitter_typescript as tsts

from parsers.query_loader import QueryLoader, QuerySet, QueryMatch, CapturedNode


@pytest.fixture(scope="module")
def ts_language():
    return Language(tsts.language_typescript())


@pytest.fixture(scope="module")
def ts_parser(ts_language):
    return Parser(ts_language)


@pytest.fixture(autouse=True)
def clear_cache():
    QueryLoader.clear_cache()


class TestQuerySet:
    def test_dataclass(self):
        qs = QuerySet(language="ts", definitions=None, references=None, imports=None)
        assert qs.language == "ts"
        assert qs.definitions is None


class TestCapturedNode:
    def test_dataclass(self):
        cn = CapturedNode(name="foo", capture_name="func.name", match_id=1, node=None)
        assert cn.name == "foo"
        assert cn.capture_name == "func.name"


class TestQueryMatch:
    def test_empty(self):
        m = QueryMatch(match_id=0)
        assert m.match_id == 0
        assert m.captures == []

    def test_get_found(self):
        m = QueryMatch(match_id=0)
        m.captures.append(CapturedNode("foo", "func.name", 0, None))
        assert m.get("func.name") is None  # node is None
        assert m.get("nonexistent") is None

    def test_get_all(self):
        m = QueryMatch(match_id=0)
        m.captures.append(CapturedNode("x", "param", 0, None))
        m.captures.append(CapturedNode("y", "param", 0, None))
        m.captures.append(CapturedNode("z", "other", 0, None))
        assert len(m.get_all("param")) == 2
        assert len(m.get_all("other")) == 1
        assert m.get_all("missing") == []


class TestQueryLoaderLoad:
    def test_load_typescript(self, ts_language):
        qs = QueryLoader.load("typescript", ts_language)
        assert qs.language == "typescript"
        assert qs.definitions is not None
        assert qs.references is not None
        assert qs.imports is not None

    def test_load_caches(self, ts_language):
        qs1 = QueryLoader.load("typescript", ts_language)
        qs2 = QueryLoader.load("typescript", ts_language)
        assert qs1 is qs2

    def test_clear_cache(self, ts_language):
        qs1 = QueryLoader.load("typescript", ts_language)
        QueryLoader.clear_cache()
        qs2 = QueryLoader.load("typescript", ts_language)
        assert qs1 is not qs2

    def test_load_nonexistent_language_returns_none_queries(self, ts_language):
        qs = QueryLoader.load("nonexistent_lang", ts_language)
        assert qs.definitions is None
        assert qs.references is None
        assert qs.imports is None

    def test_load_with_none_language_returns_none_queries(self):
        qs = QueryLoader.load("nonexistent", None)
        assert qs.definitions is None
        assert qs.references is None
        assert qs.imports is None


class TestQueryLoaderRunQuery:
    def test_run_definitions_query(self, ts_language, ts_parser):
        """Run definitions query on a simple TS snippet"""
        qs = QueryLoader.load("typescript", ts_language)
        code = b"function hello(x: number): string { return x.toString(); }"
        tree = ts_parser.parse(code)
        matches = QueryLoader.run_query(qs.definitions, tree.root_node)
        assert len(matches) >= 1

        # Should capture func.def, func.name, func.params
        func_match = matches[0]
        names = {c.capture_name for c in func_match.captures}
        assert "func.def" in names
        assert "func.name" in names
        # The function node text should match
        func_name = func_match.get("func.name")
        assert func_name is not None

    def test_run_references_query(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"const x = foo(1, 2);"
        tree = ts_parser.parse(code)
        matches = QueryLoader.run_query(qs.references, tree.root_node)
        assert len(matches) >= 1

    def test_run_imports_query(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b'import { useState } from "react";'
        tree = ts_parser.parse(code)
        matches = QueryLoader.run_query(qs.imports, tree.root_node)
        assert len(matches) >= 1

        # Should capture import.stmt with source
        names = {c.capture_name for m in matches for c in m.captures}
        assert "import.stmt" in names or "import.source" in names

    def test_run_query_class_declaration(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"class MyClass { greet(): void {} }"
        tree = ts_parser.parse(code)
        matches = QueryLoader.run_query(qs.definitions, tree.root_node)
        names = {c.capture_name for m in matches for c in m.captures}
        assert "class.def" in names
        assert "class.name" in names

    def test_run_query_multiple_matches(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"function a() {} function b() {}"
        tree = ts_parser.parse(code)
        matches = QueryLoader.run_query(qs.definitions, tree.root_node)
        # Both function names should be captured even if grouped under same match_id
        names = {c.name for m in matches for c in m.captures if c.capture_name == "func.name"}
        assert "a" in names
        assert "b" in names

    def test_run_query_identifier_reference(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"const result = someFunction(x);"
        tree = ts_parser.parse(code)
        matches = QueryLoader.run_query(qs.references, tree.root_node)
        # Should capture the call expression
        call_names = set()
        for m in matches:
            for c in m.captures:
                call_names.add(c.capture_name)
        assert "call.expr" in call_names or "ref.name" in call_names


class TestExtractText:
    def test_extract_text_from_node(self, ts_language, ts_parser):
        code = b"const val = 42;"
        tree = ts_parser.parse(code)
        # Get the variable declarator name node
        decl = tree.root_node.child(0)  # lexical_declaration
        assert decl is not None
        text = QueryLoader._extract_text(decl)
        assert isinstance(text, str)
        assert len(text) > 0
