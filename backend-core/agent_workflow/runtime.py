"""
AgentRuntime — 规划→执行→观察 循环。

核心循环:
  1. plan:   调用 workflow.plan(context) 生成步骤序列
  2. exec:   对每一步，通过 ToolRegistry 查找工具并执行
  3. observe: 收集结果 → 更新 memory → 决定是否继续
  4. finalize: 所有步骤完成后，调用 workflow.finalize() 汇总

支持:
  - 取消 (cancel())
  - 进度回调 (on_progress)
  - 预算跟踪 (sandbox.budget)
  - 沙箱约束 (sandbox.path / content / rate)
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .tools import ToolRegistry, ToolResult
from .memory import AgentMemory
from .sandbox import AgentSandbox
from .workflows.base import AgentWorkflow, AgentStep, WorkflowResult

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StepProgress:
    """单步执行的进度信息"""

    step_index: int
    step_total: int
    description: str
    status: str = "pending"   # pending | running | done | failed
    result: Optional[ToolResult] = None


@dataclass
class AgentProgress:
    """Agent 整体进度（传递给回调）"""

    status: AgentStatus
    steps: list[StepProgress] = field(default_factory=list)
    step_current: int = 0
    step_total: int = 0
    tokens_used: int = 0
    elapsed_sec: float = 0.0
    message: str = ""


ProgressCallback = Callable[[AgentProgress], None]


class AgentRuntime:
    """Agent 运行时引擎"""

    def __init__(
        self,
        tools: ToolRegistry,
        sandbox: AgentSandbox,
        memory: Optional[AgentMemory] = None,
        on_progress: Optional[ProgressCallback] = None,
    ):
        self._tools = tools
        self._sandbox = sandbox
        self._memory = memory or AgentMemory()
        self._on_progress = on_progress
        self._cancelled = False
        self._status = AgentStatus.IDLE
        self._steps: list[StepProgress] = []

    def cancel(self):
        """取消当前执行"""
        self._cancelled = True
        self._status = AgentStatus.CANCELLED
        logger.info("[AgentRuntime] cancelled by user")

    async def run(self, workflow: AgentWorkflow, context: dict) -> WorkflowResult:
        """
        执行一个工作流。

        Args:
            workflow: 工作流实例
            context: 上下文 dict（来自 AnalysisContext 或调用方）

        Returns:
            WorkflowResult
        """
        self._cancelled = False
        self._status = AgentStatus.PLANNING
        self._sandbox.budget.start()

        # 1. Plan
        self._report(status=AgentStatus.PLANNING, message=f"规划中: {workflow.name}")
        try:
            steps = workflow.plan(context)
        except Exception as e:
            logger.exception(f"[AgentRuntime] plan failed: {e}")
            self._status = AgentStatus.FAILED
            return WorkflowResult(success=False, error=str(e))

        if not steps:
            logger.info(f"[AgentRuntime] no steps to execute for {workflow.name}")
            self._status = AgentStatus.COMPLETED
            return WorkflowResult(success=True, steps_completed=0, steps_total=0)

        self._steps = [
            StepProgress(step_index=i, step_total=len(steps), description=s.description)
            for i, s in enumerate(steps)
        ]

        # 2. Execute each step
        self._status = AgentStatus.RUNNING
        results: dict[str, Any] = {}
        completed_count = 0
        failed_count = 0

        for i, step in enumerate(steps):
            if self._cancelled:
                break
            if self._sandbox.budget.exhausted():
                logger.warning(f"[AgentRuntime] budget exhausted at step {i}/{len(steps)}")
                self._status = AgentStatus.PARTIAL
                break

            tool = self._tools.get(step.tool)
            if not tool:
                logger.error(f"[AgentRuntime] unknown tool: {step.tool}")
                self._steps[i].status = "failed"
                self._steps[i].result = ToolResult.fail(f"Unknown tool: {step.tool}")
                failed_count += 1
                continue

            self._steps[i].status = "running"
            self._report(
                status=AgentStatus.RUNNING,
                step_current=i + 1,
                step_total=len(steps),
                message=f"执行: {step.description}",
            )

            MAX_RETRIES = 2
            last_result: Optional[ToolResult] = None

            for attempt in range(MAX_RETRIES + 1):
                try:
                    if self._needs_rate_limit(tool.name):
                        while not self._sandbox.llm_rate.acquire():
                            await asyncio.sleep(0.05)
                            if self._cancelled:
                                break

                    result = await tool.execute(**step.args)

                    if self._needs_rate_limit(tool.name):
                        self._sandbox.llm_rate.release()

                    if result.success:
                        if result.data and isinstance(result.data, str):
                            result.data = self._sandbox.content.sanitize(result.data)
                        tokens = result.tokens_used or 0
                        self._sandbox.budget.consume_tokens(tokens)
                        logger.info(
                            f"[AgentRuntime] step {i} success consume_tokens={tokens} "
                            f"budget_used={self._sandbox.budget.tokens_used}"
                        )
                        self._steps[i].result = result
                        self._steps[i].status = "done"
                        results[step.tool] = result.data
                        completed_count += 1
                        last_result = None
                        break

                    last_result = result
                    if attempt < MAX_RETRIES:
                        logger.warning(
                            f"[AgentRuntime] step {i} ({step.tool}) failed (attempt {attempt+1}/{MAX_RETRIES+1}): {result.error}")
                        await asyncio.sleep(0.5 * (attempt + 1))

                except Exception as e:
                    logger.warning(
                        f"[AgentRuntime] step {i} ({step.tool}) exception (attempt {attempt+1}/{MAX_RETRIES+1}): {e}")
                    last_result = ToolResult.fail(str(e))
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(0.5 * (attempt + 1))

            if last_result is not None:
                self._steps[i].result = last_result
                self._steps[i].status = "failed"
                failed_count += 1

            self._report(
                status=AgentStatus.RUNNING,
                step_current=i + 1,
                step_total=len(steps),
                tokens_used=self._sandbox.budget.tokens_used,
                elapsed_sec=self._sandbox.budget.elapsed,
            )

        self._sandbox.budget.finish()

        # 3. Finalize
        logger.info(
            f"[AgentRuntime] loop done completed={completed_count} failed={failed_count} "
            f"total={len(steps)} cancelled={self._cancelled} "
            f"budget_exhausted={self._sandbox.budget.exhausted()} "
            f"tokens_used={self._sandbox.budget.tokens_used}"
        )
        if self._cancelled:
            return WorkflowResult(success=False, steps_completed=completed_count,
                                  steps_total=len(steps), error="cancelled")

        try:
            final = workflow.finalize(results)
            final.steps_completed = completed_count
            final.steps_total = len(steps)
        except Exception as e:
            logger.exception(f"[AgentRuntime] finalize failed: {e}")
            final = WorkflowResult(success=False, steps_completed=completed_count,
                                   steps_total=len(steps), error=str(e))

        if self._status in (AgentStatus.CANCELLED, AgentStatus.FAILED):
            pass
        elif failed_count > 0 and completed_count > 0:
            self._status = AgentStatus.PARTIAL
        elif failed_count > 0:
            self._status = AgentStatus.FAILED
        else:
            self._status = AgentStatus.COMPLETED

        self._report(
            status=self._status,
            step_current=len(steps),
            step_total=len(steps),
            tokens_used=self._sandbox.budget.tokens_used,
            elapsed_sec=self._sandbox.budget.elapsed,
            message=f"完成: {completed_count}/{len(steps)} 步骤成功, {failed_count} 失败",
        )

        return final

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def steps(self) -> list[StepProgress]:
        return self._steps

    def _report(self, **kwargs):
        if self._on_progress:
            progress = AgentProgress(
                status=kwargs.get("status", self._status),
                steps=self._steps,
                step_current=kwargs.get("step_current", 0),
                step_total=kwargs.get("step_total", 0),
                tokens_used=kwargs.get("tokens_used", self._sandbox.budget.tokens_used),
                elapsed_sec=kwargs.get("elapsed_sec", self._sandbox.budget.elapsed),
                message=kwargs.get("message", ""),
            )
            try:
                self._on_progress(progress)
            except Exception as e:
                logger.warning(f"[AgentRuntime] on_progress callback error: {e}")

    @staticmethod
    def _needs_rate_limit(tool_name: str) -> bool:
        """判断工具是否需要 LLM 速率限制"""
        # generate_* 和 analyze_* 类工具需要 LLM 调用
        return any(tool_name.startswith(p) for p in ("generate_", "analyze_", "summarize_"))
