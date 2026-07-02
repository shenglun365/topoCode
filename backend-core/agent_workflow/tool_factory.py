"""
共享工具工厂 — 供 RPC 和 RouterHarness 复用 tool 注册逻辑。
"""

from __future__ import annotations

from typing import Callable, Optional

from .tools import ToolRegistry


def build_component_analyst_tools(
    llm_chat_fn: Callable,
    render_prompt: Callable = None,
    save_result_fn: Callable = None,
) -> ToolRegistry:
    """构建 ComponentAnalyst 的工具集"""
    from .workflows.component_analyst import (
        _AnalyzeComponentTool, _AnalyzeComponentBatchTool
    )
    tools = ToolRegistry()
    tools.register(_AnalyzeComponentTool(llm_chat_fn, render_prompt, save_result_fn))
    tools.register(_AnalyzeComponentBatchTool(llm_chat_fn, render_prompt, save_result_fn))
    return tools


def build_agentic_component_tools(
    project_root: str = "",
    project_db=None,
    path_sandbox=None,
    project_id: str = "",
    task_id: str = "",
    multi_db=None,
    concurrency: int = 1,
) -> ToolRegistry:
    """构建 AgenticComponentAnalyst 的工具集（LLM 可见的读写工具）"""
    from .toolkits.file_tools import ReadFileTool, SearchContentTool, SummarizeFileTool
    from .toolkits.symbol_tools import GetSymbolDetailTool, SearchSymbolsTool, GetSymbolCodeTool
    from .toolkits.graph_tools import GetCommunitySubgraphTool, GetCallChainTool, GetASTNodeTool
    from .toolkits.edge_tools import GetEdgeDetailTool

    tools = ToolRegistry()
    tools.register(ReadFileTool(project_root=project_root, path_sandbox=path_sandbox))
    tools.register(SearchContentTool(project_root=project_root, path_sandbox=path_sandbox))
    tools.register(SummarizeFileTool(
        project_root=project_root, project_db=project_db,
        project_id=project_id, task_id=task_id,
        multi_db=multi_db, path_sandbox=path_sandbox,
        concurrency=concurrency,
    ))
    if project_db:
        tools.register(GetSymbolDetailTool(project_db=project_db, project_root=project_root))
        tools.register(SearchSymbolsTool(project_db=project_db, project_root=project_root))
        tools.register(GetCommunitySubgraphTool(project_db=project_db, project_root=project_root))
        tools.register(GetCallChainTool(project_db=project_db))
        tools.register(GetASTNodeTool(project_db=project_db))
        tools.register(GetEdgeDetailTool(project_db=project_db))
        tools.register(GetSymbolCodeTool(project_db=project_db, project_root=project_root))
    return tools


