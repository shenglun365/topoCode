"""
AgentWorkflow — 工作流抽象基类。

AgentWorkflow: 固定步骤工作流（ArchAnalyst / ArchSentinel / ComponentAnalyst）
AgenticWorkflow: LLM 驱动的 Agentic 工作流，可自主决定工具调用
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class AgentStep:
    """工作流中的单个执行步骤"""

    tool: str
    args: dict = field(default_factory=dict)
    description: str = ""


@dataclass
class WorkflowResult:
    """工作流执行结果"""

    success: bool
    steps_completed: int = 0
    steps_total: int = 0
    data: Any = None
    error: Optional[str] = None
    summary: str = ""


class AgentWorkflow(ABC):
    """固定步骤工作流基类 — plan() 返回预定义步骤序列"""

    name: str = ""
    description: str = ""
    input_schema: dict = {}
    output_schema: dict = {}

    @abstractmethod
    def plan(self, context: dict) -> list[AgentStep]:
        """根据上下文规划执行步骤"""
        ...

    @abstractmethod
    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        """汇总所有步骤的结果，生成最终输出"""
        ...


class AgenticWorkflow(AgentWorkflow):
    """
    LLM 驱动的 Agentic 工作流基类。
    
    运行模式：ReAct 循环（LLM → 观察 → 决定工具调用 → 执行 → 继续）。
    plan() 可返回空列表（由 ReAct 循环接管），也可返回初始准备步骤。
    """

    max_turns: int = 5
    max_turn_timeout: int = 180

    @abstractmethod
    def get_system_prompt(self, component: dict, project_summary: str = "") -> str:
        """返回单个组件分析的 ReAct 系统提示词（逐组件调用）"""
        ...

    def get_tool_filter(self, context: dict) -> Optional[list[str]]:
        return None

    def plan(self, context: dict) -> list[AgentStep]:
        """Agentic 工作流默认无预设步骤，由 ReAct 循环接管"""
        return []

    @abstractmethod
    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        ...
