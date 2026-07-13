"""
AgenticComponentAnalyst — Agent 组件分析工作流 (Agentic 模式)。

逐组件独立处理：每个组件发起一个独立的 ReAct 循环，
LLM 自主调用工具读取文件、搜索符号，完成一轮多轮对话后保存结果，
再处理下一个组件。
"""

import logging
from typing import Any, Optional

from .base import AgenticWorkflow, WorkflowResult
from ..skill_registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(
    name="skill_batch_analyze_communities",
    description="Batch analyze communities — analyze all L0/L1/L2 communities with LLM",
    steps=5,
    category="analysis",
)


class AgenticComponentAnalystWorkflow(AgenticWorkflow):
    """Agentic component analysis — LLM autonomously calls tools to analyze components"""

    name = "agentic_component_analyst"
    description = "LLM autonomously calls tools to analyze components per-component, can read files, search symbols, outputs component name and functional summary"

    max_turns: int = 30

    input_schema = {
        "task_id": "str — analysis task ID",
        "components": "[{id, name, type, metadata, context, parent_summary}] — component list to analyze",
        "language": "str — output language (zh/en/empty)",
        "concurrency": "int — concurrency (1-5, currently forced to 1 per component iteration)",
        "project_summary": "str — project summary",
    }
    output_schema = {
        "component_results": "[{component_id, output_text, turns}] — per-component results",
        "success": "int — success count",
        "failed": "int — failure count",
    }

    def get_system_prompt(self, component: dict, project_summary: str = "",
                           detail_level: str = "quick", language: str = "") -> str:
        cid = component.get("id", "?")
        cname = component.get("name", cid)
        parent_summary = component.get("parent_summary", "")
        metadata = component.get("metadata", {})

        is_deep = detail_level == "deep"
        summary_range = "500-2000 chars" if is_deep else "100-300 chars"

        base_prompt = (
                "You are a code architecture analysis expert. Analyze components through systematic tool calls.\n\n"
                "## Core Rule: Use summarize_file instead of read_file\n"
                "summarize_file is the **default way** to read files. It can process up to 10 files at once with auto-summary, "
                "results are cached and consume no tokens in subsequent turns.\n"
                "read_file should only be used when you think a file's summary is **clearly insufficient**, and only one file per call.\n"
                "**Do not call read_file per file** — this is extremely inefficient and wastes context.\n\n"
                "Analysis Process:\n"
                "  Step 1 — Structure Exploration:\n"
                "    Call get_community_subgraph to understand component topology\n"
                "    Call search_symbols to discover key function/class definitions\n"
                "\n"
                "  Step 2 — File Summary (**must use summarize_file**):\n"
                "    Based on Step 1 findings, identify key files and batch read with summarize_file\n"
                "    Example: summarize_file(path=[\"src/a.cpp\", \"src/b.h\"], focus=\"focus on interface definitions\")\n"
                "    Pass all files to summarize_file at once or in batches\n"
                "\n"
                "  Step 3 — Final Output (**required**):\n"
                "    Combine all information, **must** output JSON, no other text.\n"
                "    If information is insufficient, continue calling tools for more info.\n"
                "    After receiving tool results, do not call more tools, directly output JSON.\n"
                "    JSON format:\n"
                "    {{\"name\": \"semantic name (≤20 chars)\", "
                f"\"summary\": \"functional summary ({summary_range})\", "
                "\"role\": \"architecture role (≤3 words)\", "
                "\"key_files\": [{{\"path\": \"...\", \"summary\": \"file function\"}}], "
                "\"depends_on\": [\"other components or external packages\"]}}\n\n"
                f"Currently analyzing component: {cname} (ID: {cid})\n"
            )

        parts = [base_prompt]
        if metadata:
            parts.append(f"Metadata: nodes={metadata.get('nodeCount','?')}, "
                         f"files={metadata.get('fileCount','?')}, "
                         f"quality_score={metadata.get('qualityScore','?')}")
        if project_summary:
            parts.append(f"Project Summary: {project_summary[:500]}")
        if parent_summary:
            parts.append(f"Parent Summary: {parent_summary[:500]}")

        parts.append(
            "Important Notes:\n"
            "- Must provide a semantically meaningful name, not a community ID\n"
            "- **Do not call read_file per file**, always use summarize_file for batch reads\n"
            "- Only output JSON upon completion, no other text"
        )
        return "\n".join(parts)

    def get_tool_filter(self, context: dict) -> Optional[list[str]]:
        return [
            "read_file", "search_content", "summarize_file",
            "get_symbol_detail", "search_symbols", "get_symbol_code",
            "get_community_subgraph", "get_call_chain",
            "get_ast_node", "get_edge_detail",
        ]

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        comp_results = results.get("component_results", [])
        total = len(comp_results)
        success_count = sum(1 for r in comp_results if r.get("output_text"))
        return WorkflowResult(
            success=success_count > 0,
            data={
                "component_results": comp_results,
                "success": success_count,
                "failed": total - success_count,
                "total": total,
            },
            summary=f"Agentic per-component analysis complete: {success_count}/{total} succeeded",
        )