def build_pipeline_tools(multi_db, project_db, project_root, task_id, pid,
                         project_summary, concurrency=1, subagent_concurrency=1) -> ToolRegistry:
    """构建流水线工具集 (PipelineWorkflow 专用)"""
    from .tools import AgentTool, ToolResult
    import logging
    _log = logging.getLogger(__name__)
    _sub_conc = max(1, min(int(subagent_concurrency), 5))

    class EnsureSummaryTool(AgentTool):
        name = "pipeline_ensure_summary"
        description = "确保项目摘要已生成"
        category = "pipeline"
        llm_visible = False

        def to_openai_schema(self, filter_names=None):
            return None

        async def execute(self, task_id: str, force: bool = False) -> ToolResult:
            try:
                existing = multi_db.main_db.execute(
                    "SELECT summary FROM projects WHERE id=?", (pid,)
                ).fetchone()
                if existing and existing[0] and not force:
                    _log.info(f"[Pipeline] summary already exists for {pid}")
                    return ToolResult.ok({"summary": "项目摘要 ✅ 已存在"})

                from core_service import _do_generate_project_summary
                await _do_generate_project_summary(multi_db, pid)
                _log.info(f"[Pipeline] generated project summary for {pid}")
                return ToolResult.ok({"summary": "项目摘要 ✅ 已生成"})
            except Exception as e:
                _log.warning(f"[Pipeline] ensure summary failed: {e}")
                return ToolResult.fail(str(e))

    class RunPreSummaryTool(AgentTool):
        name = "pipeline_run_presummary"
        description = "运行预摘要批次"
        category = "pipeline"
        llm_visible = False

        def to_openai_schema(self, filter_names=None):
            return None

        async def execute(self, task_id: str, batches: list[str], force: bool = False) -> ToolResult:
            try:
                from .sandbox import PathSandbox, AgentSandbox as _AS
                from .runtime import AgentRuntime
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError

                ce = getattr(self, 'cancel_event', None)

                sub_results = []
                total_files = 0
                completed_files = 0

                for batch in batches:
                    if ce and ce.is_set():
                        _log.info(f"[Pipeline] preSummary cancelled at {batch}")
                        break
                    files = _pipeline_get_batch_files(project_db, task_id, batch, force, project_root)
                    if not files:
                        sub_results.append(f"{batch}: 0 文件 (全缓存)")
                        continue

                    ps = PathSandbox(project_root) if project_root else None
                    sub_tools = build_agentic_component_tools(
                        project_root=project_root, project_db=project_db,
                        path_sandbox=ps, project_id=pid, task_id=task_id,
                        multi_db=multi_db, concurrency=RunPreSummaryTool._sub_conc,
                    )

                    from .workflows.pre_summary import PreSummaryWorkflow
                    workflow = PreSummaryWorkflow()
                    context = {"task_id": task_id, "files": files, "subagent_concurrency": RunPreSummaryTool._sub_conc}
                    sandbox = _AS(project_root, max_tokens=0, timeout_seconds=0)

                    def _run(_ce=ce):
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            runtime = AgentRuntime(sub_tools, sandbox, multi_db=multi_db)
                            if _ce:
                                runtime._cancel_event = _ce
                            return loop.run_until_complete(runtime.run(workflow, context))
                        finally:
                            loop.close()

                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_run)
                        if ce:
                            while not ce.is_set():
                                try:
                                    result = future.result(timeout=1.0)
                                    break
                                except _TimeoutError:
                                    continue
                            if ce.is_set():
                                future.cancel()
                                _log.info(f"[Pipeline] preSummary cancelled at {batch}")
                                break
                        else:
                            result = future.result(timeout=7200)

                    completed_files += result.steps_completed
                    total_files += result.steps_total
                    sub_results.append(f"{batch}: {result.steps_completed}/{result.steps_total}")
                    _log.info(f"[Pipeline] preSummary {batch}: {result.steps_completed}/{result.steps_total}")

                summary = f"文件预摘要 ✅ {' | '.join(sub_results)}"
                _log.info(f"[Pipeline] preSummary done: {summary}")
                return ToolResult.ok({
                    "sub_step": len(batches), "sub_total": len(batches),
                    "files_completed": completed_files, "files_total": total_files,
                    "summary": summary,
                })
            except Exception as e:
                _log.warning(f"[Pipeline] preSummary failed: {e}")
                return ToolResult.fail(str(e))

    class RunComponentAnalysisTool(AgentTool):
        name = "pipeline_run_component_analysis"
        description = "运行组件分析层级"
        category = "pipeline"
        llm_visible = False

        def to_openai_schema(self, filter_names=None):
            return None

        async def execute(self, task_id: str, levels: list[str], force: bool = False) -> ToolResult:
            try:
                from .sandbox import PathSandbox, AgentSandbox as _AS
                from .runtime import AgentRuntime
                from .workflows.agentic_component_analyst import AgenticComponentAnalystWorkflow
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError

                ce = getattr(self, 'cancel_event', None)

                sub_results = []
                total_components = 0
                completed_levels = 0

                for level in levels:
                    if ce and ce.is_set():
                        _log.info(f"[Pipeline] component analysis cancelled at {level}")
                        break
                    components = _pipeline_get_level_components(project_db, task_id, level, force)
                    if not components:
                        sub_results.append(f"{level}: 0 组件 (全已分析)")
                        completed_levels += 1
                        continue

                    ps = PathSandbox(project_root) if project_root else None
                    sub_tools = build_agentic_component_tools(
                        project_root=project_root, project_db=project_db,
                        path_sandbox=ps, project_id=pid, task_id=task_id,
                        multi_db=multi_db, concurrency=RunComponentAnalysisTool._sub_conc,
                    )

                    comp_edge_lv = {}
                    for c in components:
                        cid = c.get("id", "")
                        if cid.startswith("comm-"):
                            parts = cid.split("-")
                            et = {"incl": "INCLUDE", "call": "CALL"}.get(parts[2] if len(parts) > 2 else "", "INCLUDE")
                            lv = parts[3] if len(parts) > 3 else "L0"
                        else:
                            et = c.get("edgeType", "")
                            lv = c.get("level", "L0")
                        comp_edge_lv[cid] = (et, lv)

                    def _save_fn(result):
                        try:
                            from ingest import write_ingest
                            comp_id = result.get("component_id", "")
                            aname = result.get("analyzed_name", "") or comp_id
                            asummary = result.get("functional_summary", "")
                            comp_type = result.get("component_type", "community")
                            et, lv = comp_edge_lv.get(comp_id, ("", "L0"))
                            status = result.get("status", "completed")
                            write_ingest(project_root, "community_result", {
                                "task_id": result.get("task_id", task_id),
                                "project_id": pid,
                                "edge_type": et,
                                "comm_lv": lv,
                                "comm_id": comp_id,
                                "name": aname,
                                "summary": asummary,
                                "component_type": comp_type,
                                "status": status,
                            })
                            _log.info(f"[Pipeline] _save_fn ingest: {comp_id} status={status}")
                        except Exception as e2:
                            _log.warning(f"[Pipeline] _save_fn failed: {e2}")

                    workflow = AgenticComponentAnalystWorkflow()
                    context = {
                        "task_id": task_id,
                        "components": components,
                        "project_summary": project_summary or "",
                        "max_turns": 30,
                        "_save_fn": _save_fn,
                        "subagent_concurrency": RunComponentAnalysisTool._sub_conc,
                    }
                    sandbox = _AS(project_root, max_tokens=32768, timeout_seconds=900)

                    def _run(_ce=ce):
                        import asyncio
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        try:
                            runtime = AgentRuntime(sub_tools, sandbox, multi_db=multi_db)
                            if _ce:
                                runtime._cancel_event = _ce
                            return loop.run_until_complete(runtime.run(workflow, context))
                        finally:
                            loop.close()

                    with ThreadPoolExecutor(max_workers=1) as executor:
                        future = executor.submit(_run)
                        if ce:
                            while not ce.is_set():
                                try:
                                    future.result(timeout=1.0)
                                    break
                                except _TimeoutError:
                                    continue
                            if ce.is_set():
                                future.cancel()
                                _log.info(f"[Pipeline] component analysis cancelled at {level}")
                                break
                        else:
                            future.result(timeout=3600)

                    completed_levels += 1
                    total_components += len(components)
                    sub_results.append(f"{level}: {len(components)} 组件")
                    _log.info(f"[Pipeline] component {level}: {len(components)} components done")

                summary = f"组件分析 ✅ {' | '.join(sub_results)}"
                _log.info(f"[Pipeline] component analysis done: {summary}")
                return ToolResult.ok({
                    "sub_step": completed_levels, "sub_total": len(levels),
                    "components_total": total_components,
                    "summary": summary,
                })
            except Exception as e:
                _log.warning(f"[Pipeline] component analysis failed: {e}")
                return ToolResult.fail(str(e))

    # 在函数作用域设置类属性（避免类体闭包作用域问题）
    RunPreSummaryTool._sub_conc = _sub_conc
    RunComponentAnalysisTool._sub_conc = _sub_conc

    class RunOverviewTool(AgentTool):
        name = "pipeline_run_overview"
        description = "运行整体架构分析"
        category = "pipeline"
        llm_visible = False

        def to_openai_schema(self, filter_names=None):
            return None

        async def execute(self, task_id: str, force: bool = False) -> ToolResult:
            try:
                from .sandbox import AgentSandbox as _AS
                from .runtime import AgentRuntime
                from .tools import ToolRegistry as _TR
                from .workflows.overview import OverviewWorkflow, _GenerateOverviewTool
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as _TimeoutError

                ce = getattr(self, 'cancel_event', None)
                if ce and ce.is_set():
                    return ToolResult.ok({"skipped": True, "reason": "cancelled"})

                if not force:
                    existing = project_db.execute(
                        "SELECT id FROM report_subdocs WHERE task_id=? AND comm_id='overall'",
                        (task_id,)
                    ).fetchone()
                    if existing:
                        _log.info(f"[Pipeline] overview already exists")
                        return ToolResult.ok({"skipped": True, "reason": "already exists"})

                sub_tools = _TR()
                sub_tools.register(_GenerateOverviewTool(multi_db, project_db, task_id))
                workflow = OverviewWorkflow()
                context = {"task_id": task_id, "project_summary": project_summary or ""}
                sandbox = _AS(project_root, max_tokens=8192, timeout_seconds=600)

                def _run(_ce=ce):
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        runtime = AgentRuntime(sub_tools, sandbox, multi_db=multi_db)
                        if _ce:
                            runtime._cancel_event = _ce
                        result = loop.run_until_complete(runtime.run(workflow, context))
                        return result
                    finally:
                        loop.close()

                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(_run)
                    if ce:
                        while not ce.is_set():
                            try:
                                result = future.result(timeout=1.0)
                                break
                            except _TimeoutError:
                                continue
                        if ce.is_set():
                            future.cancel()
                            _log.info(f"[Pipeline] overview cancelled")
                            return ToolResult.ok({"skipped": True, "reason": "cancelled"})
                    else:
                        result = future.result(timeout=3600)

                overview = (result.data or {}).get("overview", "")
                if overview:
                    try:
                        from report_tree_service import save_overall_doc
                        save_overall_doc(multi_db, task_id, "架构概览文档", overview)
                    except Exception as e2:
                        _log.warning(f"[Pipeline] save overview failed: {e2}")

                _log.info(f"[Pipeline] overview done")
                return ToolResult.ok({"overview_done": bool(overview), "summary": "整体架构分析 ✅ 已生成" if overview else "整体架构分析 ⚠️ 无内容"})
            except Exception as e:
                _log.warning(f"[Pipeline] overview failed: {e}")
                return ToolResult.fail(str(e))

    registry = ToolRegistry()
    registry.register(EnsureSummaryTool())
    registry.register(RunPreSummaryTool())
    registry.register(RunComponentAnalysisTool())
    registry.register(RunOverviewTool())
    return registry


