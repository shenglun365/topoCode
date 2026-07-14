"""Web Tools — Web AI 对话可调用的架构分析工具

所有工具复用现有的 MultiDBManager + community_data 查询，
不重复实现数据访问逻辑。
"""

import json
import logging
import os
import sys as _sys

_project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_backend_dir = os.path.join(_project_root, "backend-core")
if _backend_dir not in _sys.path:
    _sys.path.insert(0, _backend_dir)

import community_data as cd
from sqlite_ctx import MultiDBManager

logger = logging.getLogger(__name__)

MAX_RESULT_LENGTH = 8000


def _is_empty_result(result: dict) -> bool:
    """检测工具返回结果是否为空（无有效数据），用于触发跳过提示"""
    if not result:
        return True
    if result.get("found") is False:
        return True
    if result.get("total") == 0 and "projects" in result:
        return True
    if result.get("total") == 0 and "tasks" in result:
        return True
    if not result.get("nodes") and not result.get("edges") and ("nodes" in result or "edges" in result):
        return True
    if result.get("levels") is not None and len(result.get("levels", [])) == 0:
        return True
    if result.get("files") is not None and len(result.get("files", [])) == 0:
        return True
    if result.get("data") is not None and len(result.get("data", [])) == 0:
        return True
    return False


REF_TYPES = {
    "project", "task", "community_doc", "community_graph",
    "source_file", "symbol", "ast_node", "subgraph", "archive",
}

# ==================== 工具定义 ====================

