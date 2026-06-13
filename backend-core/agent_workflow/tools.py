"""
AgentTool — Agent 可调用的工具抽象。

所有 Agent 工具必须继承 AgentTool 并实现 execute 方法。
ToolRegistry 管理工具注册，AgentRuntime 通过它获取可用工具集。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ToolResult:
    """工具执行结果"""

    success: bool
    data: Any = None
    error: Optional[str] = None
    tokens_used: int = 0
    metadata: dict = field(default_factory=dict)

    @classmethod
    def ok(cls, data: Any = None, tokens_used: int = 0, **metadata) -> "ToolResult":
        return cls(success=True, data=data, tokens_used=tokens_used, metadata=metadata)

    @classmethod
    def fail(cls, error: str, **metadata) -> "ToolResult":
        return cls(success=False, error=error, metadata=metadata)


class AgentTool(ABC):
    """工具抽象基类"""

    name: str = ""
    description: str = ""
    version: str = "1.0"
    author: str = ""
    category: str = ""

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具，返回 ToolResult"""
        ...

    def to_schema(self) -> dict:
        """生成工具描述（供 LLM function calling 使用）"""
        return {
            "name": self.name,
            "description": self.description,
        }


class ToolRegistry:
    """工具注册表，白名单管理"""

    def __init__(self):
        self._tools: dict[str, AgentTool] = {}

    def register(self, tool: AgentTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool '{tool.name}' already registered")
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def get(self, name: str) -> Optional[AgentTool]:
        return self._tools.get(name)

    def list(self) -> list[str]:
        return list(self._tools.keys())

    def all(self) -> dict[str, AgentTool]:
        return dict(self._tools)

    def to_schema_list(self) -> list[dict]:
        return [t.to_schema() for t in self._tools.values()]

    def __contains__(self, name: str) -> bool:
        return name in self._tools
