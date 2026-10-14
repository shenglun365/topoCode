"""agent 调度域（pipeline/preSummary/analyzeComponents/进度）（MS5-V1 自 task_manager.py 切分；注册顺序经 task_api/__init__ 锁序）。
"""
import asyncio
import json
import os
import subprocess
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from topoone.db.manager import MultiDBManager
from topoone.engine.store.task_store import TaskStore
from topoone.engine.store.analysis_store import AnalysisStore
from topoone.engine.analysis_utils import get_cascade_levels_impl, get_l0_comps
from topoone.engine.community_data import unified_l0_components
from topoone.engine.analyst_runner import (
    _execute_task, set_stop_flag, clear_stop_flag, is_task_executing, enqueue_analysis_task,
)
from . import common
from .common import (
    _FIELD_MAP,
    _resolve_node_list_items,
    _compute_file_ranks,
    _count_batched_source_files,
    _reset_tasks_to_pending,
    _with_fixed_report_types,
    _ensure_project_db,
    _ensure_table,
    Shared,
)
from .git_info import detect_git_info, save_git_info, get_git_info, check_import_status, _run_git
from .positions import save_positions, load_positions, list_position_keys, clear_positions

logger = logging.getLogger(__name__)


def register(server, multi_db, S):
    @server.register("analysis.startOverview")
    def start_overview(task_id=None, taskId=None, force=False, language=None):
        """启动整体架构概览生成 (OverviewWorkflow 入口)"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        lang = language or ""
        logger.info(f"[startOverview] task_id={tid} language={lang or '(default)'}")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = S.get_project_root(pid)
        project_summary = S.get_project_summary(pid)
        project_name = task.get("name") or task.get("project_name") or pid

        # ── 前置检查：L0/L1 社区分析是否完成 ──
        missing = []
        for et in ('INCLUDE', 'CALL'):
            for lv in ('L0', 'L1'):
                comm_count = project_db.execute(
                    "SELECT COUNT(*) FROM community_hierarchy WHERE task_id=? AND edge_type=? AND comm_lv=?",
                    (tid, et, lv)
                ).fetchone()[0]
                if comm_count == 0:
                    continue
                analyzed = project_db.execute(
                    "SELECT COUNT(*) FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_lv=? AND name!=''",
                    (tid, et, lv)
                ).fetchone()[0]
                if analyzed < comm_count:
                    missing.append(f"{et} {lv}: {analyzed}/{comm_count} not analyzed")
        if missing:
            raise ValueError(f"Prerequisites not met: {'; '.join(missing)}. Please run /analyze_components first.")

        # ── 检查是否已生成（跳过）──
        if not force:
            existing = project_db.execute(
                "SELECT id FROM report_subdocs WHERE task_id=? AND comm_id='overall' AND (title='Architecture Overview Document' OR template_id='overview')",
                (tid,)
            ).fetchone()
            if existing:
                logger.info(f"[startOverview] overview already exists, skipping (use --force to regenerate)")
                return {"taskId": tid, "success": True, "agentTaskId": None, "skipped": True}

        # ── distributed 模式 → Agent Worker ────────────────────────
        mgr = S.agent_mgr()
        if S._agent_proxy is not None:
            context = {
                "task_id": tid, "project_id": pid,
                "project_name": project_name,
                "project_summary": project_summary,
                "language": lang,
            }
            result = mgr.dispatch("overview", tid, context,
                                  project_id=pid, project_root=project_root,
                                  project_summary=project_summary)
            S.save_agent_running_history(project_db, pid, tid, result.get("agent_id"), "overview")
            return {"taskId": tid, "success": True, "agentTaskId": result.get("agent_id"), "skipped": False}

        # ── 构建上下文（monolith）──
        from topoone.agent.agent_workflow.router import create_default_router
        router = create_default_router(
            project_root=project_root, project_db=project_db, multi_db=multi_db,
            task_id=tid, project_summary=project_summary,
        )
        context = {
            "task_id": tid, "project_id": pid,
            "project_name": project_name,
            "project_summary": project_summary,
            "language": lang,
        }

        # ── 完成回调：保存概览文档 ──
        def _on_overview_complete(state_dict):
            S.make_agent_history_cb(pid, project_db, tid, "overview")(state_dict)
            try:
                overview = (state_dict.get("result") or {}).get("overview", "")
                if overview:
                    from topoone.engine.report_tree_service import save_overall_doc
                    save_overall_doc(multi_db, tid, "Architecture Overview Document", overview)
                    logger.info(f"[startOverview] saved overview doc for task {tid}, len={len(overview)}")
            except Exception as e:
                logger.warning(f"[startOverview] failed to save overview doc: {e}")

        agent_id = router.dispatch("overview", tid, context,
            on_complete=_on_overview_complete)
        S.save_agent_running_history(project_db, pid, tid, agent_id, "overview")

        return {"taskId": tid, "success": True, "agentTaskId": agent_id, "skipped": False}

    @server.register("analysis.getAgentProgress")
    def get_agent_progress(agent_task_id=None, agentTaskId=None):
        aid = agent_task_id or agentTaskId
        if not aid:
            raise ValueError("agent_task_id is required")
        mgr = S.agent_mgr()
        if S._agent_proxy is not None:
            result = mgr.get_progress(aid)
            if not result:
                return {"found": False}
            if isinstance(result, dict):
                return {**result, "found": True}
            return {"found": True}
        result = mgr.get_progress(aid)
        if not result:
            return {"found": False}
        return {**result, "found": True}

    @server.register("analysis.getProgressStats")
    def get_progress_stats(task_id=None, taskId=None):
        """纯 DB 查询的任务执行统计，不依赖内存状态"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            return {"taskId": tid, "found": False}
        pid = task["project_id"]
        try:
            project_db = multi_db.get_project_db(pid)
        except Exception:
            logger.warning(f"[get_progress_stats] project {pid} not accessible (task {tid}), returning empty")
            return {"taskId": tid, "found": True, "done_files": 0, "total_files": 0,
                    "done_comps": 0, "total_comps": 0, "cached_count": 0,
                    "batch_files": {}, "failed_count": 0}
        if not project_db:
            return {"taskId": tid, "found": False}

        done_files = 0
        total_files = 0
        done_comps = 0
        total_comps = 0

        try:
            # 分母 = 预摘要范围内的源码文件（P0/P1/P2 批次并集）；
            # 图内全部文件含范围外文件，会导致文件进度永远 <100%
            pr = S.get_project_root(pid)
            total_files = _count_batched_source_files(tid, project_db, pr)
            if not total_files:
                row = project_db.execute(
                    "SELECT COUNT(DISTINCT file_path) FROM graph_node WHERE task_id=? AND kind='file'", (tid,)
                ).fetchone()
                if row: total_files = row[0]
        except Exception:
            pass
        try:
            row = project_db.execute(
                "SELECT COUNT(*) FROM file_summaries WHERE project_id=? AND summary IS NOT NULL", (pid,)
            ).fetchone()
            if row: done_files = row[0]
        except Exception:
            pass
        try:
            row = project_db.execute(
                "SELECT COUNT(DISTINCT comm_id) FROM community_hierarchy WHERE task_id=?", (tid,)
            ).fetchone()
            if row: total_comps = row[0]
        except Exception:
            pass
        try:
            row = project_db.execute(
                "SELECT COUNT(*) FROM community_llm_results WHERE task_id=? AND status='completed' AND name IS NOT NULL AND name != ''", (tid,)
            ).fetchone()
            if row: done_comps = row[0]
        except Exception:
            pass

        # 项目摘要/架构概览各占 90 权重（与 total_weight 的 +180 对应），
        # 全部完成后加权进度才能到达 100%
        summary_weight = 0
        try:
            srow = multi_db.main_db.execute(
                "SELECT summary FROM projects WHERE id=?", (pid,)
            ).fetchone()
            if srow and srow[0]:
                summary_weight = 90
        except Exception:
            pass
        overview_weight = 0
        try:
            orow = project_db.execute(
                "SELECT 1 FROM report_subdocs WHERE task_id=? AND comm_id='overall' LIMIT 1", (tid,)
            ).fetchone()
            if orow:
                overview_weight = 90
        except Exception:
            pass
        total_weight = total_files * 30 + total_comps * 120 + 180
        if total_weight <= 0:
            total_weight = 60  # 空范围兜底，防除零
        done_weight = done_files * 30 + done_comps * 120 + summary_weight + overview_weight
        if total_weight > 0:
            weighted_progress = round(min(done_weight, total_weight) / total_weight * 100, 1)
        else:
            weighted_progress = 0.0

        return {
            "taskId": tid,
            "found": True,
            "totalFiles": total_files,
            "doneFiles": done_files,
            "totalComps": total_comps,
            "doneComps": done_comps,
            "weightedProgress": weighted_progress,
        }

    @server.register("analysis.cancelAgentTask")
    def cancel_agent_task(agent_task_id=None, agentTaskId=None):
        aid = agent_task_id or agentTaskId
        if not aid:
            raise ValueError("agent_task_id is required")
        mgr = S.agent_mgr()
        if S._agent_proxy is not None:
            return mgr.cancel(aid)
        ok = mgr.cancel(aid)
        return {"cancelled": ok}

    @server.register("analysis.startPipeline")
    def start_pipeline(task_id=None, taskId=None, force=False, language=None,
                       concurrency=None, subagent_concurrency=None,
                       component_timeout=None, componentTimeout=None):
        """启动流水线整体激活 (PipelineWorkflow 入口)"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        conc = max(1, min(int(concurrency or 1), 5))
        raw_sub = subagent_concurrency if subagent_concurrency is not None else conc
        sub_conc = max(1, min(int(raw_sub), 5))
        comp_timeout = component_timeout if component_timeout is not None else (componentTimeout or 60)
        comp_timeout = max(0, min(int(comp_timeout), 600))
        logger.info(f"[startPipeline] task_id={tid} force={force} lang={language} concurrency={conc} subagent={sub_conc} timeout={comp_timeout}min")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = S.get_project_root(pid)
        project_summary = S.get_project_summary(pid)
        project_name = task.get("name") or task.get("project_name") or pid

        mgr = S.agent_mgr()
        if S._agent_proxy is not None:
            context = {
                "task_id": tid, "project_id": pid,
                "project_name": project_name,
                "project_summary": project_summary,
                "force": force,
                "language": language or "",
                "concurrency": conc,
                "subagent_concurrency": sub_conc,
                "component_timeout": comp_timeout,
            }
            result = mgr.dispatch("pipeline", tid, context,
                                  project_id=pid, project_root=project_root,
                                  project_summary=project_summary)
            S.save_agent_running_history(project_db, pid, tid, result.get("agent_id"), "pipeline")
            return {"taskId": tid, "success": True, "agentTaskId": result.get("agent_id"), "skipped": False}

        # Pre-compute total and cached counts for stable progress denominator
        _total_files = 0
        _total_comps = 0
        try:
            # 与 getProgressStats 同口径：预摘要范围内的源码文件
            _total_files = _count_batched_source_files(tid, project_db, project_root)
        except Exception:
            pass
        if not _total_files:
            try:
                row = project_db.execute(
                    "SELECT COUNT(DISTINCT file_path) as cnt FROM graph_node WHERE task_id=? AND kind='file'", (tid,)
                ).fetchone()
                if row: _total_files = row["cnt"]
            except Exception:
                pass
        try:
            row = project_db.execute(
                "SELECT COUNT(DISTINCT comm_id) as cnt FROM community_hierarchy WHERE task_id=?",
                (tid,)
            ).fetchone()
            if row: _total_comps = row["cnt"]
        except Exception:
            pass
        _est_weight = _total_files * 30 + _total_comps * 120 + 180
        if _est_weight <= 0:
            _est_weight = 60
        logger.info(f"[Pipeline] total files={_total_files} comps={_total_comps} est_weight={_est_weight}")

        def _on_pipeline_complete(state_dict):
            S.make_agent_history_cb(pid, project_db, tid, "pipeline")(state_dict)

        backend = os.environ.get("TOPOCODE_PIPELINE_BACKEND", "tagent").lower()

        if backend == "tagent":
            # ── I3: tAgent 薄接线（替代旧 RouterHarness + PipelineWorkflow 直跑路径）──
            import threading as _threading
            from topocode_agent.workflows.pipeline import run_kb_pipeline
            from topoone.llm.tagent_adapter import TopoLLMClientAdapter
            from topoone.agent.tagent_host import (
                TopoPipelineProvider, build_topo_pipeline_callbacks,
            )

            model_id = ""  # LLMService 默认模型（与旧路径同口径）
            llm = TopoLLMClientAdapter(multi_db, model_id=model_id,
                                       session_suffix=f"tagent-{tid[:8]}")
            provider = TopoPipelineProvider(multi_db, project_db,
                                            project_root=project_root,
                                            project_id=pid, task_id=tid)
            callbacks = build_topo_pipeline_callbacks(
                multi_db, pid, tid, model_id=model_id,
                project_root=project_root, concurrency=conc)
            cancel_event = _threading.Event()

            def _make_coro(on_progress):
                return run_kb_pipeline(
                    llm, provider, callbacks,
                    project_root, pid, tid,
                    project_summary=project_summary, model=model_id,
                    project_name=project_name, force=force, language=language or "",
                    subagent_concurrency=sub_conc, component_timeout=comp_timeout,
                    estimated_total_weight=_est_weight,
                    total_files=_total_files, total_comps=_total_comps,
                    on_progress=on_progress, cancel_event=cancel_event,
                )

            agent_id = mgr.enqueue_async(tid, _make_coro, cancel_event,
                                         on_complete=_on_pipeline_complete)
            S.save_agent_running_history(project_db, pid, tid, agent_id, "pipeline")
            logger.info(f"[startPipeline] dispatched via tAgent agent_id={agent_id}")
            return {"taskId": tid, "success": True, "agentTaskId": agent_id, "skipped": False}

        # ── legacy: 旧 RouterHarness + PipelineWorkflow（I6 删除） ──
        from topoone.agent.agent_workflow.router import RouterHarness, RouteEntry
        from topoone.agent.agent_workflow.workflows.pipeline import PipelineWorkflow
        from topoone.agent.agent_workflow.tool_factory import build_pipeline_tools
        from topoone.agent.agent_workflow.sandbox import AgentSandbox

        tools = build_pipeline_tools(multi_db, project_db, project_root, tid, pid, project_summary,
                                      concurrency=conc, subagent_concurrency=sub_conc,
                                      component_timeout=comp_timeout)
        router = RouterHarness(project_root=project_root, multi_db=multi_db)
        router.register("pipeline", RouteEntry(
            workflow_class=PipelineWorkflow,
            tool_builder=lambda ctx: tools,
            description="Pipeline execution: project summary -> pre-summary -> component analysis -> architecture analysis. Options: -j N (concurrency 1-5, default 1), --force (force regenerate), -L zh/en (output language)",
            sandbox_builder=lambda root: AgentSandbox(root, max_tokens=0, timeout_seconds=0),
        ))

        context = {
            "task_id": tid, "project_id": pid,
            "project_name": project_name,
            "project_summary": project_summary,
            "force": force,
            "language": language or "",
            "concurrency": conc,
            "subagent_concurrency": sub_conc,
            "_estimated_total_weight": _est_weight,
            "_total_files": _total_files,
            "_total_comps": _total_comps,
        }
        agent_id = router.dispatch("pipeline", tid, context,
            on_complete=_on_pipeline_complete)
        S.save_agent_running_history(project_db, pid, tid, agent_id, "pipeline")

        return {"taskId": tid, "success": True, "agentTaskId": agent_id, "skipped": False}

    @server.register("analysis.getAgentTaskHistory")
    def get_agent_task_history(task_id=None, taskId=None, offset=0, limit=10):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        mgr = S.agent_mgr()
        if S._agent_proxy is not None:
            return mgr.get_history(tid, offset, limit)
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        from topoone.engine.store.analysis_store import AnalysisStore
        s = AnalysisStore(project_db)
        return s.list_agent_task_history(tid, offset, limit)

    @server.register("analysis.clearAgentTaskHistory")
    def clear_agent_task_history(task_id=None, taskId=None):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        from topoone.engine.store.analysis_store import AnalysisStore
        s = AnalysisStore(project_db)
        s.clear_agent_task_history(pid, tid)
        return {"success": True}

    def get_l0_comps(project_db, tid):
        """获取 L0 社区列表（组件统一：标准访问器，直查 SQLite）。"""
        from topoone.engine.community_data import unified_l0_components
        return [{"id": c["id"],
                 "metadata": {"qualityScore": c["qualityScore"]}}
                for c in unified_l0_components(project_db, tid)]

    @server.register("analysis.getPreSummaryStatus")
    def get_pre_summary_status(task_id=None, taskId=None):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = S.get_project_root(pid)

        rank_data = multi_db.cache_store.get_file_ranks(tid)
        if rank_data is None:
            comps = [{"id": c["id"], "metadata": {"qualityScore": c["qualityScore"]}}
                     for c in unified_l0_components(project_db, tid)]
            rank_data = common._compute_file_ranks(tid, project_db, comps, project_root)
            multi_db.cache_store.set_file_ranks(tid, rank_data)

        # 查已缓存文件数 + 按批次统计（每次轮询只查 COUNT）
        cached_count = 0
        batch_cached = {"P0": 0, "P1": 0, "P2": 0, "P3": 0}
        # P3 不计入进度分母，但按批次统计其已缓存数（供 P3 行展示）
        rank_paths = {f["file_path"] for f in rank_data["files"] if f["batch"] != "P3"}
        rank_map = {f["file_path"]: f["batch"] for f in rank_data["files"]}
        try:
            cached_rows = project_db.execute(
                "SELECT file_path FROM file_summaries WHERE project_id=?", (pid,)
            ).fetchall()
            for r in cached_rows:
                b = rank_map.get(r[0])
                if b is None:
                    continue
                batch_cached[b] += 1
                if b != "P3":
                    cached_count += 1
        except Exception:
            pass

        # total_files 为预摘要分母（P0+P1+P2）；P3 未纳入不计入进度
        return {
            "counts": rank_data["counts"],
            "total_files": len(rank_paths),
            "p3_count": len(rank_data["files"]) - len(rank_paths),
            "cached_count": cached_count, "batch_cached": batch_cached,
            "project_root": project_root,
            "failed_count": multi_db.cache_store.get_ps_failed(tid),
        }

    @server.register("analysis.getPreSummaryFileSource")
    def get_pre_summary_file_source(task_id=None, taskId=None,
                                    file_path=None, filePath=None):
        """预摘要详情：读取文件源码（路径限定项目根内防穿越；≤512KB 截断）"""
        import os as _os
        tid = task_id or taskId
        rel = file_path or filePath
        if not tid or not rel:
            raise ValueError("task_id and file_path are required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_root = S.get_project_root(pid)

        abs_path = _os.path.realpath(_os.path.join(project_root, rel))
        root_real = _os.path.realpath(project_root)
        if abs_path != root_real and not abs_path.startswith(root_real + _os.sep):
            return {"found": False, "error": "path outside project root"}
        if not _os.path.isfile(abs_path):
            return {"found": False, "error": "file not found"}
        cap = 512 * 1024
        with open(abs_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read(cap)
        size = _os.path.getsize(abs_path)
        return {"found": True, "content": content, "size": size,
                "truncated": size > cap, "file_path": rel}

    @server.register("analysis.listPreSummaryFiles")
    def list_pre_summary_files(task_id=None, taskId=None, batch="P0",
                                page=1, page_size=20, search=""):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = S.get_project_root(pid)

        def _load_and_filter(cached_ok=True):
            rd = multi_db.cache_store.get_file_ranks(tid) if cached_ok else None
            if rd is None:
                comps = [{"id": c["id"], "metadata": {"qualityScore": c["qualityScore"]}}
                         for c in unified_l0_components(project_db, tid)]
                rd = common._compute_file_ranks(tid, project_db, comps, project_root)
                if cached_ok:
                    multi_db.cache_store.set_file_ranks(tid, rd)
            bfs = [f for f in rd["files"] if f["batch"] == batch]
            if search:
                q = search.lower()
                bfs = [f for f in bfs if q in f["file_path"].lower()]
            return bfs, rd

        batch_files, rank_data = _load_and_filter(cached_ok=True)

        # 搜索无结果时重算（可能是缓存数据与当前 L0 社区不同步）
        if search and not batch_files:
            batch_files, rank_data = _load_and_filter(cached_ok=False)

        total = len(batch_files)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = batch_files[start:end]

        cached_set: set[str] = set()
        if page_items:
            try:
                paths = [item["file_path"] for item in page_items]
                placeholders = ",".join("?" for _ in paths)
                cache_rows = project_db.execute(
                    f"SELECT DISTINCT file_path FROM file_summaries WHERE project_id=? AND file_path IN ({placeholders})",
                    (pid, *paths)
                ).fetchall()
                cached_set = {r[0] for r in cache_rows}
            except Exception:
                pass
        for item in page_items:
            item["has_summary"] = item["file_path"] in cached_set

        return {
            "batch": batch, "page": page, "page_size": page_size,
            "total": total, "files": page_items,
        }

    @server.register("analysis.startPreSummary")
    def start_pre_summary(task_id=None, taskId=None, batch="P0", limit=0,
                          subagent_concurrency=None, subagentConcurrency=None):
        """启动预摘要 agent 任务"""
        raw = subagent_concurrency if subagent_concurrency is not None else subagentConcurrency
        subagent_concurrency = max(1, min(int(raw or 1), 5))
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        return _launch_pre_summary_batch(tid, pid, project_db, batch, limit, subagent_concurrency)

    @server.register("analysis.startPreSummaryPipeline")
    def start_pre_summary_pipeline(task_id=None, taskId=None, batches=None,
                                    limit=0, subagent_concurrency=None,
                                    subagentConcurrency=None):
        """链式顺序启动多个预摘要批次。"""
        subagent_concurrency = subagent_concurrency if subagent_concurrency is not None else (subagentConcurrency or 1)
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        batches = batches or ["P0", "P1", "P2"]

        # ── distributed 模式 → Agent Worker 内部链式处理 ──────────
        if S._agent_proxy is not None:
            result = S._agent_proxy._send("presummary_chain", {
                "task_id": tid, "project_id": pid, "batches": batches,
                "limit": limit, "subagent_concurrency": subagent_concurrency,
                "project_root": S.get_project_root(pid),
                "project_summary": S.get_project_summary(pid),
            }, timeout=30.0)
            if isinstance(result, dict) and result.get("error"):
                return {"success": False, "error": result["error"], "batches": batches,
                        "total": len(batches), "agentTaskId": "", "fileCount": 0}
            agent_task_id = result.get("agentTaskId", "") if isinstance(result, dict) else ""
            S.save_agent_running_history(project_db, pid, tid, agent_task_id, "presummary_files")
            return {"success": True, "batches": batches, "total": len(batches),
                    "agentTaskId": agent_task_id, "fileCount": 0,
                    "allCached": not agent_task_id}

        result = _chain_start_pre_summary(tid, pid, project_db, batches, 0, limit, subagent_concurrency)
        agent_task_id = result.get("agentTaskId", "") if result else ""
        S.save_agent_running_history(project_db, pid, tid, agent_task_id, "presummary_files")
        file_count = result.get("fileCount", 0) if result else 0
        return {"success": True, "batches": batches, "total": len(batches), "agentTaskId": agent_task_id,
                "fileCount": file_count, "allCached": not agent_task_id}

    def _launch_pre_summary_batch(tid, pid, project_db, batch="P0", limit=0,
                                   subagent_concurrency=None, on_complete=None):

        comps = get_l0_comps(project_db, tid)

        project_root = S.get_project_root(pid)
        rank_data = common._compute_file_ranks(tid, project_db, comps, project_root)
        batch_files = [f["file_path"] for f in rank_data["files"]
                       if f["batch"] == batch]
        if limit > 0:
            batch_files = batch_files[:limit]
        if not batch_files:
            logger.info("[startPreSummary] no files in batch %s, skipping", batch)
            if on_complete:
                on_complete({"status": "completed", "failed_count": 0})
            return {"success": True, "skipped": True, "fileCount": 0}

        # 查询已缓存文件集（路径格式：项目相对路径，与 _compute_file_ranks 和 SubAgent 一致）
        cached_paths: set[str] = set()
        try:
            placeholders = ",".join("?" for _ in batch_files)
            cache_rows = project_db.execute(
                f"SELECT file_path FROM file_summaries WHERE project_id=? AND file_path IN ({placeholders})",
                (pid, *batch_files)
            ).fetchall()
            cached_paths = {r[0] for r in cache_rows}
            logger.info("[startPreSummary] resume: %d/%d files already cached",
                       len(cached_paths), len(batch_files))
        except Exception as e:
            logger.warning("[startPreSummary] resume check failed: %s", e)

        # 快速跳过: 所有文件均已缓存
        if cached_paths and len(cached_paths) == len(batch_files):
            logger.info("[startPreSummary] all %d files already cached, skipping", len(batch_files))
            # 触发链式回调（如有），继续下一批次
            if on_complete:
                on_complete({"status": "completed", "failed_count": 0})
            return {"success": True, "allCached": True, "fileCount": len(batch_files), "cachedCount": len(cached_paths)}
        # 部分缓存: 仅提交未缓存文件（路径格式一致，直接比较）
        if cached_paths:
            n_total = len(batch_files)
            batch_files = [fp for fp in batch_files if fp not in cached_paths]
            logger.info("[startPreSummary] %d/%d files cached, submitting %d uncached",
                       len(cached_paths), n_total, len(batch_files))

        raw_sub_conc = subagent_concurrency if subagent_concurrency is not None else 1
        sub_conc = max(1, min(10, int(raw_sub_conc or 1)))

        context = {
            "task_id": tid,
            "project_id": pid,
            "files": batch_files,
            "cached_paths": cached_paths,
            "subagent_concurrency": sub_conc,
        }

        # ── distributed 模式 → Agent Worker ────────────────────────
        if S._agent_proxy is not None:
            result = S._agent_proxy.dispatch(
                "presummary_files", tid, context,
                project_id=pid, project_root=project_root,
                project_summary=S.get_project_summary(pid),
            )
            S.save_agent_running_history(project_db, pid, tid, result.get("agent_id"), "presummary_files")
            return {"success": True, "agentTaskId": result.get("agent_id"),
                    "fileCount": len(batch_files)}

        from topoone.agent.agent_workflow.router import create_default_router
        project_summary = S.get_project_summary(pid)
        router = create_default_router(
            project_root=project_root,
            project_db=project_db,
            multi_db=multi_db,
            task_id=tid,
            project_summary=project_summary,
        )

        # 重置前次运行的失败计数
        try:
            from topoone.agent.agent_workflow.sub_agent import SubAgent
            SubAgent.reset_failed(tid)
            multi_db.cache_store.reset_ps_failed(tid)
        except Exception:
            pass

        cb = on_complete if on_complete else (lambda state: logger.info(f"[startPreSummary] done: {state}"))
        # 同时保存到 agent_task_history，前端通过 getAgentTaskHistory 可查到
        history_cb = S.make_agent_history_cb(pid, project_db, tid, "presummary")
        if on_complete:
            orig_cb = on_complete
            def _combined_cb(state):
                history_cb(state)
                orig_cb(state)
            cb = _combined_cb
        else:
            cb = history_cb

        agent_id = router.dispatch(
            "presummary_files", tid, context, on_complete=cb)

        # 立即写入一条 running 记录到 agent_task_history，前端 getAgentTaskHistory 可查到
        try:
            from topoone.engine.store.analysis_store import AnalysisStore
            import datetime as _dt
            s = AnalysisStore(project_db)
            # 写入前清理同 task 下旧的 presummary_files running 记录，防止残留
            s._db.execute(
                "UPDATE agent_task_history SET status='cancelled', finished_at=datetime('now') "
                "WHERE task_id=? AND action='presummary_files' AND status='running'",
                (tid,)
            )
            s._db.commit()
            s.save_agent_task_history({
                "project_id": pid,
                "task_id": tid,
                "agent_id": agent_id,
                "action": "presummary_files",
                "status": "running",
                "steps": "",
                "message": "",
                "error": "",
                "created_at": _dt.datetime.now().isoformat(),
                "finished_at": None,
            })
        except Exception as e:
            logger.warning(f"[startPreSummary] save running history failed: {e}")

        from topoone.agent.agent_workflow.agent_queue import get_global_queue
        queue = get_global_queue()
        return {"success": True, "agentTaskId": agent_id,
                "fileCount": len(batch_files)}

    def _chain_start_pre_summary(tid, pid, project_db, batches, idx=0, limit=0, subagent_concurrency=1):
        """链式顺序启动预摘要批次：前一批完成后触发下一批。
        返回链中第一个实际启动的 agentTaskId（跳过全缓存批次），
        全部批次均已缓存时返回 {"allCached": True}。
        """
        if idx >= len(batches):
            logger.info("[chainPreSummary] all batches done: %s", batches)
            return {}
        batch = batches[idx]
        logger.info("[chainPreSummary] starting batch %s (%d/%d)", batch, idx + 1, len(batches))
        launched = {}

        def _chain_cb(state):
            fc = state.get("failed_count", 0)
            if fc:
                multi_db.cache_store.set_ps_failed(tid, fc)
            st = state.get("status", "")
            if st in ("cancelled", "failed"):
                logger.info("[chainPreSummary] batch %s %s, stopping chain", batch, st)
                return
            logger.info("[chainPreSummary] batch %s done, starting next", batch)
            nxt = _chain_start_pre_summary(tid, pid, project_db, batches, idx + 1, limit, subagent_concurrency)
            if nxt and nxt.get("agentTaskId"):
                launched["agentTaskId"] = nxt["agentTaskId"]

        first_result = _launch_pre_summary_batch(tid, pid, project_db, batch, limit, subagent_concurrency, on_complete=_chain_cb) or {}
        if first_result.get("agentTaskId"):
            return first_result
        if launched.get("agentTaskId"):
            return {"agentTaskId": launched["agentTaskId"], "fileCount": first_result.get("fileCount", 0)}
        return {"allCached": True, "fileCount": first_result.get("fileCount", 0)}

    @server.register("analysis.getFileSummary")
    def get_file_summary(task_id=None, taskId=None, file_path=None):
        tid = task_id or taskId
        if not tid or not file_path:
            raise ValueError("task_id and file_path are required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = S.get_project_root(pid)

        # 优先用相对路径查找（file_summaries 存储格式）
        query_path = file_path
        if project_root and file_path.lower().startswith(project_root.lower()):
            query_path = file_path[len(project_root):].lstrip("/")

        from topoone.agent.agent_workflow.file_summary_cache import FileSummaryCache
        cache = FileSummaryCache(project_db, pid, project_root, data_dir=multi_db.data_dir)
        detail = cache.get_detail(query_path)
        if detail:
            return {"found": True, **detail}

        # 回退：用原始路径（兼容旧数据或绝对路径存储）
        if query_path != file_path:
            detail = cache.get_detail(file_path)
            if detail:
                return {"found": True, **detail}

        return {"found": False}

    @server.register("analysis.deleteFileSummary")
    def delete_file_summary(task_id=None, taskId=None, file_path=None):
        tid = task_id or taskId
        if not tid or not file_path:
            raise ValueError("task_id and file_path are required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = S.get_project_root(pid)

        # 标准化为相对路径（同 get_file_summary 的兼容逻辑）
        query_path = file_path
        if project_root and file_path.lower().startswith(project_root.lower()):
            query_path = file_path[len(project_root):].lstrip("/")

        from topoone.agent.agent_workflow.file_summary_cache import FileSummaryCache
        cache = FileSummaryCache(project_db, pid, project_root, data_dir=multi_db.data_dir)
        deleted = cache.delete(query_path)
        return {"success": True, "deleted": deleted}

    @server.register("analysis.rerunFileSummary")
    def rerun_file_summary(task_id=None, taskId=None, file_path=None):
        """单个文件重跑摘要 (启动 agent 任务强制刷新)。"""
        tid = task_id or taskId
        if not tid or not file_path:
            raise ValueError("task_id and file_path are required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = S.get_project_root(pid)

        context = {"task_id": tid, "project_id": pid, "files": [file_path]}

        from topoone.agent.agent_workflow.router import create_default_router
        project_summary = S.get_project_summary(pid)
        router = create_default_router(
            project_root=project_root, project_db=project_db,
            multi_db=multi_db, task_id=tid, project_summary=project_summary,
        )
        agent_id = router.dispatch("presummary_files", tid, context)
        S.save_agent_running_history(project_db, pid, tid, agent_id, "presummary_files")
        return {"success": True, "agentTaskId": agent_id, "fileCount": 1}

    @server.register("analysis.analyzeComponents")
    def analyze_components(task_id=None, taskId=None, components=None,
                           language=None, language_=None, concurrency=None,
                           agentic=None, max_turns=None, maxTurns=None,
                           summary_model_id=None, summaryModelId=None,
                           subagent_concurrency=None, subagentConcurrency=None,
                           analysis_mode=None, analysisMode=None,
                           force=False):
        """按需组件分析入口 — 用户选中组件后启动批量 LLM 分析"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        comps = components or []
        if not comps:
            return {"success": False, "error": "no components specified"}
        total_requested = len(comps)
        lang = language or language_ or ""
        conc = max(1, min(int(concurrency or 1), 5))
        agentic_mode = bool(agentic)

        # SubAgent 并发（文件摘要 LLM 调用并行数）
        raw_sub_conc = subagent_concurrency if subagent_concurrency is not None else subagentConcurrency
        sub_conc = max(1, min(int(raw_sub_conc or 1), 10))

        # 解析轮次参数 (-r N)
        turns = 30
        raw_turns = max_turns if max_turns is not None else maxTurns
        if raw_turns is not None:
            try:
                turns = int(raw_turns)
            except (TypeError, ValueError):
                return {"success": False, "error": f"max_turns must be an integer (1-30), got: {raw_turns}"}
        if turns < 1 or turns > 30:
            return {"success": False, "error": f"max_turns must be between 1-30, got: {turns}"}

        # 解析分析模式
        mode = str(analysis_mode or analysisMode or "quick").lower()
        if mode not in ("quick", "deep"):
            mode = "quick"

        # 解析摘要模型
        summary_model = summary_model_id or summaryModelId or ""
        if summary_model and multi_db:
            try:
                sm = multi_db.main_db.fetchone(
                    "SELECT id FROM model_configs WHERE id=?", (summary_model,)
                )
                if not sm:
                    return {"success": False, "error": f"summary model not configured: {summary_model}"}
            except Exception as e:
                return {"success": False, "error": f"summary model validation failed: {e}"}

        try:
            store = TaskStore(multi_db.main_db)
            task = store.get_task(tid)
            if not task:
                raise ValueError(f"Task {tid} not found")
            pid = task["project_id"]
            project_db = multi_db.get_project_db(pid)
            project_root = S.get_project_root(pid)
            project_summary = S.get_project_summary(pid)

            logger.info(f"[analyzeComponents] task_id={tid} components={len(comps)}")

            # ── 富上下文构建：为每个 community 组件加载 node_list → 文件路径 + 关键符号 ──
            import json as _json
            enriched_comps = []
            fp_map = {}
            existing_results = {}
            try:
                from topoone.engine.store.analysis_store import AnalysisStore as _AS3
                _as = _AS3(project_db)
                all_nodes = _as.get_graph_nodes(tid)
                for n in all_nodes:
                    fp = (n.get("file_path") or "").strip()
                    if fp:
                        fp_map.setdefault(fp, []).append(n)
            except Exception:
                pass
            try:
                rows = project_db.execute(
                    "SELECT comm_id, component_type, status, name FROM community_llm_results WHERE task_id=?",
                    (tid,)
                ).fetchall()
                for r in rows:
                    existing_results[r["comm_id"]] = dict(r)
            except Exception:
                pass

            # ── 跳过已分析组件（除非 force=True）──
            if not force:
                def _skip(cid):
                    row = existing_results.get(cid) or existing_results.get(f"community:{cid}")
                    if not row:
                        return False
                    # 只有 status=completed 且 name 非空才算有效分析
                    return row.get("status") != "failed" and row.get("name")
                filtered = []
                for c in comps:
                    if _skip(c.get("id", "")):
                        continue
                    filtered.append(c)
                skipped = len(comps) - len(filtered)
                comps = filtered
                if skipped:
                    logger.info(f"[analyzeComponents] skipped {skipped} already-analyzed components (use --force to override)")
                if not comps:
                    logger.info(f"[analyzeComponents] all {skipped} components already analyzed, nothing to do")
                    return {"success": True, "agentTaskId": None, "skipped": skipped}
            else:
                skipped = 0

            for c in comps:
                cid = c.get("id", "")
                if not (c.get("type") == "community" and cid.startswith("comm-")):
                    enriched_comps.append(c)
                    continue

                meta = c.get("metadata", {})
                file_paths: set[str] = set()
                edge_list_raw: list = []

                try:
                    doc = project_db.execute(
                        "SELECT node_list, edge_list, edge_count FROM graph_doc WHERE task_id=? AND comm_id=?",
                        (tid, cid)
                    ).fetchone()
                    if doc:
                        edge_list_raw = _json.loads(doc["edge_list"]) if doc["edge_list"] else []
                        raw_paths = _json.loads(doc["node_list"]) if doc["node_list"] else []
                        file_paths = {fp.strip() for fp in raw_paths if isinstance(fp, str) and fp.strip()}
                except Exception as e:
                    logger.warning(f"[analyzeComponents] graph_doc load failed {cid}: {e}")

                # 确定 edge label
                parts = cid.split("-")
                edge_kind = parts[2] if len(parts) > 2 and parts[0] == "comm" else "incl"
                edge_label = {"incl": "Dependency (INCLUDE)", "call": "Call relation (CALL)"}.get(edge_kind, "relation")

                # 构建社区元数据（供 CommunityInfoIngredient）
                comm_meta = {
                    "nodeCount": meta.get("nodeCount", 0),
                    "fileCount": meta.get("fileCount", 0),
                    "qualityScore": meta.get("qualityScore"),
                    "edgeCount": doc["edge_count"] if doc else 0,
                    "edgeLabel": edge_label,
                }

                # 构建 CollectContext
                from topoone.llm.context.assembly import CollectContext
                from topoone.llm.context.recipes import (
                    RECIPE_COMPONENT_ANALYSIS,
                    RECIPE_COMPONENT_ANALYSIS_AGENTIC,
                )
                from topoone.llm.context.registry import get_assembler

                ctx = CollectContext(
                    db=project_db,
                    task_id=tid,
                    project_root=project_root or "",
                    comm_id=cid,
                    file_paths=file_paths,
                    fp_map=fp_map,
                    edge_list=edge_list_raw,
                    existing_results=existing_results,
                    _comm_meta=comm_meta,
                )

                recipe = RECIPE_COMPONENT_ANALYSIS_AGENTIC if agentic_mode else RECIPE_COMPONENT_ANALYSIS
                context_text = get_assembler().assemble(recipe, ctx)

                if agentic_mode:
                    context_text += (
                        f"\nTask ID: {tid}"
                        f"\nTool guide: use summarize_file to read and summarize key files; "
                        f"get_community_subgraph to view the complete subgraph structure"
                    )

                enriched_comps.append({
                    "id": cid,
                    "name": c.get("name", cid),
                    "type": c.get("type", "community"),
                    "metadata": meta,
                    "context": context_text,
                })
                logger.info(
                    f"[analyzeComponents] enriched {cid} context_len={len(context_text)} "
                    f"ctx_begin={context_text[:400]!r}"
                )

            from topoone.agent.agent_workflow.router import create_default_router
            from topoone.engine.store.analysis_store import AnalysisStore

            # 构建组件→(edge_type, comm_lv) 查找表
            comp_edge_lv = {}
            for ec in enriched_comps:
                cid = ec["id"]
                if ec.get("type") == "community" and cid.startswith("comm-"):
                    parts = cid.split("-")
                    et = {"incl": "INCLUDE", "call": "CALL", "uni": "UNIFIED"}.get(parts[2] if len(parts) > 2 else "", "INCLUDE")
                    lv = parts[3] if len(parts) > 3 else "L0"
                else:
                    et = ""
                    lv = "L0"
                comp_edge_lv[cid] = (et, lv)

            def _save_fn(result):
                try:
                    from topoone.engine.ingest import write_ingest
                    comp_id = result.get("component_id", "")
                    comp_type = result.get("component_type", "community")
                    aname = result.get("analyzed_name", "") or comp_id
                    asummary = result.get("functional_summary", "")
                    et, lv = comp_edge_lv.get(comp_id, ("", "L0"))
                    status = result.get("status", "completed")
                    write_ingest(pid, "community_result", {
                        "task_id": result.get("task_id", tid),
                        "project_id": pid,
                        "edge_type": et,
                        "comm_lv": lv,
                        "comm_id": comp_id,
                        "name": aname,
                        "summary": asummary,
                        "component_type": comp_type,
                        "status": status,
                    }, data_dir=multi_db.data_dir)
                    logger.info(f"[analyzeComponents] _save_fn ingested: {comp_id} status={status}")
                except Exception as e:
                    logger.error(f"[analyzeComponents] _save_fn failed: {e}", exc_info=True)

            router = create_default_router(
                project_root=project_root, project_db=project_db, multi_db=multi_db,
                task_id=tid, project_summary=project_summary,
                llm_model_id="",
            )

            context = {
                "task_id": tid,
                "project_id": pid,
                "language": lang,
                "concurrency": conc,
                "analysis_mode": mode,
                "components": [
                    {
                        "id": c.get("id", ""),
                        "name": c.get("name", ""),
                        "type": c.get("type", "community"),
                        "metadata": c.get("metadata", {}),
                        "context": c.get("context", ""),
                        "analysis_mode": mode,
                    }
                    for c in enriched_comps
                ],
            }
            context["_save_fn"] = _save_fn
            context["max_turns"] = turns
            if agentic_mode:
                context["subagent_concurrency"] = sub_conc
                if summary_model:
                    context["summary_model_id"] = summary_model
            # ── distributed 模式 → Agent Worker ────────────────────
            if S._agent_proxy is not None:
                result = S._agent_proxy.dispatch(
                    "analyze_components", tid, context,
                    project_id=pid, project_root=project_root,
                    project_summary=project_summary,
                    comp_edge_lv=comp_edge_lv,
                )
                S.save_agent_running_history(project_db, pid, tid, result.get("agent_id"), "analyze_components")
                return {"success": True, "agentTaskId": result.get("agent_id"), "skipped": skipped}

            for c in context["components"]:
                logger.info(
                    f"[analyzeComponents] component id={c['id']} type={c['type']} "
                    f"metadata={c['metadata']}"
                )

            route_action = "analyze_components"
            agent_id = router.dispatch(route_action, tid, context,
                on_complete=S.make_agent_history_cb(pid, project_db, tid, route_action))
            S.save_agent_running_history(project_db, pid, tid, agent_id, route_action)
            return {"success": True, "agentTaskId": agent_id, "skipped": skipped}

        except Exception as e:
            logger.exception(f"[analyzeComponents] handler failed: {e}")
            return {"success": False, "error": str(e), "skipped": 0}

    @server.register("analysis.dispatchArchNL")
    def dispatch_arch_nl(task_id=None, taskId=None, input_text=None, inputText=None,
                          edge_type=None, edgeType=None, level=None,
                          model_id=None, modelId=None):
        """自然语言路由 — LLM 推理分类 → 分发到对应 Workflow"""
        tid = task_id or taskId
        text = input_text or inputText or ""
        if not tid or not text:
            raise ValueError("task_id and input_text are required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = S.get_project_root(pid)
        project_summary = S.get_project_summary(pid)
        project_name = task.get("name") or pid
        et = edge_type or edgeType or "UNIFIED"
        lv = level or "L0"
        mid = model_id or modelId or ""

        result = get_cascade_levels_impl(project_db, tid, et)
        communities = []
        for lv_item in result.get("levels", []):
            if lv_item.get("lv") == lv:
                communities = [
                    {"communityId": it.get("id", ""), "label": it.get("label", ""),
                     "nodeCount": it.get("nodeCount", 0), "qualityScore": it.get("qualityScore", 0),
                     "level": lv, "edgeType": et}
                    for it in lv_item.get("items", [])
                ]
                break

        from topoone.agent.agent_workflow.llm_adapter import create_llm_chat_fn
        from topoone.agent.agent_workflow.router import create_default_router
        from topoone.engine.store.analysis_store import AnalysisStore

        llm_fn = create_llm_chat_fn(multi_db, mid)

        async def _save_fn(**kw):
            s = AnalysisStore(project_db)
            s.bulk_insert_llm_results([{
                "task_id": kw.get("taskId", tid), "edge_type": kw.get("edgeType", et),
                "comm_lv": kw.get("commLv", lv), "comm_id": kw.get("commId", ""),
                "name": kw.get("name", ""), "summary": kw.get("summary", ""),
                "model_id": mid or "default", "template_id": "community_analyze",
                "component_type": "community",
                "status": "completed",
            }])

        base_context = {
            "task_id": tid, "edge_type": et, "level": lv,
            "project_name": project_name, "project_summary": project_summary,
            "communities": communities,
            "_save_fn": _save_fn,
        }
        router = create_default_router(
            project_root=project_root, project_db=project_db, multi_db=multi_db,
            task_id=tid, project_summary=project_summary,
            llm_model_id=mid,
        )
        try:
            agent_id = router.dispatch_nl(text, tid, base_context, llm_fn)
            return {"taskId": tid, "success": True, "agentTaskId": agent_id,
                    "mode": "nl", "input": text[:100]}
        except ValueError as e:
            return {"taskId": tid, "success": False, "error": str(e),
                    "mode": "nl", "input": text[:100]}



    # ==================== 子文档 CRUD ====================

