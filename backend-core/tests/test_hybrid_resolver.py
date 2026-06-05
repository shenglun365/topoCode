"""Tests for hybrid_resolver.py"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "parsers"))

import pytest
from unittest.mock import MagicMock, patch, AsyncMock

from parsers.symbol_model import (
    SourceLocation, Symbol, SymbolKind, Reference, RefKind, FileSymbolTable,
)
from parsers.binder import SimpleBinder
from stack_graphs_service import StackGraphsService, StackGraphsResult
from hybrid_resolver import HybridResolver


def _loc(file="f.ts", sb=0, eb=5, sl=1, sc=0, el=1, ec=5):
    return SourceLocation(file, sb, eb, sl, sc, el, ec)


def _sym(name, kind=SymbolKind.FUNCTION, scope="module", file="f.ts"):
    return Symbol(name=name, kind=kind, location=_loc(file), scope=scope)


def _ref(name, kind=RefKind.CALL, scope="module", file="f.ts"):
    return Reference(name=name, kind=kind, location=_loc(file), scope=scope)


def make_table(file_path="f.ts", symbols=None):
    t = FileSymbolTable(file_path=file_path, language="typescript")
    for s in (symbols or []):
        t.add_symbol(s)
    return t


class TestHybridResolver:
    def test_resolve_high_confidence_local(self):
        t = make_table(symbols=[_sym("foo")])
        binder = SimpleBinder({"f.ts": t})
        resolver = HybridResolver(binder)
        ref = _ref("foo")

        async def run():
            return await resolver.resolve(ref)

        result = asyncio_run(run())
        assert result.confidence >= 0.9
        assert result.target is not None
        assert result.target.name == "foo"
        assert result.method == "local"

    def test_resolve_low_confidence_falls_back_to_binder(self):
        """When SG not available, low confidence returns binder result."""
        t = make_table()
        binder = SimpleBinder({"f.ts": t})
        resolver = HybridResolver(binder)
        ref = _ref("unknown")

        async def run():
            return await resolver.resolve(ref)

        result = asyncio_run(run())
        assert result.confidence == 0.0
        assert result.method == "unresolved"

    def test_resolve_with_sg_available_and_found(self):
        """When SG finds a definition, return high confidence result."""
        t = make_table()
        binder = SimpleBinder({"f.ts": t})
        sg = MagicMock(spec=StackGraphsService)
        sg.available = True

        async def mock_definition(file, line, col):
            return StackGraphsResult(
                file="target.ts", line=5, column=3, scope_stack=[]
            )
        sg.definition = mock_definition

        resolver = HybridResolver(binder, sg_service=sg)
        ref = _ref("unknown")

        async def run():
            return await resolver.resolve(ref)

        result = asyncio_run(run())
        assert result.confidence == 1.0
        assert result.method == "stack-graphs"

    def test_resolve_with_sg_available_not_found(self):
        """When SG doesn't find anything, fall back to binder."""
        t = make_table()
        binder = SimpleBinder({"f.ts": t})
        sg = MagicMock(spec=StackGraphsService)
        sg.available = True

        async def mock_definition(file, line, col):
            return None
        sg.definition = mock_definition

        resolver = HybridResolver(binder, sg_service=sg)
        ref = _ref("unknown")

        async def run():
            return await resolver.resolve(ref)

        result = asyncio_run(run())
        assert result.confidence == 0.0
        assert result.method == "unresolved"

    def test_resolve_with_sg_available_error_returns_binder_result(self):
        t = make_table()
        binder = SimpleBinder({"f.ts": t})
        sg = MagicMock(spec=StackGraphsService)
        sg.available = True

        async def mock_definition(file, line, col):
            raise Exception("SG error")
        sg.definition = mock_definition

        resolver = HybridResolver(binder, sg_service=sg)
        ref = _ref("unknown")

        async def run():
            return await resolver.resolve(ref)

        result = asyncio_run(run())
        assert result == resolver.binder.resolve(ref)

    def test_from_file_tables(self):
        t = make_table(symbols=[_sym("foo")])
        resolver = HybridResolver.from_file_tables([t])
        assert resolver.binder is not None
        assert "f.ts" in resolver.binder.file_tables

    def test_from_file_tables_with_sg(self):
        t = make_table()
        sg = MagicMock(spec=StackGraphsService)
        resolver = HybridResolver.from_file_tables([t], sg_service=sg)
        assert resolver.sg is sg

    def test_sg_result_to_symbol(self):
        t = make_table()
        binder = SimpleBinder({"f.ts": t})
        resolver = HybridResolver(binder)

        sg_result = StackGraphsResult(
            file="/project/src/helper.ts", line=42, column=10, scope_stack=[]
        )
        sym = resolver._sg_result_to_symbol(sg_result)
        assert sym.name == "helper"
        assert sym.location.file_path == "/project/src/helper.ts"
        assert sym.location.start_line == 42

    def test_resolve_uses_file_path_from_ref(self):
        t = make_table()
        binder = SimpleBinder({"other.ts": t})
        resolver = HybridResolver(binder)
        loc = _loc(file="other.ts")
        ref = Reference(name="foo", kind=RefKind.CALL, location=loc, scope="module")
        ref.location = loc

        async def run():
            return await resolver.resolve(ref)

        result = asyncio_run(run())
        assert result.method == "unresolved"


def asyncio_run(coro):
    """Helper to run async test in sync context."""
    import asyncio
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