def _pipeline_get_batch_files(project_db, task_id: str, batch: str, force: bool, project_root: str = "") -> list:
    try:
        from task_manager import _compute_file_ranks

        components = []
        for et in ("INCLUDE", "CALL"):
            rows = project_db.execute(
                "SELECT comm_id, quality_score FROM community_hierarchy "
                "WHERE task_id=? AND edge_type=? AND comm_lv='L0' ORDER BY node_count DESC",
                (task_id, et)
            ).fetchall()
            for row in rows:
                components.append({"id": row[0], "metadata": {"qualityScore": row[1] or 0}})
        ranks = _compute_file_ranks(task_id, project_db, components, project_root)
        files = [f["file_path"] for f in ranks.get("files", []) if f.get("batch") == batch]
        if not force:
            cached = set()
            rows = project_db.execute(
                "SELECT file_path FROM file_summaries WHERE task_id=? AND summary IS NOT NULL",
                (task_id,)
            ).fetchall()
            cached = {r[0] for r in rows}
            files = [f for f in files if f not in cached]
        return files
    except Exception:
        return []


def _pipeline_get_level_components(project_db, task_id: str, level: str, force: bool) -> list:
    edge_types = ['INCLUDE', 'CALL']
    results = []
    for et in edge_types:
        rows = project_db.execute(
            "SELECT comm_id, file_count, node_count, quality_score FROM community_hierarchy "
            "WHERE task_id=? AND edge_type=? AND comm_lv=? ORDER BY node_count DESC LIMIT 200",
            (task_id, et, level)
        ).fetchall()
        if not force:
            analyzed_ids = set()
            arows = project_db.execute(
                "SELECT comm_id FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_lv=? AND status='completed'",
                (task_id, et, level)
            ).fetchall()
            analyzed_ids = {r[0] for r in arows}
        for row in rows:
            cid = row[0]
            if not force and cid in analyzed_ids:
                continue
            results.append({
                "id": cid, "type": "community", "name": cid,
                "level": level, "edgeType": et,
                "metadata": {"fileCount": row[1], "nodeCount": row[2], "qualityScore": row[3] or 0},
            })
    return results[:100]