WEB_TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "web_list_projects",
            "description": "列出所有已分析的项目（含名称、ID、根路径、创建时间）",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_task_list",
            "description": "获取指定项目下的所有分析任务",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {
                        "type": "string",
                        "description": "项目 ID",
                    },
                },
                "required": ["projectId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_architecture_overview",
            "description": "获取项目架构概览文档（含 What/How/Why 分层描述）",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {
                        "type": "string",
                        "description": "分析任务 ID",
                    },
                },
                "required": ["taskId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_community_tree",
            "description": "浏览社区层级树（L0-L5），返回各层级的所有社区",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {"type": "string", "description": "分析任务 ID"},
                    "edgeType": {
                        "type": "string",
                        "description": "边类型: CALL 或 INCLUDE",
                        "default": "CALL",
                    },
                },
                "required": ["taskId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_community_detail",
            "description": "获取指定社区的 LLM 分析详情（名称、摘要、层级）",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {"type": "string", "description": "分析任务 ID"},
                    "commId": {"type": "string", "description": "社区 ID"},
                    "edgeType": {
                        "type": "string",
                        "description": "边类型: CALL 或 INCLUDE",
                        "default": "CALL",
                    },
                },
                "required": ["taskId", "commId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_community_graph",
            "description": "获取社区子图（节点列表和边列表），支持按深度展开子社区",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {"type": "string", "description": "分析任务 ID"},
                    "commId": {"type": "string", "description": "社区 ID"},
                    "edgeType": {
                        "type": "string",
                        "description": "边类型: CALL 或 INCLUDE",
                        "default": "CALL",
                    },
                    "depth": {
                        "type": "integer",
                        "description": "展开深度（1-3）",
                        "default": 1,
                    },
                    "gran": {
                        "type": "string",
                        "description": "粒度: component 或 file",
                        "default": "component",
                    },
                },
                "required": ["taskId", "commId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_community_files",
            "description": "列出指定社区包含的所有源码文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {"type": "string", "description": "分析任务 ID"},
                    "commId": {"type": "string", "description": "社区 ID"},
                    "edgeType": {
                        "type": "string",
                        "description": "边类型: CALL 或 INCLUDE",
                        "default": "CALL",
                    },
                },
                "required": ["taskId", "commId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_read_file",
            "description": "读取项目中的源码文件内容（自动截断过长文件）",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "description": "项目 ID"},
                    "path": {"type": "string", "description": "文件相对路径"},
                },
                "required": ["projectId", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_file_summary",
            "description": "获取文件的 AI 预摘要（如果已生成）",
            "parameters": {
                "type": "object",
                "properties": {
                    "taskId": {"type": "string", "description": "分析任务 ID"},
                    "path": {"type": "string", "description": "文件相对路径"},
                },
                "required": ["taskId", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_symbols",
            "description": "按名称搜索项目中的符号（函数/类/方法/变量）",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "description": "项目 ID"},
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数",
                        "default": 20,
                    },
                },
                "required": ["projectId", "query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_symbol_detail",
            "description": "获取符号的详细信息：类型、签名、所在文件路径",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "description": "项目 ID"},
                    "symbolId": {"type": "string", "description": "符号 ID (graph_node.id)"},
                },
                "required": ["projectId", "symbolId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_call_chain",
            "description": "获取指定符号的调用链路（调用者和被调用者）",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "description": "项目 ID"},
                    "symbol": {"type": "string", "description": "符号名"},
                    "depth": {
                        "type": "integer",
                        "description": "调用链深度",
                        "default": 2,
                    },
                },
                "required": ["projectId", "symbol"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_archives",
            "description": "搜索历史对话中保存的知识归档条目",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "projectId": {
                        "type": "string",
                        "description": "项目 ID（可选，筛选）",
                    },
                    "category": {
                        "type": "string",
                        "description": "分类（可选，筛选）",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_save_archive",
            "description": "将有价值的分析结论保存到知识归档中，供后续检索",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "归档标题"},
                    "content": {"type": "string", "description": "归档内容"},
                    "sessionId": {"type": "string", "description": "当前会话 ID"},
                    "category": {
                        "type": "string",
                        "description": "分类: component/algorithm/pattern/decision/note",
                        "default": "note",
                    },
                    "tags": {
                        "type": "string",
                        "description": "逗号分隔的标签",
                    },
                },
                "required": ["title", "content", "sessionId"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_set_session_title",
            "description": "当你理解了用户的问题和对话主题后，调用此工具为会话设置一个有意义的标题（10字以内）。调用一次即可。",
            "parameters": {
                "type": "object",
                "properties": {
                    "sessionId": {"type": "string", "description": "当前会话 ID"},
                    "title": {"type": "string", "description": "会话标题（10字以内）"},
                },
                "required": ["sessionId", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_conversation_history",
            "description": "搜索当前会话或指定会话的对话历史。当需要回顾更早的讨论内容时使用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "会话ID，不传则搜索当前会话。可使用 @session:xxx 格式指定其他会话"
                    },
                    "query": {
                        "type": "string",
                        "description": "搜索关键词，搜索 user 和 assistant 消息内容"
                    },
                },
                "required": ["query"],
            },
        },
    },
    # ── conversation_analyst ──
    {
        "type": "function",
        "function": {
            "name": "web_list_sessions",
            "description": "列出所有会话，支持按项目、状态过滤。获取会话列表后可进一步查看详情。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "项目ID，过滤该项目下的会话"},
                    "status": {"type": "string", "enum": ["active", "archived"], "description": "会话状态"},
                    "limit": {"type": "integer", "description": "返回条数（默认 20，最大 100）"},
                    "offset": {"type": "integer", "description": "分页偏移"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_session_info",
            "description": "获取指定会话的元信息：标题、状态、模型、消息数、创建时间、活跃技能等。",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "会话ID"},
                },
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search_across_sessions",
            "description": "跨所有会话搜索消息内容。支持按关键词、项目过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "project_id": {"type": "string", "description": "限定项目ID"},
                    "limit": {"type": "integer", "description": "每会话返回条数（默认 5）"},
                    "session_limit": {"type": "integer", "description": "搜索的会话数上限（默认 10）"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_session_messages",
            "description": "获取指定会话的全部或部分消息。支持按角色过滤和分页。",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "会话ID"},
                    "role": {"type": "string", "enum": ["user", "assistant", "tool", "all"], "description": "过滤角色"},
                    "limit": {"type": "integer", "description": "返回条数（默认 50，最大 200）"},
                    "offset": {"type": "integer", "description": "分页偏移"},
                },
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_summarize_session",
            "description": "基于指定会话的全部消息，生成结构化摘要。可用于压缩长会话、提取关键信息。",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "要摘要的会话ID"},
                    "max_length": {"type": "integer", "description": "摘要最大字数（默认 500）"},
                },
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_extract_topics",
            "description": "从指定会话中提取讨论的主题、涉及的项目/社区/文件/符号等关键实体。",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "会话ID"},
                    "detail": {"type": "string", "enum": ["brief", "full"], "description": "详细程度"},
                },
                "required": ["session_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_compare_sessions",
            "description": "对比多个会话的讨论主题、涉及资源和关键结论。可用于发现跨会话的知识关联。",
            "parameters": {
                "type": "object",
                "properties": {
                    "session_ids": {"type": "string", "description": "会话ID列表，逗号分隔，如 chat_xxx,chat_yyy"},
                    "aspect": {"type": "string", "enum": ["topic", "resource", "conclusion"], "description": "对比维度"},
                },
                "required": ["session_ids"],
            },
        },
    },
    # ── knowledge_keeper 增强 ──
    {
        "type": "function",
        "function": {
            "name": "web_list_archives",
            "description": "列出知识归档，支持按分类、标签过滤。",
            "parameters": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string", "description": "限定项目ID"},
                    "category": {"type": "string", "description": "归档分类（如 compress / note / insight）"},
                    "tag": {"type": "string", "description": "按标签过滤"},
                    "limit": {"type": "integer", "description": "返回条数（默认 20，最大 100）"},
                    "offset": {"type": "integer", "description": "分页偏移"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_delete_archive",
            "description": "删除指定的知识归档。",
            "parameters": {
                "type": "object",
                "properties": {
                    "archive_id": {"type": "string", "description": "归档ID"},
                },
                "required": ["archive_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_update_archive",
            "description": "更新指定归档的分类和标签。",
            "parameters": {
                "type": "object",
                "properties": {
                    "archive_id": {"type": "string", "description": "归档ID"},
                    "category": {"type": "string", "description": "新分类"},
                    "tags": {"type": "string", "description": "新标签，逗号分隔"},
                },
                "required": ["archive_id"],
            },
        },
    },
]

WEB_TOOL_MAP = {t["function"]["name"]: t for t in WEB_TOOL_DEFINITIONS}


def get_web_tool_definitions(tool_names=None):
    if tool_names is None:
        return WEB_TOOL_DEFINITIONS
    return [WEB_TOOL_MAP[n] for n in tool_names if n in WEB_TOOL_MAP]


# ==================== 工具执行器 ====================


import re as _re
_RE_TYPE_PREFIX = _re.compile(r'^@\w+:(.+)')

def _strip_ref_prefix(val: str) -> str:
    """精确去除 @type: 前缀，仅当字符串以 @type: 开头时才剥离。"""
    if isinstance(val, str):
        m = _RE_TYPE_PREFIX.match(val)
        if m:
            return m.group(1)
    return val


class WebToolExecutor:
    """Web AI 对话的工具执行器"""

    def __init__(self, multi_db: MultiDBManager, current_session_id: str = ""):
        self.multi_db = multi_db
        self._current_session_id = current_session_id
        self._handlers = {
            "web_list_projects": self._list_projects,
        "web_get_task_list": self._get_task_list,
            "web_get_architecture_overview": self._get_architecture_overview,
            "web_get_community_tree": self._get_community_tree,
            "web_get_community_detail": self._get_community_detail,
            "web_get_community_graph": self._get_community_graph,
            "web_get_community_files": self._get_community_files,
            "web_read_file": self._read_file,
            "web_get_file_summary": self._get_file_summary,
            "web_search_symbols": self._search_symbols,
            "web_get_symbol_detail": self._get_symbol_detail,
            "web_get_call_chain": self._get_call_chain,
            "web_search_archives": self._search_archives,
            "web_save_archive": self._save_archive,
            "web_set_session_title": self._set_session_title,
            "web_search_conversation_history": self._search_conversation_history,
            "web_list_sessions": self._list_sessions,
            "web_get_session_info": self._get_session_info,
            "web_search_across_sessions": self._search_across_sessions,
            "web_get_session_messages": self._get_session_messages,
            "web_summarize_session": self._summarize_session,
            "web_extract_topics": self._extract_topics,
            "web_compare_sessions": self._compare_sessions,
            "web_list_archives": self._list_archives,
            "web_delete_archive": self._delete_archive,
            "web_update_archive": self._update_archive,
        }

    def execute(self, tool_name: str, args: dict) -> dict:
        handler = self._handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}", "skip": True}
        try:
            result = handler(args)
            result_str = json.dumps(result, ensure_ascii=False, default=str)
            if len(result_str) > MAX_RESULT_LENGTH:
                result_str = result_str[:MAX_RESULT_LENGTH] + "\n...(truncated)"
                return {"content": result_str, "truncated": True}
            # 空结果标记：让 LLM 知道此路径无有效数据，跳过
            if _is_empty_result(result):
                result["_skip"] = True
                result["_message"] = "此工具未返回有效数据，请跳过此路径，尝试其他方法"
            return result
        except Exception as e:
            logger.error(f"[WebToolExecutor] {tool_name} failed: {e}")
            return {"error": str(e), "skip": True, "_message": f"工具 {tool_name} 执行失败，请跳过此路径"}

    def _resolve_task(self, task_id: str) -> tuple:
        task = self.multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if not task:
            task = self.multi_db.main_db.fetchone(
                "SELECT project_id FROM analysis_tasks WHERE id LIKE ?", (task_id + '%',)
            )
        if not task:
            raise ValueError(f"Task {task_id} not found")
        return task["project_id"], self.multi_db.get_project_db(task["project_id"])

    def _list_projects(self, args: dict) -> dict:
        rows = self.multi_db.main_db.fetchall(
            "SELECT id, name, root_path, created_at FROM projects ORDER BY updated_at DESC"
        )
        return {
            "projects": [
                {"id": r["id"], "name": r["name"], "rootPath": r["root_path"], "createdAt": r["created_at"]}
                for r in rows
            ],
            "total": len(rows),
        }

    def _get_task_list(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        rows = self.multi_db.main_db.fetchall(
            "SELECT id, name, type, status, created_at "
            "FROM analysis_tasks WHERE project_id = ? ORDER BY created_at DESC",
            (pid,),
        )
        return {
            "tasks": [
                {
                    "id": r["id"],
                    "name": r["name"],
                    "type": r["type"],
                    "status": r["status"],
                    "createdAt": r["created_at"],
                }
                for r in rows
            ],
            "total": len(rows),
        }

    def _get_architecture_overview(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        pid, pdb = self._resolve_task(task_id)
        doc = pdb.fetchone(
            "SELECT id, title, content FROM report_subdocs WHERE id = ?",
            (f"overall-{task_id}",),
        )
        if not doc:
            return {"found": False, "message": "架构概览文档尚未生成，请先执行 /overview 命令"}
        return {"found": True, "title": doc["title"], "content": doc["content"]}

    def _get_community_tree(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        et = (args.get("edgeType") or "CALL").upper()
        pid, pdb = self._resolve_task(task_id)
        levels = cd.get_cascade_levels(pdb, task_id, et)
        return {"levels": levels, "taskId": task_id, "edgeType": et}

    def _get_community_detail(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        comm_id = args.get("commId", "")
        et = (args.get("edgeType") or "CALL").upper()
        pid, pdb = self._resolve_task(task_id)
        row = pdb.fetchone(
            "SELECT name, summary, comm_lv FROM community_llm_results "
            "WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, comm_id),
        )
        if row:
            return {
                "commId": comm_id,
                "name": row["name"],
                "summary": row["summary"],
                "level": row["comm_lv"],
                "edgeType": et,
                "found": True,
            }
        return {
            "commId": comm_id,
            "edgeType": et,
            "found": False,
            "message": "该社区尚无 LLM 分析结果",
        }

    def _get_community_graph(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        comm_id = args.get("commId", "")
        et = (args.get("edgeType") or "CALL").upper()
        depth = int(args.get("depth", 1))
        gran = (args.get("gran") or "component").lower()
        pid, pdb = self._resolve_task(task_id)
        proj = self.multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj["root_path"].replace('\\', '/') + "/") if proj and proj["root_path"] else ""
        if gran == "component":
            result = cd.get_community_graph_component(
                pdb, task_id, et, comm_id, comm_id, project_root, depth=depth
            )
        else:
            result = cd.get_community_graph_file(
                pdb, task_id, et, comm_id, comm_id, project_root
            )
        return result

    def _get_community_files(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        comm_id = args.get("commId", "")
        et = (args.get("edgeType") or "CALL").upper()
        pid, pdb = self._resolve_task(task_id)
        proj = self.multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj["root_path"].replace('\\', '/') + "/") if proj and proj["root_path"] else ""

        rows = pdb.fetchall(
            "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, comm_id),
        )
        if not rows:
            return {"files": [], "total": 0}
        seen = set()
        files = []
        for r in rows:
            try:
                nodes = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
            except Exception:
                nodes = []
            if not isinstance(nodes, list):
                nodes = [nodes]
            for n in nodes:
                nid = str(n) if isinstance(n, str) else str(n.get("id", ""))
                if project_root and nid.lower().startswith(project_root.lower()):
                    nid = nid[len(project_root):]
                nid = nid.lstrip("/")
                if nid and nid not in seen:
                    seen.add(nid)
                    files.append({
                        "path": nid,
                        "name": nid.replace('\\', '/').split("/")[-1] if "/" in nid.replace('\\', '/') else nid,
                    })
        return {"files": files, "total": len(files)}

    def _read_file(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        path = args.get("path", "")
        proj = self.multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        if not proj:
            return {"error": f"Project {pid} not found"}
        root = proj["root_path"]
        full = os.path.normpath(os.path.join(root, path))
        if not full.startswith(os.path.normpath(root)):
            return {"error": "Path outside project root"}
        if not os.path.isfile(full):
            return {"error": f"File not found: {path}"}
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(MAX_RESULT_LENGTH + 2000)
        truncated = len(content) > MAX_RESULT_LENGTH
        if truncated:
            content = content[:MAX_RESULT_LENGTH] + "\n...(truncated)"
        return {"path": path, "content": content, "size": len(content), "truncated": truncated}

    def _get_file_summary(self, args: dict) -> dict:
        task_id = args.get("taskId", "")
        path = args.get("path", "")
        pid, pdb = self._resolve_task(task_id)
        row = pdb.fetchone(
            "SELECT summary, summary_len, source FROM file_summaries "
            "WHERE project_id=? AND file_path=? ORDER BY created_at DESC LIMIT 1",
            (pid, path),
        )
        if row:
            return {"found": True, "summary": row["summary"], "source": row["source"]}
        return {"found": False, "message": "该文件尚无预摘要"}

    def _search_symbols(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        query = args.get("query", "")
        limit = int(args.get("limit", 20))
        pdb = self.multi_db.get_project_db(pid)
        rows = pdb.fetchall(
            "SELECT id, file_path, func_name, class_name, method_name, symbol_type FROM graph_node "
            "WHERE func_name LIKE ? OR class_name LIKE ? OR method_name LIKE ? "
            "OR file_path LIKE ? LIMIT ?",
            (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%", limit),
        )
        return {
            "symbols": [
                {
                    "id": r["id"],
                    "filePath": r["file_path"],
                    "name": r["func_name"] or r["class_name"] or r["method_name"] or r["file_path"],
                    "type": r["symbol_type"],
                }
                for r in rows
            ],
            "total": len(rows),
        }

    def _get_symbol_detail(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        symbol_id = args.get("symbolId", "")
        pdb = self.multi_db.get_project_db(pid)
        row = pdb.fetchone(
            "SELECT id, file_path, func_name, class_name, method_name, symbol_type,"
            " docstring, line_start, line_end FROM graph_node WHERE id = ?",
            (symbol_id,),
        )
        if not row:
            return {"error": f"Symbol {symbol_id} not found"}
        return {
            "id": row["id"],
            "filePath": row["file_path"],
            "name": row["func_name"] or row["class_name"] or row["method_name"] or "",
            "type": row["symbol_type"],
            "docstring": row["docstring"],
            "lineStart": row["line_start"],
            "lineEnd": row["line_end"],
        }

    def _get_call_chain(self, args: dict) -> dict:
        pid = args.get("projectId", "")
        symbol = args.get("symbol", "")
        depth = int(args.get("depth", 2))
        pdb = self.multi_db.get_project_db(pid)
        kind = "calls"
        rows = pdb.fetchall(
            "SELECT e.source_id, e.target_id, n1.func_name AS src_name, "
            "n2.func_name AS tgt_name, n1.file_path AS src_file, n2.file_path AS tgt_file "
            "FROM graph_edge e "
            "LEFT JOIN graph_node n1 ON e.source_id = n1.id "
            "LEFT JOIN graph_node n2 ON e.target_id = n2.id "
            "WHERE e.task_id IN (SELECT id FROM analysis_tasks WHERE project_id=?) "
            "AND e.kind=?",
            (pid, kind),
        )
        callers = []
        callees = []
        for r in rows:
            if symbol.lower() in (r["src_name"] or "").lower():
                callees.append({
                    "from": r["src_name"] or r["source_id"],
                    "to": r["tgt_name"] or r["target_id"],
                    "toFile": r["tgt_file"],
                })
            if symbol.lower() in (r["tgt_name"] or "").lower():
                callers.append({
                    "from": r["src_name"] or r["source_id"],
                    "fromFile": r["src_file"],
                    "to": r["tgt_name"] or r["target_id"],
                })
        return {
            "symbol": symbol,
            "callers": callers[:depth * 10],
            "callees": callees[:depth * 10],
        }

    def _search_archives(self, args: dict) -> dict:
        query = args.get("query", "")
        project_id = args.get("projectId", "")
        category = args.get("category", "")
        wheres = ["content LIKE ? OR title LIKE ?"]
        params = [f"%{query}%", f"%{query}%"]
        if project_id:
            wheres.append("project_id = ?")
            params.append(project_id)
        if category:
            wheres.append("category = ?")
            params.append(category)
        sql = f"SELECT id, title, content, category, tags, created_at FROM chat_archives WHERE {' AND '.join(wheres)} ORDER BY created_at DESC LIMIT 20"
        rows = self.multi_db.main_db.fetchall(sql, tuple(params))
        return {
            "archives": [
                {
                    "id": r["id"],
                    "title": r["title"],
                    "content": r["content"][:500],
                    "category": r["category"],
                    "tags": r["tags"],
                    "createdAt": r["created_at"],
                }
                for r in rows
            ],
            "total": len(rows),
        }

    def _save_archive(self, args: dict) -> dict:
        import uuid
        aid = f"arch_{uuid.uuid4().hex[:12]}"
        title = args.get("title", "")
        content = args.get("content", "")
        session_id = args.get("sessionId", "")
        category = args.get("category", "note")
        tags = args.get("tags", "")
        pid = None
        if session_id:
            row = self.multi_db.main_db.fetchone(
                "SELECT json_extract(metadata, '$.project_id') AS pid FROM llm_sessions WHERE id = ?",
                (session_id,),
            )
            if row:
                pid = row["pid"]
        self.multi_db.main_db.execute(
            "INSERT INTO chat_archives (id, session_id, project_id, title, content, category, tags, source) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'manual')",
            (aid, session_id, pid, title, content, category, tags),
        )
        return {"id": aid, "ok": True}

    def _search_conversation_history(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", self._current_session_id or ""))
        query = args.get("query", "")
        limit = min(args.get("limit", 10), 50)

        # 空 query + 指定 session_id：返回该会话的全部消息（LLM 试探会话内容）
        if not query and session_id:
            try:
                rows = self.multi_db.sessions_db.fetchall(
                    "SELECT role, content, created_at FROM llm_messages "
                    "WHERE session_id = ? ORDER BY created_at LIMIT 50",
                    (session_id,),
                )
                if not rows:
                    return {"found": False, "results": [], "total": 0, "message": "会话无消息记录"}
                results = []
                for r in rows:
                    c = (r["content"] or "")[:800]
                    if c:
                        results.append({
                            "role": r["role"],
                            "content": c,
                            "createdAt": r["created_at"],
                        })
                return {"found": True, "results": results, "total": len(results)}
            except Exception as e:
                return {"error": str(e), "skip": True}

        if not query:
            return {"error": "query is required", "skip": True}

        try:
            rows = self.multi_db.sessions_db.fetchall(
                "SELECT role, content, created_at FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') "
                "AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (session_id, f"%{query}%", limit),
            )
            results = []
            for r in rows:
                c = (r["content"] or "")[:800]
                if c:
                    results.append({
                        "role": r["role"],
                        "content": c,
                        "createdAt": r["created_at"],
                    })
            return {"found": len(results) > 0, "results": results, "total": len(results)}
        except Exception as e:
            return {"error": str(e), "skip": True}

    def _set_session_title(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("sessionId", ""))
        title = args.get("title", "").strip()
        if not session_id or not title:
            return {"error": "sessionId and title are required", "skip": True}
        title = title[:20]
        from datetime import datetime as _dt
        now = _dt.now().isoformat()
        self.multi_db.sessions_db.execute(
            "UPDATE llm_sessions SET title = ?, updated_at = ? WHERE id = ?",
            (title, now, session_id),
        )
        return {"ok": True, "title": title}

    # ── conversation_analyst tools ──

    def _list_sessions(self, args: dict) -> dict:
        project_id = args.get("project_id", "")
        status = args.get("status", "")
        limit = min(args.get("limit", 20), 100)
        offset = args.get("offset", 0)
        where = []
        params = []
        if project_id:
            where.append("project_id = ?"); params.append(project_id)
        if status:
            where.append("status = ?"); params.append(status)
        w = (" WHERE " + " AND ".join(where)) if where else ""
        rows = self.multi_db.sessions_db.fetchall(
            f"SELECT id, title, project_id, status, metadata, created_at, updated_at "
            f"FROM llm_sessions{w} ORDER BY updated_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return {"sessions": [
            {"id": r["id"], "title": r["title"], "projectId": r["project_id"],
             "status": r["status"], "createdAt": r["created_at"], "updatedAt": r["updated_at"]}
            for r in rows
        ], "total": len(rows)}

    def _get_session_info(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", ""))
        if not session_id:
            return {"error": "session_id is required", "skip": True}
        row = self.multi_db.sessions_db.fetchone(
            "SELECT id, title, project_id, status, metadata, created_at, updated_at "
            "FROM llm_sessions WHERE id = ?", (session_id,)
        )
        if not row:
            return {"error": "Session not found", "skip": True}
        meta = json.loads(row["metadata"]) if row["metadata"] else {}
        cnt = self.multi_db.sessions_db.fetchone(
            "SELECT COUNT(*) AS c FROM llm_messages WHERE session_id = ?", (session_id,)
        )
        return {
            "id": row["id"], "title": row["title"],
            "projectId": row["project_id"], "status": row["status"],
            "modelId": meta.get("model_id", ""),
            "activeSkills": meta.get("active_skills", []),
            "messageCount": cnt["c"] if cnt else 0,
            "createdAt": row["created_at"], "updatedAt": row["updated_at"],
        }

    def _search_across_sessions(self, args: dict) -> dict:
        query = args.get("query", "")
        if not query:
            return {"error": "query is required", "skip": True}
        project_id = args.get("project_id", "")
        limit = min(args.get("limit", 5), 20)
        session_limit = min(args.get("session_limit", 10), 50)
        where = "1=1"
        params = []
        if project_id:
            where += " AND project_id = ?"; params.append(project_id)
        sessions = self.multi_db.sessions_db.fetchall(
            f"SELECT id, title FROM llm_sessions WHERE {where} ORDER BY updated_at DESC LIMIT ?",
            (*params, session_limit),
        )
        results = []
        for s in sessions:
            rows = self.multi_db.sessions_db.fetchall(
                "SELECT role, content, created_at FROM llm_messages "
                "WHERE session_id = ? AND role IN ('user', 'assistant') "
                "AND content LIKE ? ORDER BY created_at DESC LIMIT ?",
                (s["id"], f"%{query}%", limit),
            )
            for r in rows:
                c = (r["content"] or "")[:600]
                if c:
                    results.append({
                        "session_id": s["id"],
                        "session_title": s["title"],
                        "role": r["role"], "content": c,
                        "createdAt": r["created_at"],
                    })
        return {"found": len(results) > 0, "results": results, "total": len(results)}

    def _get_session_messages(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", ""))
        if not session_id:
            return {"error": "session_id is required", "skip": True}
        role = args.get("role", "all")
        limit = min(args.get("limit", 50), 200)
        offset = args.get("offset", 0)
        where = "session_id = ?"
        params = [session_id]
        if role and role != "all":
            where += " AND role = ?"; params.append(role)
        rows = self.multi_db.sessions_db.fetchall(
            f"SELECT id, role, content, metadata, created_at FROM llm_messages "
            f"WHERE {where} ORDER BY created_at LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return {"messages": [
            {"id": r["id"], "role": r["role"], "content": (r["content"] or "")[:2000],
             "createdAt": r["created_at"]}
            for r in rows
        ], "total": len(rows)}

    def _summarize_session(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", ""))
        if not session_id:
            return {"error": "session_id is required", "skip": True}
        max_length = min(args.get("max_length", 500), 2000)
        rows = self.multi_db.sessions_db.fetchall(
            "SELECT role, content FROM llm_messages "
            "WHERE session_id = ? AND role IN ('user', 'assistant') "
            "ORDER BY created_at LIMIT 100",
            (session_id,),
        )
        if not rows:
            return {"found": False, "summary": "会话无消息记录"}
        conv_text = "\n".join(
            f"[{'用户' if r['role']=='user' else 'AI'}] {(r['content'] or '')[:2000]}"
            for r in rows
        )
        return {"found": True, "summary": f"会话 {session_id[:12]}：\n{conv_text[:max_length * 4]}",
                "message_count": len(rows)}

    def _extract_topics(self, args: dict) -> dict:
        session_id = _strip_ref_prefix(args.get("session_id", ""))
        if not session_id:
            return {"error": "session_id is required", "skip": True}
        detail = args.get("detail", "brief")
        rows = self.multi_db.sessions_db.fetchall(
            "SELECT role, content, metadata FROM llm_messages "
            "WHERE session_id = ? AND role IN ('user', 'assistant') "
            "ORDER BY created_at LIMIT 100",
            (session_id,),
        )
        topics = set()
        resources = set()
        for r in rows:
            content = r["content"] or ""
            for kw in ["struct ", "class ", "function ", "module ", "社区", "文件", "协议", "驱动"]:
                if kw in content:
                    topics.add(kw.rstrip())
                    break
            meta = json.loads(r["metadata"]) if r["metadata"] else {}
            for tc in meta.get("tool_calls", []):
                if tc.get("name"):
                    resources.add(tc["name"])
        return {
            "found": True,
            "topics": list(topics) if detail == "brief" else list(topics)[:10],
            "resources": list(resources)[:10],
            "message_count": len(rows),
        }

    def _compare_sessions(self, args: dict) -> dict:
        session_ids_str = args.get("session_ids", "")
        ids = [s.strip() for s in session_ids_str.split(",") if s.strip()]
        if len(ids) < 2:
            return {"error": "至少需要两个会话ID", "skip": True}
        aspect = args.get("aspect", "topic")
        sessions_info = []
        for sid in ids[:5]:
            row = self.multi_db.sessions_db.fetchone(
                "SELECT title FROM llm_sessions WHERE id = ?", (sid.strip(),)
            )
            title = row["title"] if row else sid[:12]
            cnt = self.multi_db.sessions_db.fetchone(
                "SELECT COUNT(*) AS c FROM llm_messages WHERE session_id = ?", (sid.strip(),)
            )
            sessions_info.append({"id": sid.strip(), "title": title, "messageCount": cnt["c"] if cnt else 0})
        return {"found": True, "aspect": aspect, "sessions": sessions_info}

    # ── knowledge_keeper enhanced tools ──

    def _list_archives(self, args: dict) -> dict:
        project_id = args.get("project_id", "")
        category = args.get("category", "")
        tag = args.get("tag", "")
        limit = min(args.get("limit", 20), 100)
        offset = args.get("offset", 0)
        where = []
        params = []
        if project_id:
            where.append("project_id = ?"); params.append(project_id)
        if category:
            where.append("category = ?"); params.append(category)
        if tag:
            where.append("tags LIKE ?"); params.append(f"%{tag}%")
        w = (" WHERE " + " AND ".join(where)) if where else ""
        rows = self.multi_db.main_db.fetchall(
            f"SELECT id, session_id, project_id, title, content, category, tags, source, created_at "
            f"FROM chat_archives{w} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return {"archives": [{
            "id": r["id"], "title": r["title"], "category": r["category"],
            "tags": r["tags"], "content": (r["content"] or "")[:500],
            "createdAt": r["created_at"],
        } for r in rows], "total": len(rows)}

    def _delete_archive(self, args: dict) -> dict:
        archive_id = args.get("archive_id", "")
        if not archive_id:
            return {"error": "archive_id is required", "skip": True}
        self.multi_db.main_db.execute("DELETE FROM chat_archives WHERE id = ?", (archive_id,))
        return {"ok": True, "deleted": archive_id}

    def _update_archive(self, args: dict) -> dict:
        archive_id = args.get("archive_id", "")
        if not archive_id:
            return {"error": "archive_id is required", "skip": True}
        updates = []
        params = []
        if args.get("category"):
            updates.append("category = ?"); params.append(args["category"])
        if "tags" in args:
            updates.append("tags = ?"); params.append(args.get("tags", ""))
        if not updates:
            return {"error": "没有要更新的字段", "skip": True}
        params.append(archive_id)
        self.multi_db.main_db.execute(
            f"UPDATE chat_archives SET {', '.join(updates)} WHERE id = ?", params
        )
        return {"ok": True}


# ==================== 引用解析 ====================


def resolve_refs_to_context(refs: list[dict], multi_db: MultiDBManager) -> str:
    """将 refs 列表解析为注入用的 system message 内容"""
    parts = []
    for ref in refs:
        t = ref.get("type")
        label = ref.get("label", "")
        handler = _REF_RESOLVERS.get(t)
        if handler:
            try:
                text = handler(ref, multi_db)
                if text:
                    parts.append(text)
            except Exception as e:
                parts.append(f"引用「{label}」加载失败: {e}")
        elif not t:
            # draft refs（无 type 字段）：直接使用 label + text
            meta = []
            if ref.get("projectName"): meta.append(f"项目:{ref['projectName']}")
            elif ref.get("projectId"): meta.append(f"项目:{ref['projectId'][:12]}")
            if ref.get("taskId"): meta.append(f"任务:{ref['taskId'][:10]}")
            if ref.get("componentId"): meta.append(f"组件:{ref['componentId'][:10]}")
            if label: meta.append(f"来源:{label}")
            s = " | ".join(meta)
            text = ref.get("text", "")
            if text: s += "\n" + text
            if s: parts.append(s)
        else:
            parts.append(f"引用「{label}」")
    return "\n\n".join(parts) if parts else ""


def _resolve_project_ref(ref: dict, multi_db: MultiDBManager) -> str:
    pid = ref.get("id", "")
    row = multi_db.main_db.fetchone("SELECT name, root_path FROM projects WHERE id = ?", (pid,))
    if not row:
        return ""
    return (
        f"用户引用了一个项目「{row['name']}」：\n"
        f"- 根路径: {row['root_path']}\n"
        f"- 项目 ID: {pid}"
    )


def _resolve_task_ref(ref: dict, multi_db: MultiDBManager) -> str:
    tid = ref.get("id", "")
    row = multi_db.main_db.fetchone(
        "SELECT id, name, status, project_id FROM analysis_tasks WHERE id = ?", (tid,)
    )
    if not row:
        return ""
    return (
        f"用户引用了一个分析任务「{row['name']}」(状态: {row['status']})：\n"
        f"- 任务 ID: {tid}\n"
        f"- 项目 ID: {row['project_id']}"
    )


def _resolve_community_doc_ref(ref: dict, multi_db: MultiDBManager) -> str:
    task_id = ref.get("taskId", "")
    comm_id = ref.get("commId", "")
    et = ref.get("edgeType", "CALL")
    label = ref.get("label", comm_id)
    try:
        task = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if not task:
            return ""
        pdb = multi_db.get_project_db(task["project_id"])
        row = pdb.fetchone(
            "SELECT name, summary, comm_lv FROM community_llm_results "
            "WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, comm_id),
        )
        if row:
            return (
                f"用户引用了社区分析结果「{label}」：\n"
                f"- 层级: {row['comm_lv']}\n"
                f"- 名称: {row['name']}\n"
                f"- 功能摘要: {row['summary']}"
            )
        return f"用户引用了社区「{label}」(暂无 LLM 分析结果)"
    except Exception as e:
        return f"引用社区「{label}」加载失败: {e}"


def _resolve_community_graph_ref(ref: dict, multi_db: MultiDBManager) -> str:
    task_id = ref.get("taskId", "")
    comm_id = ref.get("commId", "")
    et = ref.get("edgeType", "CALL")
    label = ref.get("label", comm_id)
    try:
        task = multi_db.main_db.fetchone(
            "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,)
        )
        if not task:
            return ""
        pdb = multi_db.get_project_db(task["project_id"])
        rows = pdb.fetchall(
            "SELECT comm_lv, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
            (task_id, et, comm_id),
        )
        file_count = 0
        node_count = 0
        for r in rows:
            try:
                nodes = json.loads(r["node_list"]) if isinstance(r["node_list"], str) else r["node_list"] or []
                node_count += len(nodes) if isinstance(nodes, list) else 1
            except Exception:
                pass
        return (
            f"用户引用了社区图结构「{label}」：\n"
            f"- 社区 ID: {comm_id}\n"
            f"- 边类型: {et}\n"
            f"- 节点/文件数: ~{node_count}"
        )
    except Exception as e:
        return f"引用社区图「{label}」加载失败: {e}"


def _resolve_source_file_ref(ref: dict, multi_db: MultiDBManager) -> str:
    pid = ref.get("projectId", "")
    path = ref.get("path", "")
    label = ref.get("label", path)
    try:
        proj = multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
        if not proj:
            return f"用户引用了文件「{label}」"
        full = os.path.normpath(os.path.join(proj["root_path"], path))
        if not full.startswith(os.path.normpath(proj["root_path"])):
            return f"用户引用了文件「{label}」"
        if not os.path.isfile(full):
            return f"用户引用了文件「{label}」(文件不在磁盘)"
        with open(full, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(2000)
        if len(content) >= 2000:
            content += "\n...(截断)"
        return f"用户引用了源码文件「{label}」：\n```\n{content}\n```"
    except Exception:
        return f"用户引用了文件「{label}」"


def _resolve_symbol_ref(ref: dict, multi_db: MultiDBManager) -> str:
    symbol = ref.get("name", "")
    label = ref.get("label", symbol)
    return f"用户引用了符号「{label}」(将在 AI 需要时通过工具查询详情)"


def _resolve_archive_ref(ref: dict, multi_db: MultiDBManager) -> str:
    aid = ref.get("id", "")
    label = ref.get("label", aid)
    row = multi_db.main_db.fetchone(
        "SELECT title, content, category FROM chat_archives WHERE id = ?", (aid,)
    )
    if not row:
        return f"用户引用了归档知识「{label}」(内容未找到)"
    return (
        f"用户引用了历史归档知识「{row['title']}」(分类: {row['category']})：\n"
        f"{row['content'][:1000]}"
    )


def _resolve_session_ref(ref: dict, multi_db: MultiDBManager) -> str:
    """加载目标会话的消息作为上下文"""
    session_id = ref.get("id", "")
    if not session_id:
        return ""
    sess = multi_db.sessions_db.fetchone(
        "SELECT title, project_id FROM llm_sessions WHERE id = ?", (session_id,)
    )
    if not sess:
        logger.info(f"[resolve_session] session={session_id[:12]} not found")
        return f"（会话 {session_id[:12]} 不存在或已被删除）"
    rows = multi_db.sessions_db.fetchall(
        "SELECT role, content FROM llm_messages "
        "WHERE session_id = ? ORDER BY created_at LIMIT 50",
        (session_id,),
    )
    logger.info(f"[resolve_session] session={session_id[:12]} title={sess['title']} rows={len(rows)}")
    if not rows:
        return f"（会话 {session_id[:12]}「{sess['title'] or '未命名'}」无消息记录）"
    parts = [f"以下是对话 {session_id[:12]}「{sess['title'] or '未命名'}」的内容："]
    for r in rows:
        role_label = {"user": "用户", "assistant": "AI", "tool": "工具", "system": "系统"}.get(r["role"], r["role"])
        content = (r["content"] or "")[:1000]
        if content:
            parts.append(f"[{role_label}] {content}")
    return "\n".join(parts)


_REF_RESOLVERS = {
    "project": _resolve_project_ref,
    "task": _resolve_task_ref,
    "community_doc": _resolve_community_doc_ref,
    "community_graph": _resolve_community_graph_ref,
    "source_file": _resolve_source_file_ref,
    "symbol": _resolve_symbol_ref,
    "archive": _resolve_archive_ref,
    "session": _resolve_session_ref,
}
