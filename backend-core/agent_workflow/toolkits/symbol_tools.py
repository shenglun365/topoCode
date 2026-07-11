"""
符号查询工具 — 用于 LLM Agentic 工作流查询代码符号信息。
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


class GetSymbolDetailTool(AgentTool):
    """Get detailed info for a specific symbol"""

    name = "get_symbol_detail"
    description = "Get detailed symbol info: type, signature, code snippet, file path"
    category = "query"
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
                        "symbol_id": {
                            "type": "string",
                            "description": "Unique symbol ID (graph_node.id)",
                        },
                    },
                    "required": ["symbol_id"],
                },
            },
        }

    async def execute(self, symbol_id: str = "", **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("Database not initialized")
        try:
            row = self._db.execute(
                "SELECT * FROM graph_node WHERE id = ?", (symbol_id,)
            ).fetchone()
            if not row:
                return ToolResult.fail(f"Symbol not found: {symbol_id}")
            d = dict(row)
            if "file_path" in d:
                d["file_path"] = _rel_path(d["file_path"], self._project_root)
            return ToolResult.ok(data=json.dumps(d, ensure_ascii=False, default=str)[:5000])
        except Exception as e:
            logger.warning(f"[GetSymbolDetailTool] failed: {e}")
            return ToolResult.fail(str(e))


class SearchSymbolsTool(AgentTool):
    """Search code symbols by name"""

    name = "search_symbols"
    description = "Search code symbols by name (functions, classes, methods, etc.), returns matching symbol list"
    category = "query"
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
                        "pattern": {
                            "type": "string",
                            "description": "Symbol name keyword (supports LIKE fuzzy matching)",
                        },
                        "kind": {
                            "type": "string",
                            "description": "Symbol type filter: function / method / class / variable (optional)",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Max number of results (default 20)",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        }

    async def execute(self, pattern: str = "", kind: str = "", limit: int = 20, **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("Database not initialized")
        try:
            # Compatible with LLM possibly passing string-typed numeric params
            if not isinstance(limit, int):
                try:
                    limit = int(limit)
                except (TypeError, ValueError):
                    limit = 20
            # Support | delimited multiple patterns (OR search)
            patterns = [p.strip() for p in pattern.split("|") if p.strip()] or [pattern]
            clauses = []
            params: list[Any] = []
            for p in patterns:
                clauses.append("name LIKE ?")
                params.append(f"%{p}%")
            sql = "SELECT id, name, kind, file_path FROM graph_node WHERE (" + " OR ".join(clauses) + ")"
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            sql += f" ORDER BY name LIMIT {min(limit, 100)}"
            rows = self._db.execute(sql, params).fetchall()
            if not rows:
                return ToolResult.fail(f"No symbols matching '{pattern}'")
            results = [
                f"{r['name']} ({r['kind']}) — {_rel_path(r['file_path'], self._project_root)}"
                for r in rows
            ]
            return ToolResult.ok(data="\n".join(results))
        except Exception as e:
            logger.warning(f"[SearchSymbolsTool] failed: {e}")
            return ToolResult.fail(str(e))


class GetSymbolCodeTool(AgentTool):
    """Get full source code for a symbol (supports ID / name+file / line+file lookups)"""

    name = "get_symbol_code"
    description = (
        "Get full source code snippet for a symbol. Supports three lookup methods:"
        "1) symbol_id: exact lookup (graph_node.id);"
        "2) file_path + name: lookup by file name + symbol name;"
        "3) file_path + line: lookup by file name + line number range"
    )
    category = "query"
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
                        "symbol_id": {
                            "type": "string",
                            "description": "Symbol ID (graph_node.id, visible in structured output)"
                        },
                        "file_path": {
                            "type": "string",
                            "description": "File path (use with name or line)"
                        },
                        "name": {
                            "type": "string",
                            "description": "Symbol name (use with file_path)"
                        },
                        "line": {
                            "type": "integer",
                            "description": "Line number (use with file_path, returns symbol containing that line)"
                        },
                    },
                },
            },
        }

    async def execute(self, symbol_id: str = "", file_path: str = "",
                      name: str = "", line: int = 0, **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("Database not initialized")
        try:
            row = None
            method = ""

            # 1. symbol_id primary key
            if symbol_id:
                method = "symbol_id"
                row = self._db.execute(
                    "SELECT * FROM graph_node WHERE id=?", (symbol_id,)
                ).fetchone()

            # 2. file_path + name
            if not row and file_path and name:
                method = "file_path+name"
                qpath = _rel_path(file_path, self._project_root) if self._project_root else file_path
                row = self._db.execute(
                    "SELECT * FROM graph_node WHERE file_path=? AND name=? LIMIT 1",
                    (qpath, name)
                ).fetchone()

            # 3. file_path + line
            if not row and file_path and line > 0:
                method = "file_path+line"
                qpath = _rel_path(file_path, self._project_root) if self._project_root else file_path
                row = self._db.execute(
                    "SELECT * FROM graph_node WHERE file_path=? "
                    "AND start_line <= ? AND end_line >= ? LIMIT 1",
                    (qpath, line, line)
                ).fetchone()

            if not row:
                hint = ("Symbol not found. Try: "
                        "1) get_symbol_code(file_path=\"...\", name=\"function_name\") to search by name; "
                        "2) search_symbols(pattern=\"...\") to find symbols then use symbol_id for exact lookup")
                return ToolResult.fail(hint)

            d = dict(row)
            logger.info(
                f"[GetSymbolCodeTool] found: name={d.get('name','')} "
                f"kind={d.get('kind','')} lookup={method} id={d.get('id','')[:16]}"
            )
            abs_path = d.get("file_path", "")
            if self._project_root and not os.path.isabs(abs_path):
                abs_path = os.path.join(self._project_root, abs_path)

            if not os.path.isfile(abs_path):
                return ToolResult.fail(
                    f"File not on disk. Use get_symbol_detail(symbol_id=\"{d['id']}\") to view metadata"
                )

            start = max(1, d.get("start_line", 1) - 3)
            end = d.get("end_line", start + 30)
            try:
                with open(abs_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                    code = "".join(lines[start-1:end])
            except (UnicodeDecodeError, LookupError):
                with open(abs_path, "r", encoding="latin-1") as f:
                    lines = f.readlines()
                    code = "".join(lines[start-1:end])

            return ToolResult.ok(data=json.dumps({
                "symbol_id": d["id"],
                "name": d.get("name", ""),
                "kind": d.get("kind", ""),
                "file_path": _rel_path(abs_path, self._project_root),
                "line_range": f"L{start}-{end}",
                "signature": d.get("signature", ""),
                "docstring": d.get("docstring", ""),
                "code": code[:10000],
                "lookup_method": method,
            }, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"[GetSymbolCodeTool] failed: {e}")
            return ToolResult.fail(str(e))
