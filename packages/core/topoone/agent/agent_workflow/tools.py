from __future__ import annotations

"""
AgentTool — Agent 可调用的工具抽象。

所有 Agent 工具必须继承 AgentTool 并实现 execute 方法。
ToolRegistry 管理工具注册，AgentRuntime 通过它获取可用工具集。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional
import threading


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
    llm_visible: bool = False  # 该工具是否可被 LLM 的 function calling 调用
    cancel_event: Optional[threading.Event] = None  # 由运行时注入，供工具检查取消信号

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """执行工具，返回 ToolResult"""
        ...

    def to_schema(self) -> dict:
        """生成工具描述（兼容旧的 schema 格式）"""
        return {
            "name": self.name,
            "description": self.description,
        }

    def to_openai_schema(self) -> Optional[dict]:
        """
        返回 OpenAI function calling schema。
        子类可重写以提供完整的 function schema，使工具能被 LLM 自主调用。
        """
        if not self.llm_visible:
            return None
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
            },
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

    def to_openai_tools(self, filter_names: Optional[list[str]] = None) -> list[dict]:
        """
        返回符合 OpenAI function calling 格式的工具定义。
        filter_names: 只返回指定名称的工具（None 返回所有 llm_visible=True 的工具）
        """
        tools = self._tools.values()
        if filter_names is not None:
            tools = [t for t in tools if t.name in filter_names]
        result: list[dict] = []
        for t in tools:
            schema = t.to_openai_schema()
            if schema:
                result.append(schema)
        return result

    def __contains__(self, name: str) -> bool:
        return name in self._tools
