"""
图分析工具 — AgentTool 版本的社区子图 / 调用链 / AST 查询。
"""

import json
import logging
import os
from typing import Any, Optional

from ..tools import AgentTool, ToolResult

logger = logging.getLogger(__name__)


def _rel_path(path: str, project_root: Optional[str]) -> str:
    """Convert absolute path to relative path (reduce LLM context token cost)"""
    if project_root and os.path.isabs(path):
        try:
            return os.path.relpath(path, project_root)
        except ValueError:
            return path
    return path


class GetCommunitySubgraphTool(AgentTool):
    """Get subgraph structure from community analysis"""

    name = "get_community_subgraph"
    description = "Get subgraph structure of a community: includes all nodes and edges, supports depth expansion"
    category = "graph"
    llm_visible = True

    def __init__(self, project_db=None, project_root=""):
        self._db = project_db
        self._project_root = project_root

    def to_openai_schema(self) -> Optional[dict]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {"type": "string", "description": "Analysis task ID"},
                        "comm_id": {"type": "string", "description": "Community group ID"},
                        "comm_lv": {"type": "string", "description": "Community level (L0/L1/L2)", "default": "L2"},
                        "edge_type": {"type": "string", "description": "Edge type (CALL/INCLUDE)", "default": "CALL"},
                        "depth": {"type": "integer", "description": "Expand depth (1-4), default 2", "default": 2},
                    },
                    "required": ["task_id", "comm_id"],
                },
            },
        }

    async def execute(self, task_id: str = "", comm_id: str = "",
                      comm_lv: str = "", edge_type: str = "",
                      depth: int = 2, **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("Database not initialized")
        try:
            # Compatible with LLM passing string-typed depth
            if not isinstance(depth, int):
                try:
                    depth = int(depth)
                except (TypeError, ValueError):
                    depth = 2

            # When model mistakenly passes comm_id to task_id, auto-resolve real task_id from community records
            if task_id and task_id.startswith("comm-"):
                resolved = self._db.execute(
                    "SELECT task_id FROM graph_doc WHERE comm_id=? LIMIT 1",
                    (task_id,)
                ).fetchone()
                if resolved:
                    task_id = resolved["task_id"]
                    logger.info(f"[GetCommunitySubgraphTool] auto-resolved task_id={task_id} from comm_id={comm_id}")

            # Try with provided values first, then fallback
            candidates = []
            if edge_type and comm_lv:
                candidates.append((edge_type, comm_lv))
            if edge_type:
                candidates.append((edge_type, ""))
            if comm_lv:
                candidates.append(("", comm_lv))
            candidates.extend([("INCLUDE", ""), ("CALL", "")])

            for et, cl in candidates:
                params: list = [task_id, comm_id]
                sql = "SELECT * FROM graph_doc WHERE task_id=? AND comm_id=?"
                if et:
                    sql += " AND edge_type=?"
                    params.append(et)
                if cl:
                    sql += " AND comm_lv=?"
                    params.append(cl)
                rows = self._db.execute(sql, params).fetchall()
                if rows:
                    result = {"edge_type": et, "comm_lv": cl if cl else "any",
                              "nodes": [], "edges": []}
                    for r in rows:
                        d = dict(r)
                        if d.get("node_list"):
                            try:
                                nodes = json.loads(d["node_list"])
                                # String entries are file paths, convert to relative paths
                                result["nodes"].extend(
                                    _rel_path(n, self._project_root) if isinstance(n, str) else n
                                    for n in nodes
                                )
                            except json.JSONDecodeError:
                                pass
                        if d.get("edge_list"):
                            try:
                                result["edges"].extend(json.loads(d["edge_list"]))
                            except json.JSONDecodeError:
                                pass
                    return ToolResult.ok(
                        data=json.dumps(result, ensure_ascii=False, default=str)[:8000]
                    )

            return ToolResult.fail(f"Subgraph not found: {comm_id}")
        except Exception as e:
            logger.warning(f"[GetCommunitySubgraphTool] failed: {e}")
            return ToolResult.fail(str(e))


class GetCallChainTool(AgentTool):
    """Get call chain between two symbols"""

    name = "get_call_chain"
    description = "Get call chain between two symbols (with intermediate nodes), supports max depth limit"
    category = "graph"
    llm_visible = True

    def __init__(self, project_db=None):
        self._db = project_db

    def to_openai_schema(self) -> Optional[dict]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "from_symbol_id": {"type": "string", "description": "Source symbol ID"},
                        "to_symbol_id": {"type": "string", "description": "Target symbol ID"},
                        "task_id": {"type": "string", "description": "Analysis task ID"},
                        "max_depth": {"type": "integer", "description": "Max depth, default 5", "default": 5},
                    },
                    "required": ["from_symbol_id", "to_symbol_id", "task_id"],
                },
            },
        }

    async def execute(self, from_symbol_id: str = "", to_symbol_id: str = "",
                      task_id: str = "", max_depth: int = 5, **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("Database not initialized")
        try:
            from_id = from_symbol_id
            to_id = to_symbol_id
            visited = set()
            queue = [(from_id, [from_id])]
            chain = None

            while queue and len(queue[0][1]) <= max_depth:
                curr, path = queue.pop(0)
                if curr == to_id:
                    chain = path
                    break
                if curr in visited:
                    continue
                visited.add(curr)
                edges = self._db.execute(
                    "SELECT target_id FROM dependencies WHERE source_id=? AND task_id=?",
                    (curr, task_id)
                ).fetchall()
                for e in edges:
                    if e["target_id"] not in visited:
                        queue.append((e["target_id"], path + [e["target_id"]]))

            if chain:
                node_names = []
                for nid in chain:
                    row = self._db.execute(
                        "SELECT name, kind FROM graph_node WHERE id=?", (nid,)
                    ).fetchone()
                    node_names.append(f"{row['name'] if row else nid} ({row['kind'] if row else '?'})")
                return ToolResult.ok(data=" → ".join(node_names))
            return ToolResult.fail(f"Call chain not found from {from_id} to {to_id}")
        except Exception as e:
            logger.warning(f"[GetCallChainTool] failed: {e}")
            return ToolResult.fail(str(e))


class GetASTNodeTool(AgentTool):
    """Get detailed code content for a specific AST node"""

    name = "get_ast_node"
    description = "Get detailed code content for an AST node (with file path and line range)"
    category = "graph"
    llm_visible = True

    def __init__(self, project_db=None):
        self._db = project_db

    def to_openai_schema(self) -> Optional[dict]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "node_id": {
                            "type": "string",
                            "description": "AST node ID (base_node node_id)",
                        },
                        "file_id": {
                            "type": "string",
                            "description": "File ID (works with node_id for precise location)",
                        },
                    },
                    "required": ["node_id"],
                },
            },
        }

    async def execute(self, node_id: str = "", file_id: str = "", **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("Database not initialized")
        try:
            sql = "SELECT * FROM base_node WHERE node_id=?"
            params: list[Any] = [node_id]
            if file_id:
                sql += " AND file_id=?"
                params.append(file_id)
            row = self._db.execute(sql, params).fetchone()
            if not row:
                return ToolResult.fail(f"AST node not found: {node_id}")
            d = dict(row)
            code = d.get("code") or d.get("content") or ""
            return ToolResult.ok(data=json.dumps({
                "node_id": node_id,
                "kind": d.get("kind", ""),
                "file_id": d.get("file_id", ""),
                "code": code[:5000],
                "line_start": d.get("line_start", 0),
                "line_end": d.get("line_end", 0),
            }, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"[GetASTNodeTool] failed: {e}")
            return ToolResult.fail(str(e))
