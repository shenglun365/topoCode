"""ToolDispatcher — dispatches MCP tools/call requests to handlers.

v2 refactor: LSP-style tools replaced with architecture-cognition tools.
Handlers use AnalysisContext to access graph_node / graph_edge / community data.
"""

import json as json_mod
import logging
from typing import Any, Optional

from .tools import CORE_TOOLS, get_deprecation_notice
from .path_validator import PathValidator

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Receives MCP tools/call requests, dispatches to handlers.

    v2 tools: topocode_community, topocode_community_detail,
               topocode_architecture_overview, topocode_diff,
               topocode_session_summary, topocode_quality_inspect
    """

    def __init__(
        self,
        project_root: str,
        context: Optional[Any] = None,
        snapshot_store: Optional[Any] = None,
        git_adapter: Optional[Any] = None,
        zmq_client: Optional[Any] = None,
    ):
        """
        Args:
            project_root: project root path
            context: AnalysisContext instance (v2, preferred over old tables/resolver)
            snapshot_store: SnapshotStore for diff/version tools
            git_adapter: GitAdapter for commit operations
            zmq_client: ZMQ client for forwarding to main backend
        """
        self.project_root = project_root
        self.path_validator = PathValidator(project_root)
        self._ctx = context
        self._snapshot_store = snapshot_store
        self._git_adapter = git_adapter
        self._zmq_client = zmq_client

        # v2 handlers (architecture-cognition)
        self._handlers = {
            "topocode_community": self._handle_community,
            "topocode_community_detail": self._handle_community_detail,
            "topocode_architecture_overview": self._handle_arch_overview,
            "topocode_diff": self._handle_diff,
            "topocode_session_summary": self._handle_session_summary,
            "topocode_quality_inspect": self._handle_quality_inspect,
        }

        # Deprecated tool names → v2 redirect or deprecation notice
        self._deprecated = {
            "get_definition": self._deprecated_handler,
            "get_references": self._deprecated_handler,
            "get_symbol_info": self._deprecated_handler,
            "get_call_hierarchy": self._deprecated_handler,
            "get_file_symbols": self._deprecated_handler,
            "get_dependencies": self._deprecated_handler,
            "search_symbol": self._deprecated_handler,
            "get_changes": self._handle_diff,  # redirect to v2
            "evaluate_change": self._deprecated_handler,
            "get_version_history": self._deprecated_handler,
            "track_symbol_history": self._deprecated_handler,
        }

    # ---- dispatch ----

    async def dispatch(self, tool_name: str, arguments: dict) -> dict:
        # ZMQ mode: forward to main backend
        if self._zmq_client:
            try:
                params = dict(arguments)
                params["_project_root"] = self.project_root
                result = await self._zmq_client.call("mcp.dispatch", {
                    "tool_name": tool_name,
                    "arguments": params,
                })
                return result
            except Exception as e:
                logger.exception(f"ZMQ dispatch failed for {tool_name}")
                return {"error": str(e)}

        # Direct mode: local handlers
        handler = self._handlers.get(tool_name)
        if not handler:
            handler = self._deprecated.get(tool_name)

        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            result = handler(arguments)
            return {"content": [{"type": "text", "text": _json_dumps(result)}]}
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed")
            return {"error": str(e)}

    # ═══════════════════════════════════════════
    # v2 Handlers
    # ═══════════════════════════════════════════

    def _handle_community(self, args: dict) -> dict:
        if not self._ctx:
            return {"error": "AnalysisContext not available. Run project analysis first."}

        edge_type = args.get("edge_type", "INCLUDE")
        level = args.get("level", 0)
        communities = self._ctx._store.get_communities(self._ctx._task_id, edge_type=edge_type)

        filtered = [c for c in communities if c.get("comm_lv") == f"L{level}"]
        if not filtered:
            filtered = communities[:20]  # fallback

        return {
            "edge_type": edge_type,
            "level": level,
            "total": len(filtered),
            "communities": [
                {
                    "comm_id": c.get("comm_id"),
                    "node_count": c.get("node_count"),
                    "edge_count": c.get("edge_count"),
                    "quality_score": c.get("quality_score"),
                    "parent_comm_id": c.get("parent_comm_id"),
                }
                for c in filtered[:30]
            ],
        }

    def _handle_community_detail(self, args: dict) -> dict:
        if not self._ctx:
            return {"error": "AnalysisContext not available."}

        comm_id = args["comm_id"]
        layer = self._ctx.get_community_layer(comm_id)

        return {
            "comm_id": comm_id,
            "name": layer.name,
            "what": layer.what,
            "how": layer.how,
            "why": layer.why,
            "detail": {
                "node_count": layer.detail.get("node_count"),
                "edge_count": layer.detail.get("edge_count"),
                "hubs": layer.detail.get("hubs", [])[:10],
                "hub_names": layer.detail.get("hub_names", []),
                "quality_score": layer.detail.get("quality_score"),
            },
            "children": layer.children[:20],
        }

    def _handle_arch_overview(self, args: dict) -> dict:
        if not self._ctx:
            return {"error": "AnalysisContext not available."}

        focus = args.get("focus", "overview")
        layer = self._ctx.get_project_layer()

        include_comms = self._ctx._store.get_communities(self._ctx._task_id, edge_type="INCLUDE", comm_lv="L0")
        call_comms = self._ctx._store.get_communities(self._ctx._task_id, edge_type="CALL", comm_lv="L0")

        return {
            "focus": focus,
            "what": layer.what,
            "how": layer.how,
            "why": layer.why,
            "detail": layer.detail,
            "include_communities": [
                {"comm_id": c.get("comm_id"), "node_count": c.get("node_count"), "quality_score": c.get("quality_score")}
                for c in include_comms[:15]
            ],
            "call_communities": [
                {"comm_id": c.get("comm_id"), "node_count": c.get("node_count"), "quality_score": c.get("quality_score")}
                for c in call_comms[:15]
            ],
        }

    def _handle_diff(self, args: dict) -> dict:
        from_change = args.get("from_commit", "HEAD~1")
        to_change = args.get("to_commit", "HEAD")
        scope = args.get("scope", "full")

        if self._snapshot_store and self._git_adapter:
            try:
                from change_tracker.diff_engine import DiffEngine
                from_snap = self._snapshot_store.get_snapshot(self.project_root, from_change)
                to_snap = self._snapshot_store.get_snapshot(self.project_root, to_change)
                if from_snap and to_snap:
                    report = DiffEngine().compare(from_snap, to_snap)
                    return {
                        "from_commit": from_change,
                        "to_commit": to_change,
                        "scope": scope,
                        "summary": {
                            "files_changed": report.summary.files_changed,
                            "symbols_added": report.summary.symbols_added,
                            "symbols_modified": report.summary.symbols_modified,
                            "symbols_removed": report.summary.symbols_removed,
                            "risk_score": report.summary.risk_score,
                        },
                    }
            except Exception as e:
                logger.warning(f"diff failed: {e}")

        return {
            "from_commit": from_change,
            "to_commit": to_change,
            "note": "Full diff analysis requires snapshot data. Run project analysis with --snapshot enabled.",
        }

    def _handle_session_summary(self, args: dict) -> dict:
        session_id = args.get("session_id", "")
        try:
            if self._ctx and self._ctx._store:
                # Check for saved session data
                summary = self._ctx.get_summary()
                return {
                    "session_id": session_id or "latest",
                    "project_summary": summary,
                    "note": "Session tracking is not available. Current output is project-level summary.",
                }
        except Exception as e:
            logger.warning(f"session_summary failed: {e}")
        return {"session_id": session_id or "latest", "note": "No session data available."}

    def _handle_quality_inspect(self, args: dict) -> dict:
        focus = args.get("focus", "all")
        if not self._ctx:
            return {"error": "AnalysisContext not available."}

        issues = []
        try:
            include_comms = self._ctx._store.get_communities(self._ctx._task_id, edge_type="INCLUDE")
            call_comms = self._ctx._store.get_communities(self._ctx._task_id, edge_type="CALL")

            for comm in include_comms + call_comms:
                node_count = comm.get("node_count", 0) or 0
                if node_count > 100 and focus in ("hub_overload", "all"):
                    issues.append({
                        "type": "hub_overload",
                        "severity": "MEDIUM",
                        "community": comm.get("comm_id"),
                        "node_count": node_count,
                        "message": f"社区 {comm.get('comm_id')} 包含 {node_count} 个节点，考虑拆分。",
                    })

            # Check for orphan communities
            small_comms = [c for c in include_comms if (c.get("node_count") or 0) < 3]
            for c in small_comms[:5]:
                if focus in ("test_gaps", "all"):
                    issues.append({
                        "type": "small_community",
                        "severity": "LOW",
                        "community": c.get("comm_id"),
                        "node_count": c.get("node_count"),
                        "message": f"社区 {c.get('comm_id')} 节点过少，可能缺少测试覆盖。",
                    })
        except Exception as e:
            logger.warning(f"quality_inspect failed: {e}")

        return {
            "focus": focus,
            "total_issues": len(issues),
            "issues": issues[:20],
        }

    # ═══════════════════════════════════════════
    # Deprecated
    # ═══════════════════════════════════════════

    def _deprecated_handler(self, args: dict) -> dict:
        """Return deprecation notice for old tool names."""
        # The tool_name is unfortunately not available here; we detect it heuristically
        tool_name = args.get("_tool_name", "unknown")
        notice = get_deprecation_notice(tool_name) or "This tool has been deprecated."
        return {
            "deprecated": True,
            "tool": tool_name,
            "message": f"This MCP tool is deprecated. {notice}",
        }


def _json_dumps(obj: Any) -> str:
    return json_mod.dumps(obj, indent=2, default=str)
