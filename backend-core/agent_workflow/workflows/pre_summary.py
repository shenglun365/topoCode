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
    """File pre-summary workflow — batch summarize files to cache"""

    name = "presummary_files"
    description = "Batch pre-summarize specified files, results written to file_summaries cache"

    def plan(self, context: dict) -> list[AgentStep]:
        files = context.get("files", [])
        if not files:
            logger.warning("[PreSummaryWorkflow] no files to summarize")
            return []

        # Resume: skip already cached files
        cached = context.get("cached_paths") or set()
        uncached = [fp for fp in files if fp not in cached]
        skipped = len(files) - len(uncached)

        if not uncached:
            return []

        concurrency = context.get("subagent_concurrency", 1) or 1

        steps = []
        for i in range(0, len(uncached), concurrency):
            batch = uncached[i:i + concurrency]
            if len(batch) == 1:
                desc = f"Pre-summary: {batch[0]}"
            else:
                desc = f"Pre-summary: {batch[0]} and {len(batch)} files"
            steps.append(AgentStep(
                tool="summarize_file",
                args={"path": batch},
                description=desc,
            ))

        if skipped:
            logger.info("[PreSummaryWorkflow] resume: skipped %d already cached files, remaining %d steps",
                       skipped, len(steps))
        logger.info("[PreSummaryWorkflow] plan: %d files, concurrency=%d, steps=%d",
                    len(uncached), concurrency, len(steps))
        return steps

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        data = results.get("summarize_file", "")
        has_content = bool(data and isinstance(data, str) and len(data) > 10)
        failed_count = getattr(self, '_file_failed', 0)
        return WorkflowResult(
            success=has_content,
            steps_completed=1 if has_content else 0,
            steps_total=1,
            error=None if has_content else "All file summary steps failed, check LLM model configuration or [SummarizeFileTool] / [SubAgent] errors in logs",
            summary=f"Pre-summary: {'succeeded' if has_content else 'failed'}",
            data={"failed_count": failed_count},
        )
