"""
ArchAnalyst — 架构分析工作流 (Agent 模式)。

Skill 步骤序列:
  1. 对每个社区: analyze_community (LLM 摘要) + generate_diagram (模板图)
  2. generate_overview (汇总全部结果 + 项目概要 → overview.md)
  3. save_community_results (持久化)
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..tools import AgentTool, ToolResult
from ..workflows.base import AgentWorkflow, AgentStep, WorkflowResult
from ..shared_utils import parse_structured_response, build_markdown_summary

logger = logging.getLogger(__name__)


class _AnalyzeCommunityTool(AgentTool):
    """分析单个社区: LLM 生成名称和功能摘要"""

    name = "analyze_community"
    description = "使用 LLM 分析单个社区模块，生成名称和功能摘要"
    category = "analysis"

    def __init__(self, llm_chat_fn: Callable, render_prompt: Callable = None):
        self._chat = llm_chat_fn
        self._render = render_prompt

    async def execute(self, community: dict, **kwargs) -> ToolResult:
        comm_id = community.get("communityId") or community.get("comm_id", "")
        comm_label = community.get("name") or community.get("label") or comm_id
        project_summary = kwargs.get("project_summary", "")
        ctx = community.get("context", "")
        if not ctx:
            ctx = str(community)
        logger.info(
            f"[ArchAnalyst] analyze_community id={comm_id} ctx_len={len(ctx)} "
            f"has_project_summary={bool(project_summary)} "
            f"ctx_begin={ctx[:500]!r}"
        )
        try:
            if self._render:
                messages = self._render("agent_analyze_community", {
                    "comm_id": comm_id,
                    "context": ctx,
                    "project_summary": project_summary[:1500],
                })
            else:
                system_text = (
                    "你是架构分析专家。基于提供的社区上下文数据（文件列表、关键符号、边关系），"
                    "分析该代码社区模块的功能与架构角色。\n\n"
                    "以 JSON 格式输出，包含以下字段：\n"
                    '- name: 组件名称（≤20字）\n'
                    '- summary: 功能概要（100-300字）\n'
                    '- role: 架构角色（≤3词，如 ConfigLoader / RequestRouter）\n'
                    '- key_files: 关键文件及其功能概要数组（Top 10）\n'
                    '  格式: [{"path": "src/foo.cpp", "summary": "实现矩阵乘法运算"}, ...]\n'
                    '- depends_on: 依赖的其他组件或外部包数组\n'
                    "只输出 JSON，不要其他内容。"
                )
                if project_summary:
                    system_text = f"## 项目背景\n{project_summary[:1500]}\n\n{system_text}"
                messages = [
                    {"role": "system", "content": system_text},
                    {"role": "user", "content": f"社区ID: {comm_id}\n\n{ctx}"},
                ]
            resp = await self._chat(messages=messages, temperature=0.3, max_tokens=1200)
            text = resp if isinstance(resp, str) else str(resp)
            parsed = parse_structured_response(text, comm_id)
            name = parsed.get("name", comm_label[:60])
            summary_text = parsed.get("summary", "")
            role = parsed.get("role", "")
            key_files = parsed.get("key_files", [])
            depends_on = parsed.get("depends_on", [])

            # 构建增强 Markdown summary（嵌入 role + key_files + depends_on）
            enhanced_summary = build_markdown_summary(name, summary_text, role, key_files, depends_on)

            return ToolResult.ok(
                data={
                    "communityId": comm_id,
                    "name": name[:60],
                    "summary": enhanced_summary,
                },
                tokens_used=1200,
            )
        except Exception as e:
            logger.warning(f"[ArchAnalyst] analyze failed for {comm_id}: {e}")
            return ToolResult.fail(str(e), communityId=comm_id)


class _GenerateDiagramTool(AgentTool):
    """模板化生成 Mermaid/PlantUML (无需 LLM)"""

    name = "generate_diagram"
    description = "基于社区结构数据，模板化生成 Mermaid 和 PlantUML 图"
    category = "visualization"

    async def execute(self, community: dict, child_communities: list[dict] = None,
                      edges: list[dict] = None, **kwargs) -> ToolResult:
        comm_id = community.get("communityId") or community.get("comm_id", "")
        comm_label = community.get("name") or community.get("label") or comm_id
        children = child_communities or []
        comm_edges = edges or []

        try:
            mermaid = _build_mermaid(comm_id, comm_label, children, comm_edges)
            plantuml = _build_plantuml(comm_id, comm_label, children, comm_edges)
            return ToolResult.ok(data={"communityId": comm_id, "mermaid": mermaid, "plantuml": plantuml},
                                 tokens_used=0)
        except Exception as e:
            logger.warning(f"[ArchAnalyst] diagram failed for {comm_id}: {e}")
            return ToolResult.fail(str(e), communityId=comm_id)


class _GenerateOverviewTool(AgentTool):
    """生成整体架构概览 (含项目概要 + 社区分析结果)"""

    name = "generate_overview"
    description = "汇总所有社区分析结果，结合项目概要，生成整体架构概览 Markdown"
    category = "analysis"

    def __init__(self, llm_chat_fn: Callable, render_prompt: Callable = None):
        self._chat = llm_chat_fn
        self._render = render_prompt

    async def execute(self, community_results: list[dict], project_name: str = "",
                      project_summary: str = "", project_context: str = "",
                      community_stats: list[dict] = None, **kwargs) -> ToolResult:
        try:
            parts = []
            for r in community_results:
                parts.append(
                    f"### {r.get('name', r.get('communityId', ''))}\n"
                    f"- 节点数: {r.get('nodeCount', '?')}\n"
                    f"- 质量分: {r.get('qualityScore', '?')}\n"
                    f"{r.get('summary', '')}\n"
                )
            comm_text = "\n".join(parts)

            stats_text = ""
            if community_stats:
                stats_lines = []
                for s in community_stats:
                    stats_lines.append(
                        f"| {s.get('name', s.get('communityId', ''))} | {s.get('nodeCount', '?')} | "
                        f"{s.get('qualityScore', '?')} | {s.get('level', 'L0')} |"
                    )
                if stats_lines:
                    stats_text = (
                        "| 社区 | 节点数 | 质量分 | 层级 |\n"
                        "|------|--------|--------|------|\n" + "\n".join(stats_lines)
                    )

            proj_context = project_summary or ""
            if proj_context:
                proj_context = f"\n## 项目背景\n{proj_context}\n"

            if project_context:
                proj_context += f"\n## 项目上下文\n{project_context}\n"

            if self._render:
                messages = self._render("agent_generate_overview", {
                    "project_name": project_name,
                    "project_background": proj_context,
                    "community_count": str(len(community_results)),
                    "stats_text": stats_text,
                    "community_summaries": comm_text[:10000],
                })
            else:
                messages = [
                    {"role": "system", "content": (
                        "你是资深架构师。基于社区分析结果和项目背景，生成整体架构概览（中文，800-1500 字）。"
                        "Markdown 格式，包含: 1) 项目架构总览 2) 各层职责与依赖 3) 核心设计模式 "
                        "4) 架构质量评估 5) 改进建议。"
                        "社区分析结果已包含每社区的名称和摘要，请直接引用。"
                    )},
                    {"role": "user", "content": (
                        f"项目: {project_name}{proj_context}\n"
                        f"社区数量: {len(community_results)}\n\n"
                        f"社区统计:\n{stats_text}\n\n"
                        f"社区分析结果:\n{comm_text[:10000]}"
                    )},
                ]
            resp = await self._chat(messages=messages, temperature=0.3, max_tokens=2000)
            overview = resp if isinstance(resp, str) else resp
            return ToolResult.ok(data=overview, tokens_used=2000)
        except Exception as e:
            logger.warning(f"[ArchAnalyst] overview failed: {e}")
            return ToolResult.fail(str(e))


class _SaveResultsTool(AgentTool):
    """持久化社区分析结果到 community_llm_results"""

    name = "save_community_results"
    description = "将 LLM 分析结果持久化到数据库"
    category = "persistence"

    def __init__(self, save_result_fn: Callable):
        self._save = save_result_fn

    async def execute(self, results: list[dict], task_id: str = "", edge_type: str = "",
                      level: str = "", **kwargs) -> ToolResult:
        saved = 0
        for r in results:
            try:
                if self._save:
                    await self._save(
                        taskId=task_id, edgeType=edge_type, commLv=level,
                        commId=r["communityId"], name=r.get("name", ""),
                        summary=r.get("summary", ""), mermaid=r.get("mermaid", ""),
                        plantuml=r.get("plantuml", ""),
                    )
                saved += 1
            except Exception:
                pass
        return ToolResult.ok(data=saved)


# ─── 模板化图生成 ───

def _build_mermaid(comm_id: str, comm_label: str,
                   children: list[dict], edges: list[dict]) -> str:
    label = comm_label[:30]
    lines = ["graph TD"]
    lines.append(f'  subgraph {comm_id.replace("-","_")} ["{label}"]')
    lines.append("    direction TB")
    for ch in children:
        cid = (ch.get("communityId") or ch.get("comm_id", "")).replace("-", "_")
        cname = (ch.get("name") or ch.get("label") or ch.get("communityId") or "")[:25]
        lines.append(f'    {cid}("{cname}")')
    lines.append("  end")
    for e in edges:
        src = (e.get("source") or "").replace("-", "_")
        tgt = (e.get("target") or "").replace("-", "_")
        if src and tgt:
            lines.append(f"  {src} --> {tgt}")
    return "\n".join(lines)


def _build_plantuml(comm_id: str, comm_label: str,
                    children: list[dict], edges: list[dict]) -> str:
    label = comm_label[:30]
    lines = ["@startuml"]
    lines.append(f'package "{label}" {{')
    for ch in children:
        cid = ch.get("communityId") or ch.get("comm_id", "")
        cname = (ch.get("name") or ch.get("label") or cid)[:25]
        lines.append(f'  [{cname}] as {cid.replace("-","_")}')
    lines.append("}")
    for e in edges:
        src = (e.get("source") or "").replace("-", "_")
        tgt = (e.get("target") or "").replace("-", "_")
        if src and tgt:
            lines.append(f"{src} --> {tgt}")
    lines.append("@enduml")
    return "\n".join(lines)


# ─── 工作流 ───

class ArchAnalystWorkflow(AgentWorkflow):
    """批量架构分析工作流 (per-community 粒度)"""

    name = "arch_analyst"
    description = "批量 LLM 分析社区模块，生成摘要和图，最终输出架构概览"

    def plan(self, context: dict) -> list[AgentStep]:
        communities = context.get("communities", [])
        if not communities:
            return []

        steps: list[AgentStep] = []

        for c in communities:
            cid = c.get("communityId") or c.get("comm_id", f"comm-?")
            label = c.get("name") or c.get("label") or cid
            steps.append(AgentStep(
                tool="analyze_community",
                args={
                    "community": c,
                    "project_summary": context.get("project_summary", ""),
                },
                description=f"分析社区: {label[:30]}",
            ))
            steps.append(AgentStep(
                tool="generate_diagram",
                args={
                    "community": c,
                    "child_communities": context.get("child_communities", {}).get(cid, []),
                    "edges": context.get("cross_edges", {}).get(cid, []),
                },
                description=f"生成图: {label[:30]}",
            ))

        steps.append(AgentStep(
            tool="generate_overview",
            args={
                "project_name": context.get("project_name", ""),
                "project_summary": context.get("project_summary", ""),
                "project_context": context.get("project_context", ""),
                "community_stats": communities,
            },
            description=f"生成架构概览 ({len(communities)} 社区)",
        ))

        steps.append(AgentStep(
            tool="save_community_results",
            args={
                "task_id": context.get("task_id", ""),
                "edge_type": context.get("edge_type", "INCLUDE"),
                "level": context.get("level", "L0"),
            },
            description="持久化分析结果",
        ))

        return steps

    def finalize(self, results: dict[str, Any]) -> WorkflowResult:
        overview = results.get("generate_overview", "")
        saved = results.get("save_community_results", 0)
        return WorkflowResult(
            success=True,
            data={"overview": overview, "saved_communities": saved},
            summary=f"完成: {saved} 个社区",
        )
