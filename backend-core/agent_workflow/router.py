"""
RouterHarness — 路由型总控。

位于 AgentRuntime 上层，根据 action 路由到正确的 Workflow + Tool 组合。
隔离"业务调度"和"执行引擎"，未来增加新业务流程只需添加路由分支。

设计:
  - 输入: action (str) + context (dict) → 输出: agent_task_id (str)
  - 负责: Workflow 实例化、ToolRegistry 组装、Sandbox 配置
  - 不负责: 具体执行（交给 AgentRuntime）、任务队列（交给 AgentTaskManager）
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from .tools import ToolRegistry
from .sandbox import AgentSandbox
from .workflows.base import AgentWorkflow

logger = logging.getLogger(__name__)


class RouteEntry:
    """一条路由定义"""

    def __init__(self, workflow_class: type, tool_builder: callable,
                 description: str = "",
                 sandbox_builder: Optional[callable] = None,
                 context_transformer: Optional[callable] = None):
        self.workflow_class = workflow_class
        self.tool_builder = tool_builder
        self.description = description
        self.sandbox_builder = sandbox_builder
        self.context_transformer = context_transformer


class RouterHarness:
    """路由型 Harness — 高层 action → Workflow 分发器"""

    def __init__(self, project_root: str = "", max_concurrency: int = 3, multi_db=None):
        self._project_root = project_root
        self._multi_db = multi_db
        self._routes: dict[str, RouteEntry] = {}
        self._queue = None  # lazy load

    def register(self, action: str, entry: RouteEntry) -> "RouterHarness":
        self._routes[action] = entry
        return self

    def dispatch(self, action: str, task_id: str, context: dict,
                 on_complete: Optional[callable] = None) -> str:
        """
        路由 action → 出队执行 → 返回 agent_task_id。

        Args:
            action: 操作名 ("analyze", "track_start", "track_stop", "diff")
            task_id: 任务 ID
            context: 上下文 dict (含 communities, edge_type 等)
            on_complete: 可选完成回调

        Returns:
            agent_task_id
        """
        entry = self._routes.get(action)
        if not entry:
            available = list(self._routes.keys())
            raise ValueError(f"Unknown action '{action}'. Available: {available}")

        # Apply context transformation if provided
        if entry.context_transformer:
            ctx = entry.context_transformer(context)
        else:
            ctx = dict(context)

        # Build tools
        tools = entry.tool_builder(ctx)

        # Build sandbox
        if entry.sandbox_builder:
            sandbox = entry.sandbox_builder(self._project_root)
        else:
            sandbox = AgentSandbox(self._project_root)

        # Instantiate workflow
        workflow = entry.workflow_class()

        # Enqueue
        from .agent_queue import get_global_queue
        self._queue = get_global_queue()

        agent_id = self._queue.enqueue(
            task_id=task_id,
            workflow=workflow,
            context=ctx,
            tools=tools,
            sandbox=sandbox,
            on_complete=on_complete,
            multi_db=self._multi_db,
        )

        logger.info(f"[Router] {action} → {workflow.name} agent={agent_id}")
        return agent_id

    def get_progress(self, agent_id: str) -> dict | None:
        if self._queue:
            return self._queue.get_progress(agent_id)
        return None

    def cancel(self, agent_id: str) -> bool:
        if self._queue:
            return self._queue.cancel(agent_id)
        return False

    def pause(self, agent_id: str) -> bool:
        if self._queue:
            return self._queue.pause(agent_id)
        return False

    def resume(self, agent_id: str) -> bool:
        if self._queue:
            return self._queue.resume(agent_id)
        return False

    # ─── LLM 推理路由 ───

    def classify(self, natural_language: str, llm_chat_fn: callable) -> dict:
        """
        使用 LLM 推理将自然语言分类到 action + 提取参数。

        Returns:
            {"action": "analyze", "params": {"level": "L0", "all": True}, "confidence": 0.95}
        """
        routes_desc = []
        for action, entry in self._routes.items():
            desc = entry.description or entry.workflow_class.description or action
            routes_desc.append(f"- {action}: {desc}")

        prompt = f"""You are an architecture analysis route classifier. Based on the user's natural language request, determine which action to execute.

Available actions:
{routes_desc}

Return JSON in format:
{{"action": <action_name>, "params": {{extracted params}}, "confidence": <0.0-1.0>}}

Rules:
- action must be one of the available actions
- params extracted from user text (level, edge_type, all, tag, etc.)
- If uncertain, return confidence=0, action="unknown"

