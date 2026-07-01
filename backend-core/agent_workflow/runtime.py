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
import os
import threading
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
    file_count: int = 0        # 该步骤包含的文件数（预摘要批量时 >1）
    retries_used: int = 0      # 实际重试次数
    last_error: str = ""       # 最后一次错误信息（失败时）


@dataclass
class AgentProgress:
    """Agent 整体进度（传递给回调）"""

    status: AgentStatus
    steps: list[StepProgress] = field(default_factory=list)
    step_current: int = 0
    step_total: int = 0
    file_current: int = 0      # 已处理文件数
    file_total: int = 0        # 总文件数
    tokens_used: int = 0
    elapsed_sec: float = 0.0
    message: str = ""
    failed_count: int = 0      # 失败的 step 数
    retry_count: int = 0       # 累计重试次数


ProgressCallback = Callable[[AgentProgress], None]


def _is_low_quality_content(content: str) -> bool:
    """检测模型输出的极端低质量内容（空白/纯符号/字符重复）"""
    if not content:
        return True
    txt = content.strip()
    if len(txt) < 3:
        return True
    # 1. 纯符号/无实际文字（检查是否包含中英文或数字字符）
    has_word_char = any(
        'a' <= c <= 'z' or 'A' <= c <= 'Z' or '0' <= c <= '9'
        or '\u4e00' <= c <= '\u9fff' for c in txt
    )
    if not has_word_char:
        return True
    # 2. 单一字符占比 >=50%（可识别 \"aaaa...\" 或 \"好的好的...\"）
    if len(txt) > 10:
        most_common = max(txt.count(c) for c in set(txt))
        if most_common / len(txt) >= 0.5:
            return True
    return False


