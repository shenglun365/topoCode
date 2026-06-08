"""Tests for hybrid_resolver.py (v2)"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "parsers"))

from parsers.core.symbol_model import Node, Edge, UnresolvedReference, FileSymbolTable
from parsers.core.node_types import NodeKind, EdgeKind
from parsers.core.resolver import ResolutionEngine
from hybrid_resolver import HybridResolver


def _node(name, kind=NodeKind.FUNCTION, file_path="f.ts", line=1):
    return Node(
        id=f"n:{file_path}:{name}", kind=kind, name=name,
        qualified_name=name, file_path=file_path,
        start_line=line, end_line=line,
    )


def _ref(name, from_id="n:f.ts:caller", kind=EdgeKind.CALLS, file_path="f.ts"):
    return UnresolvedReference(
        from_node_id=from_id, reference_name=name,
        reference_kind=kind, file_path=file_path, line=1,
    )


def make_table(file_path="f.ts", nodes=None, refs=None, language="typescript"):
    t = FileSymbolTable(file_path=file_path, language=language)
    for n in (nodes or []):
        t.add_node(n)
    for r in (refs or []):
        t.add_ref(r)
    return t


class TestHybridResolver:
    def test_from_file_tables(self):
        t = make_table(nodes=[_node("foo")])
        resolver = HybridResolver.from_file_tables([t])
        assert resolver._engine is not None

    def test_resolve_with_node_found(self):
        foo = _node("foo")
        caller = _node("caller")
        t = make_table(nodes=[foo, caller])
        ref = _ref("foo", from_id=caller.id, file_path="f.ts")
        t.add_ref(ref)

        resolver = HybridResolver.from_file_tables([t])
        edge = resolver.resolve_one(ref)
        assert edge is not None
        assert edge.target == foo.id

    def test_resolve_with_node_not_found(self):
        t = make_table(nodes=[_node("bar")])
        ref = _ref("unknown", from_id="n:f.ts:caller")
        t.add_ref(ref)

        resolver = HybridResolver.from_file_tables([t])
        edge = resolver.resolve_one(ref)
        # Unresolved refs get empty target
        assert edge is None

    def test_resolve_across_files(self):
        t1 = make_table(file_path="f1.ts", nodes=[_node("foo", file_path="f1.ts")])
        t2 = make_table(file_path="f2.ts", nodes=[_node("bar", file_path="f2.ts")])

        ref = _ref("foo", from_id="n:f2.ts:bar", file_path="f2.ts")
        t2.add_ref(ref)

        resolver = HybridResolver.from_file_tables([t1, t2])
        edge = resolver.resolve_one(ref)
        assert edge is not None

    def test_resolve_calls_edge(self):
        foo = _node("foo")
        caller = _node("caller")
        t = make_table(nodes=[foo, caller])
        ref = _ref("foo", from_id=caller.id, kind=EdgeKind.CALLS)
        t.add_ref(ref)

        resolver = HybridResolver.from_file_tables([t])
        edge = resolver.resolve_one(ref)
        assert edge is not None
        assert edge.target == foo.id

    def test_resolve_implements_edge(self):
        iface = _node("IHandler", kind=NodeKind.INTERFACE)
        impl = _node("Handler", kind=NodeKind.CLASS)
        t = make_table(nodes=[iface, impl])
        ref = _ref("IHandler", from_id=impl.id, kind=EdgeKind.IMPLEMENTS)
        t.add_ref(ref)

        resolver = HybridResolver.from_file_tables([t])
        edge = resolver.resolve_one(ref)
        assert edge is not None
        assert edge.target == iface.id
