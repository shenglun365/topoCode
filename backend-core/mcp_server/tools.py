"""MCP Tool definitions — 11 core tools for code analysis."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolDefinition:
    """MCP Tool definition with JSON Schema input."""
    name: str
    description: str
    inputSchema: dict[str, Any] = field(default_factory=dict)


# ===== 符号导航类 =====

GET_DEFINITION = ToolDefinition(
    name="get_definition",
    description="Resolve the definition location of a symbol at the given file/position.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string", "description": "Absolute or project-relative file path."},
            "line": {"type": "integer"},
            "character": {"type": "integer"},
        },
        "required": ["file_path", "line", "character"],
    },
)

GET_REFERENCES = ToolDefinition(
    name="get_references",
    description="Find all references to a symbol at the given file/position. Results grouped by file.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "character": {"type": "integer"},
            "max_results": {"type": "integer", "default": 500, "description": "Max references to return"},
        },
        "required": ["file_path", "line", "character"],
    },
)

GET_SYMBOL_INFO = ToolDefinition(
    name="get_symbol_info",
    description="Get detailed information about a symbol: name, kind, signature, docstring, location, modifiers.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "character": {"type": "integer"},
        },
        "required": ["file_path", "line", "character"],
    },
)

# ===== 项目级架构理解 =====

GET_CALL_HIERARCHY = ToolDefinition(
    name="get_call_hierarchy",
    description="Get the call hierarchy for a function: who calls it (incoming) and what it calls (outgoing).",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "line": {"type": "integer"},
            "character": {"type": "integer"},
            "direction": {
                "type": "string", "enum": ["incoming", "outgoing", "both"], "default": "both",
            },
            "max_depth": {"type": "integer", "default": 3},
        },
        "required": ["file_path", "line", "character"],
    },
)

GET_FILE_SYMBOLS = ToolDefinition(
    name="get_file_symbols",
    description="Get all top-level symbols (functions, classes, variables) defined in a file. Like IDE outline.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "kind_filter": {
                "type": "array", "items": {"type": "string"},
                "description": "Filter by symbol kind: function, class, variable, interface, enum",
            },
        },
        "required": ["file_path"],
    },
)

GET_DEPENDENCIES = ToolDefinition(
    name="get_dependencies",
    description="Get module-level dependency information: what this file imports, or what files depend on it.",
    inputSchema={
        "type": "object",
        "properties": {
            "file_path": {"type": "string"},
            "direction": {
                "type": "string", "enum": ["imports", "imported_by", "both"], "default": "both",
            },
        },
        "required": ["file_path"],
    },
)

SEARCH_SYMBOL = ToolDefinition(
    name="search_symbol",
    description="Fuzzy search for symbols across the entire project by name.",
    inputSchema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Symbol name (partial match)"},
            "kind_filter": {
                "type": "string",
                "description": "Filter: function, class, variable, interface, all",
                "default": "all",
            },
            "max_results": {"type": "integer", "default": 20},
        },
        "required": ["query"],
    },
)

# ===== 变更分析类 (Phase 7 扩展) =====

GET_CHANGES = ToolDefinition(
    name="get_changes",
    description="Get a complete change report between two commits: files changed, symbols added/removed/modified, "
               "dependency changes, architectural impact, and risk assessment.",
    inputSchema={
        "type": "object",
        "properties": {
            "from_commit": {"type": "string", "description": "Base commit hash. Use 'HEAD~1' for previous commit."},
            "to_commit": {"type": "string", "description": "Target commit hash. Defaults to HEAD.", "default": "HEAD"},
            "scope": {
                "type": "string", "enum": ["summary", "files", "symbols", "dependencies", "full"],
                "default": "summary", "description": "Level of detail to return.",
            },
        },
        "required": ["from_commit"],
    },
)

GET_VERSION_HISTORY = ToolDefinition(
    name="get_version_history",
    description="List recent commits with their analysis snapshot availability. Shows which versions have been analyzed.",
    inputSchema={
        "type": "object",
        "properties": {
            "max_count": {"type": "integer", "default": 20, "description": "Number of recent commits to list."},
            "only_analyzed": {
                "type": "boolean", "default": False,
                "description": "Only show commits with analysis snapshots.",
            },
        },
    },
)

EVALUATE_CHANGE = ToolDefinition(
    name="evaluate_change",
    description="AI-assisted semantic evaluation of a code change. What was refactored? Is it a breaking change? "
               "What's the risk? Uses LLM to analyze the change report.",
    inputSchema={
        "type": "object",
        "properties": {
            "from_commit": {"type": "string", "description": "Base commit hash."},
            "to_commit": {"type": "string", "description": "Target commit hash.", "default": "HEAD"},
            "focus": {
                "type": "string", "enum": ["overview", "breaking", "refactoring", "security"],
                "default": "overview", "description": "Evaluation focus area.",
            },
        },
        "required": ["from_commit"],
    },
)

TRACK_SYMBOL_HISTORY = ToolDefinition(
    name="track_symbol_history",
    description="Track how a specific symbol has evolved across versions: when it was created, modified, "
               "its signature changes over time.",
    inputSchema={
        "type": "object",
        "properties": {
            "symbol_name": {"type": "string", "description": "Full qualified name of the symbol."},
            "file_path": {"type": "string", "description": "File containing the symbol."},
            "max_versions": {"type": "integer", "default": 10},
        },
        "required": ["symbol_name", "file_path"],
    },
)

# ===== 所有核心 Tools 注册表 =====

CORE_TOOLS: list[ToolDefinition] = [
    GET_DEFINITION,
    GET_REFERENCES,
    GET_SYMBOL_INFO,
    GET_CALL_HIERARCHY,
    GET_FILE_SYMBOLS,
    GET_DEPENDENCIES,
    SEARCH_SYMBOL,
    GET_CHANGES,
    GET_VERSION_HISTORY,
    EVALUATE_CHANGE,
    TRACK_SYMBOL_HISTORY,
]
