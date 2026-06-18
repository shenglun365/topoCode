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

    max_turns: int = 6

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

    def get_system_prompt(self, component: dict, project_summary: str = "") -> str:
        cid = component.get("id", "?")
        cname = component.get("name", cid)
        parent_summary = component.get("parent_summary", "")
        metadata = component.get("metadata", {})

        parts = [(
            "你是代码架构分析专家。你的任务是通过逐步调查来分析一个软件组件。\n\n"
            "工作流程：\n"
            "1. 阅读上下文数据（文件列表、关键符号、函数调用关系）\n"
            "2. 必要时调用 read_file 查看具体文件内容\n"
            "3. 必要时调用 search_content / search_symbols 搜索特定信息\n"
            "4. 综合所有信息，输出：\n"
            "   - name: 有实际语义的组件名称（≤20字）\n"
            "   - summary: 功能概要（100-300字）\n"
            "   - role: 架构角色（≤3词，如 ConfigLoader / DataAccessLayer）\n"
            "   - key_files: 关键文件及其功能概要数组（Top 10），"
            "格式 [{\"path\": \"src/foo.cpp\", \"summary\": \"实现矩阵乘法运算\"}, ...]\n"
            "   - depends_on: 依赖的其他组件或外部包数组\n\n"
            f"当前分析的组件: {cname} (ID: {cid})\n"
        )]
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
            "- 分析完成后只输出 JSON，不要包含其他文本\n"
            "- JSON 格式: {\"name\": \"...\", \"summary\": \"...\", \"role\": \"...\", "
            "\"key_files\": [{\"path\": \"...\", \"summary\": \"...\"}], \"depends_on\": [...]}"
        )
        return "\n".join(parts)

    def get_tool_filter(self, context: dict) -> Optional[list[str]]:
        return [
            "read_file", "search_content",
            "get_symbol_detail", "search_symbols",
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
