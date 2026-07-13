"""
ComponentAnalyst — 组件分析工作流 (Agent 模式)。

对用户选中的组件执行 LLM 分析，提取组件名称和功能概要，
每个组件分析后立即写入 SQLite community_llm_results 表。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from ..tools import AgentTool, ToolResult
from ..workflows.base import AgentWorkflow, AgentStep, WorkflowResult
from ..shared_utils import parse_structured_response, build_markdown_summary
from ..skill_registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(
    name="skill_analyze_community",
    description="Analyze a community in depth — extract component name, functional summary, architecture role",
    steps=4,
    category="analysis",
)
class _AnalyzeComponentTool(AgentTool):
    """Analyze single component: LLM → name + summary → write to SQLite immediately"""

    name = "analyze_component"
    description = "Use LLM to analyze a single component, extract name and functional summary, persist to SQLite"
    category = "analysis"

    def __init__(self, llm_chat_fn: Callable, render_prompt: Callable = None,
                 save_fn: Callable = None):
        self._chat = llm_chat_fn
        self._render = render_prompt
        self._save = save_fn

    async def _analyze_single(self, component: dict, task_id: str = "",
                               project_summary: str = "", parent_summary: str = "",
                               language: str = "") -> ToolResult:
        """Analyze single component (internal method, shared by execute and batch tool)"""
        comp_id = component.get("id", "")
        comp_name = component.get("name", comp_id)
        comp_type = component.get("type", "community")
        metadata = component.get("metadata", {})
        ctx = component.get("context", "")

        type_label = "community module" if comp_type == "community" else "external dependency"
        if not ctx:
            ctx_parts = [f"Component ID: {comp_id}", f"Component Name: {comp_name}", f"Component Type: {type_label}"]
            if metadata:
                ctx_parts.append(f"Metadata: {metadata}")
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
                analysis_mode = component.get("analysis_mode", "quick")
                summary_range = "500-2000 chars" if analysis_mode == "deep" else "100-300 chars"
                max_tok = 2000 if analysis_mode == "deep" else 1200
                system_text = (
                    "You are a code architecture analysis expert. Based on the provided component context data (file list, key symbols, edge relations), "
                    "analyze the function and architecture role of this software component module.\n\n"
                    "Output in JSON format with the following fields:\n"
                    '- name: Semantically meaningful component name (≤20 chars), named by function, '
                    'e.g. OpenVinoBackend / FlashAttentionOp / ModelOptimizerPass; '
                    'do NOT return raw community IDs (e.g. L0-0007, comm-xxx) as name\n'
                    f'- summary: Functional summary ({summary_range})\n'
                    '- role: Architecture role (≤3 words, e.g. ConfigLoader / RequestRouter / DataAccessLayer)\n'
                    '- key_files: Key files and their functional summaries array (Top 10)\n'
                    '  Format: [{"path": "src/foo.cpp", "summary": "Implements matrix multiplication"}, ...]\n'
                    '- depends_on: Array of other components or external packages\n'
                    "**Only output JSON, no other content** (including analysis process, thought process, explanations). Directly output JSON object, do not wrap in ```json code blocks."
                )
                if project_summary:
                    system_text += f"\n\nProject Summary: {project_summary[:500]}"
                if parent_summary:
                    system_text += f"\n\nParent Component Summary: {parent_summary[:300]}"
                if language == "zh":
                    system_text += "\n\nOutput name and summary in Chinese."
                elif language == "en":
                    system_text += "\n\nOutput name and summary in English."
                messages = [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": ctx},
                ]

            try:
                    resp = await asyncio.wait_for(
                        self._chat(messages=messages, temperature=0.3, max_tokens=max_tok),
                        timeout=600
                    )
            except asyncio.TimeoutError:
                logger.warning(f"[ComponentAnalyst] LLM timeout for {comp_id}")
                if self._save:
                    try:
                        self._save({"task_id": task_id, "component_id": comp_id,
                                     "component_type": comp_type, "analyzed_name": comp_id,
                                     "functional_summary": "", "status": "failed"})
                    except Exception:
                        pass
                return ToolResult.fail("LLM call timed out (120s)", componentId=comp_id)
            text = resp if isinstance(resp, str) else str(resp)
            parsed = parse_structured_response(text, comp_name)
            parse_error = parsed.pop("_parse_error", False)
            parse_error_reason = parsed.pop("_error_reason", "")
            analyzed_name = parsed.get("name", comp_name[:60])
            summary_text = parsed.get("summary", "")
            role = parsed.get("role", "")
            key_files = parsed.get("key_files", [])
            depends_on = parsed.get("depends_on", [])

            if len(analyzed_name) > 20:
                analyzed_name = comp_name[:20]

            enhanced_summary = build_markdown_summary(
                analyzed_name, summary_text, role, key_files, depends_on
            )

            import re as _re
            is_bad_name = (
                not analyzed_name.strip()
                or analyzed_name == comp_id
                or analyzed_name == comp_name
                or bool(_re.match(r'^L\d+-\d+$', analyzed_name))
                or analyzed_name.startswith('comm-')
            )
            if is_bad_name and not parse_error_reason:
                parse_error_reason = f"LLM returned name '{analyzed_name}' has no semantic meaning, needs re-analysis"

            comp_status = "failed" if (parse_error or is_bad_name) else "completed"

            if self._save:
                try:
                    self._save({
                        "task_id": task_id,
                        "component_id": comp_id,
                        "component_type": comp_type,
                        "analyzed_name": analyzed_name,
                        "functional_summary": enhanced_summary,
                        "status": comp_status,
                    })
                except Exception as e:
                    logger.warning(f"[ComponentAnalyst] save failed for {comp_id}: {e}")

            if parse_error or is_bad_name:
                return ToolResult.fail(
                    parse_error_reason,
                    componentId=comp_id,
                )

            return ToolResult.ok(
                data={
                    "componentId": comp_id,
                    "analyzedName": analyzed_name,
                    "functionalSummary": enhanced_summary,
                    "status": "completed",
                },
                tokens_used=1200,
            )
        except Exception as e:
            logger.warning(f"[ComponentAnalyst] analyze failed for {comp_id}: {e}")
            return ToolResult.fail(str(e), componentId=comp_id)

    async def execute(self, component: dict, project_summary: str = "",
                      parent_summary: str = "", language: str = "",
                      task_id: str = "", **kwargs) -> ToolResult:
        """Delegate to _analyze_single (single component, backward compatible)"""
        return await self._analyze_single(component, task_id, project_summary, parent_summary, language)


class _AnalyzeComponentBatchTool(AgentTool):
    """Batch analyze components, internally concurrent LLM calls"""

    name = "analyze_component_batch"
    description = "Batch analyze components, call LLM in parallel with specified concurrency, persist to SQLite"
    category = "analysis"

    def __init__(self, llm_chat_fn: Callable, render_prompt: Callable = None,
                 save_fn: Callable = None):
        self._chat = llm_chat_fn
        self._render = render_prompt
        self._save = save_fn

    async def execute(self, components: list, task_id: str = "",
                      concurrency: int = 1, project_summary: str = "",
                      language: str = "", **kwargs) -> ToolResult:
        sem = asyncio.Semaphore(concurrency)
        master = _AnalyzeComponentTool(self._chat, self._render, self._save)

        async def analyze_one(comp: dict) -> ToolResult:
            async with sem:
                return await master._analyze_single(
                    comp, task_id=task_id,
                    project_summary=project_summary,
                    parent_summary=comp.get("parent_summary", ""),
                    language=comp.get("language", language),
                )

        tasks = [analyze_one(c) for c in components]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)

        successes = 0
        failures = 0
        total_tokens = 0
        for r in gathered:
            if isinstance(r, ToolResult) and r.success:
                successes += 1
                total_tokens += r.tokens_used or 0
            else:
                failures += 1

        msg = f"Succeeded {successes}/{len(components)}, Failed {failures}"
        if failures > 0 and successes == 0:
            return ToolResult.fail(msg)
        if failures > 0:
            return ToolResult.ok(
                data={"success": successes, "failed": failures, "warning": msg},
                tokens_used=total_tokens,
            )
        return ToolResult.ok(
            data={"success": successes, "failed": failures},
            tokens_used=total_tokens,
        )


class ComponentAnalystWorkflow(AgentWorkflow):
    """On-demand component analysis workflow — only analyze user-selected components"""

    name = "component_analyst"
    description = "On-demand LLM analysis of selected components, extract name and functional summary, persist to SQLite"

    def plan(self, context: dict) -> list[AgentStep]:
        components = context.get("components", [])
        if not components:
            return []

        steps: list[AgentStep] = []
        tid = context.get("task_id", "")
        project_summary = context.get("project_summary", "")
        language = context.get("language", "")
        concurrency = min(int(context.get("concurrency", 1)), 5)
        batch_size = max(concurrency, 1)
        batches = [components[i:i + batch_size]
                   for i in range(0, len(components), batch_size)]

        for i, batch in enumerate(batches):
            start = i * batch_size + 1
            end = min((i + 1) * batch_size, len(components))
            steps.append(AgentStep(
                tool="analyze_component_batch",
                args={
                    "components": batch,
                    "task_id": tid,
                    "concurrency": concurrency,
                    "project_summary": project_summary,
                    "language": language,
                },
                description=f"Analyzing components: {start}-{end}/{len(components)}",
            ))

        return steps

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        return WorkflowResult(
            success=True,
            data={"completed": True},
            summary="Component analysis complete",
        )
