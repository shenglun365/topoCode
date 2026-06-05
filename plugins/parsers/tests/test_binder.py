"""Tests for binder.py — SimpleBinder, ResolveResult"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parsers.symbol_model import (
    SourceLocation, Symbol, SymbolKind, Reference, RefKind, FileSymbolTable, ImportRecord,
)
from parsers.binder import SimpleBinder, ResolveResult


def _loc(file="f.ts", sb=0, eb=5, sl=1, sc=0, el=1, ec=5):
    return SourceLocation(file, sb, eb, sl, sc, el, ec)


def _sym(name, kind=SymbolKind.FUNCTION, scope="module", file="f.ts"):
    return Symbol(name=name, kind=kind, location=_loc(file), scope=scope)


def _ref(name, kind=RefKind.CALL, scope="module", file="f.ts"):
    return Reference(name=name, kind=kind, location=_loc(file), scope=scope)


def make_table(file_path="f.ts", symbols=None, imports=None):
    t = FileSymbolTable(file_path=file_path, language="typescript")
    for s in (symbols or []):
        t.add_symbol(s)
    for i in (imports or []):
        t.add_import(i)
    return t


class TestResolveResult:
    def test_minimal(self):
        r = ResolveResult(target=None, confidence=0.0)
        assert r.target is None
        assert r.confidence == 0.0
        assert r.candidates == []
        assert r.method == "local"

    def test_resolved(self):
        loc = _loc()
        sym = Symbol(name="foo", kind=SymbolKind.FUNCTION, location=loc, scope="module")
        r = ResolveResult(target=sym, confidence=1.0, method="local")
        assert r.target is sym
        assert r.method == "local"


class TestSimpleBinder:
    def test_empty_tables(self):
        binder = SimpleBinder({})
        assert binder.file_tables == {}
        assert binder._scope_index == {}
        assert binder._export_index == {}

    def test_build_index_top_level_symbols_are_exports(self):
        t = make_table(symbols=[_sym("foo"), _sym("bar")])
        binder = SimpleBinder({"f.ts": t})
        assert "foo" in binder._export_index["f.ts"]
        assert "bar" in binder._export_index["f.ts"]

    def test_build_index_non_top_level_not_exported(self):
        t = make_table(symbols=[_sym("helper", scope="class.Util")])
        binder = SimpleBinder({"f.ts": t})
        assert "helper" not in binder._export_index["f.ts"]

    def test_resolve_local_direct(self):
        t = make_table(symbols=[_sym("foo")])
        binder = SimpleBinder({"f.ts": t})
        r = binder.resolve(_ref("foo"))
        assert r.target is not None
        assert r.target.name == "foo"
        assert r.confidence == 1.0
        assert r.method == "local"

    def test_resolve_local_scope_chain(self):
        """Nested scope: inner scope shadows outer — inner symbol wins"""
        inner_sym = _sym("x", scope="class.Outer.method.inner")
        outer_sym = _sym("x", scope="class.Outer")
        t = make_table(symbols=[outer_sym, inner_sym])
        binder = SimpleBinder({"f.ts": t})
        ref = _ref("x", scope="class.Outer.method.inner")
        r = binder.resolve(ref)
        assert r.target is inner_sym
        assert r.method == "local"

    def test_resolve_local_not_found_returns_none(self):
        t = make_table(symbols=[_sym("foo")])
        binder = SimpleBinder({"f.ts": t})
        r = binder.resolve(_ref("bar"))
        assert r.target is None
        assert r.confidence == 0.0
        assert r.method == "unresolved"

    def test_resolve_local_prefers_inner_scope(self):
        """When same name exists at multiple scope levels, closest scope wins"""
        inner = _sym("x", scope="class.A.method.b")
        outer = _sym("x", scope="class.A")
        t = make_table(symbols=[outer, inner])
        binder = SimpleBinder({"f.ts": t})
        ref = _ref("x", scope="class.A.method.b")
        r = binder.resolve(ref)
        assert r.target is inner
        assert r.method == "local"

    def test_resolve_via_import_found(self):
        """Unresolved reference resolved via import to another file's export"""
        target_loc = _loc(file="target.ts")
        target_sym = Symbol(name="Helper", kind=SymbolKind.FUNCTION, location=target_loc, scope="module")
        target_table = make_table(file_path="target.ts", symbols=[target_sym])

        imp = ImportRecord(module="target.ts", imported_names=["Helper"])
        source_table = make_table(file_path="source.ts", imports=[imp])

        binder = SimpleBinder({"source.ts": source_table, "target.ts": target_table})
        ref = _ref("Helper", file="source.ts")
        r = binder.resolve(ref)
        assert r.target is target_sym
        assert r.confidence >= 0.7
        assert r.method == "import"

    def test_resolve_via_import_alias(self):
        """Import with alias: ref name matches imported_names, not alias"""
        target_sym = _sym("LongName", file="target.ts")
        target_table = make_table(file_path="target.ts", symbols=[target_sym])

        imp = ImportRecord(module="target.ts", imported_names=["LongName"], alias="ln")
        source_table = make_table(file_path="source.ts", imports=[imp])

        binder = SimpleBinder({"source.ts": source_table, "target.ts": target_table})
        # Resolve by real name, not alias
        ref = _ref("LongName", file="source.ts")
        r = binder.resolve(ref)
        assert r.target is target_sym
        assert r.method == "import"

    def test_resolve_via_import_no_matching_file(self):
        """Import exists but target file not in tables — falls through to unresolved"""
        imp = ImportRecord(module="missing.ts", imported_names=["Foo"])
        source_table = make_table(file_path="source.ts", imports=[imp])
        binder = SimpleBinder({"source.ts": source_table})
        ref = _ref("Foo", file="source.ts")
        r = binder.resolve(ref)
        # Low confidence from import branch (< 0.7 threshold) → falls through to unresolved
        assert r.target is None
        assert r.confidence == 0.0
        assert r.method == "unresolved"

    def test_resolve_qualified_name_returns_low_confidence(self):
        """Qualified names fall through to unresolved (< 0.7 threshold)"""
        t = make_table()
        binder = SimpleBinder({"f.ts": t})
        ref = _ref("obj.prop", file="f.ts")
        r = binder.resolve(ref)
        assert r.confidence == 0.0
        assert r.method == "unresolved"

    def test_resolve_qualified_no_dot_falls_through(self):
        """Non-qualified names should not match qualified resolver"""
        t = make_table(symbols=[_sym("foo")])
        binder = SimpleBinder({"f.ts": t})
        ref = _ref("foo", file="f.ts")
        r = binder.resolve(ref)
        assert r.method == "local"

    def test_resolve_qualified_empty_string(self):
        t = make_table()
        binder = SimpleBinder({"f.ts": t})
        ref = _ref("", file="f.ts")
        r = binder.resolve(ref)
        assert r.method == "unresolved"

    def test_resolve_prefers_local_over_import(self):
        """Local symbol should take priority over imported one"""
        local = _sym("Foo", file="source.ts")
        target = _sym("Foo", file="target.ts")
        imp = ImportRecord(module="target.ts", imported_names=["Foo"])
        source_table = make_table(file_path="source.ts", symbols=[local], imports=[imp])
        target_table = make_table(file_path="target.ts", symbols=[target])
        binder = SimpleBinder({"source.ts": source_table, "target.ts": target_table})
        ref = _ref("Foo", scope="module", file="source.ts")
        r = binder.resolve(ref)
        assert r.target is local
        assert r.method == "local"

    def test_scope_chain_top_level(self):
        binder = SimpleBinder({})
        assert binder._scope_chain("module") == ["module"]

    def test_scope_chain_nested(self):
        binder = SimpleBinder({})
        chain = binder._scope_chain("class.Foo.method.bar")
        # Each dot is a scope boundary
        assert chain == ["class.Foo.method.bar", "class.Foo.method", "class.Foo", "class", "module"]

    def test_scope_chain_empty(self):
        binder = SimpleBinder({})
        assert binder._scope_chain("") == ["module"]

    def test_find_file_from_import_exact(self):
        t = make_table(file_path="/project/src/mod.ts")
        binder = SimpleBinder({"/project/src/mod.ts": t})
        imp = ImportRecord(module="/project/src/mod.ts", imported_names=["X"])
        assert binder._find_file_from_import(imp) == "/project/src/mod.ts"

    def test_find_file_from_import_resolved(self):
        t = make_table(file_path="/src/mod.ts")
        binder = SimpleBinder({"/src/mod.ts": t})
        imp = ImportRecord(module="./mod.ts", imported_names=["X"], resolved_file="/src/mod.ts")
        assert binder._find_file_from_import(imp) == "/src/mod.ts"

    def test_find_symbol_in_file(self):
        sym = _sym("Foo", file="f.ts")
        t = make_table(file_path="f.ts", symbols=[sym])
        binder = SimpleBinder({"f.ts": t})
        assert binder._find_symbol_in_file("f.ts", "Foo") is sym
        assert binder._find_symbol_in_file("f.ts", "Bar") is None
        assert binder._find_symbol_in_file("missing.ts", "Foo") is None

    def test_from_tables_constructor(self):
        t1 = make_table(file_path="a.ts")
        t2 = make_table(file_path="b.ts")
        binder = SimpleBinder.from_tables([t1, t2])
        assert "a.ts" in binder.file_tables
        assert "b.ts" in binder.file_tables
        assert len(binder.file_tables) == 2
