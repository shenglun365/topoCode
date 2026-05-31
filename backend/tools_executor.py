"""Tools Executor — Tools Calling 模式下的工具执行器

在后端执行 LLM 请求的工具调用，支持的工具类型：
  - DB 查询: get_file_content / get_symbol_detail / search_symbols / get_edge_detail
  - 图分析: get_community_subgraph / get_call_chain

所有工具直接查询 SQLite，零网络延迟。
"""

import json
import logging
import os
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
                    "fileId": {"type": "string", "description": "文件的唯一标识 ID"},
                    "filePath": {"type": "string", "description": "文件的相对路径（与 fileId 二选一）"}
                },
                "required": []
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
                    "commLv": {"type": "string", "description": "社区层级 (L0/L1/L2)", "default": "L2"},
                    "edgeType": {"type": "string", "description": "边类型 (CALL/DEPENDENCY)", "default": "CALL"},
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
    },
    {
        "type": "function",
        "function": {
            "name": "get_ast_node",
            "description": "获取指定 AST 节点的详细代码内容（含所在文件和行号范围）",
            "parameters": {
                "type": "object",
                "properties": {
                    "nodeId": {"type": "string", "description": "AST 节点 ID（base_node 的 node_id）"},
                    "fileId": {"type": "string", "description": "文件 ID（与 nodeId 配合精确定位）", "default": ""}
                },
                "required": ["nodeId"]
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
            'get_ast_node': self._get_ast_node,
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
        """获取源码文件内容（从磁盘读取真实内容）"""
        file_id = args.get('fileId', '')
        file_path = args.get('filePath', '')

        if not file_id and not file_path:
            return {"error": "fileId or filePath is required"}

        # 从项目库找到关联的 project_id
        project_row = self.multi_db.main_db.fetchone(
            "SELECT id, root_path FROM projects ORDER BY updated_at DESC LIMIT 1"
        )
        if not project_row:
            return {"error": "No project found"}

        project_id = project_row['id']
        root_path = project_row['root_path']

        try:
            project_db = self.multi_db.get_project_db(project_id)
            if file_id:
                row = project_db.fetchone(
                    "SELECT id, file_path as path, language FROM source_files WHERE id = ?",
                    (file_id,)
                )
            elif file_path:
                row = project_db.fetchone(
                    "SELECT id, file_path as path, language FROM source_files WHERE file_path = ?",
                    (file_path,)
                )
            if not row:
                return {"error": f"File not found: {file_id or file_path}"}

            # 从磁盘读取真实内容
            full_path = os.path.join(root_path, row['path'])
            if not os.path.isfile(full_path):
                return {"error": f"File not on disk: {full_path}"}

            with open(full_path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(self.MAX_RESULT_LENGTH + 1000)

            truncated = len(content) > self.MAX_RESULT_LENGTH
            if truncated:
                content = content[:self.MAX_RESULT_LENGTH] + "\n...(truncated)"

            return {
                "fileId": row['id'],
                "path": row['path'],
                "language": row['language'],
                "content": content,
                "size": len(content),
                "truncated": truncated,
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

    def _get_ast_node(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取 AST 节点的详细代码内容"""
        node_id = args.get('nodeId', '')
        file_id = args.get('fileId', '')

        if not node_id:
            return {"error": "nodeId is required"}

        for db_key in list(getattr(self.multi_db, '_project_db_cache', {}).keys()):
            db = self.multi_db._project_db_cache[db_key]
            row = db.fetchone(
                """SELECT id, file_id, node_id, type, name, refs, start, end
                   FROM base_node WHERE node_id = ?""",
                (node_id,)
            )
            if not row and file_id:
                row = db.fetchone(
                    """SELECT id, file_id, node_id, type, name, refs, start, end
                       FROM base_node WHERE node_id = ? AND file_id = ?""",
                    (node_id, file_id)
                )
            if row:
                # Get file path for context
                file_row = db.fetchone(
                    "SELECT file_path FROM source_files WHERE id = ?",
                    (row['file_id'],)
                )
                return {
                    "nodeId": row['node_id'],
                    "fileId": row['file_id'],
                    "filePath": file_row['file_path'] if file_row else '?',
                    "type": row['type'],
                    "name": row['name'],
                    "refs": row.get('refs', ''),
                    "start": row['start'],
                    "end": row['end'],
                }

        return {"error": f"AST node not found: {node_id}"}

    def _get_community_subgraph(self, args: Dict[str, Any]) -> Dict[str, Any]:
        """获取社区子图（真实查询 graph_doc 表）"""
        task_id = args.get('taskId', '')
        comm_id = args.get('commId', '')
        comm_lv = args.get('commLv', 'L2')
        edge_type = args.get('edgeType', 'CALL')
        depth = min(max(int(args.get('depth', 2)), 1), 4)

        if not task_id or not comm_id:
            return {"error": "taskId and commId are required"}

        # 从所有项目库中找到包含此 task 的库
        project_id = None
        project_db = None
        for db_key in list(self.multi_db._project_db_cache.keys()):
            db = self.multi_db._project_db_cache[db_key]
            row = db.fetchone(
                "SELECT DISTINCT task_id FROM graph_doc WHERE task_id = ? LIMIT 1",
                (task_id,)
            )
            if row:
                project_id = db_key
                project_db = db
                break

        if not project_db:
            # Fallback: try all project DBs
            for db_key in self.multi_db._project_dbs:
                db = self.multi_db._project_dbs[db_key]
                row = db.fetchone(
                    "SELECT DISTINCT task_id FROM graph_doc WHERE task_id = ? LIMIT 1",
                    (task_id,)
                )
                if row:
                    project_id = db_key
                    project_db = db
                    break

        if not project_db:
            return {"error": f"Task not found: {task_id}"}

        try:
            # 查找主社区记录
            comm_row = project_db.fetchone(
                """SELECT * FROM graph_doc
                   WHERE task_id = ? AND comm_id = ? AND comm_lv = ? AND edge_type = ?
                   LIMIT 1""",
                (task_id, comm_id, comm_lv, edge_type)
            )
            if not comm_row:
                # Try without comm_lv filter
                comm_row = project_db.fetchone(
                    """SELECT * FROM graph_doc
                       WHERE task_id = ? AND comm_id = ?
                       LIMIT 1""",
                    (task_id, comm_id)
                )
            if not comm_row:
                return {"error": f"Community not found: {comm_id} in task {task_id}"}

            node_list = json.loads(comm_row['node_list']) if isinstance(comm_row['node_list'], str) else comm_row['node_list']
            edge_list = json.loads(comm_row['edge_list']) if comm_row.get('edge_list') and isinstance(comm_row['edge_list'], str) else comm_row.get('edge_list', [])

            # 查询子社区
            children = []
            if depth > 1:
                child_rows = project_db.fetchall(
                    """SELECT comm_id, comm_lv, node_count, edge_count FROM graph_doc
                       WHERE task_id = ? AND parent_comm_id = ? AND edge_type = ?
                       ORDER BY comm_lv, comm_id""",
                    (task_id, comm_id, edge_type)
                )
                for cr in child_rows:
                    children.append({
                        "communityId": cr['comm_id'],
                        "level": cr['comm_lv'],
                        "nodeCount": cr['node_count'],
                        "edgeCount": cr['edge_count'],
                    })

            return {
                "communityId": comm_id,
                "level": comm_row.get('comm_lv', comm_lv),
                "edgeType": edge_type,
                "nodeCount": comm_row['node_count'],
                "edgeCount": comm_row['edge_count'],
                "qualityScore": comm_row.get('quality_score'),
                "nodes": node_list if isinstance(node_list, list) else str(node_list)[:2000],
                "edges": edge_list if isinstance(edge_list, list) else str(edge_list)[:2000],
                "children": children,
                "depth": depth,
            }
        except Exception as e:
            logger.error(f"[ToolExecutor] get_community_subgraph failed: {e}")
            return {"error": str(e)}

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
        """获取调用链（BFS 查询 graph_node 表）"""
        from_id = args.get('fromSymbolId', '')
        to_id = args.get('toSymbolId', '')
        task_id = args.get('taskId', '')
        max_depth = min(max(int(args.get('maxDepth', 5)), 1), 10)

        if not from_id or not to_id or not task_id:
            return {"error": "fromSymbolId, toSymbolId, and taskId are required"}

        # 找到正确的项目库
        project_db = None
        for db_key in list(getattr(self.multi_db, '_project_db_cache', {}).keys()):
            db = self.multi_db._project_db_cache[db_key]
            row = db.fetchone(
                "SELECT DISTINCT task_id FROM graph_node WHERE task_id = ? LIMIT 1",
                (task_id,)
            )
            if row:
                project_db = db
                break

        if not project_db:
            return {"error": f"Task not found: {task_id}"}

        try:
            # BFS 查找调用链
            # node format: { 'id': graph_node.id, 'caller': name, 'callee': name, 'depth': d, 'path': [...] }
            queue = [{'nodeId': from_id, 'depth': 0, 'path': [from_id]}]
            visited = {from_id}
            found_paths = []

            while queue and len(found_paths) < 3:  # max 3 paths
                current = queue.pop(0)
                if current['depth'] >= max_depth:
                    continue

                # 查找以 current 为 caller 的边
                edges = project_db.fetchall(
                    """SELECT id, caller_func_name, callee_name, callee_node_id
                       FROM graph_node
                       WHERE task_id = ? AND caller_node_id = ?""",
                    (task_id, current['nodeId'])
                )

                for edge in edges:
                    callee_node = edge.get('callee_node_id') or str(edge['id'])
                    new_path = current['path'] + [callee_node]

                    if callee_node == to_id:
                        # Found target
                        path_details = []
                        for pn in new_path:
                            detail = project_db.fetchone(
                                """SELECT id, caller_func_name, callee_name
                                   FROM graph_node WHERE task_id = ? AND (caller_node_id = ? OR id = ?)
                                   LIMIT 1""",
                                (task_id, pn, pn)
                            )
                            path_details.append({
                                'nodeId': pn,
                                'caller': detail.get('caller_func_name', '?') if detail else '?',
                                'callee': detail.get('callee_name', '?') if detail else '?',
                            })
                        found_paths.append(path_details)
                        break

                    if callee_node not in visited and current['depth'] + 1 < max_depth:
                        visited.add(callee_node)
                        queue.append({
                            'nodeId': callee_node,
                            'depth': current['depth'] + 1,
                            'path': new_path,
                        })

            return {
                "fromSymbolId": from_id,
                "toSymbolId": to_id,
                "maxDepth": max_depth,
                "paths": found_paths if found_paths else [],
                "message": f"Found {len(found_paths)} call path(s)" if found_paths else "No call path found",
            }
        except Exception as e:
            logger.error(f"[ToolExecutor] get_call_chain failed: {e}")
            return {"error": str(e)}
