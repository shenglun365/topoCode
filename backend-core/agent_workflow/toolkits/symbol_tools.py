"""
符号查询工具 — 用于 LLM Agentic 工作流查询代码符号信息。
"""

import json
import logging
from typing import Any, Optional

from ..tools import AgentTool, ToolResult

logger = logging.getLogger(__name__)


class GetSymbolDetailTool(AgentTool):
    """获取指定符号的详细信息"""

    name = "get_symbol_detail"
    description = "获取指定符号的详细信息：类型、签名、代码片段、所在文件路径"
    category = "query"
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
                        "symbol_id": {
                            "type": "string",
                            "description": "符号的唯一标识 ID（graph_node.id）",
                        },
                    },
                    "required": ["symbol_id"],
                },
            },
        }

    async def execute(self, symbol_id: str = "", **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("数据库未初始化")
        try:
            row = self._db.execute(
                "SELECT * FROM graph_node WHERE id = ?", (symbol_id,)
            ).fetchone()
            if not row:
                return ToolResult.fail(f"符号未找到: {symbol_id}")
            d = dict(row)
            return ToolResult.ok(data=json.dumps(d, ensure_ascii=False, default=str)[:5000])
        except Exception as e:
            logger.warning(f"[GetSymbolDetailTool] failed: {e}")
            return ToolResult.fail(str(e))


class SearchSymbolsTool(AgentTool):
    """按名称搜索代码符号"""

    name = "search_symbols"
    description = "按名称搜索代码符号（函数、类、方法等），返回匹配的符号列表"
    category = "query"
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
                        "pattern": {
                            "type": "string",
                            "description": "符号名称关键字（支持 LIKE 模糊匹配）",
                        },
                        "kind": {
                            "type": "string",
                            "description": "符号类型过滤: function / method / class / variable（可选）",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最大返回数量（默认 20）",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        }

    async def execute(self, pattern: str = "", kind: str = "", limit: int = 20, **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("数据库未初始化")
        try:
            sql = "SELECT id, name, kind, file_path FROM graph_node WHERE name LIKE ?"
            params: list[Any] = [f"%{pattern}%"]
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            sql += f" LIMIT {min(limit, 100)}"
            rows = self._db.execute(sql, params).fetchall()
            if not rows:
                return ToolResult.fail(f"未找到匹配 '{pattern}' 的符号")
            results = [f"{r['name']} ({r['kind']}) — {r['file_path']}" for r in rows]
            return ToolResult.ok(data="\n".join(results))
        except Exception as e:
            logger.warning(f"[SearchSymbolsTool] failed: {e}")
            return ToolResult.fail(str(e))
