from __future__ import annotations

import logging
from typing import Any

from ..llm_adapter import create_llm_chat_fn
from ..tools import AgentTool, ToolResult
from ..workflows.base import AgentWorkflow, AgentStep, WorkflowResult

logger = logging.getLogger(__name__)


class _GenerateOverviewTool(AgentTool):
    """生成整体架构概览 — 预加载社区结果 + 文件摘要，单次 LLM 调用"""

    name = "generate_overview"
    description = "基于项目上下文、社区分析结果和文件摘要，生成整体架构概览 Markdown"
    category = "analysis"

    def __init__(self, multi_db, project_db, task_id):
        self._multi_db = multi_db
        self._project_db = project_db
        self._task_id = task_id

    def _format_comm(self, rows: list, label: str) -> str:
        from collections import Counter
        total = len(rows)
        # 过滤：跳过 name/summary 为空的行
        valid = [r for r in rows if r.get("name") and r.get("summary")]
        skipped = total - len(valid)
        if skipped:
            logger.info("[Overview] %s: skipped %d/%d rows (empty name/summary)",
                        label, skipped, total)
        if not valid:
            return ""

        # 层级统计
        lv_counts = Counter(r.get("comm_lv", "?") for r in valid)
        lv_summary = ", ".join(f"{k}={v}" for k, v in sorted(lv_counts.items()))
        logger.info("[Overview] %s: total=%d valid=%d levels=%s",
                    label, total, len(valid), lv_summary)

        # L0/L1 优先，最多 25 条；其余最多 10 条
        priority = [r for r in valid if r.get("comm_lv") in ("L0", "L1")][:25]
        others = [r for r in valid if r not in priority][:10]
        selected = priority + others
        remaining = len(valid) - len(selected)

        lines = [f"\n## {label} ({len(valid)} 个已分析, 层级: {lv_summary})\n"]
        for i, c in enumerate(selected):
            name = (c.get("name") or c.get("comm_id") or f"comm-{i}").strip()
            lv = c.get("comm_lv", "?")
            summary = c.get("summary") or ""
            truncated = len(summary) > 2000
            summary = summary[:2000] + "…" if truncated else summary
            lines.append(f"### {i+1}. {name} (层级: {lv})")
            lines.append(summary)
        if remaining > 0:
            lines.append(f"\n... 还有 {remaining} 个社区（L2+）")
        return "\n".join(lines)

    async def execute(self, project_name: str = "", project_summary: str = "",
                      **kwargs) -> ToolResult:
        # 获取 project_id（用于 file_summaries 降级查询）
        _project_id = ""
        try:
            row = self._multi_db.main_db.fetchone(
                "SELECT project_id FROM analysis_tasks WHERE id = ?",
                (self._task_id,)
            )
            if row:
                _project_id = row["project_id"] if isinstance(row, dict) else row[0]
        except Exception as e:
            logger.warning(f"[Overview] cannot get project_id: {e}")

        try:
            # ── 1. 加载社区分析结果 ──
            from store.analysis_store import AnalysisStore
            store = AnalysisStore(self._project_db)
            communities_include = store.list_llm_results(self._task_id, "INCLUDE")
            communities_call = store.list_llm_results(self._task_id, "CALL")
            logger.info("[Overview] loaded communities: INCLUDE=%d CALL=%d",
                        len(communities_include), len(communities_call))

            context_parts = [f"# 项目: {project_name or '-'}"]
            if project_summary:
                context_parts.append(f"\n## 项目概要\n{project_summary}\n")

            incl_text = self._format_comm(communities_include, "INCLUDE (依赖包含)")
            call_text = self._format_comm(communities_call, "CALL (调用)")
            if incl_text:
                context_parts.append(incl_text)
            if call_text:
                context_parts.append(call_text)
            logger.info("[Overview] context: INCLUDE=%dchars CALL=%dchars",
                        len(incl_text or ""), len(call_text or ""))

            # ── 2. 加载文件摘要 ──
            summary_count = 0
            try:
                ranked = self._project_db.execute(
                    "SELECT file_path FROM source_files ORDER BY size DESC LIMIT 20"
                ).fetchall()
                logger.info("[Overview] source_files top20 count=%d", len(ranked))
                if ranked:
                    paths = [r["file_path"] for r in ranked]
                    placeholders = ",".join("?" * len(paths))
                    # 先按 task_id 查
                    summaries = self._project_db.execute(
                        f"SELECT file_path, summary FROM file_summaries WHERE task_id=? AND file_path IN ({placeholders}) LIMIT 20",
                        (self._task_id, *paths)
                    ).fetchall()
                    # 降级：按 project_id 查
                    if not summaries and _project_id:
                        logger.info("[Overview] file_summaries by task_id=0, fallback to project_id=%s", _project_id)
                        summaries = self._project_db.execute(
                            f"SELECT file_path, summary FROM file_summaries WHERE project_id=? AND file_path IN ({placeholders}) LIMIT 20",
                            (_project_id, *paths)
                        ).fetchall()
                    summary_count = len(summaries)
                    if summaries:
                        context_parts.append("\n## 关键文件摘要\n")
                        for s in summaries:
                            fp = s["file_path"]
                            text = (s["summary"] or "")[:300]
                            if text:
                                context_parts.append(f"- **{fp}**: {text}")
                    logger.info("[Overview] file_summaries loaded=%d", summary_count)
            except Exception as e:
                logger.warning(f"[Overview] file summaries error: {e}")

            context_text = "\n".join(context_parts)
            logger.info("[Overview] context total=%d chars (communities=%d+%d, files=%d)",
                        len(context_text), len(communities_include), len(communities_call), summary_count)

            # ── 3. LLM 生成 ──
            llm_fn = create_llm_chat_fn(self._multi_db)
            prompt = (
                "你是一个代码架构分析专家。请根据以下项目信息生成一份整体架构概览 Markdown 文档。\n\n"
                "{context}\n\n"
                "请生成一份结构化的架构概览文档，包括：\n"
                "1. 项目整体架构描述（基于社区分析结果总结）\n"
                "2. 核心模块及其职责\n"
                "3. 模块间的分层与依赖关系\n"
                "4. 主要设计模式与架构风格\n\n"
                "要求：\n"
                "- 社区名称已基于代码功能命名，请直接使用这些名称描述各模块\n"
                "- 不得输出原始 comm_id（如 comm-xxx-xxx 格式的 ID）\n"
                "- 每引用一个模块时，请使用其社区名称\n"
                "- 不要使用反引号 ` 包裹模块名称\n"
                "- 请用中文输出。"
            ).format(context=context_text)

            messages = [{"role": "user", "content": prompt}]
            logger.info("[Overview] calling LLM with prompt=%d chars", len(prompt))
            resp = await llm_fn(messages=messages, temperature=0.3, max_tokens=8192)
            overview = resp if isinstance(resp, str) else str(resp or "")
            logger.info("[Overview] LLM response=%d chars", len(overview))

            return ToolResult.ok(data=overview, tokens_used=len(context_text) // 4 + 1000)
        except Exception as e:
            logger.warning(f"[Overview] failed: {e}")
            return ToolResult.fail(str(e))


class OverviewWorkflow(AgentWorkflow):
    """整体架构概览生成工作流 — 强制 Agent 模式"""

    name = "overview"
    description = "生成整体架构概览文档。Agent 可读取社区分析结果、文件预摘要、源码文件等，输出架构总览 Markdown"

    def plan(self, context: dict) -> list[AgentStep]:
        return [AgentStep(
            tool="generate_overview",
            args={
                "project_name": context.get("project_name", ""),
                "project_summary": context.get("project_summary", ""),
            },
            description="生成整体架构概览",
        )]

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        overview = results.get("generate_overview", "")
        return WorkflowResult(
            success=True,
            data={"overview": overview},
            summary="架构概览生成完成",
        )
