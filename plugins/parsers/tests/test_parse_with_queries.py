"""Tests for parse_with_queries.py — Query-to-Symbol pipeline"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from tree_sitter import Language, Parser
import tree_sitter_typescript as tsts

from parsers.query_loader import QueryLoader
from parsers.symbol_model import (
    SymbolKind, RefKind, FileSymbolTable,
)
from parsers.parse_with_queries import (
    _build_symbol_table,
    _detect_symbol_kind,
    _node_text,
    _make_location,
    _detect_language,
)


@pytest.fixture(scope="module")
def ts_language():
    return Language(tsts.language_typescript())


@pytest.fixture(scope="module")
def ts_parser(ts_language):
    return Parser(ts_language)


@pytest.fixture(autouse=True)
def clear_cache():
    QueryLoader.clear_cache()


def test_detect_language():
    assert _detect_language("/a/b.ts") == "typescript"
    assert _detect_language("/a/b.tsx") == "tsx"
    assert _detect_language("/a/b.py") == "python"
    assert _detect_language("/a/b.java") == "java"
    assert _detect_language("/a/b.c") == "c"
    assert _detect_language("/a/b.rs") == "rust"
    assert _detect_language("/a/b.txt") is None


class TestBuildSymbolTable:
    def test_function_declaration(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"function greet(name: string): void { return; }"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        assert len(table.symbols) >= 1
        funcs = [s for s in table.symbols if s.kind == SymbolKind.FUNCTION]
        assert any(s.name == "greet" for s in funcs)

    def test_class_declaration(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"class MyClass {}"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        classes = [s for s in table.symbols if s.kind == SymbolKind.CLASS]
        assert any(s.name == "MyClass" for s in classes)

    def test_variable_declarator(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"const x = 42;"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        vars_ = [s for s in table.symbols if s.kind == SymbolKind.VARIABLE]
        assert any(s.name == "x" for s in vars_)

    def test_interface_declaration(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"interface Foo { bar: string; }"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        interfaces = [s for s in table.symbols if s.kind == SymbolKind.INTERFACE]
        assert any(s.name == "Foo" for s in interfaces)

    def test_enum_declaration(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"enum Color { Red, Green, Blue }"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        enums = [s for s in table.symbols if s.kind == SymbolKind.ENUM]
        assert any(s.name == "Color" for s in enums)

    def test_references_call_expression(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"const r = foo(1, 2);"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        calls = [r for r in table.references if r.kind == RefKind.CALL]
        assert any(r.name == "foo" for r in calls)

    def test_import_statement(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b'import { useState } from "react";'
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        assert len(table.imports) >= 1
        imp = table.imports[0]
        assert imp.module == "react"
        assert "useState" in imp.imported_names

    def test_default_import(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b'import React from "react";'
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        assert any(
            imp.is_default and imp.module == "react"
            for imp in table.imports
        )

    def test_dynamic_import(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b'const mod = await import("./module");'
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        assert any(
            imp.module == "./module"
            for imp in table.imports
        )

    def test_export_re_export(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b'export { type } from "./types";'
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        assert any(
            imp.module == "./types"
            for imp in table.imports
        )

    def test_method_in_class(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"class Foo { bar(): void {} }"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        methods = [s for s in table.symbols if s.kind == SymbolKind.METHOD]
        assert any(s.name == "bar" for s in methods)

    def test_arrow_function_not_captured_as_definition(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"const add = (a: number, b: number): number => a + b;"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/test.ts", qs)
        # Arrow function has arrow.def capture, variable has var.def
        vars_ = [s for s in table.symbols if s.kind == SymbolKind.VARIABLE]
        assert any(s.name == "add" for s in vars_)

    def test_empty_file(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b""
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/empty.ts", qs)
        assert len(table.symbols) == 0

    def test_symbol_has_location(self, ts_language, ts_parser):
        qs = QueryLoader.load("typescript", ts_language)
        code = b"function foo() {}"
        tree = ts_parser.parse(code)
        table = _build_symbol_table(tree, "typescript", "/f.ts", qs)
        assert len(table.symbols) >= 1
        sym = table.symbols[0]
        assert sym.location.file_path == "/f.ts"
        assert sym.location.start_line >= 1


class TestDetectSymbolKind:
    class FakeMatch:
        def __init__(self, capture_names):
            self._caps = capture_names

        def get(self, name):
            return name in self._caps

    def test_function(self):
        m = self.FakeMatch({"func.def", "func.name"})
        assert _detect_symbol_kind(m) == SymbolKind.FUNCTION

    def test_class(self):
        m = self.FakeMatch({"class.def"})
        assert _detect_symbol_kind(m) == SymbolKind.CLASS

    def test_method(self):
        m = self.FakeMatch({"method.def"})
        assert _detect_symbol_kind(m) == SymbolKind.METHOD

    def test_constructor(self):
        m = self.FakeMatch({"ctor.def"})
        assert _detect_symbol_kind(m) == SymbolKind.CONSTRUCTOR

    def test_variable(self):
        m = self.FakeMatch({"var.def"})
        assert _detect_symbol_kind(m) == SymbolKind.VARIABLE

    def test_interface(self):
        m = self.FakeMatch({"interface.def"})
        assert _detect_symbol_kind(m) == SymbolKind.INTERFACE

    def test_type_alias(self):
        m = self.FakeMatch({"type_alias.def"})
        assert _detect_symbol_kind(m) == SymbolKind.TYPE_ALIAS

    def test_enum(self):
        m = self.FakeMatch({"enum.def"})
        assert _detect_symbol_kind(m) == SymbolKind.ENUM

    def test_namespace(self):
        m = self.FakeMatch({"namespace.def"})
        assert _detect_symbol_kind(m) == SymbolKind.MODULE

    def test_property(self):
        m = self.FakeMatch({"prop_sig.def"})
        assert _detect_symbol_kind(m) == SymbolKind.PROPERTY

    def test_param(self):
        m = self.FakeMatch({"param.def"})
        assert _detect_symbol_kind(m) == SymbolKind.PARAMETER

    def test_unknown_falls_to_variable(self):
        m = self.FakeMatch({"unknown.def"})
        assert _detect_symbol_kind(m) == SymbolKind.VARIABLE


class TestMakeLocation:
    class FakeNode:
        start_byte = 0
        end_byte = 5
        start_point = (0, 0)
        end_point = (0, 5)

    def test_location(self):
        loc = _make_location("/f.ts", self.FakeNode())
        assert loc.file_path == "/f.ts"
        assert loc.start_line == 1
        assert loc.start_col == 1
        assert loc.end_line == 1
        assert loc.end_col == 6


class TestNodeText:
    class FakeNode:
        text = b"hello"

    def test_text(self):
        assert _node_text(self.FakeNode()) == "hello"

    def test_empty_on_error(self):
        class BadNode:
            pass
        result = _node_text(BadNode())
        assert result == ""
