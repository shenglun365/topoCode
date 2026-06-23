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

logger = logging.getLogger(__name__)


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

    async def _analyze_single(self, component: dict, task_id: str = "",
                               project_summary: str = "", parent_summary: str = "",
                               language: str = "") -> ToolResult:
        """分析单个组件（内部方法，供 execute 和 batch tool 共用）"""
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
                analysis_mode = component.get("analysis_mode", "quick")
                summary_range = "500-2000字" if analysis_mode == "deep" else "100-300字"
                max_tok = 2000 if analysis_mode == "deep" else 1200
                system_text = (
                    "你是代码架构分析专家。基于提供的组件上下文数据（文件列表、关键符号、边关系），"
                    "分析该软件组件模块的功能与架构角色。\n\n"
                    "以 JSON 格式输出，包含以下字段：\n"
                    '- name: 有实际语义的组件名称（≤20字），根据功能命名，'
                    '如 OpenVinoBackend / FlashAttentionOp / ModelOptimizerPass；'
                    '严禁返回原始社区编号（如 L0-0007、comm-xxx）作为名称\n'
                    f'- summary: 功能概要（{summary_range}）\n'
                    '- role: 架构角色（≤3词，如 ConfigLoader / RequestRouter / DataAccessLayer）\n'
                    '- key_files: 关键文件及其功能概要数组（Top 10）\n'
                    '  格式: [{"path": "src/foo.cpp", "summary": "实现矩阵乘法运算"}, ...]\n'
                    '- depends_on: 依赖的其他组件或外部包数组\n'
                    "**只输出 JSON，禁止输出任何其他内容**（包括分析过程、思考过程、解释说明）。直接输出 JSON 对象，不要用 ```json 代码块包裹。"
                )
                if project_summary:
                    system_text += f"\n\n项目摘要：{project_summary[:500]}"
                if parent_summary:
                    system_text += f"\n\n父组件功能概要：{parent_summary[:300]}"
                if language == "zh":
                    system_text += "\n\n请用中文输出 name 和 summary。"
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
                return ToolResult.fail("LLM 调用超时（120s）", componentId=comp_id)
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
                parse_error_reason = f"LLM 返回的名称「{analyzed_name}」无实际语义，需重新分析"

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
        """委托给 _analyze_single（单组件，保持向后兼容）"""
        return await self._analyze_single(component, task_id, project_summary, parent_summary, language)


class _AnalyzeComponentBatchTool(AgentTool):
    """批量分析组件，内部并发执行 LLM 调用"""

    name = "analyze_component_batch"
    description = "批量分析组件，按指定并发数并行调用 LLM 并持久化到 SQLite"
    category = "analysis"

    def __init__(self, llm_chat_fn: Callable, render_prompt: Callable = None,
                 save_fn: Callable = None):
        self._chat = llm_chat_fn
        self._render = render_prompt
        self._save = save_fn

    async def execute(self, components: list, task_id: str = "",
                      concurrency: int = 1, project_summary: str = "",
                      **kwargs) -> ToolResult:
        sem = asyncio.Semaphore(concurrency)
        master = _AnalyzeComponentTool(self._chat, self._render, self._save)

        async def analyze_one(comp: dict) -> ToolResult:
            async with sem:
                return await master._analyze_single(
                    comp, task_id=task_id,
                    project_summary=project_summary,
                    parent_summary=comp.get("parent_summary", ""),
                    language=comp.get("language", ""),
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

        msg = f"成功 {successes}/{len(components)}, 失败 {failures}"
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
    """按需组件分析工作流 — 仅分析用户选中的组件"""

    name = "component_analyst"
    description = "按需 LLM 分析选中的组件，提取名称和功能概要，持久化到 SQLite"

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
                },
                description=f"分析组件: {start}-{end}/{len(components)}",
            ))

        return steps

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        return WorkflowResult(
            success=True,
            data={"completed": True},
            summary="组件分析完成",
        )
