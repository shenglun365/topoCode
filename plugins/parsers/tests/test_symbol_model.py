"""Tests for symbol_model.py — Symbol, Reference, ImportRecord, FileSymbolTable"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from parsers.symbol_model import (
    Symbol,
    Reference,
    ImportRecord,
    SourceLocation,
    FileSymbolTable,
    SymbolKind,
    RefKind,
)


class TestSymbolKind:
    def test_values(self):
        assert SymbolKind.FUNCTION.value == "function"
        assert SymbolKind.CLASS.value == "class"
        assert SymbolKind.VARIABLE.value == "variable"

    def test_enum_members(self):
        expected = {
            "FUNCTION", "METHOD", "CLASS", "VARIABLE", "PARAMETER",
            "INTERFACE", "TYPE_ALIAS", "ENUM", "MODULE", "CONSTRUCTOR", "PROPERTY",
        }
        assert set(SymbolKind.__members__) == expected


class TestRefKind:
    def test_values(self):
        assert RefKind.CALL.value == "call"
        assert RefKind.IMPORT.value == "import"

    def test_enum_members(self):
        expected = {
            "CALL", "MEMBER", "IMPORT", "TYPE_REF",
            "IDENT", "NEW", "ASSIGN", "RETURN",
        }
        assert set(RefKind.__members__) == expected


class TestSourceLocation:
    def test_basic(self):
        loc = SourceLocation(
            file_path="/a/b.ts",
            start_byte=10, end_byte=20,
            start_line=1, start_col=5,
            end_line=1, end_col=15,
        )
        assert loc.file_path == "/a/b.ts"
        assert loc.start_line == 1
        assert loc.end_col == 15


class TestSymbol:
    def test_minimal(self):
        loc = SourceLocation("f.ts", 0, 5, 1, 0, 1, 5)
        s = Symbol(name="foo", kind=SymbolKind.FUNCTION, location=loc, scope="module")
        assert s.name == "foo"
        assert s.is_definition is True
        assert s.parent_name is None
        assert s.doc_comment is None

    def test_full(self):
        loc = SourceLocation("f.ts", 0, 5, 1, 0, 1, 5)
        s = Symbol(
            name="bar",
            kind=SymbolKind.METHOD,
            location=loc,
            scope="class.Foo",
            is_definition=True,
            doc_comment="/** doc */",
            signature='{"params":["x"]}',
            parent_name="Foo",
        )
        assert s.signature == '{"params":["x"]}'
        assert s.parent_name == "Foo"

    def test_dataclass_equality(self):
        loc = SourceLocation("f.ts", 0, 5, 1, 0, 1, 5)
        a = Symbol(name="x", kind=SymbolKind.VARIABLE, location=loc, scope="module")
        b = Symbol(name="x", kind=SymbolKind.VARIABLE, location=loc, scope="module")
        assert a == b


class TestReference:
    def test_minimal(self):
        loc = SourceLocation("f.ts", 10, 15, 2, 3, 2, 8)
        r = Reference(name="foo", kind=RefKind.CALL, location=loc, scope="module")
        assert r.name == "foo"
        assert r.target is None

    def test_with_target(self):
        loc = SourceLocation("f.ts", 10, 15, 2, 3, 2, 8)
        r = Reference(name="foo", kind=RefKind.CALL, location=loc, scope="module", target="module.foo")
        assert r.target == "module.foo"


class TestImportRecord:
    def test_named_import(self):
        imp = ImportRecord(
            module="./utils/helper",
            imported_names=["Helper", "formatTime"],
        )
        assert imp.module == "./utils/helper"
        assert "Helper" in imp.imported_names
        assert imp.is_default is False
        assert imp.is_namespace is False

    def test_default_import(self):
        imp = ImportRecord(
            module="react",
            imported_names=["React"],
            is_default=True,
        )
        assert imp.is_default is True

    def test_namespace_import(self):
        imp = ImportRecord(
            module="./utils",
            imported_names=["utils"],
            is_namespace=True,
            alias="utils",
        )
        assert imp.is_namespace is True
        assert imp.alias == "utils"


class TestFileSymbolTable:
    def test_empty(self):
        table = FileSymbolTable(file_path="/a/b.ts", language="typescript")
        assert table.file_path == "/a/b.ts"
        assert table.language == "typescript"
        assert table.symbols == []
        assert table.references == []
        assert table.imports == []

    def test_add_symbol(self):
        table = FileSymbolTable(file_path="f.ts", language="ts")
        loc = SourceLocation("f.ts", 0, 5, 1, 0, 1, 5)
        sym = Symbol(name="foo", kind=SymbolKind.FUNCTION, location=loc, scope="module")
        table.add_symbol(sym)
        assert len(table.symbols) == 1
        assert table.symbols[0].name == "foo"

    def test_add_reference(self):
        table = FileSymbolTable(file_path="f.ts", language="ts")
        loc = SourceLocation("f.ts", 10, 15, 2, 3, 2, 8)
        ref = Reference(name="bar", kind=RefKind.CALL, location=loc, scope="module")
        table.add_reference(ref)
        assert len(table.references) == 1

    def test_add_import(self):
        table = FileSymbolTable(file_path="f.ts", language="ts")
        imp = ImportRecord(module="./mod", imported_names=["x"])
        table.add_import(imp)
        assert len(table.imports) == 1

    def test_get_symbol_found(self):
        table = FileSymbolTable(file_path="f.ts", language="ts")
        loc = SourceLocation("f.ts", 0, 5, 1, 0, 1, 5)
        sym = Symbol(name="foo", kind=SymbolKind.FUNCTION, location=loc, scope="module")
        table.add_symbol(sym)
        assert table.get_symbol("foo") is sym
        assert table.get_symbol("foo", scope="module") is sym
        assert table.get_symbol("foo", scope="class.X") is None

    def test_get_symbol_not_found(self):
        table = FileSymbolTable(file_path="f.ts", language="ts")
        assert table.get_symbol("nonexistent") is None

    def test_get_symbol_scope_mismatch_returns_none(self):
        table = FileSymbolTable(file_path="f.ts", language="ts")
        loc = SourceLocation("f.ts", 0, 5, 1, 0, 1, 5)
        sym = Symbol(name="foo", kind=SymbolKind.METHOD, location=loc, scope="class.Foo")
        table.add_symbol(sym)
        assert table.get_symbol("foo", scope="module") is None

    def test_symbols_by_kind(self):
        table = FileSymbolTable(file_path="f.ts", language="ts")
        loc = SourceLocation("f.ts", 0, 5, 1, 0, 1, 5)
        table.add_symbol(Symbol(name="a", kind=SymbolKind.FUNCTION, location=loc, scope="module"))
        table.add_symbol(Symbol(name="b", kind=SymbolKind.CLASS, location=loc, scope="module"))
        table.add_symbol(Symbol(name="c", kind=SymbolKind.FUNCTION, location=loc, scope="module"))
        funcs = table.symbols_by_kind(SymbolKind.FUNCTION)
        assert len(funcs) == 2
        assert all(s.kind == SymbolKind.FUNCTION for s in funcs)

    def test_top_level_symbols(self):
        table = FileSymbolTable(file_path="f.ts", language="ts")
        loc = SourceLocation("f.ts", 0, 5, 1, 0, 1, 5)
        table.add_symbol(Symbol(name="a", kind=SymbolKind.FUNCTION, location=loc, scope="module"))
        table.add_symbol(Symbol(name="b", kind=SymbolKind.CLASS, location=loc, scope="module"))
        table.add_symbol(Symbol(name="c", kind=SymbolKind.METHOD, location=loc, scope="class.Foo"))
        tops = table.top_level_symbols()
        assert len(tops) == 2
        assert all(s.scope == "module" for s in tops)
