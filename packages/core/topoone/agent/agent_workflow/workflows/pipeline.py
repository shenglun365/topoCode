"""
PipelineWorkflow — 流水线整体激活

执行单元（4 个任务组）:
  1. 项目摘要 — 确保项目摘要已生成
  2. 文件预摘要 P0→P1→P2 — 批量文件摘要缓存
  3. 组件分析 L0→L5 — 逐层社区 LLM 分析
  4. 整体架构分析 — 生成架构概览文档

每个任务组内部循环子任务，工具返回 sub_progress 供上层展示。
"""

from __future__ import annotations

import logging
from typing import Any

from .base import AgentWorkflow, AgentStep, WorkflowResult

logger = logging.getLogger(__name__)


class PipelineWorkflow(AgentWorkflow):
    name = "PipelineWorkflow"

    def plan(self, context: dict) -> list[AgentStep]:
        task_id = context.get("task_id", "")
        force = context.get("force", False)
        language = context.get("language", "")
        self._context = context

        return [
            AgentStep(
                tool="pipeline_ensure_summary",
                description="[流水线] 项目摘要",
                args={"task_id": task_id, "force": force, "language": language},
            ),
            AgentStep(
                tool="pipeline_run_presummary",
                description="[流水线] 文件预摘要 P0→P1→P2",
                args={"task_id": task_id, "batches": ["P0", "P1", "P2"], "force": force, "language": language},
            ),
            AgentStep(
                tool="pipeline_run_component_analysis",
                description="[流水线] 组件分析 L0→L5",
                args={"task_id": task_id, "levels": ["L0", "L1", "L2", "L3", "L4", "L5"], "force": force, "language": language},
            ),
            AgentStep(
                tool="pipeline_run_overview",
                description="[流水线] 整体架构分析",
                args={"task_id": task_id, "force": force, "language": language},
            ),
        ]

    _STEP_TOOLS = (
        "pipeline_ensure_summary",
        "pipeline_run_presummary",
        "pipeline_run_component_analysis",
        "pipeline_run_overview",
    )

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        # 严格判定：任一执行单元失败（results 只含成功步骤）→ 整体不算成功。
        # 旧实现 completed>0 会让「组件分析失败但其余 3 步完成」被标记为
        # 成功/已完成，而实际可能还差几百个组件未分析。
        missing = [t for t in self._STEP_TOOLS if not results.get(t)]
        completed = len(self._STEP_TOOLS) - len(missing)
        total = len(self._STEP_TOOLS)
        error = ("步骤未完成: " + ", ".join(missing)) if missing else None
        return WorkflowResult(
            success=completed == total,
            steps_completed=completed,
            steps_total=total,
            error=error,
            data={"completed": completed, "total": total, "failed_steps": missing},
        )
