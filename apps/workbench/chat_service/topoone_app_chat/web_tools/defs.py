"""Web Tools — Web AI 对话可调用的架构分析工具

所有工具复用现有的 MultiDBManager + community_data 查询，
不重复实现数据访问逻辑。
"""

import json
import logging
import os

# M12: 包已安装为 topoone_app_chat，topoone 为正规包，无需 path 注入
import topoone.engine.community_data as cd
from topoone.db.manager import MultiDBManager

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
                        "description": "边类型: UNIFIED（统一组件口径）",
                        "default": "UNIFIED",
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
                        "description": "边类型: UNIFIED（统一组件口径）",
                        "default": "UNIFIED",
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
                        "description": "边类型: UNIFIED（统一组件口径）",
                        "default": "UNIFIED",
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
                        "description": "边类型: UNIFIED（统一组件口径）",
                        "default": "UNIFIED",
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
            "description": "获取文件中关键符号的结构概览（含符号名、类型、行号范围、函数签名）。不返回完整代码。如需获取具体代码行，请使用 web_read_file_lines。",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "description": "项目 ID"},
                    "path": {"type": "string", "description": "文件相对路径"},
                    "taskId": {"type": "string", "description": "分析任务 ID（可选，指定后可获取更精确的符号信息）"},
                },
                "required": ["projectId", "path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_read_file_lines",
            "description": "按行号范围读取源码文件的具体代码行，返回带行号的内容。应在 web_read_file 获取符号概览后，针对感兴趣的行号范围调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "projectId": {"type": "string", "description": "项目 ID"},
                    "path": {"type": "string", "description": "文件相对路径"},
                    "startLine": {"type": "integer", "description": "起始行号（含），从 1 开始"},
                    "endLine": {"type": "integer", "description": "结束行号（含）"},
                },
                "required": ["projectId", "path", "startLine", "endLine"],
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
    {
        "type": "function",
        "function": {
            "name": "web_search_knowledge",
            "description": "统一搜索知识库。用户存档文档、对话归档、架构分析报告等。返回结果带 source_type 区分类型：user_doc（用户存档）、archive（对话归档）、community_analysis（社区分析报告）、report（架构概览）。写入由用户手动操作，本工具只读。",
            "parameters": {
                "type": "object",
                "properties": {
                    "search": {"type": "string", "description": "搜索关键词"},
                    "types": {"type": "array", "items": {"type": "string", "enum": ["user_doc", "archive", "community_analysis", "report"]}, "description": "可选，按类型过滤结果"},
                    "project_id": {"type": "string", "description": "可选，指定项目ID后可搜索该项目的社区分析和架构报告"},
                    "limit": {"type": "integer", "description": "返回条数（默认10，最大30）"},
                },
                "required": ["search"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_get_document",
            "description": "获取知识库中文档的完整内容。返回文档 ID、标题、完整正文（Markdown 格式）、更新时间。用于阅读已搜索到的文档。",
            "parameters": {
                "type": "object",
                "properties": {
                    "doc_id": {"type": "string", "description": "文档 ID"},
                },
                "required": ["doc_id"],
            },
        },
    },
    # ── 图编辑工具（diagram_tools） ──
    {
        "type": "function",
        "function": {
            "name": "web_diagram_build",
            "description": "从 IR 生成语法正确的 Mermaid/PlantUML 图代码。这是唯一能产生图代码的工具。支持的 diagram_type 和 IR 字段定义详见系统消息中的建图能力章节。禁止直接输出代码。",
            "parameters": {
                "type": "object",
                "properties": {
                    "ir": {
                        "type": "object",
                        "description": "完整 IR，包含 lang/diagram_type/nodes/edges/subgraphs/init_config。nodes 必须有 id 和 text。",
                    },
                },
                "required": ["ir"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_diagram_validate",
            "description": "校验 web_diagram_build 生成的代码语法。每次 build 后必须调用。返回 {valid, errors, warnings}。",
            "parameters": {
                "type": "object",
                "properties": {
                    "code": {"type": "string", "description": "要校验的图代码"},
                    "lang": {"type": "string", "enum": ["mermaid", "plantuml"]},
                },
                "required": ["code", "lang"],
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

