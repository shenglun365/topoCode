"""
AgenticComponentAnalyst — Agent 组件分析工作流 (Agentic 模式)。

逐组件独立处理：每个组件发起一个独立的 ReAct 循环，
LLM 自主调用工具读取文件、搜索符号，完成一轮多轮对话后保存结果，
再处理下一个组件。
"""

import logging
from typing import Any, Optional

from .base import AgenticWorkflow, WorkflowResult

logger = logging.getLogger(__name__)


class AgenticComponentAnalystWorkflow(AgenticWorkflow):
    """Agentic 组件分析 — LLM 自主调用工具逐组件分析"""

    name = "agentic_component_analyst"
    description = "LLM 自主调用工具逐组件分析，可读取文件、搜索符号，最终输出组件名称和功能概要"

    max_turns: int = 30

    input_schema = {
        "task_id": "str — 分析任务 ID",
        "components": "[{id, name, type, metadata, context, parent_summary}] — 待分析组件列表",
        "language": "str — 输出语言 (zh/en/空)",
        "concurrency": "int — 并发数 (1-5，当前置1随组件迭代)",
        "project_summary": "str — 项目摘要",
    }
    output_schema = {
        "component_results": "[{component_id, output_text, turns}] — 逐组件结果",
        "success": "int — 成功数",
        "failed": "int — 失败数",
    }

    def get_system_prompt(self, component: dict, project_summary: str = "",
                           detail_level: str = "quick") -> str:
        cid = component.get("id", "?")
        cname = component.get("name", cid)
        parent_summary = component.get("parent_summary", "")
        metadata = component.get("metadata", {})

        is_deep = detail_level == "deep"
        summary_range = "500-2000字" if is_deep else "100-300字"

        base_prompt = (
                "你是代码架构分析专家。通过系统化的工具调用分析组件。\n\n"
                "## 核心规则：用 summarize_file 代替 read_file\n"
                "summarize_file 是读取文件的**默认方式**。它一次可处理最多 10 个文件并自动摘要，"
                "结果会被缓存，后续轮次不消耗 token。\n"
                "read_file 只能在你认为某个文件的摘要**明显不充分**时才使用，且每次只能读一个文件。\n"
                "**不要逐文件调用 read_file** — 这效率极低且浪费上下文。\n\n"
                "分析流程：\n"
                "  Step 1 — 结构探索：\n"
                "    调用 get_community_subgraph 了解组件拓扑结构\n"
                "    调用 search_symbols 发现关键函数/类定义\n"
                "\n"
                "  Step 2 — 文件摘要（**必须用 summarize_file**）：\n"
                "    根据 Step 1 的发现确定关键文件，用 summarize_file 批量读取\n"
                "    示例: summarize_file(path=[\"src/a.cpp\", \"src/b.h\"], focus=\"关注接口定义\")\n"
                "    将所有需要读的文件一次性或分批传给 summarize_file\n"
                "\n"
                "  Step 3 — 综合输出（**必须执行**）：\n"
                "    综合所有信息，**必须**输出 JSON，不得输出其他文本。\n"
                "    如果信息不足，继续调用工具获取更多信息。\n"
                "    收到工具结果后，不要再调用工具，直接输出 JSON。\n"
                "    JSON 格式：\n"
                "    {{\"name\": \"有实际语义的名称（≤20字）\", "
                f"\"summary\": \"功能概要（{summary_range}）\", "
                "\"role\": \"架构角色（≤3词）\", "
                "\"key_files\": [{{\"path\": \"...\", \"summary\": \"该文件功能\"}}], "
                "\"depends_on\": [\"其他组件或外部包\"]}}\n\n"
                f"当前分析的组件: {cname} (ID: {cid})\n"
            )

        parts = [base_prompt]
        if metadata:
            parts.append(f"元数据: 节点数={metadata.get('nodeCount','?')}, "
                         f"文件数={metadata.get('fileCount','?')}, "
                         f"质量分={metadata.get('qualityScore','?')}")
        if project_summary:
            parts.append(f"项目摘要: {project_summary[:500]}")
        if parent_summary:
            parts.append(f"父组件概要: {parent_summary[:500]}")

        parts.append(
            "重要提示：\n"
            "- 必须给出有实际语义的名称，不能是社区编号\n"
            "- **禁止逐文件调用 read_file**，一律用 summarize_file 批量读取\n"
            "- 分析完成后只输出 JSON，不要包含其他文本"
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
            summary=f"Agentic 逐组件分析完成: {success_count}/{total} 成功",
        )
