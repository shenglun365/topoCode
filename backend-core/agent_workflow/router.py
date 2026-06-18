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

    def __init__(self, project_root: str = "", max_concurrency: int = 3):
        self._project_root = project_root
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

        prompt = f"""你是架构分析路由分类器。根据用户的自然语言请求，判断应执行哪个操作。

可用操作:
{routes_desc}

请返回 JSON，格式:
{{"action": <操作名>, "params": {{提取的参数}}, "confidence": <0.0-1.0>}}

规则:
- action 必须是可用操作之一
- params 从用户文本中提取 (level, edge_type, all, tag 等)
- 如果无法确定，返回 confidence=0，action="unknown"

用户请求: "{natural_language}"
JSON:"""

        import asyncio
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            resp = loop.run_until_complete(
                llm_chat_fn(
                    messages=[
                        {"role": "system", "content": "你是路由分类器。只输出 JSON，不要解释。"},
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
                f"无法理解您的请求。可用操作: {available}。请尝试更明确的描述。"
            )

        if confidence < 0.7:
            available = self.routes
            raise ValueError(
                f"不确定您的意图 (置信度={confidence:.0%})。可用操作: {available}。"
                f"请明确选择: {', '.join(available)}"
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
    save_result_fn: callable = None,
) -> RouterHarness:
    """
    构建 RouterHarness 并注册所有默认路由。

    注册的路由:
      - "analyze"     → ArchAnalystWorkflow (LLM 分析 + 图 + 概览)
      - "track_start" → ArchSentinelWorkflow (记录快照)
      - "track_stop"  → ArchSentinelWorkflow (对比 + 摘要 + 持久化)
    """
    router = RouterHarness(project_root=project_root)

    # ── analyze 路由 ──
    def _build_analyst_tools(ctx: dict) -> ToolRegistry:
        from .llm_adapter import create_llm_chat_fn
        from .tool_factory import build_analyst_tools
        from prompt_manager import PromptManager
        pm = PromptManager(multi_db.main_db)

        def _render(template_id, variables):
            result = pm.render(template_id, variables, locale='zh-CN')
            return result.get('messages', [])

        llm_fn = create_llm_chat_fn(multi_db, llm_model_id)
        return build_analyst_tools(llm_fn, _render, save_result_fn)

    def _analyst_context_transform(ctx: dict) -> dict:
        ctx["project_summary"] = project_summary
        return ctx

    from .workflows.arch_analyst import ArchAnalystWorkflow
    router.register("analyze", RouteEntry(
        workflow_class=ArchAnalystWorkflow,
        tool_builder=_build_analyst_tools,
        context_transformer=_analyst_context_transform,
        description="批量 LLM 分析全部社区模块，生成模块名称、功能摘要、架构图和整体架构概览文档。适用于新人理解项目结构或全面梳理现有架构。",
    ))

    # ── track_start / track_stop 路由 ──
    def _build_sentinel_tools(ctx: dict) -> ToolRegistry:
        from .llm_adapter import create_llm_chat_fn
        from .tool_factory import build_sentinel_tools
        from prompt_manager import PromptManager
        pm = PromptManager(multi_db.main_db)

        def _render(template_id, variables):
            result = pm.render(template_id, variables, locale='zh-CN')
            return result.get('messages', [])

        llm_fn = create_llm_chat_fn(multi_db, llm_model_id)
        return build_sentinel_tools(llm_fn, project_root, _render)

    def _sentinel_context_transform(ctx: dict) -> dict:
        import time as _time
        ctx["timestamp"] = _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime())
        if not ctx.get("version_id"):
            ctx["version_id"] = f"v-{int(_time.time())}"
        return ctx

    from .workflows.arch_sentinel import ArchSentinelWorkflow
    sentinel_start = RouteEntry(
        workflow_class=ArchSentinelWorkflow,
        tool_builder=_build_sentinel_tools,
        context_transformer=_sentinel_context_transform,
        description="开始架构变更追踪，记录当前架构快照（社区数量、质量分）。适用于重构或大规模修改前的基线记录。",
    )
    sentinel_stop = RouteEntry(
        workflow_class=ArchSentinelWorkflow,
        tool_builder=_build_sentinel_tools,
        context_transformer=_sentinel_context_transform,
        description="结束架构追踪，对比起始与当前快照，生成变更摘要（新增/删除/变更的社区数，风险评估）。适用于重构完成后验证架构变化是否符合预期。",
    )
    router.register("track_start", sentinel_start)
    router.register("track_stop", sentinel_stop)

    # ── analyze_components 路由 ──
    def _build_component_tools(ctx: dict) -> ToolRegistry:
        from .llm_adapter import create_llm_chat_fn
        from .tool_factory import build_component_analyst_tools
        llm_fn = create_llm_chat_fn(multi_db, llm_model_id) if multi_db else None
        return build_component_analyst_tools(llm_fn, render_prompt=None, save_result_fn=save_result_fn)

    def _component_context_transform(ctx: dict) -> dict:
        ctx["project_summary"] = project_summary
        return ctx

    from .workflows.component_analyst import ComponentAnalystWorkflow
    router.register("analyze_components", RouteEntry(
        workflow_class=ComponentAnalystWorkflow,
        tool_builder=_build_component_tools,
        context_transformer=_component_context_transform,
        description="按需 LLM 分析用户选中的组件，提取组件名称和功能概要，结果写入 SQLite。支持单组件和批量分析。",
    ))

    return router
