"""ToolDispatcher — dispatches MCP tools/call requests to handlers.

Each tool maps to a handler method. Handlers use SimpleBinder + FileSymbolTable
to resolve symbols and references from in-memory analysis data.
"""

import json as json_mod
import logging
from typing import Any, Optional

from .tools import CORE_TOOLS
from .path_validator import PathValidator

logger = logging.getLogger(__name__)


class ToolDispatcher:
    """Receives MCP tools/call requests, dispatches to corresponding handler.

    When zmq_client is provided (ZMQ mode), calls are forwarded to the main
    backend process. Otherwise, handlers run locally via direct library calls.
    """

    def __init__(
        self,
        project_root: str,
        tables: Optional[list] = None,
        resolver: Optional[Any] = None,
        snapshot_store: Optional[Any] = None,
        git_adapter: Optional[Any] = None,
        zmq_client: Optional[Any] = None,
    ):
        self.project_root = project_root
        self.path_validator = PathValidator(project_root)
        self._tables = tables or []
        self._resolver = resolver
        self._snapshot_store = snapshot_store
        self._git_adapter = git_adapter
        self._zmq_client = zmq_client
        self._handlers = {
            "get_definition": self._handle_definition,
            "get_references": self._handle_references,
            "get_symbol_info": self._handle_symbol_info,
            "get_call_hierarchy": self._handle_call_hierarchy,
            "get_file_symbols": self._handle_file_symbols,
            "get_dependencies": self._handle_dependencies,
            "search_symbol": self._handle_search_symbol,
            "get_changes": self._handle_get_changes,
            "get_version_history": self._handle_version_history,
            "evaluate_change": self._handle_evaluate_change,
            "track_symbol_history": self._handle_track_symbol_history,
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
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            if "file_path" in arguments:
                self.path_validator.assert_valid(arguments["file_path"])
            result = handler(arguments)
            return {"content": [{"type": "text", "text": _json_dumps(result)}]}
        except Exception as e:
            logger.exception(f"Tool {tool_name} failed")
            return {"error": str(e)}

    # ---- handlers ----

    def _handle_definition(self, args: dict) -> dict:
        file_path = args["file_path"]
        line = args["line"]
        character = args["character"]
        # Build a reference from the given position and resolve it
        ref = self._make_ref(file_path, line, character)
        if not ref:
            return {"found": False, "error": "No symbol at position"}

        if self._resolver:
            result = self._resolver.resolve(ref, file_path=file_path)
            if result and result.target:
                sym = result.target
                return {
                    "found": True,
                    "file_path": sym.location.file_path,
                    "line": sym.location.start_line,
                    "character": sym.location.start_col,
                    "symbol_name": sym.name,
                    "symbol_kind": sym.kind.value,
                    "scope": sym.scope,
                    "confidence": result.confidence,
                    "method": result.method,
                }
        return {"found": False}

    def _handle_references(self, args: dict) -> dict:
        file_path = args["file_path"]
        line = args["line"]
        character = args["character"]
        max_results = args.get("max_results", 500)

        ref = self._make_ref(file_path, line, character)
        if not ref:
            return {"found": False, "error": "No symbol at position"}

        # Collect references from all tables
        refs = []
        for table in self._tables:
            for r in table.references:
                if r.name == ref.name and len(refs) < max_results:
                    refs.append({
                        "file_path": table.file_path,
                        "line": r.location.start_line,
                        "character": r.location.start_col,
                        "end_line": r.location.end_line,
                        "end_col": r.location.end_col,
                        "kind": r.kind.value,
                        "scope": r.scope,
                    })

        by_file = {}
        for r in refs:
            by_file.setdefault(r["file_path"], []).append(r)

        return {
            "symbol_name": ref.name,
            "total_count": len(refs),
            "truncated": len(refs) >= max_results,
            "by_file": by_file,
        }

    def _handle_symbol_info(self, args: dict) -> dict:
        file_path = args["file_path"]
        line = args["line"]
        character = args["character"]

        for table in self._tables:
            if table.file_path != file_path:
                continue
            for sym in table.symbols:
                loc = sym.location
                if loc.start_line <= line <= loc.end_line:
                    return {
                        "found": True,
                        "name": sym.name,
                        "kind": sym.kind.value,
                        "scope": sym.scope,
                        "file_path": table.file_path,
                        "line": loc.start_line,
                        "character": loc.start_col,
                        "end_line": loc.end_line,
                        "end_col": loc.end_col,
                        "doc_comment": sym.doc_comment or "",
                    }
        return {"found": False}

    def _handle_call_hierarchy(self, args: dict) -> dict:
        return {
            "info": "Call hierarchy requires full analysis pipeline. "
                    "Run project analysis first.",
            "incoming": [],
            "outgoing": [],
        }

    def _handle_file_symbols(self, args: dict) -> dict:
        file_path = args["file_path"]
        kind_filter = args.get("kind_filter")

        symbols = []
        for table in self._tables:
            if table.file_path != file_path:
                continue
            for sym in table.symbols:
                if kind_filter and sym.kind.value not in kind_filter:
                    continue
                if sym.scope == "module" or not sym.scope.count("."):
                    symbols.append({
                        "name": sym.name,
                        "kind": sym.kind.value,
                        "scope": sym.scope,
                        "line": sym.location.start_line,
                        "character": sym.location.start_col,
                    })
        return {"file_path": file_path, "symbols": symbols}

    def _handle_dependencies(self, args: dict) -> dict:
        file_path = args["file_path"]
        direction = args.get("direction", "both")

        imports = []
        imported_by = []

        for table in self._tables:
            if direction in ("imports", "both") and table.file_path == file_path:
                for imp in table.imports:
                    imports.append({
                        "module": imp.module,
                        "names": imp.imported_names,
                        "is_default": imp.is_default,
                    })
            if direction in ("imported_by", "both"):
                for imp in table.imports:
                    if imp.resolved_file == file_path:
                        imported_by.append(table.file_path)

        return {
            "file_path": file_path,
            "imports": imports,
            "imported_by": list(set(imported_by)),
        }

    def _handle_search_symbol(self, args: dict) -> dict:
        query = args["query"].lower()
        kind_filter = args.get("kind_filter", "all")
        max_results = args.get("max_results", 20)

        matches = []
        for table in self._tables:
            for sym in table.symbols:
                if len(matches) >= max_results:
                    break
                if query not in sym.name.lower():
                    continue
                if kind_filter != "all" and sym.kind.value != kind_filter:
                    continue
                matches.append({
                    "name": sym.name,
                    "kind": sym.kind.value,
                    "scope": sym.scope,
                    "file_path": table.file_path,
                    "line": sym.location.start_line,
                })
        return {"matches": matches, "total": len(matches), "truncated": len(matches) >= max_results}

    # ---- Phase 7: Change Awareness handlers ----

    def _handle_get_changes(self, args: dict) -> dict:
        from_change = args.get("from_commit", "HEAD~1")
        to_change = args.get("to_commit", "HEAD")
        scope = args.get("scope", "summary")

        if not self._snapshot_store or not self._git_adapter:
            return {"error": "Change tracking requires SnapshotStore and GitAdapter. Run project analysis with snapshot enabled."}

        git = self._git_adapter
        store = self._snapshot_store

        from_snapshot = store.get_snapshot(self.project_root, from_change)
        to_snapshot = store.get_snapshot(self.project_root, to_change)

        if not from_snapshot:
            from_snapshot = self._make_empty_snapshot(from_change)
        if not to_snapshot:
            to_snapshot = self._make_empty_snapshot(to_change)

        from change_tracker.diff_engine import DiffEngine
        report = DiffEngine().compare(from_snapshot, to_snapshot)

        from change_tracker.impact_analyzer import ImpactAnalyzer
        impact = ImpactAnalyzer(self.project_root, self._resolver).analyze(report)

        if scope == "files":
            return {
                "from_commit": from_change,
                "to_commit": to_change,
                "files": [
                    {"file_path": f.file_path, "change_type": f.change_type.value}
                    for f in report.files
                ],
                "summary": {
                    "files_changed": report.summary.files_changed,
                },
            }

        result = {
            "from_commit": from_change,
            "to_commit": to_change,
            "summary": {
                "files_changed": report.summary.files_changed,
                "symbols_added": report.summary.symbols_added,
                "symbols_modified": report.summary.symbols_modified,
                "symbols_removed": report.summary.symbols_removed,
                "risk_score": report.summary.risk_score,
                "risk_level": report.summary.risk_level.value,
            },
            "dependencies": [
                {"file_path": d.file_path, "dependency": d.dependency, "change_type": d.change_type.value}
                for d in report.dependencies
            ],
            "impact": impact,
        }

        if scope in ("symbols", "full"):
            result["files"] = [
                {
                    "file_path": f.file_path,
                    "change_type": f.change_type.value,
                    "symbols": [
                        {
                            "name": s.name,
                            "kind": s.kind,
                            "change_type": s.change_type.value,
                            "risk": s.risk.value,
                        }
                        for s in f.symbols_changed
                    ],
                }
                for f in report.files
            ]

        return result

    def _handle_version_history(self, args: dict) -> dict:
        max_count = args.get("max_count", 20)
        only_analyzed = args.get("only_analyzed", False)

        commits = []
        if self._git_adapter:
            commits = self._git_adapter.get_commit_history(max_count)

        if self._snapshot_store:
            snapshots = self._snapshot_store.list_snapshots(self.project_root, max_count)
            snap_hashes = {s["commit_hash"] for s in snapshots}
            for c in commits:
                c["has_snapshot"] = c["hash"] in snap_hashes
        else:
            for c in commits:
                c["has_snapshot"] = False

        if only_analyzed:
            commits = [c for c in commits if c.get("has_snapshot")]

        return {"commits": commits}

    def _handle_evaluate_change(self, args: dict) -> dict:
        from_change = args.get("from_commit", "HEAD~1")
        to_change = args.get("to_commit", "HEAD")
        focus = args.get("focus", "overview")

        if not self._snapshot_store or not self._git_adapter:
            return {"error": "Change evaluation requires SnapshotStore and GitAdapter."}

        store = self._snapshot_store
        git = self._git_adapter

        from_snapshot = store.get_snapshot(self.project_root, from_change)
        to_snapshot = store.get_snapshot(self.project_root, to_change)

        stats = git.get_diff_stats(from_change, to_change)
        changed_files = git.get_changed_files(from_change, to_change)

        eval_focus = focus
        result = {
            "from_commit": from_change,
            "to_commit": to_change,
            "focus": eval_focus,
            "git_stats": stats,
            "changed_files": changed_files,
            "snapshots_available": from_snapshot is not None and to_snapshot is not None,
        }

        if from_snapshot and to_snapshot:
            from change_tracker.diff_engine import DiffEngine
            report = DiffEngine().compare(from_snapshot, to_snapshot)
            result["risk_level"] = report.summary.risk_level.value
            result["risk_score"] = report.summary.risk_score

            if eval_focus == "breaking":
                breaking = any(
                    sc.risk.value in ("high", "critical")
                    for fc in report.files
                    for sc in fc.symbols_changed
                )
                result["has_breaking_changes"] = breaking

        return result

    def _handle_track_symbol_history(self, args: dict) -> dict:
        symbol_name = args.get("symbol_name", "")
        file_path = args.get("file_path", "")
        max_versions = args.get("max_versions", 10)

        if not self._snapshot_store:
            return {"error": "Symbol history tracking requires SnapshotStore."}

        snapshots = self._snapshot_store.list_snapshots(self.project_root, max_versions)
        history = []

        for snap_info in snapshots:
            snap = self._snapshot_store.get_snapshot(self.project_root, snap_info["commit_hash"])
            if not snap:
                continue
            file_symbols = snap.symbols.get(file_path, [])
            for sym in file_symbols:
                if sym.get("name") == symbol_name:
                    history.append({
                        "commit": snap.commit_hash,
                        "timestamp": snap.timestamp.isoformat(),
                        "symbol": sym,
                    })
                    break

        return {
            "symbol_name": symbol_name,
            "file_path": file_path,
            "history": history,
            "versions_found": len(history),
        }

    def _make_empty_snapshot(self, commit_hash: str):
        from datetime import datetime
        from change_tracker.change_model import ProjectSnapshot
        return ProjectSnapshot(
            commit_hash=commit_hash,
            timestamp=datetime.now(),
        )

    # ---- helpers ----

    def _make_ref(self, file_path: str, line: int, character: int):
        """Find a reference at the given position."""
        from parsers.symbol_model import Reference, RefKind, SourceLocation

        for table in self._tables:
            if table.file_path != file_path:
                continue
            for ref in table.references:
                loc = ref.location
                if loc.start_line <= line <= loc.end_line:
                    return ref
                # Also check for exact position match on symbols
            for sym in table.symbols:
                loc = sym.location
                if loc.start_line == line and loc.start_col <= character < loc.end_col:
                    return Reference(
                        name=sym.name,
                        kind=RefKind.IDENT,
                        location=loc,
                        scope=sym.scope,
                    )
        return None


def _json_dumps(obj: Any) -> str:
    import json
    return json.dumps(obj, indent=2, default=str)
