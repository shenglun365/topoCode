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

        # 断点续传：跳过已缓存文件
        cached = context.get("cached_paths") or set()
        skipped = 0
        steps = []
        for fp in files:
            if fp in cached:
                skipped += 1
                continue
            steps.append(AgentStep(
                tool="summarize_file",
                args={"path": [fp]},
                description=f"预摘要: {fp}",
            ))

        if skipped:
            logger.info("[PreSummaryWorkflow] resume: skipped %d already cached files, remaining %d steps",
                       skipped, len(steps))
        return steps

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        data = results.get("summarize_file", "")
        has_content = bool(data and isinstance(data, str) and len(data) > 10)
        return WorkflowResult(
            success=has_content,
            steps_completed=1 if has_content else 0,
            steps_total=1,
            error=None if has_content else "所有文件摘要步骤均失败，请检查 LLM 模型配置或日志中的 [SummarizeFileTool] / [SubAgent] 错误",
            summary=f"预摘要: {'成功' if has_content else '失败'}",
        )
