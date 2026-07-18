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
                args={"task_id": task_id, "levels": ["L0", "L1", "L2", "L3", "L4", "L5"],
                       "force": force, "language": language,
                       "enable_self_verify": context.get("enable_self_verify", True)},
            ),
            AgentStep(
                tool="pipeline_run_overview",
                description="[流水线] 整体架构分析",
                args={"task_id": task_id, "force": force, "language": language},
            ),
        ]

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        completed = sum(1 for r in results.values() if r)
        total = 4
        return WorkflowResult(
            success=completed > 0,
            steps_completed=completed,
            steps_total=total,
            data={"completed": completed, "total": total},
        )
