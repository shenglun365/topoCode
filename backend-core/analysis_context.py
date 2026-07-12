"""AnalysisContext — unified context manager.

Provides hierarchical project analysis data access for built-in Agents.
Four cognitive levels: project → community → file → symbol.
Each level provides three-layer structured description: "what" (function), "how" (logic), "why" (causality).

Usage:
    ctx = AnalysisContext(project_db, task_id)
    layers = ctx.get_downward_path(["project", "comm-xxx", "src/api/handler.ts", "authenticate"])
    prompt = ctx.format_for_llm(layers, direction="top-down")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Community node count threshold (communities below this threshold are considered "small communities", downweighted in summaries)
SMALL_COMMUNITY_THRESHOLD = 6

# Cache size
_CACHE_SIZE = 128


@dataclass
class ContextLayer:
    """Abstract representation of a context layer.

    Each layer contains three dimensions of information:
      - what: functionality description
      - how: logic description
      - why: causality/constraints/trade-offs
    """

    level: str  # "project" | "community" | "file" | "symbol"
    layer_id: str  # unique identifier for this layer (task_id, comm_id, file_path, symbol_name)
    name: str  # display name

    # Three-layer descriptions
    what: str = ""  # functionality description
    how: str = ""  # logic description
    why: str = ""  # causality description

    # Structured details (raw data)
    detail: dict[str, Any] = field(default_factory=dict)

    # Child layer ID list
    children: list[str] = field(default_factory=list)

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)


class AnalysisContext:
    """Unified context manager.

    Builds a hierarchical project cognition model based on AnalysisStore.
    All methods are read-only queries; they do not modify data.
    """

    def __init__(self, project_db, task_id: str):
        """
        Args:
            project_db: SQLiteContext instance
            task_id: analysis task ID
        """
        from store.analysis_store import AnalysisStore
        self._store = AnalysisStore(project_db)
        self._task_id = task_id
        self._project_root = getattr(project_db, 'project_root', None) or ""

    # ═══════════════════════════════════════════
    # Project Level
    # ═══════════════════════════════════════════

    def get_project_layer(self) -> ContextLayer:
        """Build project-level context: overall statistics, community distribution, language distribution."""
        nodes = self._store.get_graph_nodes(self._task_id)
        file_nodes = [n for n in nodes if n.get("kind") == "file"]
        languages = {}
        for n in nodes:
            lang = n.get("language", "unknown")
            languages[lang] = languages.get(lang, 0) + 1

        incl_comms = self._store.get_communities(self._task_id, edge_type="INCLUDE", comm_lv="L0")
        call_comms = self._store.get_communities(self._task_id, edge_type="CALL", comm_lv="L0")

        total_symbols = sum(1 for n in nodes if n.get("kind") not in ("file", "import"))

        what = (
            f"Project contains {len(file_nodes)} files, {total_symbols} symbols, "
            f"distributed across {len(incl_comms)} dependency communities and {len(call_comms)} call communities"
        )
        how = f"Main languages: {', '.join(f'{k}({v})' for k, v in sorted(languages.items(), key=lambda x: -x[1])[:5])}"
        why = f"Dependency communities reflect static dependency relationships between modules; call communities reflect runtime call clustering. Combining both assesses architecture coupling and cohesion."

        # Child layers: all L0 communities
        children = [c.get("comm_id", "") for c in incl_comms if c.get("comm_id")]
        children += [c.get("comm_id", "") for c in call_comms if c.get("comm_id")]

        return ContextLayer(
            level="project",
            layer_id=self._task_id,
            name="Project Overview",
            what=what,
            how=how,
            why=why,
            detail={
                "file_count": len(file_nodes),
                "symbol_count": total_symbols,
                "languages": languages,
                "include_communities": len(incl_comms),
                "call_communities": len(call_comms),
            },
            children=children,
        )

    # ═══════════════════════════════════════════
    # Community Level
    # ═══════════════════════════════════════════

    @lru_cache(maxsize=_CACHE_SIZE)
    def _get_node_map(self) -> dict[str, dict]:
        """Build node_id → node dict mapping (with cache)."""
        nodes = self._store.get_graph_nodes(self._task_id)
        return {n.get("id", ""): n for n in nodes}

    def get_community_layer(self, comm_id: str, depth: int = 1) -> ContextLayer:
        """Build community-level context: nodes, edges, hubs, sub-communities.

        Args:
            comm_id: community ID
            depth: sub-community expansion depth (1=direct children only, 2=grandchildren)
        """
        communities = self._store.get_communities(self._task_id)
        comm = next((c for c in communities if c.get("comm_id") == comm_id), None)
        if not comm:
            return ContextLayer(level="community", layer_id=comm_id, name=comm_id, what="Community not found")

        node_list = self._parse_json_list(comm.get("node_list", "[]"))
        edge_list = self._parse_json_list(comm.get("edge_list", "[]"))
        node_map = self._get_node_map()

        node_count = len(node_list)
        edge_count = len(edge_list)
        edge_type = comm.get("edge_type", "INCLUDE")

        # Identify hub nodes (high degree)
        degree: dict[str, int] = {}
        for e in edge_list:
            src = e if isinstance(e, str) else e.get("source_id", e.get("source", ""))
            tgt = e if isinstance(e, str) else e.get("target_id", e.get("target", ""))
            degree[src] = degree.get(src, 0) + 1
            degree[tgt] = degree.get(tgt, 0) + 1
        hub_threshold = max(5, node_count * 0.3)
        hubs = [nid for nid, d in degree.items() if d > hub_threshold]

        # Sub-communities
        children = self._store.get_communities(self._task_id, edge_type=edge_type)
        child_comms = [
            c.get("comm_id", "")
            for c in children
            if c.get("parent_comm_id") == comm_id and c.get("comm_lv") not in ("HUB", "ORPHAN")
        ]

        hub_names = [node_map.get(h, {}).get("name", h) for h in hubs[:5]]
        child_summary = f", containing {len(child_comms)} sub-communities" if child_comms else ", no significant sub-communities"

        what = (
            f"Community '{comm_id}' contains {node_count} nodes, {edge_count} {edge_type} edges, "
            f"is a {'dependency' if edge_type == 'INCLUDE' else 'call'} relationship community{child_summary}"
        )
        how = (
            f"Hub nodes: {', '.join(hub_names[:3]) if hub_names else 'No significant hubs'}."
            f" Community consists of {node_count} tightly related symbols"
        )
        why = (
            f"The formation of this community needs to be analyzed in conjunction with {edge_type} edge distribution."
            f" Hub nodes ({len(hubs)}) are the community's backbone — they are the source of community cohesion,"
            f" and also potential architecture bottlenecks."
        )

        return ContextLayer(
            level="community",
            layer_id=comm_id,
            name=comm.get("comm_id", comm_id),
            what=what,
            how=how,
            why=why,
            detail={
                "node_count": node_count,
                "edge_count": edge_count,
                "edge_type": edge_type,
                "hubs": hubs[:10],
                "hub_names": hub_names,
                "quality_score": comm.get("quality_score"),
            },
            children=child_comms,
        )

    # ═══════════════════════════════════════════
    # File Level
    # ═══════════════════════════════════════════

    def get_file_layer(self, file_path: str) -> ContextLayer:
        """Build file-level context: symbol list, imports/exports, line count."""
        nodes = self._store.get_graph_nodes(self._task_id)
        file_nodes = [n for n in nodes if n.get("file_path") == file_path]

        if not file_nodes:
            # Loose matching
            file_nodes = [n for n in nodes if file_path in (n.get("file_path") or "")]

        kinds: dict[str, int] = {}
        for n in file_nodes:
            k = n.get("kind", "unknown")
            kinds[k] = kinds.get(k, 0) + 1

        exported = [n.get("name") for n in file_nodes if n.get("is_exported")]
        imports = [n.get("name") for n in file_nodes if n.get("kind") == "import"]
        functions = [n.get("name") for n in file_nodes if n.get("kind") in ("function", "method")]

        what = (
            f"File '{file_path}' contains {len(file_nodes)} symbols"
            + (f", {len(exported)} publicly exported" if exported else "")
        )
        kind_str = ", ".join(f"{k}({v})" for k, v in sorted(kinds.items(), key=lambda x: -x[1]))
        how = f"Symbol type distribution: {kind_str}" if kind_str else "No type distribution info"

        rel_nodes = [n for n in nodes if n.get("file_path") == file_path
                     and n.get("kind") in ("function", "method", "class")]
        why = (
            f"This file's role in the project is defined by {len(functions)} functions/methods."
            + (f" Public symbols ({', '.join(exported[:5])}) are the entry points for external dependencies on this file." if exported else "")
        )

        return ContextLayer(
            level="file",
            layer_id=file_path,
            name=file_path.replace('\\', '/').split("/")[-1] if "/" in file_path.replace('\\', '/') else file_path,
            what=what,
            how=how,
            why=why,
            detail={
                "symbol_count": len(file_nodes),
                "exported_count": len(exported),
                "kinds": kinds,
                "exported": exported[:10],
                "imports": imports[:5],
                "functions": functions[:10],
            },
            children=functions[:20],  # child layers: key function names
        )

    # ═══════════════════════════════════════════
    # Symbol Level
    # ═══════════════════════════════════════════

    def get_symbol_layer(self, symbol_name: str) -> ContextLayer:
        """Build symbol-level context: signature, callers, callees, community."""
        node_map = self._get_node_map()
        edges = self._store.get_graph_edges(self._task_id)

        # Find target node
        target_node = None
        for nid, node in node_map.items():
            if node.get("name") == symbol_name:
                target_node = node
                break
            if node.get("qualified_name", "").endswith(f"::{symbol_name}"):
                target_node = node
                break

        if not target_node:
            return ContextLayer(
                level="symbol", layer_id=symbol_name, name=symbol_name, what=f"Symbol '{symbol_name}' not found"
            )

        node_id = target_node.get("id", "")
        kind = target_node.get("kind", "unknown")
        signature = target_node.get("signature", "")
        file_path = target_node.get("file_path", "")

        # Callers (calls edges where target_id == node_id)
        callers = []
        callees = []
        for e in edges:
            if e.get("target_id") == node_id and e.get("kind") == "calls":
                src_node = node_map.get(e.get("source_id", ""), {})
                callers.append(src_node.get("name", e.get("source_id", "")))
            if e.get("source_id") == node_id and e.get("kind") == "calls":
                tgt_node = node_map.get(e.get("target_id", ""), {})
                callees.append(tgt_node.get("name", e.get("target_id", "")))

        what = f"Symbol '{symbol_name}' type is {kind}" + (f", signature: {signature}" if signature else "")
        how = (
            f"Called by {len(callers)} functions" + (f" ({', '.join(callers[:5])})" if callers else ", not called")
            + f", calls {len(callees)} functions"
            + (f" ({', '.join(callees[:5])})" if callees else "")
        )
        why = (
            f"This symbol is defined in file '{file_path}'."
            + (f" As a node depended on by {len(callers)} callers, modifying it will affect the call chain." if callers else "")
        )

        return ContextLayer(
            level="symbol",
            layer_id=node_id,
            name=symbol_name,
            what=what,
            how=how,
            why=why,
            detail={
                "kind": kind,
                "signature": signature,
                "file_path": file_path,
                "visibility": target_node.get("visibility", ""),
                "is_exported": target_node.get("is_exported", 0),
                "is_async": target_node.get("is_async", 0),
                "line": target_node.get("start_line", 0),
                "callers": callers[:10],
                "callees": callees[:10],
            },
            children=callees[:10],
        )

    # ═══════════════════════════════════════════
    # Path Traversal
    # ═══════════════════════════════════════════

    def get_downward_path(self, path: list[str]) -> list[ContextLayer]:
        """Top-down path traversal.

        Args:
            path: path description, e.g. ["project", "comm-xxx", "src/api/handler.ts", "authenticate"]
                  first entry must be "project"

        Returns:
            List of ContextLayer in path order
        """
        layers: list[ContextLayer] = []
        for i, segment in enumerate(path):
            if i == 0 and segment == "project":
                layers.append(self.get_project_layer())
            elif i == 1:
                layers.append(self.get_community_layer(segment))
            elif i == 2:
                layers.append(self.get_file_layer(segment))
            elif i == 3:
                layers.append(self.get_symbol_layer(segment))
        return layers

    def get_upward_path(self, start_symbol: str) -> list[ContextLayer]:
        """Bottom-up path traversal.

        From symbol → source file → community → project overview.
        """
        layer = self.get_symbol_layer(start_symbol)
        if not layer.detail:
            return [layer]

        file_path = layer.detail.get("file_path", "")
        node_id = layer.layer_id

        # Find the community the symbol belongs to
        communities = self._store.get_communities(self._task_id)
        symbol_comm = None
        for comm in communities:
            node_list = self._parse_json_list(comm.get("node_list", "[]"))
            if node_id in node_list:
                symbol_comm = comm
                break

        layers: list[ContextLayer] = [layer]

        if file_path:
            layers.append(self.get_file_layer(file_path))

        if symbol_comm:
            layers.append(self.get_community_layer(symbol_comm.get("comm_id", "")))

        layers.append(self.get_project_layer())
        return layers

    # ═══════════════════════════════════════════
    # LLM Formatting
    # ═══════════════════════════════════════════

    def format_for_llm(self, layers: list[ContextLayer], direction: str = "top-down") -> str:
        """Format context layers as LLM prompt text.

        Args:
            layers: List of ContextLayer
            direction: "top-down" or "bottom-up"

        Returns:
            Structured prompt text
        """
        if direction == "top-down":
            return self._format_top_down(layers)
        else:
            return self._format_bottom_up(layers)

    def _format_top_down(self, layers: list[ContextLayer]) -> str:
        """Format top-down: from project overview down to source code."""
        parts: list[str] = []
        indent = 0
        for i, layer in enumerate(layers):
            prefix = "  " * indent
            level_label = {"project": "Project", "community": "Community", "file": "File", "symbol": "Symbol"}.get(
                layer.level, layer.level
            )
            parts.append(f"{prefix}## {level_label}: {layer.name}")
            parts.append(f"{prefix}  - What: {layer.what}")
            if layer.how:
                parts.append(f"{prefix}  - How: {layer.how}")
            if layer.why:
                parts.append(f"{prefix}  - Why: {layer.why}")
            parts.append("")
            indent += 1
        return "\n".join(parts)

    def _format_bottom_up(self, layers: list[ContextLayer]) -> str:
        """Format bottom-up: from source code details up to architecture overview."""
        parts: list[str] = []
        for i, layer in enumerate(layers):
            level_label = {"project": "Project", "community": "Community", "file": "File", "symbol": "Symbol"}.get(
                layer.level, layer.level
            )
            parts.append(f"## [{level_label}] {layer.name}")
            parts.append(f"  {layer.what}")
            if layer.how and i > 0:  # lower layers focus more on implementation
                parts.append(f"  Implementation: {layer.how}")
            if layer.why:
                parts.append(f"  Design rationale: {layer.why}")
            parts.append("")
        return "\n".join(parts)

    # ═══════════════════════════════════════════
    # Utility Methods
    # ═══════════════════════════════════════════

    def check_ready(self, task_id: str | None = None) -> bool:
        """Check if analysis data is ready."""
        tid = task_id or self._task_id
        try:
            count = self._store.count_graph_nodes(tid)
            return count > 0
        except Exception:
            return False

    def get_summary(self) -> dict:
        """Get analysis data summary statistics."""
        try:
            total_nodes = self._store.count_graph_nodes(self._task_id)
            total_edges = len(self._store.get_graph_edges(self._task_id))
            incl_comms = len(self._store.get_communities(self._task_id, edge_type="INCLUDE"))
            call_comms = len(self._store.get_communities(self._task_id, edge_type="CALL"))
            return {
                "task_id": self._task_id,
                "total_nodes": total_nodes,
                "total_edges": total_edges,
                "include_communities": incl_comms,
                "call_communities": call_comms,
                "ready": total_nodes > 0,
            }
        except Exception as e:
            return {"task_id": self._task_id, "ready": False, "error": str(e)}

    @staticmethod
    def _parse_json_list(raw) -> list:
        """Parse JSON string or already-decoded list."""
        if isinstance(raw, list):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return []
        return []

    @staticmethod
    def _parse_json_dict(raw) -> dict:
        """Parse JSON string or already-decoded dict."""
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, str) and raw.strip():
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}
