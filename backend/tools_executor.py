"""Tools Executor — Tools Calling 模式下的工具执行器

在后端执行 LLM 请求的工具调用，支持的工具类型：
  - DB 查询: get_file_content / get_symbol_detail / search_symbols / get_edge_detail
  - 图分析: get_community_subgraph / get_call_chain

所有工具直接查询 SQLite，零网络延迟。
"""

import json
import logging
from typing import Any, Dict, List, Optional

from sqlite_ctx import MultiDBManager

logger = logging.getLogger(__name__)

# ==================== 工具定义 (OpenAI 兼容格式) ====================

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_file_content",
            "description": "获取指定源码文件的完整内容（超过 10000 字符自动截断）",
            "parameters": {
                "type": "object",
                "properties": {
                    "fileId": {"type": "string", "description": "文件的唯一标识 ID"}
                },
                "required": ["fileId"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_symbol_detail",
            "description": "获取指定符号的详细信息：类型、签名、代码片段、所在文件路径",
            "parameters": {
                "type": "object",
                "properties": {
                    "symbolId": {"type": "string", "description": "符号的唯一标识 ID（base_node.id 或 graph_node.id）"}
                },
                "required": ["symbolId"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_community_subgraph",
            "description": "获取社区分析的子图结构：包含指定社区内的所有节点和边，支持按深度展开",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {"type": "string", "description": "分析任务 ID"},
                    "commId": {"type": "string", "description": "社区分组 ID"},
                    "depth": {"type": "integer", "description": "展开深度 (1-4)，默认 2", "default": 2}
                },
                "required": ["taskId", "commId"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_edge_detail",
            "description": "获取指定边的详细信息：调用关系、依赖类型、数据流方向",
            "parameters": {
                "type": "object",
                "properties": {
                    "edgeId": {"type": "string", "description": "边的唯一标识 ID"}
                },
                "required": ["edgeId"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_symbols",
            "description": "按名称搜索项目中的符号（函数/类/方法/变量），返回匹配的符号列表",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {"type": "integer", "description": "最多返回条数，默认 20", "default": 20}
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_call_chain",
            "description": "获取两个符号之间的调用链路（含中间节点），支持限制最大深度",
            "parameters": {
                "type": "object",
                "properties": {
                    "fromSymbolId": {"type": "string", "description": "起始符号 ID"},
                    "toSymbolId": {"type": "string", "description": "目标符号 ID"},
                    "taskId": {"type": "string", "description": "分析任务 ID"},
                    "maxDepth": {"type": "integer", "description": "最大深度，默认 5", "default": 5}
                },
                "required": ["fromSymbolId", "toSymbolId", "taskId"]
            }
        }
    }
]

# 工具名 → 索引映射
TOOL_MAP = {t["function"]["name"]: t for t in TOOL_DEFINITIONS}


def get_tool_definitions(tool_names: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    """获取工具定义列表（OpenAI 兼容格式）
    
    Args:
        tool_names: 需要的工具名列表，None 表示全部
    """
    if tool_names is None:
        return TOOL_DEFINITIONS
    return [TOOL_MAP[name] for name in tool_names if name in TOOL_MAP]


# ==================== 工具执行器 ====================

class ToolExecutor:
    """Tools Calling 模式下的工具执行器"""

    MAX_RESULT_LENGTH = 10000  # 单个工具结果最大字符数

    def __init__(self, multi_db: MultiDBManager):
        self.multi_db = multi_db
        self._handlers = {
            'get_file_content': self._get_file_content,
            'get_symbol_detail': self._get_symbol_detail,
            'get_community_subgraph': self._get_community_subgraph,
            'get_edge_detail': self._get_edge_detail,
            'search_symbols': self._search_symbols,
            'get_call_chain': self._get_call_chain,
        }

    def execute(self, tool_name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具并返回结果"""
        handler = self._handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            result = handler(args)
            # 截断过长结果
            result_str = json.dumps(result, ensure_ascii=False, default=str)
            if len(result_str) > self.MAX_RESULT_LENGTH:
                result_str = result_str[:self.MAX_RESULT_LENGTH] + "\n...(truncated)"
                result = {"content": result_str, "truncated": True}
            return result
        except Exception as e:
            logger.error(f"[ToolExecutor] {tool_name} failed: {e}")
            return {"error": str(e)}

    # ==================== 工具实现 ====================

    def _get_file_content(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取源码文件内容"""
        file_id = args.get('fileId', '')
        if not file_id:
            return {"error": "fileId is required"}

        # 从项目库的 source_files 表查询
        # 需要从 graph_node 或 base_node 找到关联的 project_id
        row = self.multi_db.main_db.fetchone(
            """SELECT p.id as project_id
               FROM projects p
               WHERE p.id IN (
                   SELECT DISTINCT project_id FROM llm_sessions
               )
               LIMIT 1"""
        )
        if not row or not row.get('project_id'):
            return {"error": "No project context found"}

        project_id = row['project_id']
        try:
            project_db = self.multi_db.get_project_db(project_id)
            row = project_db.fetchone(
                "SELECT id, relative_path as path, language FROM source_files WHERE id = ?",
                (file_id,)
            )
            if not row:
                return {"error": f"File not found: {file_id}"}

            return {
                "fileId": row['id'],
                "path": row['path'],
                "language": row['language'],
            }
        except Exception as e:
            return {"error": f"Failed to read file: {e}"}

    def _get_symbol_detail(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取符号详情"""
        symbol_id = args.get('symbolId', '')
        if not symbol_id:
            return {"error": "symbolId is required"}

        # 从 base_node 查询（跨所有项目库）
        # 先找到包含此 base_node 的项目库
        for db_key in self.multi_db._project_dbs:
            db = self.multi_db._project_dbs[db_key]
            row = db.fetchone(
                """SELECT id, file_id, func_name, class_name, method_name,
                          symbol_type, docstring, refs, line_start, line_end
                   FROM base_node WHERE id = ?""",
                (symbol_id,)
            )
            if row:
                return {
                    "symbolId": row['id'],
                    "fileId": row['file_id'],
                    "funcName": row['func_name'],
                    "className": row['class_name'],
                    "methodName": row['method_name'],
                    "symbolType": row['symbol_type'],
                    "docstring": row.get('docstring', ''),
                    "refs": row.get('refs', ''),
                    "lineRange": f"{row.get('line_start', '?')}-{row.get('line_end', '?')}",
                }

        return {"error": f"Symbol not found: {symbol_id}"}

    def _get_community_subgraph(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取社区子图"""
        task_id = args.get('taskId', '')
        comm_id = args.get('commId', '')
        depth = min(max(int(args.get('depth', 2)), 1), 4)

        if not task_id or not comm_id:
            return {"error": "taskId and commId are required"}

        # 从 graph_doc 获取社区信息
        project_id = task_id[:13]  # task_id format: project_id + suffix
        try:
            project_db = self.multi_db.get_project_db(project_id)
        except Exception:
            return {"error": f"Project DB not found for task: {task_id}"}

        return {
            "communityId": comm_id,
            "depth": depth,
            "message": "Community subgraph query — detailed implementation in Phase 3 with graph analysis",
        }

    def _get_edge_detail(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取边详情"""
        edge_id = args.get('edgeId', '')
        if not edge_id:
            return {"error": "edgeId is required"}

        # 从 graph_node 查询
        for db_key in self.multi_db._project_dbs:
            db = self.multi_db._project_dbs[db_key]
            row = db.fetchone(
                """SELECT id, task_id, symbol_node_type, caller_func_name,
                          callee_name, callee_file_id, caller_file_id
                   FROM graph_node WHERE id = ?""",
                (edge_id,)
            )
            if row:
                return {
                    "edgeId": row['id'],
                    "taskId": row['task_id'],
                    "type": row['symbol_node_type'],
                    "caller": row['caller_func_name'],
                    "callee": row['callee_name'],
                    "calleeFileId": row['callee_file_id'],
                    "callerFileId": row['caller_file_id'],
                }

        return {"error": f"Edge not found: {edge_id}"}

    def _search_symbols(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """搜索符号"""
        query = args.get('query', '')
        limit = min(int(args.get('limit', 20)), 100)

        if not query:
            return {"error": "query is required"}

        results = []
        for db_key in self.multi_db._project_dbs:
            db = self.multi_db._project_dbs[db_key]
            rows = db.fetchall(
                """SELECT id, file_id, func_name, class_name, method_name,
                          symbol_type, line_start
                   FROM base_node
                   WHERE func_name LIKE ? OR class_name LIKE ? OR method_name LIKE ?
                   LIMIT ?""",
                (f'%{query}%', f'%{query}%', f'%{query}%', limit)
            )
            for r in rows:
                name = r['func_name'] or r['method_name'] or r['class_name']
                results.append({
                    "symbolId": r['id'],
                    "name": name,
                    "type": r['symbol_type'],
                    "fileId": r['file_id'],
                    "line": r['line_start'],
                })

        return {
            "query": query,
            "count": len(results),
            "symbols": results[:limit],
        }

    def _get_call_chain(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取调用链"""
        from_id = args.get('fromSymbolId', '')
        to_id = args.get('toSymbolId', '')
        task_id = args.get('taskId', '')
        max_depth = min(max(int(args.get('maxDepth', 5)), 1), 10)

        if not from_id or not to_id or not task_id:
            return {"error": "fromSymbolId, toSymbolId, and taskId are required"}

        return {
            "fromSymbolId": from_id,
            "toSymbolId": to_id,
            "maxDepth": max_depth,
            "message": "Call chain query — detailed BFS implementation in Phase 3",
        }
