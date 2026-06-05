"""MCP Server — Model Context Protocol implementation for TopoCode.

Exposes code analysis capabilities as MCP tools for AI coding agents.
"""

from .server import MCPServer
from .dispatcher import ToolDispatcher
from .tools import CORE_TOOLS, ToolDefinition
from .skill_executor import SkillExecutor, SkillDefinition
from .skills import register_core_skills

__all__ = [
    "MCPServer",
    "ToolDispatcher",
    "CORE_TOOLS",
    "ToolDefinition",
    "SkillExecutor",
    "SkillDefinition",
    "register_core_skills",
]