User request: "{natural_language}"
JSON:"""

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            resp = loop.run_until_complete(
                llm_chat_fn(
                    messages=[
                        {"role": "system", "content": "You are a route classifier. Only output JSON, no explanation."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.0,
                    max_tokens=200,
                )
            )
        finally:
            loop.close()

        import json as _json
        text = resp if isinstance(resp, str) else str(resp)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
        try:
            parsed = _json.loads(text)
        except _json.JSONDecodeError:
            parsed = {"action": "unknown", "params": {}, "confidence": 0}
        return parsed

    def dispatch_nl(
        self,
        natural_language: str,
        task_id: str,
        context: dict,
        llm_chat_fn: callable,
        on_complete: callable = None,
    ) -> str:
        """
        基于 LLM 推理的自然语言路由。

        流程:
          1. LLM → classify → {action, params, confidence}
          2. confidence > 0.7 → dispatch(action)
          3. confidence <= 0.7 → raise ValueError (需要用户澄清)
        """
        classification = self.classify(natural_language, llm_chat_fn)

        action = classification.get("action", "unknown")
        confidence = classification.get("confidence", 0)
        params = classification.get("params", {})

        logger.info(
            f"[Router.NL] classified: action={action} confidence={confidence} params={params}"
        )

        if action == "unknown" or confidence < 0.5:
            available = self.routes
            raise ValueError(
                f"Cannot understand your request. Available actions: {available}. Please try a more specific description."
            )

        if confidence < 0.7:
            available = self.routes
            raise ValueError(
                f"Uncertain about your intent (confidence={confidence:.0%}). Available actions: {available}. "
                f"Please specify: {', '.join(available)}"
            )

        merged_context = dict(context)
        merged_context.update(params)

        return self.dispatch(action, task_id, merged_context, on_complete)

    @property
    def routes(self) -> list[str]:
        return list(self._routes.keys())


# ─── 工厂函数: 构建默认路由表 ───

def create_default_router(
    project_root: str,
    project_db,
    multi_db,
    task_id: str,
    project_summary: str = "",
    llm_model_id: str = "",
) -> RouterHarness:
    """
    构建 RouterHarness 并注册所有默认路由。

    注册的路由:
      - "overview"    → OverviewWorkflow (整体架构概览)
    """
    router = RouterHarness(project_root=project_root, multi_db=multi_db)

    # ── overview 路由 ──
    def _build_overview_tools(ctx: dict) -> ToolRegistry:
        from .tools import ToolRegistry as _TR
        from .workflows.overview import _GenerateOverviewTool
        tools = _TR()
        tools.register(_GenerateOverviewTool(
            multi_db, project_db, ctx.get("task_id", "")))
        return tools

    def _overview_context_transform(ctx: dict) -> dict:
        ctx["project_summary"] = project_summary
        return ctx

    from .sandbox import AgentSandbox
    from .workflows.overview import OverviewWorkflow
    router.register("overview", RouteEntry(
        workflow_class=OverviewWorkflow,
        tool_builder=_build_overview_tools,
        context_transformer=_overview_context_transform,
        description="Generate overall architecture overview document. Agent reads community analysis results, file pre-summaries, source files etc., outputs architecture overview Markdown. Supports: --force (force regenerate), -L zh/en (output language)",
        sandbox_builder=lambda root: AgentSandbox(root, max_tokens=8192, timeout_seconds=600),
    ))

    # ── analyze_components 路由（统一 Agentic 多轮模式） ──
    def _build_agentic_component_tools(ctx: dict) -> ToolRegistry:
        from .tool_factory import build_agentic_component_tools
        from .sandbox import PathSandbox
        ps = PathSandbox(project_root) if project_root else None
        return build_agentic_component_tools(
            project_root=project_root,
            project_db=project_db,
            path_sandbox=ps,
            project_id=ctx.get("project_id", ""),
            task_id=ctx.get("task_id", ""),
            multi_db=multi_db,
            concurrency=ctx.get("subagent_concurrency", 1),
        )

    def _agentic_component_context_transform(ctx: dict) -> dict:
        ctx["project_summary"] = project_summary
        return ctx

    from .workflows.agentic_component_analyst import AgenticComponentAnalystWorkflow
    router.register("analyze_components", RouteEntry(
        workflow_class=AgenticComponentAnalystWorkflow,
        tool_builder=_build_agentic_component_tools,
        context_transformer=_agentic_component_context_transform,
        description="Agentic multi-turn component analysis, LLM autonomously calls read_file / search_content etc. to read files then analyze. Supports: -j N (concurrency 1-5, default 1), --force (force re-analysis)",
    ))

    # ── presummary_files 路由（文件预摘要） ──
    def _build_presummary_tools(ctx: dict) -> ToolRegistry:
        from .tool_factory import build_agentic_component_tools
        from .sandbox import PathSandbox
        ps = PathSandbox(project_root) if project_root else None
        return build_agentic_component_tools(
            project_root=project_root,
            project_db=project_db,
            path_sandbox=ps,
            project_id=ctx.get("project_id", ""),
            task_id=ctx.get("task_id", ""),
            multi_db=multi_db,
            concurrency=ctx.get("subagent_concurrency", 1),
        )

    from .workflows.pre_summary import PreSummaryWorkflow
    router.register("presummary_files", RouteEntry(
        workflow_class=PreSummaryWorkflow,
        tool_builder=_build_presummary_tools,
        context_transformer=None,
        description="File pre-summary: batch summarize files to cache, accelerate subsequent component analysis. Supports: -j N (concurrency 1-5, default 1), --force (force regenerate)",
        sandbox_builder=lambda root: AgentSandbox(root, max_tokens=0, timeout_seconds=0),
    ))

    # ── pipeline 路由（完整流水线） ──
    def _build_pipeline_tools(ctx: dict) -> ToolRegistry:
        from .tool_factory import build_pipeline_tools
        pid = ctx.get("project_id", "")
        tid = ctx.get("task_id", "")
        return build_pipeline_tools(
            multi_db, project_db, project_root, tid, pid, project_summary,
            concurrency=ctx.get("concurrency", 1),
            subagent_concurrency=ctx.get("subagent_concurrency", 1),
        )

    from .workflows.pipeline import PipelineWorkflow
    router.register("pipeline", RouteEntry(
        workflow_class=PipelineWorkflow,
        tool_builder=_build_pipeline_tools,
        context_transformer=None,
        description="Pipeline: project summary -> pre-summary -> component analysis -> architecture analysis. Supports: -j N (concurrency 1-5, default 1), --force (force regenerate), -L zh/en (output language)",
        sandbox_builder=lambda root: AgentSandbox(root, max_tokens=0, timeout_seconds=0),
    ))

    return router
