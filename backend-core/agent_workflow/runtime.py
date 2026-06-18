"""
AgentRuntime — 规划→执行→观察 循环。

核心循环:
  1. plan:   调用 workflow.plan(context) 生成步骤序列
  2. exec:   对每一步，通过 ToolRegistry 查找工具并执行
  3. observe: 收集结果 → 更新 memory → 决定是否继续
  4. finalize: 所有步骤完成后，调用 workflow.finalize() 汇总

支持:
  - 取消 (cancel())
  - 进度回调 (on_progress)
  - 预算跟踪 (sandbox.budget)
  - 沙箱约束 (sandbox.path / content / rate)
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from .tools import ToolRegistry, ToolResult
from .memory import AgentMemory
from .sandbox import AgentSandbox
from .workflows.base import AgentWorkflow, AgenticWorkflow, AgentStep, WorkflowResult

logger = logging.getLogger(__name__)


class AgentStatus(Enum):
    IDLE = "idle"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class StepProgress:
    """单步执行的进度信息"""

    step_index: int
    step_total: int
    description: str
    status: str = "pending"   # pending | running | done | failed
    result: Optional[ToolResult] = None


@dataclass
class AgentProgress:
    """Agent 整体进度（传递给回调）"""

    status: AgentStatus
    steps: list[StepProgress] = field(default_factory=list)
    step_current: int = 0
    step_total: int = 0
    tokens_used: int = 0
    elapsed_sec: float = 0.0
    message: str = ""


ProgressCallback = Callable[[AgentProgress], None]


class AgentRuntime:
    """Agent 运行时引擎"""

    def __init__(
        self,
        tools: ToolRegistry,
        sandbox: AgentSandbox,
        memory: Optional[AgentMemory] = None,
        on_progress: Optional[ProgressCallback] = None,
        multi_db: Optional[Any] = None,
    ):
        self._tools = tools
        self._sandbox = sandbox
        self._memory = memory or AgentMemory()
        self._on_progress = on_progress
        self._multi_db = multi_db
        self._cancelled = False
        self._status = AgentStatus.IDLE
        self._steps: list[StepProgress] = []

    def cancel(self):
        """取消当前执行"""
        self._cancelled = True
        self._status = AgentStatus.CANCELLED
        logger.info("[AgentRuntime] cancelled by user")

    async def run(self, workflow: AgentWorkflow, context: dict) -> WorkflowResult:
        """
        执行一个工作流。

        Args:
            workflow: 工作流实例（AgentWorkflow → 顺序执行，AgenticWorkflow → ReAct 循环）
            context: 上下文 dict（来自 AnalysisContext 或调用方）

        Returns:
            WorkflowResult
        """
        if isinstance(workflow, AgenticWorkflow):
            return await self._run_agentic(workflow, context)
        return await self._run_sequential(workflow, context)

    async def _run_sequential(self, workflow: AgentWorkflow, context: dict) -> WorkflowResult:
        self._cancelled = False
        self._status = AgentStatus.PLANNING
        self._sandbox.budget.start()

        # 1. Plan
        self._report(status=AgentStatus.PLANNING, message=f"规划中: {workflow.name}")
        try:
            steps = workflow.plan(context)
        except Exception as e:
            logger.exception(f"[AgentRuntime] plan failed: {e}")
            self._status = AgentStatus.FAILED
            return WorkflowResult(success=False, error=str(e))

        if not steps:
            logger.info(f"[AgentRuntime] no steps to execute for {workflow.name}")
            self._status = AgentStatus.COMPLETED
            return WorkflowResult(success=True, steps_completed=0, steps_total=0)

        self._steps = [
            StepProgress(step_index=i, step_total=len(steps), description=s.description)
            for i, s in enumerate(steps)
        ]

        # 2. Execute each step
        self._status = AgentStatus.RUNNING
        results: dict[str, Any] = {}
        completed_count = 0
        failed_count = 0

        for i, step in enumerate(steps):
            if self._cancelled:
                break
            if self._sandbox.budget.exhausted():
                logger.warning(f"[AgentRuntime] budget exhausted at step {i}/{len(steps)}")
                self._status = AgentStatus.PARTIAL
                break

            tool = self._tools.get(step.tool)
            if not tool:
                logger.error(f"[AgentRuntime] unknown tool: {step.tool}")
                self._steps[i].status = "failed"
                self._steps[i].result = ToolResult.fail(f"Unknown tool: {step.tool}")
                failed_count += 1
                continue

            self._steps[i].status = "running"
            self._report(
                status=AgentStatus.RUNNING,
                step_current=i + 1,
                step_total=len(steps),
                message=f"执行: {step.description}",
            )

            MAX_RETRIES = 2
            last_result: Optional[ToolResult] = None

            for attempt in range(MAX_RETRIES + 1):
                try:
                    if self._needs_rate_limit(tool.name):
                        while not self._sandbox.llm_rate.acquire():
                            await asyncio.sleep(0.05)
                            if self._cancelled:
                                break

                    result = await tool.execute(**step.args)

                    if self._needs_rate_limit(tool.name):
                        self._sandbox.llm_rate.release()

                    if result.success:
                        if result.data and isinstance(result.data, str):
                            result.data = self._sandbox.content.sanitize(result.data)
                        tokens = result.tokens_used or 0
                        self._sandbox.budget.consume_tokens(tokens)
                        logger.info(
                            f"[AgentRuntime] step {i} success consume_tokens={tokens} "
                            f"budget_used={self._sandbox.budget.tokens_used}"
                        )
                        self._steps[i].result = result
                        self._steps[i].status = "done"
                        results[step.tool] = result.data
                        completed_count += 1
                        last_result = None
                        break

                    last_result = result
                    if attempt < MAX_RETRIES:
                        logger.warning(
                            f"[AgentRuntime] step {i} ({step.tool}) failed (attempt {attempt+1}/{MAX_RETRIES+1}): {result.error}")
                        await asyncio.sleep(0.5 * (attempt + 1))

                except Exception as e:
                    logger.warning(
                        f"[AgentRuntime] step {i} ({step.tool}) exception (attempt {attempt+1}/{MAX_RETRIES+1}): {e}")
                    last_result = ToolResult.fail(str(e))
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(0.5 * (attempt + 1))

            if last_result is not None:
                self._steps[i].result = last_result
                self._steps[i].status = "failed"
                failed_count += 1

            self._report(
                status=AgentStatus.RUNNING,
                step_current=i + 1,
                step_total=len(steps),
                tokens_used=self._sandbox.budget.tokens_used,
                elapsed_sec=self._sandbox.budget.elapsed,
            )

        self._sandbox.budget.finish()

        # 3. Finalize
        logger.info(
            f"[AgentRuntime] loop done completed={completed_count} failed={failed_count} "
            f"total={len(steps)} cancelled={self._cancelled} "
            f"budget_exhausted={self._sandbox.budget.exhausted()} "
            f"tokens_used={self._sandbox.budget.tokens_used}"
        )
        if self._cancelled:
            return WorkflowResult(success=False, steps_completed=completed_count,
                                  steps_total=len(steps), error="cancelled")

        try:
            final = workflow.finalize(results)
            final.steps_completed = completed_count
            final.steps_total = len(steps)
        except Exception as e:
            logger.exception(f"[AgentRuntime] finalize failed: {e}")
            final = WorkflowResult(success=False, steps_completed=completed_count,
                                   steps_total=len(steps), error=str(e))

        if self._status in (AgentStatus.CANCELLED, AgentStatus.FAILED):
            pass
        elif failed_count > 0 and completed_count > 0:
            self._status = AgentStatus.PARTIAL
        elif failed_count > 0:
            self._status = AgentStatus.FAILED
        else:
            self._status = AgentStatus.COMPLETED

        self._report(
            status=self._status,
            step_current=len(steps),
            step_total=len(steps),
            tokens_used=self._sandbox.budget.tokens_used,
            elapsed_sec=self._sandbox.budget.elapsed,
            message=f"完成: {completed_count}/{len(steps)} 步骤成功, {failed_count} 失败",
        )

        return final

    async def _run_agentic(self, workflow: AgenticWorkflow, context: dict) -> WorkflowResult:
        """Agentic 工作流执行 — 逐组件 ReAct 循环"""
        self._cancelled = False
        self._status = AgentStatus.RUNNING
        self._sandbox.budget.start()

        components = context.get("components", [])
        project_summary = context.get("project_summary", "")
        tools_schema = self._tools.to_openai_tools(workflow.get_tool_filter(context))

        # 初始化步骤列表（用于 frontend 展示）
        self._steps = [
            StepProgress(
                step_index=i,
                step_total=len(components),
                description=f"分析组件: {comp.get('name', comp.get('id', f'comp-{i}'))[:40]}",
            )
            for i, comp in enumerate(components)
        ]

        from .tool_calling import agentic_chat, create_strategy
        strategy = create_strategy(multi_db=self._multi_db)

        component_results: list[dict] = []
        total_tokens = 0
        total_turns = 0

        for c_idx, comp in enumerate(components):
            if self._cancelled or self._sandbox.budget.exhausted():
                break

            comp_id = comp.get("id", f"comp-{c_idx}")
            comp_name = comp.get("name", comp_id)

            self._steps[c_idx].status = "running"
            self._report(
                status=AgentStatus.RUNNING,
                step_current=c_idx + 1,
                step_total=len(components),
                message=f"分析组件 {c_idx+1}/{len(components)}: {comp_name[:30]}",
            )

            # 构建单组件消息
            system_prompt = workflow.get_system_prompt(comp, project_summary)
            user_context = comp.get("context", "")
            if not user_context:
                user_context = f"组件ID: {comp_id}\n组件名称: {comp_name}\n组件类型: {comp.get('type', 'community')}"

            messages: list[dict] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_context},
            ]

            final_response: Optional[str] = None
            comp_turns = 0

            for turn in range(workflow.max_turns):
                if self._cancelled or self._sandbox.budget.exhausted():
                    break

                try:
                    response = await asyncio.wait_for(
                        agentic_chat(messages, tools=tools_schema, multi_db=self._multi_db, strategy=strategy),
                        timeout=workflow.max_turn_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[AgentRuntime] comp={comp_id} turn {turn} timeout")
                    if not final_response:
                        final_response = ""
                    break
                except Exception as e:
                    logger.warning(f"[AgentRuntime] comp={comp_id} turn {turn} failed: {e}, retrying...")
                    await asyncio.sleep(1)
                    try:
                        response = await asyncio.wait_for(
                            agentic_chat(messages, tools=tools_schema, multi_db=self._multi_db, strategy=strategy),
                            timeout=workflow.max_turn_timeout,
                        )
                    except Exception as e2:
                        logger.warning(f"[AgentRuntime] comp={comp_id} retry also failed: {e2}")
                        if not final_response:
                            final_response = ""
                        break

                total_tokens += response.tokens_used or 0
                comp_turns = turn + 1

                if not response.tool_calls:
                    final_response = response.content
                    break

                # 执行本轮工具调用
                tool_results: list[dict] = []
                for tc in response.tool_calls[:3]:
                    tool = self._tools.get(tc.name)
                    try:
                        result = await tool.execute(**tc.arguments) if tool else ToolResult.fail(f"Unknown tool: {tc.name}")
                        logger.info(f"[AgentRuntime] agentic tool={tc.name} args={tc.arguments} success={result.success} tokens={result.tokens_used or 0}")
                    except Exception as e:
                        result = ToolResult.fail(str(e))
                    total_tokens += result.tokens_used or 0
                    tool_results.append({
                        "tool_call_id": tc.id or f"call_{comp_idx}_{turn}_{len(tool_results)}",
                        "name": tc.name,
                        "content": str(result.data or result.error or ""),
                    })

                # 追加 tool_calls + tool results 到 messages
                assistant_msg: dict = {"role": "assistant", "content": None}
                if tool_results:
                    assistant_msg["tool_calls"] = [
                        {"id": tr["tool_call_id"], "type": "function",
                         "function": {"name": tr["name"], "arguments": json.dumps(tc.arguments)}}
                        for tr, tc in zip(tool_results, response.tool_calls)
                    ]
                messages.append(assistant_msg)
                for tr in tool_results:
                    messages.append({"role": "tool", "tool_call_id": tr["tool_call_id"],
                                     "content": tr["content"][:2000]})

            # 保存当前组件结果
            self._save_component_result(comp, final_response or "", context)
            comp_success = bool(final_response)
            if not comp_success and comp_turns > 0:
                # 模型执行了工具调用但未返回有效最终输出（如超出上下文窗口）
                # 用最后一条有意义的消息作为回退内容
                fallback_text = self._build_agentic_fallback(comp, messages)
                if fallback_text:
                    final_response = fallback_text
                    comp_success = True
            component_results.append({
                "component_id": comp_id,
                "output_text": final_response or "",
                "turns": comp_turns,
                "success": comp_success,
            })
            total_turns += comp_turns

            self._steps[c_idx].status = "done" if comp_success else "failed"

        self._sandbox.budget.finish()
        self._sandbox.budget.consume_tokens(total_tokens)

        if self._cancelled:
            return WorkflowResult(success=False, error="cancelled")

        try:
            final = workflow.finalize({"component_results": component_results})
            final.steps_total = len(components)
        except Exception as e:
            logger.exception(f"[AgentRuntime] agentic finalize failed: {e}")
            final = WorkflowResult(success=False, error=str(e))

        self._status = AgentStatus.COMPLETED if final.success else AgentStatus.FAILED
        self._report(
            status=self._status,
            step_current=len(components),
            step_total=len(components),
            message=f"完成: {len(components)} 组件, {total_turns} 轮",
        )
        return final

    def _save_component_result(self, component: dict, output: str, context: dict):
        """保存单个组件的分析结果到 DB"""
        save_fn = context.get("_save_fn")
        if not save_fn:
            return
        if not output:
            # 模型未返回有效输出（空内容），保存 failed 状态使前端可见
            try:
                cid = component.get("id") or ""
                if cid:
                    save_fn({
                        "task_id": context.get("task_id", ""),
                        "component_id": cid,
                        "component_type": component.get("type", "community"),
                        "analyzed_name": component.get("name", cid),
                        "functional_summary": "",
                        "status": "failed",
                    })
            except Exception:
                pass
            return
        try:
            text = output.strip()
            for fence in ("```", "`"):
                if text.startswith(fence):
                    rest = text[len(fence):].strip()
                    if rest.lower().startswith("json"):
                        rest = rest[4:].strip()
                    text = rest.rstrip(fence).strip()
                    break
            parsed = json.loads(text)
            item = parsed
            if isinstance(item, dict) and "components" in item:
                items = item["components"]
                if isinstance(items, list) and items:
                    item = items[0]
            if isinstance(item, list) and item:
                item = item[0]
            if isinstance(item, dict) and item.get("name"):
                cid = component.get("id") or item.get("component_id") or item.get("id") or ""
                save_fn({
                    "task_id": context.get("task_id", ""),
                    "component_id": cid,
                    "component_type": component.get("type", "community"),
                    "analyzed_name": item.get("name", ""),
                    "functional_summary": item.get("summary") or item.get("functional_summary", ""),
                    "status": "completed",
                })
                return
        except Exception:
            pass
        # JSON 解析失败 → 回退：将 LLM 文本作为 summary 保存
        try:
            cid = component.get("id") or component.get("component_id", "")
            if cid:
                save_fn({
                    "task_id": context.get("task_id", ""),
                    "component_id": cid,
                    "component_type": component.get("type", "community"),
                    "analyzed_name": component.get("name", ""),
                    "functional_summary": output[:2000],
                    "status": "completed",
                })
        except Exception as e:
            logger.warning(f"[AgentRuntime] save failed for {cid}: {e}")

    def _build_agentic_fallback(self, component: dict, messages: list[dict]) -> str:
        """当 LLM 未返回有效最终输出时，从已执行的工具调用中构建回退摘要"""
        cname = component.get("name", component.get("id", ""))
        metadata = component.get("metadata", {})
        node_count = metadata.get("nodeCount", metadata.get("node_count", "?"))
        file_count = metadata.get("fileCount", metadata.get("file_count", "?"))
        # 收集已读文件路径
        read_files: list[str] = []
        for msg in reversed(messages):
            if msg.get("role") == "tool":
                try:
                    content = msg.get("content", "")
                    if content and "file_path" not in msg:
                        pass
                except Exception:
                    pass
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    if fn.get("name") == "read_file":
                        try:
                            args = json.loads(fn.get("arguments", "{}"))
                            fp = args.get("path", "")
                            if fp:
                                read_files.append(fp)
                        except Exception:
                            pass
        files_preview = "\n".join(f"- `{f}`" for f in read_files[:10])
        parts = [
            f"组件: {cname}",
            f"分析状态: 已执行 {len(read_files)} 次文件读取，但 LLM 未返回结构化分析结果",
        ]
        if files_preview:
            parts.append(f"\n已读取的文件:\n{files_preview}")
        return "\n".join(parts)

    @property
    def status(self) -> AgentStatus:
        return self._status

    @property
    def steps(self) -> list[StepProgress]:
        return self._steps

    def _report(self, **kwargs):
        if self._on_progress:
            progress = AgentProgress(
                status=kwargs.get("status", self._status),
                steps=self._steps,
                step_current=kwargs.get("step_current", 0),
                step_total=kwargs.get("step_total", 0),
                tokens_used=kwargs.get("tokens_used", self._sandbox.budget.tokens_used),
                elapsed_sec=kwargs.get("elapsed_sec", self._sandbox.budget.elapsed),
                message=kwargs.get("message", ""),
            )
            try:
                self._on_progress(progress)
            except Exception as e:
                logger.warning(f"[AgentRuntime] on_progress callback error: {e}")

    @staticmethod
    def _needs_rate_limit(tool_name: str) -> bool:
        """判断工具是否需要 LLM 速率限制"""
        # generate_* 和 analyze_* 类工具需要 LLM 调用
        return any(tool_name.startswith(p) for p in ("generate_", "analyze_", "summarize_"))
