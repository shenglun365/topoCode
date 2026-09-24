"""任务 CRUD 域（MS5-V1 自 task_manager.py 切分；注册顺序经 task_api/__init__ 锁序）。
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
    @server.register("analysis.listTasks")
    def list_tasks(project_id=None, projectId=None):
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")
        store = TaskStore(multi_db.main_db)
        return store.list_tasks(pid)

    @server.register("analysis.listRunningTasks")
    def list_running_tasks():
        store = TaskStore(multi_db.main_db)
        rows = store._db.execute(
            "SELECT id, name, project_id FROM analysis_tasks WHERE status = 'running'"
        ).fetchall()
        running = [dict(r) for r in rows]
        try:
            if S._agent_proxy is not None:
                remote_tasks = S._agent_proxy.list_running_tasks()
                running.extend(remote_tasks)
            else:
                mgr = S.agent_mgr()
                for aid, state in list(mgr._tasks.items()):
                    if state.status.name in ('RUNNING', 'QUEUED'):
                        running.append({"id": aid, "name": f"[Agent] {state.task_id}", "project_id": ""})
        except Exception:
            pass
        return running

    @server.register("analysis.createTask")
    def create_task(project_id=None, projectId=None,
                    type=None, name=None,
                    scope=None, scopes=None,
                    extensions=None,
                    exclude_dirs=None, excludeDirs=None,
                    report_types=None, reportTypes=None,
                    pattern_type=None, patternType=None,
                    pattern=None):
        pid = project_id or projectId
        if not pid or not name:
            raise ValueError("project_id and name are required")

        # 字段别名转换
        exclude_dirs = exclude_dirs or excludeDirs
        report_types = report_types or reportTypes
        pattern_type = pattern_type or patternType

        store = TaskStore(multi_db.main_db)

        # 重复校验：同一项目下相同名称的任务正在排队或执行中时阻止创建
        existing = store.list_tasks(pid)
        for t in existing:
            if t["name"] == name and t["status"] in ("pending", "queued", "running"):
                raise RuntimeError(
                    f"Task '{name}' already exists (status={t['status']}), duplicate not allowed"
                )

        task = store.create_task({
            "project_id": pid,
            "type": type or "full",
            "name": name,
            "scope": scope,
            "scopes": scopes or [],
            "extensions": extensions or [],
            "exclude_dirs": exclude_dirs or [],
            # 内部依赖/内部调用分析为固定包含项（前端已不再展示该选项，始终勾选）
            "report_types": _with_fixed_report_types(report_types or []),
            "pattern_type": pattern_type,
            "pattern": pattern,
        })
        logger.info(f"[analysis.createTask] id={task['id']} name={name}")
        return task

    @server.register("analysis.runTask")
    async def run_task(task_id=None, taskId=None):
        from topoone.rpc.zmq_server import current_call_id
        _cid = current_call_id.get()
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        if _cid:
            logger.info(f"[{_cid}] analysis.runTask task={tid}")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        if task["status"] in ("running", "queued"):
            raise RuntimeError(f"Task {tid} is already {task['status']}")

        # 创建运行记录
        run = store.create_run(tid, {
            "scope": task.get("scope"),
            "scopes": task.get("scopes", []),
            "extensions": task.get("extensions", []),
            "exclude_dirs": task.get("exclude_dirs", []),
            "report_types": task.get("report_types", []),
        })

        # 更新任务状态
        store.update_task_status(tid, "running", progress=0, error="")

        # 后台启动
        start_time = time.time()
        asyncio.create_task(enqueue_analysis_task(server, multi_db, tid, run["id"], start_time))

        logger.info(f"[analysis.runTask] task={tid} run={run['id']}")
        return {
            "taskId": tid,
            "runId": run["id"],
            "runNumber": run["run_number"],
            "status": "running",
        }

    @server.register("analysis.getTask")
    def get_task(task_id=None, taskId=None):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            return None
        return task

    @server.register("analysis.getResults")
    def get_results(task_id=None, taskId=None, run_id=None, runId=None):
        tid = task_id or taskId
        rid = run_id or runId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        return store.get_results(tid, rid)

    @server.register("analysis.updateTask")
    def update_task(task_id=None, taskId=None, **kwargs):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        return store.update_task_meta(tid, **kwargs)

    @server.register("analysis.deleteTask")
    def delete_task(task_id=None, taskId=None):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")

        # 清理项目库中的分析数据
        project_id = task["project_id"]
        project_db = multi_db.get_project_db(project_id)
        tables_for_task = [
            "graph_node", "graph_edge", "graph_doc", "community_hierarchy",
            "community_llm_results",
            "report_subdocs", "agent_task_history",
        ]
        for table in tables_for_task:
            try:
                project_db.execute(f"DELETE FROM {table} WHERE task_id = ?", (tid,))
            except Exception:
                pass
        project_db.commit()
        logger.info(f"[analysis.deleteTask] Cleared analysis data for task {tid} in project {project_id}")

        # 删除主库中的任务（CASCADE 删除 runs/reports/history）
        return store.delete_task(tid)

    @server.register("analysis.clearProjectCache")
    def clear_project_cache(project_id=None, projectId=None):
        """
        清除项目的所有解析缓存（AST + 符号 + 调用图 + 依赖图 + 社区分析）
        保留 source_files 和 project_config，以便重新解析项目文件。
        兼容前端 camelCase 参数名 projectId。
        """
        project_id = project_id or projectId
        if not project_id:
            raise ValueError("project_id is required")

        # 验证项目存在
        project_db = multi_db.get_project_db(project_id)
        file_count = project_db.execute("SELECT COUNT(*) FROM source_files").fetchone()[0]
        if file_count == 0:
            raise ValueError(f"Project {project_id} has no source files")

        # 清除所有分析相关表，记录每个表的删除数量
        deleted_tables = {}
        tables_to_clear = [
            "graph_node", "graph_edge", "graph_doc", "community_hierarchy",
            "community_llm_results",
            "ast_data", "dependencies", "call_chains", "components",
            "ai_qa", "file_summaries",
            "report_subdocs", "agent_task_history",
        ]
        for table in tables_to_clear:
            before = project_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            project_db.execute(f"DELETE FROM {table}")
            deleted_tables[table] = before
            logger.info(f"[analysis.clearProjectCache] deleted {table}: {before} records")
        project_db.commit()

        # 先清理 WAL 文件，再 VACUUM 回收磁盘空间
        project_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        import os
        proj_db_path = project_db.db_path
        logger.info(f"[analysis.clearProjectCache] VACUUM project DB {project_id} (size: {os.path.getsize(proj_db_path)/1024/1024:.1f} MB)...")
        project_db.execute("VACUUM")
        project_db.commit()
        logger.info(f"[analysis.clearProjectCache] VACUUM done (size: {os.path.getsize(proj_db_path)/1024/1024:.1f} MB)")

        # 项目库体积变化后刷新主库存储统计缓存
        try:
            multi_db.refresh_project_storage_stats(project_id)
        except Exception as e:
            logger.warning(f"[analysis.clearProjectCache] storage stats refresh failed: {e}")

        # 任务保留：解析产物已清，状态重置为 pending —— 清除缓存后开放重新执行
        # （跑完再次 done 收起按钮；可再次清除再次重跑。running 任务不动）
        task_store = TaskStore(multi_db.main_db)
        reset_count = _reset_tasks_to_pending(task_store, project_id)

        # VACUUM 主库
        multi_db.main_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        main_db_path = os.path.join(multi_db.data_dir, "topoone.db")
        logger.info(f"[analysis.clearProjectCache] VACUUM main DB (size: {os.path.getsize(main_db_path)/1024/1024:.1f} MB)...")
        multi_db.main_db.execute("VACUUM")
        multi_db.main_db.commit()
        logger.info(f"[analysis.clearProjectCache] VACUUM main DB done (size: {os.path.getsize(main_db_path)/1024/1024:.1f} MB)")

        logger.info(
            f"[analysis.clearProjectCache] project={project_id}, "
            f"reset {reset_count} tasks to pending, cleared all AST/analysis data"
        )
        return {
            "projectId": project_id,
            "resetTasks": reset_count,
            "fileCount": file_count,
            "deletedTables": deleted_tables,
        }

    @server.register("analysis.getClearCacheCounts")
    def get_clear_cache_counts(project_id=None, projectId=None):
        project_id = project_id or projectId
        if not project_id:
            raise ValueError("project_id is required")
        project_db = multi_db.get_project_db(project_id)
        tables = [
            "ast_data", "dependencies", "call_chains", "community_hierarchy",
            "community_llm_results", "graph_node", "graph_edge", "graph_doc",
            "components", "ai_qa", "file_summaries",
        ]
        counts = {}
        for table in tables:
            try:
                row = project_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                if row and row[0] > 0:
                    counts[table] = row[0]
            except Exception:
                pass
        task_store = TaskStore(multi_db.main_db)
        tasks = task_store.list_tasks(project_id)
        counts["tasks"] = len(tasks) if tasks else 0
        return {"projectId": project_id, "counts": counts}

    @server.register("analysis.clearProjectCacheTable")
    def clear_project_cache_table(project_id=None, projectId=None, table=None):
        project_id = project_id or projectId
        if not project_id or not table:
            raise ValueError("project_id and table are required")
        project_db = multi_db.get_project_db(project_id)
        if table == "tasks":
            task_store = TaskStore(multi_db.main_db)
            tasks = task_store.list_tasks(project_id)
            count = len(tasks)
            for task in tasks:
                tid = task["id"]
                analysis_store = AnalysisStore(project_db)
                analysis_store.clear_task_data(tid)
                task_store.delete_task(tid)
        else:
            try:
                row = project_db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
                count = row[0] if row else 0
                if count > 0:
                    project_db.execute(f"DELETE FROM {table}")
            except Exception as e:
                raise ValueError(f"Failed to clear table {table}: {e}")
        project_db.commit()
        # 清除的是代码解析产物表 → 任务状态重置 pending（清除缓存后开放重新执行）
        reset = 0
        if table in _PARSE_CACHE_TABLES:
            task_store = TaskStore(multi_db.main_db)
            reset = _reset_tasks_to_pending(task_store, project_id)
        return {"table": table, "deleted": count, "resetTasks": reset}

    @server.register("analysis.stopTask")
    def stop_task(task_id=None, taskId=None):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        # 如果任务已经是终态，无需停止
        if task["status"] in ("done", "error", "cancelled", "stopped"):
            logger.info(f"[analysis.stopTask] task={tid} already in terminal state {task['status']}")
            return {"taskId": tid, "status": task["status"]}

        # 只有 running 状态才需要处理
        if task["status"] == "running":
            # 检测任务是否真的在线程池中执行
            if not is_task_executing(tid):
                # 孤儿任务（后端重启后残留），直接恢复为 error
                logger.warning(f"[analysis.stopTask] task={tid} is orphan (not executing), recovering to error")
                store.update_task_status(tid, "error", error="Task execution interrupted (backend terminated abnormally)")
                # 同时修复对应的 run 记录
                store._db.execute(
                    "UPDATE analysis_task_runs SET status='error', error='Execution interrupted', finished_at=datetime('now') WHERE task_id=? AND status='running'",
                    (tid,),
                )
                store._db.commit()
                server.publish("task", "error", {
                    "taskId": tid, "error": "Execution interrupted (backend terminated abnormally)",
                })
                return {"taskId": tid, "status": "error"}

            set_stop_flag(tid)
            store.update_task_status(tid, "cancelled")

        # 发布事件
        server.publish("task", "stopped", {
            "taskId": tid,
            "runId": task.get("last_run_id"),
            "status": "cancelled",
        })

        logger.info(f"[analysis.stopTask] task={tid}")
        return {"taskId": tid, "status": "cancelled"}

    @server.register("analysis.reRunTask")
    async def re_run_task(task_id=None, taskId=None):
        from topoone.rpc.zmq_server import current_call_id
        _cid = current_call_id.get()
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        if _cid:
            logger.info(f"[{_cid}] analysis.reRunTask task={tid}")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        if task["status"] in ("running", "queued", "done"):
            raise RuntimeError(f"Task {tid} status is {task['status']}, cannot rerun")

        # 复用当前配置创建新运行
        run = store.create_run(tid, {
            "scope": task.get("scope"),
            "scopes": task.get("scopes", []),
            "extensions": task.get("extensions", []),
            "exclude_dirs": task.get("exclude_dirs", []),
            "report_types": task.get("report_types", []),
        })

        # 清除旧的排名缓存，避免重跑后前端的 P0~P4 显示旧数据
        multi_db.cache_store.delete_file_ranks(tid)

        store.update_task_status(tid, "running", progress=0, error="")

        start_time = time.time()
        asyncio.create_task(enqueue_analysis_task(server, multi_db, tid, run["id"], start_time))

        # 立即让出事件循环，让 enqueue_analysis_task 有机会在 send 响应前执行
        await asyncio.sleep(0)

        return run

    @server.register("analysis.getTaskRuns")
    def get_task_runs(task_id=None, taskId=None):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        return store.get_task_runs(tid)

    @server.register("analysis.getTaskLogs")
    def get_task_logs(task_id=None, taskId=None,
                      run_id=None, runId=None):
        tid = task_id or taskId
        rid = run_id or runId
        # 支持嵌套传参 {taskId: {taskId: '...', runId: '...'}}
        if isinstance(tid, dict):
            tid = tid.get("taskId")
            rid = tid.get("runId") if isinstance(tid, dict) else rid

        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        return store.get_task_logs(tid, rid)

    @server.register("analysis.updateTaskConfig")
    def update_task_config(task_id=None, taskId=None, config=None, **kwargs):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")

        # 前端发送 { taskId, config: { name, scopes, ... } } — 提取嵌套 config
        if config and isinstance(config, dict):
            update_params = config
        else:
            # 兼容扁平参数 { taskId, name, scopes, ... }
            update_params = kwargs

        # 字段别名转换 (camelCase → snake_case)
        for camel, snake in _FIELD_MAP.items():
            if camel in update_params:
                update_params[snake] = update_params.pop(camel)

        store = TaskStore(multi_db.main_db)
        return store.update_task_config(tid, update_params)

