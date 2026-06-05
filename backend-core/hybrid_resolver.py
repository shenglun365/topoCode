"""HybridResolver — two-tier symbol resolution + graph fusion

Tier 1 (fast path): SimpleBinder — deterministic scope-chain + import lookup.
Tier 2 (exact path): StackGraphsService — precise resolution for ambiguous cases.

Graph fusion: maintains a SymbolGraph (NetworkX DiGraph) that merges all
resolution results, call edges, and dependency edges into a unified graph
for frontend visualisation and impact analysis.

Flow:
  1. SimpleBinder resolves — confidence ≥ 0.9 → return immediately
  2. SimpleBinder low confidence + Stack Graphs available → query SG
  3. Stack Graphs returns result → high confidence result
  4. Both fail → return SimpleBinder's best guess (low confidence)
  5. Every resolution writes an edge into the merged SymbolGraph
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from parsers.symbol_model import Reference, Symbol, SourceLocation, SymbolKind
from parsers.binder import SimpleBinder, ResolveResult as BinderResult
from stack_graphs_service import StackGraphsService, StackGraphsResult
from symbol_graph import SymbolGraph

logger = logging.getLogger(__name__)


class HybridResolver:
    """Two-tier resolver combining SimpleBinder and Stack GraphService.
    
    Maintains a fused SymbolGraph accessible via the .graph property.
    """

    def __init__(
        self,
        binder: SimpleBinder,
        sg_service: Optional[StackGraphsService] = None,
        tables: Optional[list] = None,
    ):
        self.binder = binder
        self.sg = sg_service
        self._graph = SymbolGraph.from_tables(tables or [])

    async def resolve(self, ref: Reference, file_path: str = "") -> BinderResult:
        """Resolve a reference, using Stack Graphs when SimpleBinder is uncertain.

        Every resolution writes an edge into the merged SymbolGraph.

        Args:
            ref: The reference to resolve.
            file_path: The file containing the reference (auto-detected from ref if empty).

        Returns:
            Resolution result with target, confidence, and method.
        """
        ctx_file = file_path or ref.location.file_path
        source_qn = f"{Path(ctx_file).stem}.{ref.name}"

        # Tier 1: SimpleBinder fast path
        result = self.binder.resolve(ref, file_path=ctx_file)
        if result.target:
            self._graph.add_resolution(source_qn, result.target.name,
                                       result.confidence, result.method or "binder")
        if result.confidence >= 0.9:
            return result

        # Tier 2: Stack Graphs exact path
        if self.sg and self.sg.available:
            sg_result = await self._resolve_via_sg(ref, ctx_file)
            if sg_result and sg_result.target:
                self._graph.add_resolution(source_qn, sg_result.target.name,
                                           1.0, "stack-graphs")
                return sg_result

        # Fallback: return SimpleBinder's best effort
        return result

    async def _resolve_via_sg(
        self, ref: Reference, file_path: str
    ) -> Optional[BinderResult]:
        """Query Stack Graphs for definition lookup."""
        try:
            loc = ref.location
            sg_def = await self.sg.definition(file_path, loc.start_line, loc.start_col)
            if not sg_def:
                return None

            target = self._sg_result_to_symbol(sg_def)
            if not target:
                return None

            return BinderResult(
                target=target,
                confidence=1.0,
                method="stack-graphs",
            )
        except Exception as e:
            logger.warning(f"Stack Graphs query failed: {e}")
            return None

    def _sg_result_to_symbol(self, sg: StackGraphsResult) -> Optional[Symbol]:
        """Convert a StackGraphsResult to a Symbol."""
        loc = SourceLocation(
            file_path=sg.file,
            start_byte=0,
            end_byte=0,
            start_line=sg.line,
            start_col=sg.column,
            end_line=sg.line,
            end_col=sg.column,
        )
        name = Path(sg.file).stem
        return Symbol(
            name=name,
            kind=SymbolKind.VARIABLE,
            location=loc,
            scope="module",
        )

    @property
    def graph(self) -> SymbolGraph:
        """The fused SymbolGraph built from all resolutions."""
        return self._graph

    @classmethod
    def from_file_tables(
        cls,
        tables: list,
        sg_service: Optional[StackGraphsService] = None,
    ) -> HybridResolver:
        """Build from FileSymbolTable list + optional StackGraphsService.
        
        The SymbolGraph is pre-populated from the tables.
        """
        binder = SimpleBinder.from_tables(tables)
        return cls(binder, sg_service=sg_service, tables=tables)
