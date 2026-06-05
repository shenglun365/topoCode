"""SymbolGraph — NetworkX-based merged code graph.

Builds a unified DiGraph from FileSymbolTable instances, resolution results,
and analysis edges. Provides query methods for graph traversal used by the
UI's impact graph, call hierarchy, and dependency viewer.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import networkx as nx

logger = logging.getLogger(__name__)


class SymbolGraph:
    """Wraps a NetworkX DiGraph built from analysis results.

    Node attributes:
      - kind: SymbolKind value (function, class, variable, ...)
      - scope: qualified scope string
      - file_path: source file path
      - line: start line number

    Edge attributes:
      - rel: relationship type (calls, imports, extends, implements, resolves)
      - confidence: resolution confidence (0.0–1.0)
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()

    # ---- builders ----

    @classmethod
    def from_tables(cls, tables: list) -> SymbolGraph:
        """Build a SymbolGraph from a list of FileSymbolTable objects."""
        sg = cls()
        for table in tables:
            sg._add_table(table)
        return sg

    def _add_table(self, table) -> None:
        """Add one FileSymbolTable's symbols, references, and imports."""
        fp = table.file_path
        for sym in table.symbols:
            qn = self._qualified_name(sym.name, sym.scope)
            self._graph.add_node(qn, kind=sym.kind.value, scope=sym.scope,
                                 file_path=fp, line=sym.location.start_line)
        for ref in table.references:
            target = ref.target or ref.name
            caller_scope = ref.scope or "module"
            caller_qn = self._qualified_name(caller_scope, "module")
            self._graph.add_edge(caller_qn, target, rel="references",
                                 confidence=0.5)
        for imp in table.imports:
            self._graph.add_node(imp.module, kind="module", scope="module",
                                 file_path=imp.resolved_file or fp, line=0)
            self._graph.add_edge(fp, imp.module, rel="imports", confidence=1.0)

    def add_resolution(self, source_qn: str, target_qn: str,
                       confidence: float, method: str) -> None:
        """Add an edge from a resolution result."""
        self._graph.add_edge(source_qn, target_qn, rel="resolves",
                             confidence=confidence, method=method)

    def add_call_edge(self, caller_qn: str, callee_qn: str,
                      confidence: float = 1.0) -> None:
        """Add a call edge."""
        self._graph.add_edge(caller_qn, callee_qn, rel="calls",
                             confidence=confidence)

    def add_dependency_edge(self, from_path: str, to_path: str,
                            dep_type: str = "imports") -> None:
        """Add a file-level dependency edge."""
        self._graph.add_edge(from_path, to_path, rel=dep_type, confidence=1.0)

    # ---- queries ----

    @property
    def graph(self) -> nx.DiGraph:
        return self._graph

    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def successors(self, node: str) -> list[dict]:
        """Outgoing edges from a node with edge data."""
        return [
            {"target": n, **self._graph.edges[node, n]}
            for n in self._graph.successors(node)
        ]

    def predecessors(self, node: str) -> list[dict]:
        """Incoming edges to a node with edge data."""
        return [
            {"source": n, **self._graph.edges[n, node]}
            for n in self._graph.predecessors(node)
        ]

    def neighbors(self, node: str, max_depth: int = 1) -> dict:
        """BFS traversal up to max_depth, returning {node: {data}}."""
        if node not in self._graph:
            return {}
        visited: dict = {}
        from collections import deque
        queue: deque = deque([(node, 0)])
        while queue:
            current, depth = queue.popleft()
            if current in visited:
                continue
            nbrs = list(self._graph.successors(current))
            nbrs += list(self._graph.predecessors(current))
            visited[current] = {
                "data": dict(self._graph.nodes[current]),
                "neighbors": [n for n in set(nbrs) if n != current],
            }
            if depth < max_depth:
                for nb in set(nbrs):
                    if nb not in visited and nb != current:
                        queue.append((nb, depth + 1))
        return visited

    def subgraph(self, nodes: list[str]) -> SymbolGraph:
        """Create a new SymbolGraph containing only the given nodes."""
        sg = SymbolGraph()
        sg._graph = self._graph.subgraph(nodes).copy()
        return sg

    def to_json(self) -> dict:
        """Serialise to JSON-serialisable dict for the frontend."""
        nodes = []
        for n, data in self._graph.nodes(data=True):
            nodes.append({"id": n, **{k: v for k, v in data.items()}})
        edges = []
        for u, v, data in self._graph.edges(data=True):
            edges.append({"source": u, "target": v, **data})
        return {"nodes": nodes, "edges": edges,
                "node_count": len(nodes), "edge_count": len(edges)}

    # ---- helpers ----

    @staticmethod
    def _qualified_name(name: str, scope: str) -> str:
        if scope and scope != "module":
            return f"{scope}.{name}"
        return name
