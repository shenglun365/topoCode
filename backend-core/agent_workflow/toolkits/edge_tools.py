"""
边关系工具 — AgentTool 版本的边详情查询。
"""

import json
import logging
from typing import Any, Optional

from ..tools import AgentTool, ToolResult

logger = logging.getLogger(__name__)


class GetEdgeDetailTool(AgentTool):
    """获取指定边的详细信息"""

    name = "get_edge_detail"
    description = "获取指定边的详细信息：调用关系、依赖类型、数据流方向"
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
                        "edge_id": {
                            "type": "string",
                            "description": "边的唯一标识 ID",
                        },
                    },
                    "required": ["edge_id"],
                },
            },
        }

    async def execute(self, edge_id: str = "", **kwargs) -> ToolResult:
        if not self._db:
            return ToolResult.fail("数据库未初始化")
        try:
            row = self._db.execute(
                "SELECT * FROM dependencies WHERE id=?",
                (edge_id,)
            ).fetchone()
            if not row:
                return ToolResult.fail(f"边未找到: {edge_id}")
            d = dict(row)
            source = self._db.execute(
                "SELECT name, kind FROM graph_node WHERE id=?",
                (d.get("source_id", ""),)
            ).fetchone()
            target = self._db.execute(
                "SELECT name, kind FROM graph_node WHERE id=?",
                (d.get("target_id", ""),)
            ).fetchone()
            return ToolResult.ok(data=json.dumps({
                "edge_id": edge_id,
                "source": f"{source['name']} ({source['kind']})" if source else d.get("source_id", ""),
                "target": f"{target['name']} ({target['kind']})" if target else d.get("target_id", ""),
                "type": d.get("type", ""),
                "dependency_type": d.get("dependency_type", ""),
            }, ensure_ascii=False))
        except Exception as e:
            logger.warning(f"[GetEdgeDetailTool] failed: {e}")
            return ToolResult.fail(str(e))
