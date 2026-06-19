"""
PreSummaryWorkflow — 文件预摘要工作流。

独立于 ReAct 循环，无 LLM 交互。通过预定义步骤调用 SummarizeFileTool，
将文件摘要写入 file_summaries 缓存，供后续组件分析复用。
"""

import logging
from typing import Any, Optional

from .base import AgentWorkflow, AgentStep, WorkflowResult

logger = logging.getLogger(__name__)


class PreSummaryWorkflow(AgentWorkflow):
    """文件预摘要工作流 — 批量摘要文件到缓存"""

    name = "presummary_files"
    description = "对指定文件列表执行批量预摘要，结果写入 file_summaries 缓存"

    def plan(self, context: dict) -> list[AgentStep]:
        files = context.get("files", [])
        if not files:
            logger.warning("[PreSummaryWorkflow] no files to summarize")
            return []
        steps = []
        for fp in files:
            steps.append(AgentStep(
                tool="summarize_file",
                args={"path": [fp]},
                description=f"预摘要: {fp}",
            ))
        return steps

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        success_count = sum(1 for v in results.values() if v and getattr(v, 'success', False))
        total = len(results)
        return WorkflowResult(
            success=success_count > 0,
            steps_completed=success_count,
            steps_total=total,
            summary=f"预摘要完成: {success_count}/{total} 文件",
        )
