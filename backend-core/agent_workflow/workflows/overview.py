from __future__ import annotations

import logging
from typing import Any

from ..llm_adapter import create_llm_chat_fn
from ..tools import AgentTool, ToolResult
from ..workflows.base import AgentWorkflow, AgentStep, WorkflowResult
from ..skill_registry import register_skill

logger = logging.getLogger(__name__)


@register_skill(
    name="skill_generate_arch_overview",
    description="Generate overall architecture overview document",
    steps=3,
    category="analysis",
)


class _GenerateOverviewTool(AgentTool):
    """Generate overall architecture overview — preload community results + file summaries, single LLM call"""

    name = "generate_overview"
    description = "Generate overall architecture overview Markdown based on project context, community analysis results and file summaries"
    category = "analysis"

    def __init__(self, multi_db, project_db, task_id):
        self._multi_db = multi_db
        self._project_db = project_db
        self._task_id = task_id

    def _format_comm(self, rows: list, label: str) -> str:
        from collections import Counter
        total = len(rows)
        # Filter: skip rows where name/summary is empty
        valid = [r for r in rows if r.get("name") and r.get("summary")]
        skipped = total - len(valid)
        if skipped:
            logger.info("[Overview] %s: skipped %d/%d rows (empty name/summary)",
                        label, skipped, total)
        if not valid:
            return ""

        # Level statistics
        lv_counts = Counter(r.get("comm_lv", "?") for r in valid)
        lv_summary = ", ".join(f"{k}={v}" for k, v in sorted(lv_counts.items()))
        logger.info("[Overview] %s: total=%d valid=%d levels=%s",
                    label, total, len(valid), lv_summary)

        # L0/L1 priority, max 25; others max 10
        priority = [r for r in valid if r.get("comm_lv") in ("L0", "L1")][:25]
        others = [r for r in valid if r not in priority][:10]
        selected = priority + others
        remaining = len(valid) - len(selected)

        lines = [f"\n## {label} ({len(valid)} analyzed, levels: {lv_summary})\n"]
        for i, c in enumerate(selected):
            name = (c.get("name") or c.get("comm_id") or f"comm-{i}").strip()
            lv = c.get("comm_lv", "?")
            summary = c.get("summary") or ""
            truncated = len(summary) > 2000
            summary = summary[:2000] + "…" if truncated else summary
            lines.append(f"### {i+1}. {name} (Level: {lv})")
            lines.append(summary)
        if remaining > 0:
            lines.append(f"\n... {remaining} more communities (L2+)")
        return "\n".join(lines)

    async def execute(self, project_name: str = "", project_summary: str = "",
                      language: str = "", **kwargs) -> ToolResult:
        # Get project_id (for file_summaries fallback query)
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
            # ── 1. Load community analysis results ──
            from store.analysis_store import AnalysisStore
            store = AnalysisStore(self._project_db)
            communities_include = store.list_llm_results(self._task_id, "INCLUDE")
            communities_call = store.list_llm_results(self._task_id, "CALL")
            logger.info("[Overview] loaded communities: INCLUDE=%d CALL=%d",
                        len(communities_include), len(communities_call))

            context_parts = [f"# Project: {project_name or '-'}"]
            if project_summary:
                context_parts.append(f"\n## Project Summary\n{project_summary}\n")

            incl_text = self._format_comm(communities_include, "INCLUDE (dependency includes)")
            call_text = self._format_comm(communities_call, "CALL (calls)")
            if incl_text:
                context_parts.append(incl_text)
            if call_text:
                context_parts.append(call_text)
            logger.info("[Overview] context: INCLUDE=%dchars CALL=%dchars",
                        len(incl_text or ""), len(call_text or ""))

            # ── 2. Load file summaries ──
            summary_count = 0
            try:
                ranked = self._project_db.execute(
                    "SELECT file_path FROM source_files ORDER BY size DESC LIMIT 20"
                ).fetchall()
                logger.info("[Overview] source_files top20 count=%d", len(ranked))
                if ranked:
                    paths = [r["file_path"] for r in ranked]
                    placeholders = ",".join("?" * len(paths))
                    # Query by task_id first
                    summaries = self._project_db.execute(
                        f"SELECT file_path, summary FROM file_summaries WHERE task_id=? AND file_path IN ({placeholders}) LIMIT 20",
                        (self._task_id, *paths)
                    ).fetchall()
                    # Fallback: query by project_id
                    if not summaries and _project_id:
                        logger.info("[Overview] file_summaries by task_id=0, fallback to project_id=%s", _project_id)
                        summaries = self._project_db.execute(
                            f"SELECT file_path, summary FROM file_summaries WHERE project_id=? AND file_path IN ({placeholders}) LIMIT 20",
                            (_project_id, *paths)
                        ).fetchall()
                    summary_count = len(summaries)
                    if summaries:
                        context_parts.append("\n## Key File Summaries\n")
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

            # ── 3. LLM generation ──
            from prompt_manager import PromptManager
            pm = PromptManager(self._multi_db)
            lang_instr = pm.get_language_instruction(language)
            llm_fn = create_llm_chat_fn(self._multi_db)
            result = pm.render("agent_generate_overview", {
                "context": context_text,
                "lang_instr": lang_instr,
            })
            messages = result['messages']
            logger.info("[Overview] calling LLM with prompt=%d chars", len(context_text))
            resp = await llm_fn(messages=messages, temperature=0.3, max_tokens=32768)
            overview = resp if isinstance(resp, str) else str(resp or "")
            logger.info("[Overview] LLM response=%d chars", len(overview))
            if overview:
                logger.info("[Overview] content preview: %s...", overview[:200].replace('\n', ' '))
            else:
                logger.warning("[Overview] LLM returned empty content")

            logger.info("[Overview] ToolResult.ok data_len=%d", len(overview))
            return ToolResult.ok(data=overview, tokens_used=len(context_text) // 4 + 1000)
        except Exception as e:
            logger.warning(f"[Overview] failed: {e}")
            return ToolResult.fail(str(e))


class OverviewWorkflow(AgentWorkflow):
    """Overall architecture overview generation workflow — forced Agent mode"""

    name = "overview"
    description = "Generate overall architecture overview document. Agent reads community analysis results, file pre-summaries, source files etc., outputs architecture overview Markdown"

    def plan(self, context: dict) -> list[AgentStep]:
        return [AgentStep(
            tool="generate_overview",
            args={
                "project_name": context.get("project_name", ""),
                "project_summary": context.get("project_summary", ""),
                "language": context.get("language", ""),
            },
            description="Generate overall architecture overview",
        )]

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        overview = results.get("generate_overview", "")
        logger.info("[Overview] finalize results keys=%s overview_len=%d is_empty=%s",
                    list(results.keys()), len(overview), not bool(overview))
        return WorkflowResult(
            success=True,
            data={"overview": overview},
            summary="Architecture overview generation complete",
        )
