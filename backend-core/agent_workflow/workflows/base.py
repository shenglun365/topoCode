"""
AgentWorkflow — 工作流抽象基类。

每个具体工作流（ArchAnalyst / ArchSentinel）继承此类，
实现 plan() 和 finalize() 方法。
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
    """工作流抽象基类"""

    name: str = ""
    description: str = ""

    @abstractmethod
    def plan(self, context: dict) -> list[AgentStep]:
        """根据上下文规划执行步骤"""
        ...

    @abstractmethod
    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        """汇总所有步骤的结果，生成最终输出"""
        ...
