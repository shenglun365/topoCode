"""Tests for SymbolGraph (NetworkX graph fusion)."""

from enum import Enum
from symbol_graph import SymbolGraph


class _MockKind(Enum):
    FUNCTION = "function"
    CLASS = "class"
    VARIABLE = "variable"


def _make_mock_table(file_path: str, symbols: list, refs: list, imports: list):
    """Build a mock duck-typed FileSymbolTable."""
    class _MockLoc:
        start_line = 1
        start_col = 0
        end_line = 1
        end_col = 10

    class _MockSym:
        def __init__(self, name, kind, scope="module"):
            self.name = name
            self.kind = _MockKind(kind) if isinstance(kind, str) else kind
            self.scope = scope
            self.location = _MockLoc()

    class _MockRef:
        def __init__(self, name, target=None, scope="module"):
            self.name = name
            self.target = target
            self.scope = scope
            self.location = _MockLoc()

    class _MockImport:
        def __init__(self, module, names, resolved_file=None):
            self.module = module
            self.imported_names = names
            self.is_default = False
            self.resolved_file = resolved_file

    class MockTable:
        def __init__(self):
            self.file_path = file_path
            self.symbols = [_MockSym(n, k, s) for n, k, s in symbols]
            self.references = [_MockRef(n, t, sc) for n, t, sc in refs]
            self.imports = [_MockImport(m, ns, rf) for m, ns, rf in imports]

    return MockTable()


class TestSymbolGraph:
    def test_empty_graph(self):
        sg = SymbolGraph()
        assert sg.node_count() == 0
        assert sg.edge_count() == 0

    def test_from_tables(self):
        t1 = _make_mock_table(
            "src/main.py",
            [("foo", "function", "module"), ("Bar", "class", "module")],
            [("foo", "util.helper", "module")],
            [("util", ["helper"], "src/util.py")],
        )
        sg = SymbolGraph.from_tables([t1])
        assert sg.node_count() >= 2  # foo + Bar (at minimum)
        assert sg.edge_count() >= 1  # references edge

    def test_add_resolution(self):
        sg = SymbolGraph()
        sg.add_resolution("a.foo", "b.Bar", 0.95, "binder")
        assert sg.edge_count() == 1

    def test_to_json(self):
        sg = SymbolGraph()
        sg.add_resolution("a", "b", 1.0, "test")
        j = sg.to_json()
        assert "nodes" in j
        assert "edges" in j
        assert j["edge_count"] == 1

    def test_neighbors(self):
        sg = SymbolGraph()
        sg.add_resolution("a", "b", 1.0, "test")
        sg.add_resolution("b", "c", 1.0, "test")
        nbrs = sg.neighbors("b", max_depth=1)
        assert "b" in nbrs
