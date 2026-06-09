"""MCP Tool definitions — 6 architecture-cognition tools.

Only exposes topocode's unique capabilities (community/architecture/temporal/quality layer).
Symbol/file-level queries are codegraph's domain and not duplicated here.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    """MCP Tool definition with JSON Schema input."""
    name: str
    description: str
    inputSchema: dict[str, Any] = field(default_factory=dict)


# ═══════════════════════════════════════════
# 6 架构认知 Tools
# ═══════════════════════════════════════════

TOPocode_COMMUNITY = ToolDefinition(
    name="topocode_community",
    description=(
        "识别项目由哪些子系统构成（干了什么），标注每层的角色——"
        "中心节点/桥接节点/边缘节点（怎么干的），"
        "解释社区边界为何形成（为什么这么干）。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "edge_type": {
                "type": "string",
                "enum": ["INCLUDE", "CALL"],
                "description": "INCLUDE=依赖关系视角, CALL=调用关系视角",
            },
            "level": {"type": "number", "default": 0, "description": "社区层级 (0=顶层)"},
        },
        "required": ["edge_type"],
    },
)

TOPocode_COMMUNITY_DETAIL = ToolDefinition(
    name="topocode_community_detail",
    description=(
        "深入理解一个子系统：它的核心是什么（Hub 节点），"
        "内部符号如何协作（怎么干的），"
        "它的边界为何这样切分（为什么这么干）。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "comm_id": {"type": "string", "description": "社区 ID"},
            "include_hierarchy": {"type": "boolean", "default": True},
        },
        "required": ["comm_id"],
    },
)

TOPocode_ARCHITECTURE_OVERVIEW = ToolDefinition(
    name="topocode_architecture_overview",
    description=(
        "识别项目整体架构模式，分析关键依赖链和子系统角色分布，"
        "解释模式的形成原因。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "enum": ["overview", "dependencies", "call_flow", "structure"],
                "default": "overview",
            },
        },
    },
)

TOPocode_DIFF = ToolDefinition(
    name="topocode_diff",
    description=(
        "发现版本间架构差异，分析分布和影响，解读变化趋势。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "from_commit": {"type": "string", "description": "基准版本"},
            "to_commit": {"type": "string", "description": "目标版本"},
            "scope": {"type": "string", "enum": ["files", "communities", "full"], "default": "full"},
        },
    },
)

TOPocode_SESSION_SUMMARY = ToolDefinition(
    name="topocode_session_summary",
    description=(
        "解读 AI coding agent 变更对架构的影响。让人对 AI 的工作成果可知、可控。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "session_id": {"type": "string", "description": "会话 ID"},
        },
    },
)

TOPocode_QUALITY_INSPECT = ToolDefinition(
    name="topocode_quality_inspect",
    description=(
        "识别架构风险，分析形成机制，解释为什么这是问题并给出解决方向。"
    ),
    inputSchema={
        "type": "object",
        "properties": {
            "focus": {
                "type": "string",
                "enum": ["cyclic_deps", "hub_overload", "arch_drift", "test_gaps", "all"],
                "default": "all",
            },
        },
    },
)


# ═══════════════════════════════════════════
# 注册表
# ═══════════════════════════════════════════

CORE_TOOLS: list[ToolDefinition] = [
    TOPocode_COMMUNITY,
    TOPocode_COMMUNITY_DETAIL,
    TOPocode_ARCHITECTURE_OVERVIEW,
    TOPocode_DIFF,
    TOPocode_SESSION_SUMMARY,
    TOPocode_QUALITY_INSPECT,
]

# ═══════════════════════════════════════════
# 向后兼容别名（过渡期，调用时返回 deprecation notice）
# ═══════════════════════════════════════════

_DEPRECATED_MAP: dict[str, str] = {
    "get_definition": "Use codegraph_node or IDE LSP instead.",
    "get_references": "Use codegraph_callers / codegraph_callees instead.",
    "get_symbol_info": "Use codegraph_node instead.",
    "get_call_hierarchy": "Use codegraph_callers / codegraph_callees instead.",
    "get_file_symbols": "Use codegraph_files instead.",
    "get_dependencies": "Use topocode_community instead.",
    "search_symbol": "Use codegraph_search instead.",
    "get_changes": "Use topocode_diff instead.",
    "get_version_history": "Internal use only.",
    "evaluate_change": "Use topocode_quality_inspect instead.",
    "track_symbol_history": "Internal use only.",
}

def get_deprecation_notice(tool_name: str) -> str | None:
    return _DEPRECATED_MAP.get(tool_name)
