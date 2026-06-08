"""HybridResolver — two-tier symbol resolution + graph fusion

v2: Uses ResolutionEngine as the core resolver.
    Stack Graphs integration is optional (Tier 2).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from parsers.core.symbol_model import Node, UnresolvedReference, Edge, FileSymbolTable
from parsers.core.node_types import NodeKind, EdgeKind
from parsers.core.resolver import ResolutionEngine

logger = logging.getLogger(__name__)


class HybridResolver:
    """Two-tier resolver combining ResolutionEngine and StackGraphsService.

    Maintains a fused SymbolGraph accessible via the .graph property.
    """

    def __init__(
        self,
        tables: list[FileSymbolTable],
        sg_service=None,
    ):
        self._engine = ResolutionEngine()
        self._engine.build_index(tables)
        self.sg = sg_service
        self._tables = tables

    def resolve_one(self, ref: UnresolvedReference) -> Optional[Edge]:
        """Resolve a single reference, returning an Edge if resolved."""
        edges = self._engine.resolve(self._tables)
        for e in edges:
            if e.source == ref.from_node_id and e.reference_kind == ref.reference_kind:
                if e.target:
                    return e
        return None

    @classmethod
    def from_file_tables(cls, tables: list[FileSymbolTable], sg_service=None) -> HybridResolver:
        """Build from FileSymbolTable list + optional StackGraphsService."""
        return cls(tables, sg_service=sg_service)
