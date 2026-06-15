"""
ArchSentinel — 架构哨兵工作流。

四路径统一触发架构变更追踪:
  GUI [开始追踪] / MCP skill / CLI track start / 三方 MCP tool
      → AgentRuntime.start(ArchSentinel) → 记录快照 vN
  ... 用户编码 ...
  GUI [结束追踪] / MCP skill / CLI track stop / 三方 MCP tool
      → AgentRuntime.stop(ArchSentinel) → diff v(N-1)→vN → LLM 摘要

持久化由 startArchTrack / stopArchTrack 同步写入 arch_timeline 表完成，
Agent 工作流仅负责 diff + LLM 摘要生成。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from ..tools import AgentTool, ToolResult
from ..workflows.base import AgentWorkflow, AgentStep, WorkflowResult

logger = logging.getLogger(__name__)


class _DiffTool(AgentTool):
    """对比两个版本的架构差异"""

    name = "diff_architecture"
    description = "对比当前架构与历史快照，计算新增/删除/变更的社区"
    category = "analysis"

    def __init__(self, diff_engine: Any = None):
        self._diff = diff_engine

    async def execute(self, previous_communities: list[dict],
                      current_communities: list[dict], **kwargs) -> ToolResult:
        try:
            prev_map = {c.get("communityId") or c.get("comm_id", ""): c for c in previous_communities}
            curr_map = {c.get("communityId") or c.get("comm_id", ""): c for c in current_communities}

            prev_ids = set(prev_map.keys())
            curr_ids = set(curr_map.keys())

            added = [curr_map[cid] for cid in (curr_ids - prev_ids)]
            removed = [prev_map[cid] for cid in (prev_ids - curr_ids)]
            changed = []
            unchanged = []

            for cid in (prev_ids & curr_ids):
                prev_c = prev_map[cid]
                curr_c = curr_map[cid]
                if (prev_c.get("node_count") != curr_c.get("node_count") or
                    abs(prev_c.get("quality_score", 0) - curr_c.get("quality_score", 0)) > 0.01):
                    changed.append({
                        "communityId": cid,
                        "prev_nodes": prev_c.get("node_count", 0),
                        "curr_nodes": curr_c.get("node_count", 0),
                        "prev_score": prev_c.get("quality_score", 0),
                        "curr_score": curr_c.get("quality_score", 0),
                    })
                else:
                    unchanged.append(curr_c)

            risk = "low"
            if len(removed) > 0:
                risk = "high"
            elif len(added) > 5 or len(changed) > len(curr_ids) * 0.3:
                risk = "medium"

            return ToolResult.ok(data={
                "added": [a["communityId"] for a in added],
                "removed": [r["communityId"] for r in removed],
                "changed": changed,
                "unchanged": len(unchanged),
                "risk": risk,
                "added_count": len(added),
                "removed_count": len(removed),
                "changed_count": len(changed),
            })
        except Exception as e:
            logger.warning(f"[ArchSentinel] diff failed: {e}")
            return ToolResult.fail(str(e))


class _SummarizeTool(AgentTool):
    """LLM 生成变更摘要"""

    name = "summarize_changes"
    description = "基于 diff 数据，调用 LLM 生成人类可读的架构变更摘要"
    category = "analysis"

    def __init__(self, llm_chat_fn: Callable, render_prompt: Callable = None):
        self._chat = llm_chat_fn
        self._render = render_prompt

    async def execute(self, diff_data: dict, from_version: str = "",
                      to_version: str = "", **kwargs) -> ToolResult:
        try:
            if self._render:
                messages = self._render("agent_summarize_changes", {
                    "from_version": from_version, "to_version": to_version,
                    "added_count": str(diff_data.get('added_count', 0)),
                    "removed_count": str(diff_data.get('removed_count', 0)),
                    "changed_count": str(diff_data.get('changed_count', 0)),
                    "risk": diff_data.get('risk', 'unknown'),
                    "diff_detail": str(diff_data)[:4000],
                })
            else:
                messages = [
                    {"role": "system", "content": (
                        "你是架构变更分析专家。根据 diff 数据生成简洁的变更摘要。"
                        "用中文，控制在 300 字以内。"
                    )},
                    {"role": "user", "content": (
                        f"从 {from_version} 到 {to_version} 的架构变化:\n"
                        f"新增: {diff_data.get('added_count', 0)} 个社区\n"
                        f"删除: {diff_data.get('removed_count', 0)} 个社区\n"
                        f"变更: {diff_data.get('changed_count', 0)} 个社区\n"
                        f"风险: {diff_data.get('risk', 'unknown')}\n"
                        f"详情: {str(diff_data)[:4000]}"
                    )},
                ]
            resp = await self._chat(messages, temperature=0.3, max_tokens=500)
            summary = resp if isinstance(resp, str) else resp.get("content", str(resp))
            tokens = resp.get("usage", {}).get("total_tokens", 0) if isinstance(resp, dict) else 0

            return ToolResult.ok(data=summary, tokens_used=tokens)
        except Exception as e:
            logger.warning(f"[ArchSentinel] summarize failed: {e}")
            return ToolResult.fail(str(e))


# ────────────────────── 工作流 ──────────────────────

class ArchSentinelWorkflow(AgentWorkflow):
    """架构变更追踪工作流"""

    name = "arch_sentinel"
    description = "架构哨兵 — 捕获快照、对比差异、生成变更摘要"

    def plan(self, context: dict) -> list[AgentStep]:
        action = context.get("action", "start")

        if action == "start":
            return [AgentStep(
                tool="diff_architecture",
                args={
                    "previous_communities": [],
                    "current_communities": context.get("communities", []),
                },
                description=f"对比架构差异: {context.get('version_id', '')}",
            )]

        elif action == "stop":
            return [
                AgentStep(
                    tool="diff_architecture",
                    args={
                        "previous_communities": context.get("previous_communities", []),
                        "current_communities": context.get("communities", []),
                    },
                    description="对比架构差异",
                ),
                AgentStep(
                    tool="summarize_changes",
                    args={
                        "from_version": context.get("previous_version", ""),
                        "to_version": context.get("version_id", ""),
                    },
                    description="LLM 生成变更摘要",
                ),
            ]

        return []

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        summary = results.get("summarize_changes", "")
        diff = results.get("diff_architecture", {})

        version = (
            results.get("snapshot_architecture", {}).get("version", "?")
            if isinstance(results.get("snapshot_architecture"), dict)
            else "?"
        )
        risk = diff.get("risk", "low") if isinstance(diff, dict) else "low"

        return WorkflowResult(
            success=True,
            data={
                "summary": summary,
                "diff": diff,
            },
            summary=f"架构变更追踪完成 (风险: {risk})",
        )
