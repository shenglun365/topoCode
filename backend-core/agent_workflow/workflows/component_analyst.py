"""
ComponentAnalyst — 组件分析工作流 (Agent 模式)。

对用户选中的组件执行 LLM 分析，提取组件名称和功能概要，
每个组件分析后立即写入 SQLite component_analysis 表。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..tools import AgentTool, ToolResult
from ..workflows.base import AgentWorkflow, AgentStep, WorkflowResult

logger = logging.getLogger(__name__)


def _parse_structured_response(text: str, fallback_name: str = "") -> dict:
    """从 LLM 响应中提取 JSON，出错时尝试从纯文本恢复。"""
    import json as _json
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:]) if len(lines) > 1 else text
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    if text.startswith("json"):
        text = text[4:].strip()
    try:
        return _json.loads(text)
    except (_json.JSONDecodeError, ValueError):
        pass
    lines = text.strip().split("\n")
    name = lines[0].strip()[:60] if lines else fallback_name[:60]
    summary = "\n".join(lines[1:]) if len(lines) > 1 else text
    return {"name": name, "summary": summary, "role": "", "key_files": [], "depends_on": []}


def _build_markdown_summary(name: str, summary: str, role: str,
                              key_files: list, depends_on: list) -> str:
    parts = []
    parts.append(f"## 功能概要\n{summary}")
    if role:
        parts.append(f"\n**架构角色**: {role}")
    if key_files:
        files_md = "\n".join(f"- `{f}`" for f in key_files[:10])
        parts.append(f"\n**关键文件**:\n{files_md}")
    if depends_on:
        deps_md = ", ".join(depends_on[:10])
        parts.append(f"\n**依赖组件**: {deps_md}")
    return "\n".join(parts)


class _AnalyzeComponentTool(AgentTool):
    """分析单个组件: LLM → name + summary → 立即写入 SQLite"""

    name = "analyze_component"
    description = "使用 LLM 分析单个组件，提取名称和功能概要，并持久化到 SQLite"
    category = "analysis"

    def __init__(self, llm_chat_fn: Callable, render_prompt: Callable = None,
                 save_fn: Callable = None):
        self._chat = llm_chat_fn
        self._render = render_prompt
        self._save = save_fn

    async def execute(self, component: dict, task_id: str = "", **kwargs) -> ToolResult:
        comp_id = component.get("id", "")
        comp_name = component.get("name", comp_id)
        comp_type = component.get("type", "community")
        metadata = component.get("metadata", {})
        ctx = component.get("context", "")

        type_label = "社区模块" if comp_type == "community" else "外部依赖包"
        if not ctx:
            ctx_parts = [f"组件ID: {comp_id}", f"组件名称: {comp_name}", f"组件类型: {type_label}"]
            if metadata:
                ctx_parts.append(f"元数据: {metadata}")
            ctx = "\n".join(ctx_parts)

            logger.info(
                f"[ComponentAnalyst] analyze_component id={comp_id} type={comp_type} "
                f"ctx_len={len(ctx)} ctx_begin={ctx[:500]!r}"
            )
        try:
            if self._render:
                messages = self._render("agent_analyze_component", {
                    "comp_id": comp_id,
                    "comp_name": comp_name,
                    "comp_type": type_label,
                    "context": ctx,
                })
            else:
                system_text = (
                    "你是代码架构分析专家。基于提供的组件上下文数据（文件列表、关键符号、边关系），"
                    "分析该软件组件模块的功能与架构角色。\n\n"
                    "以 JSON 格式输出，包含以下字段：\n"
                    '- name: 组件名称（≤20字）\n'
                    '- summary: 功能概要（100-300字）\n'
                    '- role: 架构角色（≤3词，如 ConfigLoader / RequestRouter / DataAccessLayer）\n'
                    '- key_files: 关键文件路径数组（Top 5）\n'
                    '- depends_on: 依赖的其他组件或外部包数组\n'
                    "只输出 JSON，不要其他内容。"
                )
                messages = [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": ctx},
                ]

            resp = await self._chat(messages=messages, temperature=0.3, max_tokens=1200)
            text = resp if isinstance(resp, str) else str(resp)
            parsed = _parse_structured_response(text, comp_name)
            analyzed_name = parsed.get("name", comp_name[:60])
            summary_text = parsed.get("summary", "")
            role = parsed.get("role", "")
            key_files = parsed.get("key_files", [])
            depends_on = parsed.get("depends_on", [])

            if len(analyzed_name) > 20:
                analyzed_name = comp_name[:20]

            enhanced_summary = _build_markdown_summary(
                analyzed_name, summary_text, role, key_files, depends_on
            )

            if self._save:
                try:
                    self._save({
                        "task_id": task_id,
                        "component_id": comp_id,
                        "component_type": comp_type,
                        "analyzed_name": analyzed_name,
                        "functional_summary": enhanced_summary,
                        "status": "completed",
                    })
                except Exception as e:
                    logger.warning(f"[ComponentAnalyst] save failed for {comp_id}: {e}")

            return ToolResult.ok(
                data={
                    "componentId": comp_id,
                    "analyzedName": analyzed_name,
                    "functionalSummary": enhanced_summary,
                },
                tokens_used=1200,
            )
        except Exception as e:
            logger.warning(f"[ComponentAnalyst] analyze failed for {comp_id}: {e}")
            return ToolResult.fail(str(e), componentId=comp_id)


class ComponentAnalystWorkflow(AgentWorkflow):
    """按需组件分析工作流 — 仅分析用户选中的组件"""

    name = "component_analyst"
    description = "按需 LLM 分析选中的组件，提取名称和功能概要，持久化到 SQLite"

    def plan(self, context: dict) -> list[AgentStep]:
        components = context.get("components", [])
        if not components:
            return []

        steps: list[AgentStep] = []
        tid = context.get("task_id", "")

        for c in components:
            cid = c.get("id", "?")
            cname = c.get("name", cid)
            steps.append(AgentStep(
                tool="analyze_component",
                args={"component": c, "task_id": tid},
                description=f"分析组件: {cname[:30]}",
            ))

        return steps

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        return WorkflowResult(
            success=True,
            data={"completed": True},
            summary="组件分析完成",
        )