class AgentRuntime:
    """Agent 运行时引擎"""

    def __init__(
        self,
        tools: ToolRegistry,
        sandbox: AgentSandbox,
        memory: Optional[AgentMemory] = None,
        on_progress: Optional[ProgressCallback] = None,
        on_state_change: Optional[Callable[[str], None]] = None,
        multi_db: Optional[Any] = None,
    ):
        self._tools = tools
        self._sandbox = sandbox
        self._memory = memory or AgentMemory()
        self._on_progress = on_progress
        self._on_state_change = on_state_change
        self._multi_db = multi_db
        self._cancelled = False
        self._paused = False
        self._cancel_event = threading.Event()
        self._pause_event = threading.Event()
        self._status = AgentStatus.IDLE
        self._actually_paused = False  # True only when runtime is in the pause loop
        self._task_id = ""
        self._steps: list[StepProgress] = []
        self._tool_call_history: list[tuple] = []
        self._loop_warning_count: int = 0
        self._content_warning_count: int = 0

    def _detect_tool_call_loop(self, tool_calls: list, max_repeat: int = 3) -> bool:
        """检测连续 N 轮相同的工具调用组合"""
        sig = tuple(
            (tc.name, tuple(sorted(tc.arguments.items())))
            for tc in sorted(tool_calls, key=lambda t: t.name)
        )
        self._tool_call_history.append(sig)
        if len(self._tool_call_history) > max_repeat:
            self._tool_call_history = self._tool_call_history[-max_repeat:]
            return all(s == sig for s in self._tool_call_history)
        return False

    def _reset_detection_state(self):
        """重置检测状态（每组件循环开始时调用）"""
        self._tool_call_history.clear()
        self._loop_warning_count = 0
        self._content_warning_count = 0

    def cancel(self):
        """取消当前执行。状态在运行时实际退出循环后由 on_state_change 通知。"""
        self._cancelled = True
        self._cancel_event.set()
        logger.info("[AgentRuntime] cancelled by user (flag set)")

    def _sync_cancel(self):
        """将 threading.Event 同步到 boolean 标志（跨线程安全）。"""
        if self._cancel_event.is_set():
            self._cancelled = True

    def pause(self):
        """暂停当前执行（在下一步/轮边界生效）。状态在进入暂停循环后由 on_state_change 通知。"""
        self._paused = True
        self._pause_event.set()
        self._actually_paused = False
        logger.info("[AgentRuntime] paused by user (flag set)")

    def resume(self):
        """恢复暂停的执行"""
        self._paused = False
        self._pause_event.clear()
        self._actually_paused = False
        logger.info("[AgentRuntime] resumed by user")

    def _notify_state(self, state: str):
        """通过 on_state_change 回调通知外部当前状态变化（仅在实际进入/离开暂停时调用）。"""
        if self._on_state_change:
            try:
                self._on_state_change(state)
            except Exception as e:
                logger.warning(f"[AgentRuntime] on_state_change callback error: {e}")

    async def run(self, workflow: AgentWorkflow, context: dict) -> WorkflowResult:
        """
        执行一个工作流。

        Args:
            workflow: 工作流实例（AgentWorkflow → 顺序执行，AgenticWorkflow → ReAct 循环）
            context: 上下文 dict（来自 AnalysisContext 或调用方）

        Returns:
            WorkflowResult
        """
        self._task_id = context.get("task_id", "") or ""
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

        self._steps = []
        file_total = 0
        for i, s in enumerate(steps):
            fc = len(s.args.get("path", [])) if s.args else 0
            self._steps.append(StepProgress(
                step_index=i, step_total=len(steps), description=s.description,
                file_count=fc,
            ))
            file_total += fc

        # 2. Execute each step
        self._status = AgentStatus.RUNNING
        results: dict[str, Any] = {}
        completed_count = 0
        failed_count = 0
        retry_count = 0
        file_current = 0

        for i, step in enumerate(steps):
            self._sync_cancel()
            if self._cancelled:
                break
            if self._pause_event.is_set() and not self._actually_paused:
                self._actually_paused = True
                self._notify_state("paused")
            while self._pause_event.is_set():
                await asyncio.sleep(0.2)
                self._sync_cancel()
                if self._cancelled:
                    break
            if self._actually_paused:
                self._actually_paused = False
                self._notify_state("running")

                self._sync_cancel()
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
            tool.cancel_event = self._cancel_event

            self._steps[i].status = "running"
            self._report(
                status=AgentStatus.RUNNING,
                step_current=i + 1,
                step_total=len(steps),
                message=f"执行: {step.description}",
            )

            MAX_RETRIES = 2
            last_result: Optional[ToolResult] = None
            step_retries = 0

            for attempt in range(MAX_RETRIES + 1):
                try:
                    if attempt > 0:
                        step_retries += 1
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
                        self._steps[i].retries_used = step_retries
                        # 工具返回了子进度摘要 → 更新步骤描述
                        if result.data and isinstance(result.data, dict) and result.data.get("summary"):
                            self._steps[i].description = result.data["summary"]
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
                    step_retries += 1
                    logger.warning(
                        f"[AgentRuntime] step {i} ({step.tool}) exception (attempt {attempt+1}/{MAX_RETRIES+1}): {e}")
                    last_result = ToolResult.fail(str(e))
                    if attempt < MAX_RETRIES:
                        await asyncio.sleep(0.5 * (attempt + 1))

            self._steps[i].retries_used = step_retries
            retry_count += step_retries
            if last_result is not None:
                self._steps[i].result = last_result
                self._steps[i].status = "failed"
                self._steps[i].last_error = last_result.error or ""
                failed_count += 1

            file_current += self._steps[i].file_count

            self._report(
                status=AgentStatus.RUNNING,
                step_current=i + 1,
                step_total=len(steps),
                file_current=file_current,
                file_total=file_total,
                tokens_used=self._sandbox.budget.tokens_used,
                elapsed_sec=self._sandbox.budget.elapsed,
                message=f"{self._steps[i].description}",
                failed_count=failed_count,
                retry_count=retry_count,
            )

        # 从 SubAgent 类级别读取预摘要文件失败数（绕过编译版 SummarizeFileTool）
        if context.get("task_id"):
            try:
                from .sub_agent import SubAgent
                ff = SubAgent.get_failed(context["task_id"])
                if ff:
                    workflow._file_failed = ff
            except Exception:
                pass

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
            failed_count=failed_count,
            retry_count=retry_count,
        )

        return final

    async def _run_agentic_chat(self, messages, tools_schema, strategy, timeout):
        """运行 agentic_chat，每 2s 轮询 self._cancelled / self._paused。"""
        from .tool_calling import agentic_chat
        chat_task = asyncio.create_task(
            agentic_chat(messages, tools=tools_schema, multi_db=self._multi_db, strategy=strategy)
        )
        remaining = timeout
        try:
            while remaining > 0:
                self._sync_cancel()
                if self._cancelled:
                    chat_task.cancel()
                    raise asyncio.CancelledError("cancelled by user")
                if self._pause_event.is_set():
                    # LLM 请求在后台继续，但暂停等待
                    if self._pause_event.is_set() and not self._actually_paused:
                        self._actually_paused = True
                        self._notify_state("paused")
                    while self._pause_event.is_set():
                        await asyncio.sleep(0.2)
                        self._sync_cancel()
                        if self._cancelled:
                            chat_task.cancel()
                            raise asyncio.CancelledError("cancelled by user")
                    if self._actually_paused:
                        self._actually_paused = False
                        self._notify_state("running")
                    # 恢复后重新计算剩余超时
                    remaining = min(remaining, timeout)
                done, _ = await asyncio.wait([chat_task], timeout=min(2.0, remaining))
                if done:
                    return chat_task.result()
                remaining -= 2.0
            chat_task.cancel()
            raise asyncio.TimeoutError()
        except asyncio.CancelledError:
            chat_task.cancel()
            raise

    async def _run_agentic(self, workflow: AgenticWorkflow, context: dict) -> WorkflowResult:
        """Agentic 工作流执行 — 逐组件 ReAct 循环"""
        self._cancelled = False
        self._status = AgentStatus.RUNNING
        self._sandbox.budget.start()

        components = context.get("components", [])
        project_summary = context.get("project_summary", "")
        effective_max_turns = context.get("max_turns", workflow.max_turns)
        analysis_mode = context.get("analysis_mode", "quick")
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
            self._sync_cancel()
            if self._cancelled:
                break
            if self._pause_event.is_set() and not self._actually_paused:
                self._actually_paused = True
                self._notify_state("paused")
            while self._pause_event.is_set():
                await asyncio.sleep(0.2)
                self._sync_cancel()
                if self._cancelled:
                    break
            if self._actually_paused:
                self._actually_paused = False
                self._notify_state("running")
            self._sync_cancel()
            if self._cancelled:
                break
            self._sandbox.budget.reset()

            comp_id = comp.get("id", f"comp-{c_idx}")
            comp_name = comp.get("name", comp_id)
            self._reset_detection_state()

            self._steps[c_idx].status = "running"
            self._report(
                status=AgentStatus.RUNNING,
                step_current=c_idx + 1,
                step_total=len(components),
                message=f"分析组件 {c_idx+1}/{len(components)}: {comp_name[:30]}",
            )

            # 构建单组件消息
            system_prompt = workflow.get_system_prompt(comp, project_summary,
                                                        detail_level=analysis_mode)
            user_context = comp.get("context", "")
            if not user_context:
                user_context = f"组件ID: {comp_id}\n组件名称: {comp_name}\n组件类型: {comp.get('type', 'community')}"

            messages: list[dict] = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_context},
            ]

            final_response: Optional[str] = None
            comp_turns = 0

            for turn in range(effective_max_turns):
                self._sync_cancel()
                if self._pause_event.is_set() and not self._actually_paused:
                    self._actually_paused = True
                    self._notify_state("paused")
                while self._pause_event.is_set():
                    await asyncio.sleep(0.2)
                    self._sync_cancel()
                    if self._cancelled:
                        break
                if self._actually_paused:
                    self._actually_paused = False
                    self._notify_state("running")
                self._sync_cancel()
                if self._cancelled or self._sandbox.budget.exhausted():
                    break

                try:
                    response = await self._run_agentic_chat(
                        messages, tools_schema, strategy, workflow.max_turn_timeout,
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"[AgentRuntime] comp={comp_id} turn {turn} timeout")
                    if not final_response:
                        final_response = ""
                    break
                except asyncio.CancelledError:
                    logger.info(f"[AgentRuntime] comp={comp_id} turn {turn} cancelled")
                    break
                except Exception as e:
                    logger.warning(f"[AgentRuntime] comp={comp_id} turn {turn} failed: {e}, retrying...")
                    await asyncio.sleep(1)
                    try:
                        response = await self._run_agentic_chat(
                            messages, tools_schema, strategy, workflow.max_turn_timeout,
                        )
                    except asyncio.CancelledError:
                        logger.info(f"[AgentRuntime] comp={comp_id} turn {turn} cancelled (retry)")
                        break
                    except Exception as e2:
                        logger.warning(f"[AgentRuntime] comp={comp_id} retry also failed: {e2}")
                        if not final_response:
                            final_response = ""
                        break

                total_tokens += response.tokens_used or 0
                comp_turns = turn + 1

                # ── 死循环检测 ──
                if response.tool_calls:
                    if self._detect_tool_call_loop(response.tool_calls):
                        self._loop_warning_count += 1
                        if self._loop_warning_count >= 2:
                            logger.warning(f"[AgentRuntime] comp={comp_id} 工具死循环，强制退出")
                            final_response = self._build_agentic_fallback(comp, messages)
                            break
                        logger.info(f"[AgentRuntime] comp={comp_id} 工具死循环，推送提醒")
                        messages.append({
                            "role": "user",
                            "content": "你在重复相同的工具调用。请根据已有结果直接输出最终 JSON 分析结果。"
                        })
                        continue
                # ── 低质量内容检测 ──
                elif response.content and _is_low_quality_content(response.content):
                    self._content_warning_count += 1
                    if self._content_warning_count >= 2:
                        logger.warning(f"[AgentRuntime] comp={comp_id} 连续低质量内容，强制退出")
                        final_response = self._build_agentic_fallback(comp, messages)
                        break
                    logger.info(f"[AgentRuntime] comp={comp_id} 低质量内容，推送提醒")
                    messages.append({
                        "role": "user",
                        "content": "请输出有意义的分析内容，不要输出空白或重复字符。"
                    })
                    continue

                if not response.tool_calls:
                    if response.content:
                        final_response = response.content
                        break
                    # 模型返回空内容 + 无工具调用 → 引导输出 JSON（最多引导 1 次）
                    if turn < effective_max_turns - 1:
                        logger.info(f"[AgentRuntime] comp={comp_id} push: 引导输出 JSON")
                        messages.append({
                            "role": "user",
                            "content": "请根据已有的所有工具结果，直接输出最终 JSON 分析结果。"
                        })
                        continue
                    final_response = ""
                    break

                # 最后一轮：不执行工具，用已有 content（可能为空）退出
                if turn == effective_max_turns - 1:
                    logger.info(f"[AgentRuntime] comp={comp_id} 最后一轮，忽略工具调用")
                    final_response = response.content or ""
                    break

                # 执行本轮工具调用
                tool_results: list[dict] = []
                for tc in response.tool_calls[:3]:
                    tool = self._tools.get(tc.name)
                    if tool:
                        tool.cancel_event = self._cancel_event
                    # 防御性参数修复：XML fallback 解析可能将数组保留为 JSON 字符串
                    sanitized = {}
                    for k, v in tc.arguments.items():
                        if isinstance(v, str):
                            try:
                                parsed = json.loads(v)
                                if isinstance(parsed, (list, dict)):
                                    sanitized[k] = parsed
                                    continue
                            except Exception:
                                pass
                        sanitized[k] = v
                    try:
                        result = await tool.execute(**sanitized) if tool else ToolResult.fail(f"Unknown tool: {tc.name}")
                        logger.info(f"[AgentRuntime] agentic tool={tc.name} args={tc.arguments} success={result.success} tokens={result.tokens_used or 0}")
                        if result.success and result.data and isinstance(result.data, str):
                            result.data = self._sandbox.content.sanitize(result.data)
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

                # 倒数第二轮：追加提醒，让模型在最后一轮直接输出 JSON
                if turn == effective_max_turns - 2:
                    logger.info(f"[AgentRuntime] comp={comp_id} 最后一轮提醒")
                    messages.append({
                        "role": "user",
                        "content": "这是最后一轮。请根据已有的所有信息，直接输出最终 JSON 分析结果，不要再调用工具。"
                    })

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
            logger.warning("[AgentRuntime] _save_component_result: no _save_fn in context, skipping")
            return
        if not output:
            logger.warning("[AgentRuntime] _save_component_result: output empty, saving failed status")
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
                    logger.info(f"[AgentRuntime] _save_component_result: saved failed status for {cid}")
            except Exception as e:
                logger.warning(f"[AgentRuntime] _save_component_result: save failed status error: {e}")
            return
        try:
            text = output.strip()
            # 剥离 markdown 代码块标记
            if text.startswith("```"):
                lines = text.split("\n")
                text = "\n".join(lines[1:]) if len(lines) > 1 else text
                if text.endswith("```"):
                    text = text[:-3]
                text = text.strip()
            if text.startswith("json"):
                text = text[4:].strip()
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
                # 构建含关键文件和依赖的增强摘要
                raw_summary = item.get("summary") or item.get("functional_summary") or ""
                role = item.get("role", "")
                kf = item.get("key_files", [])
                deps = item.get("depends_on", [])
                summary_parts = [f"## 功能概要\n{raw_summary}"]
                if role:
                    summary_parts.append(f"\n**架构角色**: {role}")
                if kf:
                    files_lines = []
                    for f in kf[:10]:
                        if isinstance(f, dict):
                            fp = f.get("path", f.get("file", ""))
                            fs = f.get("summary", "")
                            if fp and fs:
                                files_lines.append(f"- `{fp}` — {fs}")
                            elif fp:
                                files_lines.append(f"- `{fp}`")
                        elif isinstance(f, str):
                            files_lines.append(f"- `{f}`")
                    if files_lines:
                        summary_parts.append(f"\n**关键文件**:\n" + "\n".join(files_lines))
                if deps:
                    deps_md = ", ".join(deps[:10])
                    summary_parts.append(f"\n**依赖组件**: {deps_md}")
                enhanced_summary = "\n".join(summary_parts)
                save_fn({
                    "task_id": context.get("task_id", ""),
                    "component_id": cid,
                    "component_type": component.get("type", "community"),
                    "analyzed_name": item.get("name", ""),
                    "functional_summary": enhanced_summary,
                    "status": "completed",
                })
                logger.info(f"[AgentRuntime] _save_component_result: JSON save OK for {cid}, name={item.get('name', '')[:30]}")
                return
            else:
                logger.warning(f"[AgentRuntime] _save_component_result: parsed JSON lacks 'name': {item}")

        except Exception as e:
            logger.warning(f"[AgentRuntime] _save_component_result: JSON parse failed: {e}")
            # 尝试从推理文本中正则提取 JSON
            try:
                import re
                for pattern in [r'(\{.*\})', r'(\[.*\])']:
                    match = re.search(pattern, text, re.DOTALL)
                    if match:
                        candidate = match.group(1)
                        parsed = json.loads(candidate)
                        item = parsed
                        if isinstance(item, list) and item:
                            item = item[0]
                        if isinstance(item, dict) and item.get("name"):
                            cid = component.get("id") or item.get("component_id") or item.get("id") or ""
                            raw_summary = item.get("summary") or item.get("functional_summary") or ""
                            role = item.get("role", "")
                            kf = item.get("key_files", [])
                            deps = item.get("depends_on", [])
                            summary_parts = [f"## 功能概要\n{raw_summary}"]
                            if role:
                                summary_parts.append(f"\n**架构角色**: {role}")
                            if kf:
                                files_lines = []
                                for f in kf[:10]:
                                    if isinstance(f, dict):
                                        fp = f.get("path", f.get("file", ""))
                                        fs = f.get("summary", "")
                                        if fp and fs:
                                            files_lines.append(f"- `{fp}` — {fs}")
                                        elif fp:
                                            files_lines.append(f"- `{fp}`")
                                    elif isinstance(f, str):
                                        files_lines.append(f"- `{f}`")
                                if files_lines:
                                    summary_parts.append(f"\n**关键文件**:\n" + "\n".join(files_lines))
                            if deps:
                                deps_md = ", ".join(deps[:10])
                                summary_parts.append(f"\n**依赖组件**: {deps_md}")
                            enhanced_summary = "\n".join(summary_parts)
                            save_fn({
                                "task_id": context.get("task_id", ""),
                                "component_id": cid,
                                "component_type": component.get("type", "community"),
                                "analyzed_name": item.get("name", ""),
                                "functional_summary": enhanced_summary,
                                "status": "completed",
                            })
                            logger.info(f"[AgentRuntime] _save_component_result: regex extraction OK for {cid}, name={item.get('name', '')[:30]}")
                            return
            except Exception:
                pass
        # JSON 解析失败 → 回退：标记为 failed
        try:
            cid = component.get("id") or component.get("component_id", "")
            if cid:
                save_fn({
                    "task_id": context.get("task_id", ""),
                    "component_id": cid,
                    "component_type": component.get("type", "community"),
                    "analyzed_name": component.get("name", ""),
                    "functional_summary": "",
                    "status": "failed",
                })
                logger.warning(f"[AgentRuntime] _save_component_result: fallback save as failed for {cid}, text_len={len(output)}")
        except Exception as e:
            logger.warning(f"[AgentRuntime] save failed for {cid}: {e}")

    def _build_agentic_fallback(self, component: dict, messages: list[dict]) -> str:
        """当 LLM 未返回有效最终输出时，从已执行的工具调用中构建回退摘要"""
        cname = component.get("name", component.get("id", ""))
        metadata = component.get("metadata", {})
        node_count = metadata.get("nodeCount", metadata.get("node_count", "?"))
        file_count = metadata.get("fileCount", metadata.get("file_count", "?"))
        # 收集已读或已摘要的文件路径
        processed_files: list[str] = []
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc.get("function", {})
                    tname = fn.get("name", "")
                    if tname in ("read_file", "summarize_file"):
                        try:
                            args = json.loads(fn.get("arguments", "{}"))
                            fp = args.get("path", "")
                            if isinstance(fp, list):
                                processed_files.extend(fp)
                            elif isinstance(fp, str):
                                import json as _rj
                                try:
                                    plist = _rj.loads(fp)
                                    if isinstance(plist, list):
                                        processed_files.extend(plist)
                                    else:
                                        processed_files.append(fp)
                                except Exception:
                                    processed_files.append(fp)
                        except Exception:
                            pass
        # 去重
        seen = set()
        unique_files = []
        for f in processed_files:
            norm = os.path.basename(f)
            if norm not in seen:
                seen.add(norm)
                unique_files.append(f)
        files_preview = "\n".join(f"- `{f}`" for f in unique_files[:10])
        parts = [
            f"组件: {cname}",
            f"分析状态: 已处理 {len(unique_files)} 个文件，但 LLM 未返回结构化分析结果",
        ]
        if files_preview:
            parts.append(f"\n已处理文件:\n{files_preview}")
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
                file_current=kwargs.get("file_current", 0),
                file_total=kwargs.get("file_total", 0),
                tokens_used=kwargs.get("tokens_used", self._sandbox.budget.tokens_used),
                elapsed_sec=kwargs.get("elapsed_sec", self._sandbox.budget.elapsed),
                message=kwargs.get("message", ""),
                failed_count=kwargs.get("failed_count", 0),
                retry_count=kwargs.get("retry_count", 0),
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
