"""
Task Manager — 13 个 analysis.* 后端方法

通过 @server.register 注册到 RPC 服务器。
"""
import asyncio
import fcntl
import json
import os
import subprocess
import time
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from sqlite_ctx import MultiDBManager
from store.task_store import TaskStore
from store.analysis_store import AnalysisStore
from analyst_runner import _execute_task, set_stop_flag, clear_stop_flag, is_task_executing, enqueue_analysis_task

logger = logging.getLogger(__name__)

# 字段映射 (camelCase → snake_case)
_FIELD_MAP = {
    "excludeDirs": "exclude_dirs",
    "reportTypes": "report_types",
    "patternType": "pattern_type",
    "selectedExtensions": "selected_extensions",
}

# 预摘要失败计数（task_id → int），由 _cb 回调写入，getPreSummaryStatus 读取
_ps_failed_counts: dict[str, int] = {}
_rank_cache: dict[str, dict] = {}


def register_analysis_methods(server, multi_db: MultiDBManager):
    """将所有 analysis.* 方法注册到 RPC 服务器"""

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
            from agent_workflow.agent_queue import get_global_queue
            q = get_global_queue()
            for aid, state in list(q._tasks.items()):
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
            "report_types": report_types or [],
            "pattern_type": pattern_type,
            "pattern": pattern,
        })
        logger.info(f"[analysis.createTask] id={task['id']} name={name}")
        return task

    @server.register("analysis.runTask")
    async def run_task(task_id=None, taskId=None):
        from zmq_server import current_call_id
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
            "report_subdocs", "file_summaries", "agent_task_history",
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
            logger.info(f"[analysis.clearProjectCache] 删除 {table}: {before} 条记录")
        project_db.commit()

        # 先清理 WAL 文件，再 VACUUM 回收磁盘空间
        project_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        import os
        proj_db_path = project_db.db_path
        logger.info(f"[analysis.clearProjectCache] VACUUM 项目库 {project_id} (尺寸: {os.path.getsize(proj_db_path)/1024/1024:.1f} MB)...")
        project_db.execute("VACUUM")
        project_db.commit()
        logger.info(f"[analysis.clearProjectCache] VACUUM 完成 (尺寸: {os.path.getsize(proj_db_path)/1024/1024:.1f} MB)")

        # 清除主库中的任务（连带 runs/reports/history）
        task_store = TaskStore(multi_db.main_db)
        tasks = task_store.list_tasks(project_id)
        deleted_count = 0
        for task in tasks:
            task_store.delete_task(task["id"])
            deleted_count += 1

        # VACUUM 主库
        multi_db.main_db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        main_db_path = os.path.join(multi_db.data_dir, "topoone.db")
        logger.info(f"[analysis.clearProjectCache] VACUUM 主库 (尺寸: {os.path.getsize(main_db_path)/1024/1024:.1f} MB)...")
        multi_db.main_db.execute("VACUUM")
        multi_db.main_db.commit()
        logger.info(f"[analysis.clearProjectCache] VACUUM 主库完成 (尺寸: {os.path.getsize(main_db_path)/1024/1024:.1f} MB)")

        logger.info(
            f"[analysis.clearProjectCache] project={project_id}, "
            f"deleted {deleted_count} tasks, cleared all AST/analysis data"
        )
        return {
            "projectId": project_id,
            "deletedTasks": deleted_count,
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
        return {"table": table, "deleted": count}

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
                store.update_task_status(tid, "error", error="任务执行中断（后端异常终止）")
                # 同时修复对应的 run 记录
                store._db.execute(
                    "UPDATE analysis_task_runs SET status='error', error='执行中断', finished_at=datetime('now') WHERE task_id=? AND status='running'",
                    (tid,),
                )
                store._db.commit()
                server.publish("task", "error", {
                    "taskId": tid, "error": "执行中断（后端异常终止）",
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
        from zmq_server import current_call_id
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
        _rank_cache.pop(f"ranks:{tid}", None)

        store.update_task_status(tid, "running", progress=0, error="")

        start_time = time.time()
        asyncio.create_task(enqueue_analysis_task(server, multi_db, tid, run["id"], start_time))

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

    @server.register("analysis.scanFileStats")
    def scan_file_stats(project_id=None, projectId=None,
                        scope=None, scopes=None,
                        pattern_type=None, patternType=None,
                        pattern=None,
                        exclude_dirs=None, excludeDirs=None,
                        selected_extensions=None, selectedExtensions=None):
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")

        # 字段别名
        pattern_type = pattern_type or patternType
        exclude_dirs = exclude_dirs or excludeDirs
        selected_extensions = selected_extensions or selectedExtensions

        try:
            project_db = multi_db.get_project_db(pid)
            store = AnalysisStore(project_db)
            final_scopes = scopes if scopes else ([scope] if scope else None)
            logger.debug(f"[scan_file_stats] scopes={scopes}, scope={scope}, final_scopes={final_scopes}")

            # 1. totalFiles — COUNT 查询（极快）
            total_files = store.count_files(
                scopes=final_scopes,
                extensions=selected_extensions,
                exclude_dirs=exclude_dirs,
                pattern_type=pattern_type,
                pattern=pattern,
            )
            logger.debug(f"[scan_file_stats] totalFiles={total_files}")

            # 2. 目录树 — 只取 file_path（路径列）
            all_paths = store.list_file_paths()
            logger.debug(f"[scan_file_stats] {len(all_paths)} paths for directory tree")

            # 3. 扩展名分布 — 跟随目录选项（scopes 过滤），不受 selected_extensions 限制
            extensions = store.count_by_extensions(
                scopes=final_scopes,
                extensions=None,
                exclude_dirs=exclude_dirs,
                pattern_type=pattern_type,
                pattern=pattern,
            )
            dir_count_paths = store.list_file_paths(
                extensions=selected_extensions,
                exclude_dirs=exclude_dirs,
                pattern_type=pattern_type,
                pattern=pattern,
            )
            logger.debug(f"[scan_file_stats] {len(dir_count_paths)} paths for directory counts, {len(extensions)} extension types")

        except Exception as e:
            logger.error(f"[scan_file_stats] error: {e}")
            total_files = 0
            all_paths = []
            extensions = {}
            dir_count_paths = []

        # 完整目录树（基于全量文件路径，不受 scopes 影响）
        dir_tree: dict = {}
        for dir_path in all_paths:
            if dir_path:
                parts = dir_path.split("/")
                current = dir_tree
                for part in parts[:-1]:  # 跳过文件名，只处理目录
                    if part not in current:
                        current[part] = {}
                    current = current[part]

        # 按目录统计文件数（基于语言类型过滤，不受 scopes 影响）
        dir_counts: dict = {}
        for dir_path in dir_count_paths:
            if dir_path:
                parts = dir_path.split("/")
                current = dir_counts
                # 遍历所有目录层级，每层计数 +1
                for part in parts[:-1]:
                    if part not in current:
                        current[part] = {"_count": 0}
                    current[part]["_count"] = current[part].get("_count", 0) + 1
                    # 进入下一层
                    next_level = current[part]
                    if not isinstance(next_level, dict):
                        next_level = {}
                        current[part] = {"_count": 0}
                    current = current[part]

        # 将树形结构展平为前端可用的格式
        def flatten_dir_tree(tree: dict, prefix: str = "", counts: dict = None) -> list:
            result = []
            for name, children in sorted(tree.items()):
                path = f"{prefix}/{name}" if prefix else name
                file_count = None
                if counts:
                    cnt_node = counts.get(name, {})
                    if isinstance(cnt_node, dict):
                        file_count = cnt_node.get("_count", 0) or None
                node = {
                    "name": name,
                    "path": path,
                    "children": flatten_dir_tree(children, path, counts.get(name, {}) if counts and isinstance(counts.get(name, {}), dict) else None) if children else [],
                }
                if file_count is not None:
                    node["fileCount"] = file_count
                result.append(node)
            return result

        def count_all_dirs(tree: dict) -> int:
            """递归计算目录树中的节点总数"""
            count = len(tree)
            for children in tree.values():
                count += count_all_dirs(children)
            return count

        dir_list = flatten_dir_tree(dir_tree, "", dir_counts)
        total_dirs = count_all_dirs(dir_tree)

        return {
            "extensions": extensions,
            "totalFiles": total_files,
            "totalDirs": total_dirs,
            "directories": dir_list,
        }

    # ==================== 社区 LLM 结果 ====================

    @server.register("analysis.saveCommunityResult")
    def save_community_result(task_id=None, taskId=None, edge_type=None, edgeType=None,
                                comm_lv=None, commLv=None, comm_id=None, commId=None,
                                name=None, summary=None,
                                model_id=None, modelId=None, template_id=None, templateId=None):
        from zmq_server import current_call_id
        _cid = current_call_id.get()
        tid = task_id or taskId
        et = edge_type or edgeType
        cl = comm_lv or commLv
        cid = comm_id or commId
        mid = model_id or modelId
        tpid = template_id or templateId
        logger.info("[analysis.saveCommunityResult] ENTRY task_id=%s edge_type=%s comm_lv=%s comm_id=%s name=%s",
                     tid, et, cl, cid, name)
        if not tid or not et or not cl or not cid:
            logger.error("[analysis.saveCommunityResult] missing required fields")
            raise ValueError("task_id, edge_type, comm_lv, comm_id are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            logger.error("[analysis.saveCommunityResult] task not found task_id=%s", tid)
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        store = AnalysisStore(project_db)
        logger.info("[analysis.saveCommunityResult] validated name=%s summary_len=%d model_id=%s template_id=%s",
                     name, len(summary or ''), mid, tpid)
        validated = {
            "task_id": tid, "edge_type": et, "comm_lv": cl, "comm_id": cid,
            "name": name, "summary": summary,
            "model_id": mid, "template_id": tpid,
        }
        store.bulk_insert_llm_results([validated])
        logger.info("[analysis.saveCommunityResult] DONE task_id=%s comm_id=%s", tid, cid)
        return {"success": True}

    @server.register("analysis.getCommunityResult")
    def get_community_result(task_id=None, taskId=None, edge_type=None, edgeType=None,
                              comm_lv=None, commLv=None, comm_id=None, commId=None):
        tid = task_id or taskId
        et = edge_type or edgeType
        cl = comm_lv or commLv
        cid = comm_id or commId
        if not tid or not et or not cl or not cid:
            raise ValueError("task_id, edge_type, comm_lv, comm_id are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        store = AnalysisStore(project_db)
        return store.get_llm_result(tid, et, cl, cid) or {}

    @server.register("analysis.listCommunityResults")
    def list_community_results(task_id=None, taskId=None, edge_type=None, edgeType=None):
        tid = task_id or taskId
        et = edge_type or edgeType
        logger.info("[analysis.listCommunityResults] ENTRY task_id=%s edge_type=%s", tid, et)
        if not tid or not et:
            logger.error("[analysis.listCommunityResults] missing required fields")
            raise ValueError("task_id and edge_type are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            logger.error("[analysis.listCommunityResults] task not found task_id=%s", tid)
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        store = AnalysisStore(project_db)
        results = store.list_llm_results(tid, et)
        logger.info("[analysis.listCommunityResults] DONE task_id=%s edge_type=%s results=%d", tid, et, len(results))
        return {"results": results}

    @server.register("analysis.updateCommunityName")
    def update_community_name(task_id=None, taskId=None, edge_type=None, edgeType=None,
                               comm_lv=None, commLv=None, comm_id=None, commId=None, name=None):
        tid = task_id or taskId
        et = edge_type or edgeType
        cl = comm_lv or commLv
        cid = comm_id or commId
        if not tid or not et or not cl or not cid:
            raise ValueError("task_id, edge_type, comm_lv, comm_id are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        store = AnalysisStore(project_db)
        store.update_community_name(tid, et, cl, cid, name or "")
        return {"success": True}

    # ==================== 报告 Tab 接口 ====================

    @server.register("analysis.getAvailableLevels")
    def get_available_levels(task_id=None, taskId=None, edge_type=None, edgeType=None):
        """获取任务实际生成的社区层级列表"""
        tid = task_id or taskId
        et = edge_type or edgeType
        if not tid:
            raise ValueError("task_id is required")

        # 从主库获取任务所属项目
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            return []
        project_id = task["project_id"]

        project_db = multi_db.get_project_db(project_id)
        if et:
            rows = project_db.execute(
                "SELECT DISTINCT comm_lv FROM graph_doc WHERE task_id=? AND edge_type=? ORDER BY comm_lv",
                (tid, et)
            ).fetchall()
        else:
            rows = project_db.execute(
                "SELECT DISTINCT comm_lv FROM graph_doc WHERE task_id=? ORDER BY comm_lv",
                (tid,)
            ).fetchall()
        levels = [row[0] for row in rows]

        return levels

    @server.register("analysis.getCommunityGraph")
    def get_community_graph(task_id=None, taskId=None,
                            edge_type=None, edgeType=None,
                            comm_lv=None, commLv=None,
                            comm_ids=None, commIds=None,
                            depth=None):
        """按条件查询社区图数据，支持深度展开"""
        tid = task_id or taskId
        et = edge_type or edgeType
        lv = comm_lv or commLv
        ids = comm_ids or commIds
        d = depth or 2

        if not tid or not lv:
            raise ValueError("task_id and comm_lv are required")

        # 从主库获取任务所属项目
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]

        project_db = multi_db.get_project_db(project_id)

        # 构建 file_id → file_path 缓存 + file_id → 显示标签（使用相对路径避免同名文件混淆）
        file_rows = project_db.execute(
            "SELECT id, file_path FROM source_files"
        ).fetchall()
        file_path_map = {row[0]: row[1] for row in file_rows}
        file_name_map = {row[0]: row[1] for row in file_rows if row[1]}

        # ==================== 辅助函数 ====================

        def bad_id(v):
            """判断是否为无效 ID"""
            s = str(v).strip()
            return not s or s == 'None'

        def clean_edge_source(src):
            """清理边 source 中的 garbled 前缀"""
            s = str(src) if src else ''
            if s.startswith('None:['):
                s = s[6:]
            elif s.startswith('['):
                s = s[1:]
            return s

        def build_node_ref_map(all_node_lists, all_edge_lists):
            """构建 node_id → {label, fileId, filePath, graphNodeId, symbolName} 映射

            node_id 格式（当前）:
              - 文件节点: file:/full/path/to/file.ts
              - 符号节点: 16 位 hex hash
            """
            ref_map = {}

            # 收集所有唯一 node_id
            all_node_ids = set()
            for nl in all_node_lists:
                for nid in nl:
                    if nid and not bad_id(nid):
                        all_node_ids.add(str(nid))

            if not all_node_ids:
                return ref_map

            # 仅查询所需的 node_id（而非全表 30K+ 行），批量 IN 查询利用主键索引
            gn_index = {}  # node_id → row
            node_list = list(all_node_ids)
            batch_size = 500
            for i in range(0, len(node_list), batch_size):
                batch = node_list[i:i + batch_size]
                placeholders = ','.join(['?' for _ in batch])
                gn_rows = project_db.execute(
                    f"SELECT id, kind, name, qualified_name, file_path, file_id"
                    f" FROM graph_node WHERE task_id=? AND id IN ({placeholders})",
                    (tid, *batch)
                ).fetchall()
                for row in gn_rows:
                    gn_index[str(row['id'])] = row

            # 为每个 node_id 查询元数据 — 通过 graph_node 直接查找
            for nid in all_node_ids:
                row = gn_index.get(nid)
                if row:
                    file_path = str(row['file_path'] or '')
                    name = str(row['name'] or '')
                    qualified = str(row['qualified_name'] or '')
                    kind = str(row['kind'] or '')
                    file_id = str(row['file_id'] or '')

                    if kind == 'file':
                        label = os.path.basename(file_path) or nid
                    elif qualified:
                        label = qualified
                    elif name:
                        label = name
                    else:
                        label = nid

                    ref_map[nid] = {
                        'label': label,
                        'fileId': file_id or nid,
                        'filePath': file_path,
                        'graphNodeId': row['id'],
                        'symbolName': name if kind != 'file' else '',
                    }
                else:
                    # 不在 graph_node 中的 ID（可能是文件名/路径），尝试从 source_files 查找
                    file_name = file_name_map.get(nid, '')
                    if not file_name:
                        base = os.path.basename(nid) if isinstance(nid, str) else str(nid)
                        file_name = file_name_map.get(base, base)
                    ref_map[nid] = {
                        'label': file_name or nid,
                        'fileId': nid,
                        'filePath': file_path_map.get(nid, ''),
                        'graphNodeId': None,
                        'symbolName': '',
                    }

            return ref_map

        # 查询选中的社区
        if ids and len(ids) > 0:
            placeholders = ','.join(['?' for _ in ids])
            rows = project_db.execute(
                f"SELECT comm_id, node_list, edge_list, node_count, edge_count, quality_score, description FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=? AND comm_id IN ({placeholders})",
                [tid, et, lv] + ids
            ).fetchall()
        else:
            # 返回该层级所有社区
            rows = project_db.execute(
                "SELECT comm_id, node_list, edge_list, node_count, edge_count, quality_score, description FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=? ORDER BY quality_score DESC",
                (tid, et, lv)
            ).fetchall()

        nodes = []
        edges = []
        communities = []

        # 先收集所有 node_list / edge_list，用于批量构建 ref_map
        all_nls = []
        all_els = []
        rows_with_meta = []

        for row in rows:
            comm_id = row[0]
            node_list = json.loads(row[1]) if row[1] else []
            edge_list = json.loads(row[2]) if row[2] else []
            node_count = row[3] or 0
            edge_count = row[4] or 0
            quality_score = row[5] or 0
            description = row[6] or ''
            direction = row[7] if len(row) > 7 else ''

            all_nls.append(node_list)
            all_els.append(edge_list)
            rows_with_meta.append({
                'comm_id': comm_id,
                'node_list': node_list,
                'edge_list': edge_list,
                'node_count': node_count,
                'edge_count': edge_count,
                'quality_score': quality_score,
                'description': description,
            })

        # 批量构建实名映射
        ref_map = build_node_ref_map(all_nls, all_els)

        def node_display(nid):
            """获取节点的实名标签"""
            info = ref_map.get(nid, {})
            label = info.get('label', '')
            if label and label != str(nid):
                return label
            # 尝试去掉后缀再查 ref_map（CALL 汇总后 key 不匹配场景）
            if ':' in str(nid):
                bare_id = str(nid).split(':', 1)[0]
                info = ref_map.get(bare_id, {})
                label = info.get('label', '')
                if label and label != str(nid):
                    return label
            # Fallback: source_files 查询（多种 ID 格式兼容）
            label = file_name_map.get(nid, '')
            if not label:
                label = file_name_map.get(f'file-{nid}', '')
            if not label and nid.startswith('file-'):
                label = file_name_map.get(nid[5:], '')  # 去掉 file- 前缀再查
            return label or str(nid)

        def node_ref_id(nid):
            """获取节点的 graph_node 索引 ID"""
            info = ref_map.get(nid, {})
            return info.get('graphNodeId')

        def node_file_id(nid):
            """获取节点的 source_files.id"""
            info = ref_map.get(nid, {})
            return info.get('fileId', '')

        def node_file_path(nid):
            """获取节点的文件路径"""
            info = ref_map.get(nid, {})
            return info.get('filePath', '')

        def aggregate_to_files(_nodes, _edges):
            """将语法级节点汇聚到文件级：去重 + 合并边，优先通过 graph_node 查找文件归属"""
            file_nodes = {}
            for node_id in _nodes:
                # 优先通过 ref_map 获取文件归属（已修正为 graph_node 直查）
                ref_info = ref_map.get(node_id)
                if ref_info and ref_info.get('filePath'):
                    clean_id = ref_info['filePath']
                else:
                    # fallback: 解析 node_id（兼容旧格式）
                    clean_id = node_id.split(':')[0] if ':' in (node_id or '') else node_id
                if bad_id(clean_id):
                    continue
                if clean_id not in file_nodes:
                    label = file_name_map.get(clean_id, '')
                    if not label:
                        label = ref_map.get(node_id, {}).get('label', '')
                    if not label:
                        label = str(clean_id)
                    file_nodes[clean_id] = label

            file_edges = set()
            for edge in _edges:
                if isinstance(edge, dict):
                    s, t = edge.get('source', ''), edge.get('target', '')
                elif isinstance(edge, list) and len(edge) >= 2:
                    s, t = edge[0], edge[1]
                else:
                    continue
                s_clean = clean_edge_source(s).split(':')[0] if ':' in str(s) else clean_edge_source(s)
                t_clean = t.split(':')[0] if ':' in str(t) else str(t)
                if bad_id(s_clean) or bad_id(t_clean):
                    continue
                if s_clean and t_clean and s_clean != t_clean:
                    file_edges.add((s_clean, t_clean))

            return list(file_nodes.keys()), file_nodes, list(file_edges)

        for row in rows:
            comm_id = row[0]
            node_list = json.loads(row[1]) if row[1] else []
            edge_list = json.loads(row[2]) if row[2] else []
            node_count = row[3] or 0
            edge_count = row[4] or 0
            quality_score = row[5] or 0
            description = row[6] or ''

            # CALL 类型：汇聚到文件级
            agg_labels_map = {}
            if et == 'CALL':
                agg_ids, agg_labels_map, agg_edges = aggregate_to_files(node_list, edge_list)
                node_list = agg_ids
                edge_list = [{'source': s, 'target': t} for s, t in agg_edges]
                description = f'CALL community ({len(agg_ids)} files, {len(agg_edges)} edges)'

            # 添加社区节点
            communities.append({
                'comm_id': comm_id,
                'node_count': node_count,
                'edge_count': edge_count,
                'quality_score': quality_score,
                'description': description,
            })

            # 添加节点和边（使用实名 + 索引信息）
            for node in node_list:
                nodes.append({
                    'id': f'n_{node}',
                    'label': agg_labels_map.get(node) or node_display(node),
                    'refId': node_ref_id(node),
                    'fileId': node_file_id(node),
                    'filePath': node_file_path(node),
                    'comm_id': comm_id,
                    'type': 'symbol',
                })
            for edge in edge_list:
                if isinstance(edge, dict):
                    s, t = edge.get('source', ''), edge.get('target', '')
                    direction = edge.get('direction', '')
                elif isinstance(edge, list) and len(edge) >= 2:
                    s, t = edge[0], edge[1]
                    direction = edge[2] if len(edge) > 2 else ''
                else:
                    continue
                # 清理 garbled source
                s = clean_edge_source(s)
                t = t.split(':')[0] if ':' in str(t) else str(t)
                if bad_id(s) or bad_id(t):
                    continue
                edges.append({
                    'id': f'e_{s}_{t}',
                    'source': f'n_{s}',
                    'target': f'n_{t}',
                    'sourceLabel': agg_labels_map.get(s) or node_display(s),
                    'targetLabel': agg_labels_map.get(t) or node_display(t),
                    'sourceRefId': node_ref_id(s),
                    'targetRefId': node_ref_id(t),
                    'type': et or 'CALL',
                    'direction': direction,
                })

            # 深度展开：查询子社区
            if d > 1:
                child_rows = project_db.execute(
                    "SELECT comm_id, node_list, edge_list, node_count, comm_lv FROM graph_doc WHERE task_id=? AND edge_type=? AND parent_comm_id=?",
                    (tid, et, comm_id)
                ).fetchall()

                for depth_level in range(d - 1):
                    child_comm_ids = [r[0] for r in child_rows]
                    for cr in child_rows:
                        child_comm_id = cr[0]
                        child_node_list = json.loads(cr[1]) if cr[1] else []
                        child_edge_list = json.loads(cr[2]) if cr[2] else []
                        child_node_count = cr[3] or 0

                        communities.append({
                            'comm_id': child_comm_id,
                            'node_count': child_node_count,
                            'edge_count': len(child_edge_list) if child_edge_list else 0,
                            'quality_score': 0,
                            'description': '',
                            'parent_comm_id': comm_id if depth_level == 0 else None,
                        })

                        # 如果深度还没到最大，继续查询子社区
                        if depth_level < d - 2:
                            grandchild_rows = project_db.execute(
                                "SELECT comm_id, node_list, edge_list, node_count FROM graph_doc WHERE task_id=? AND edge_type=? AND parent_comm_id=?",
                                (tid, et, child_comm_id)
                            ).fetchall()
                            child_rows = grandchild_rows
                        else:
                            # 最深层，直接添加符号节点（CALL 类型先汇聚到文件级）
                            if et == 'CALL':
                                agg_ids, agg_labels_map, agg_edges = aggregate_to_files(child_node_list, child_edge_list)
                                for node in agg_ids:
                                    nodes.append({
                                        'id': f'n_{child_comm_id}_{node}',
                                        'label': agg_labels_map.get(node, str(node)),
                                        'refId': node_ref_id(node),
                                        'fileId': node_file_id(node),
                                        'filePath': node_file_path(node),
                                        'comm_id': child_comm_id,
                                        'type': 'symbol',
                                    })
                                for s, t in agg_edges:
                                    edges.append({
                                        'id': f'e_{child_comm_id}_{s}_{t}',
                                        'source': f'n_{child_comm_id}_{s}',
                                        'target': f'n_{child_comm_id}_{t}',
                                        'sourceLabel': agg_labels_map.get(s) or node_display(s),
                                        'targetLabel': agg_labels_map.get(t) or node_display(t),
                                        'sourceRefId': node_ref_id(s),
                                        'targetRefId': node_ref_id(t),
                                        'type': et,
                                    })
                            else:
                                for node in child_node_list:
                                    nodes.append({
                                        'id': f'n_{child_comm_id}_{node}',
                                        'label': node_display(node),
                                        'refId': node_ref_id(node),
                                        'fileId': node_file_id(node),
                                        'filePath': node_file_path(node),
                                        'comm_id': child_comm_id,
                                        'type': 'symbol',
                                    })
                                for edge in (child_edge_list or []):
                                    if isinstance(edge, list) and len(edge) >= 2:
                                        edges.append({
                                            'id': f'e_{child_comm_id}_{edge[0]}_{edge[1]}',
                                            'source': f'n_{child_comm_id}_{edge[0]}',
                                            'target': f'n_{child_comm_id}_{edge[1]}',
                                            'sourceLabel': node_display(edge[0]),
                                            'targetLabel': node_display(edge[1]),
                                            'sourceRefId': node_ref_id(edge[0]),
                                            'targetRefId': node_ref_id(edge[1]),
                                            'type': et or 'CALL',
                                        })
                            break

        return {
            'nodes': nodes,
            'edges': edges,
            'communities': communities,
        }

    @server.register("analysis.getSymbolDetail")
    def get_symbol_detail(task_id=None, taskId=None, symbol_id=None, symbolId=None):
        """获取符号详情 + 代码抽样"""
        tid = task_id or taskId
        sid = symbol_id or symbolId
        if not tid or not sid:
            raise ValueError("task_id and symbol_id are required")

        # 从主库获取任务所属项目
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]

        project_db = multi_db.get_project_db(project_id)

        # 查询符号信息
        row = project_db.execute(
            "SELECT kind, name, qualified_name, file_id FROM graph_node WHERE task_id=? AND id=?",
            (tid, sid)
        ).fetchone()

        if not row:
            # 尝试按名称搜索
            row = project_db.execute(
                "SELECT kind, name, qualified_name, file_id FROM graph_node WHERE task_id=? AND (name=? OR qualified_name=?)",
                (tid, sid, sid)
            ).fetchone()

        if not row:
            return None

        symbol_type = row[0]
        name = row[1]
        qualified_name = row[2]
        file_id = row[3]

        # 获取文件路径
        file_path = ''
        if file_id:
            file_row = project_db.execute(
                "SELECT file_path FROM source_files WHERE id=?",
                (file_id,)
            ).fetchone()
            file_path = file_row[0] if file_row else ''

        # 查询 graph_node 获取行号
        start_line = 1
        end_line = 20
        ast_row = project_db.execute(
            "SELECT start_line, end_line FROM graph_node WHERE file_id=? AND name=? LIMIT 1",
            (file_id, name or qualified_name)
        ).fetchone()

        if ast_row:
            try:
                start_line = int(ast_row[0])
                end_line = int(ast_row[1])
            except (ValueError, IndexError):
                pass

        # 读取代码抽样（最多 20 行）
        code_snippet = ''
        if file_path and start_line and end_line:
            try:
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    lines = f.readlines()
                    snippet_start = max(0, start_line - 1)
                    snippet_end = min(len(lines), end_line)
                    code_snippet = ''.join(lines[snippet_start:snippet_end])
            except (FileNotFoundError, PermissionError):
                pass

        # 判断是否需要 LLM 压缩
        needs_summarize = len(code_snippet) > 500

        return {
            'symbol_id': sid,
            'symbol_type': symbol_type,
            'name': name or qualified_name or sid,
            'class_name': '',
            'file_path': file_path,
            'start_line': start_line,
            'end_line': end_line,
            'code_snippet': code_snippet,
            'needs_summarize': needs_summarize,
        }

    @server.register("analysis.getEdgeDetail")
    def get_edge_detail(task_id=None, taskId=None, edge_id=None, edgeId=None):
        """获取边详情"""
        tid = task_id or taskId
        eid = edge_id or edgeId
        if not tid or not eid:
            raise ValueError("task_id and edge_id are required")

        # 从主库获取任务所属项目
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]

        project_db = multi_db.get_project_db(project_id)

        # 从 edge_id 解析 source 和 target
        # edge_id 格式: e_source_target
        parts = eid.replace('e_', '').rsplit('_', 1)
        if len(parts) != 2:
            return None

        source_id, target_id = parts

        # 查询边的信息
        row = project_db.execute(
            "SELECT kind, source_id, target_id, provenance, line, col, file_path, metadata FROM graph_edge WHERE task_id=? AND id=?",
            (tid, eid)
        ).fetchone()

        if not row:
            # 尝试通过 source/target 查找
            row = project_db.execute(
                "SELECT kind, source_id, target_id, provenance, line, col, file_path, metadata FROM graph_edge WHERE task_id=? AND (source_id=? OR target_id=?)",
                (tid, source_id, target_id)
            ).fetchone()

        if not row:
            return None

        kind = row[0]

        if kind == 'calls':
            return {
                'edge_id': eid,
                'edge_type': 'CALL',
                'source': {
                    'name': row[1],  # source_id
                    'file_id': row[1],  # source_id
                },
                'target': {
                    'name': row[2],  # target_id
                    'file_id': row[2],  # target_id
                },
                'call_site_node_id': None,
            }
        elif kind == 'imports':
            return {
                'edge_id': eid,
                'edge_type': 'DEPENDENCE',
                'include_path': row[6],
                'is_system': False,
            }

        return None

    # ==================== 级联社区查询 ====================

    @server.register("analysis.getReportDashboard")
    def get_report_dashboard(task_id=None, taskId=None):
        """获取报告仪表盘数据：任务详情 + 社区层级 + LLM 结果 + 文件统计（一次调用）
        用于 ReportHome 页面初始加载，替代多次独立 RPC 调用
        """
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        t_total = time.perf_counter()
        logger.info("[analysis.getReportDashboard] ENTRY task_id=%s", tid)

        t0 = time.perf_counter()
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            return None
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        logger.info("[PERF] getReportDashboard load_task=%.1fms", (time.perf_counter() - t0) * 1000)

        # 1. 获取级联社区层级 (CALL + INCLUDE)
        t0 = time.perf_counter()
        call_levels = _get_cascade_levels_impl(project_db, tid, 'CALL')
        t_call = time.perf_counter() - t0
        t0 = time.perf_counter()
        dep_levels = _get_cascade_levels_impl(project_db, tid, 'INCLUDE')
        t_dep = time.perf_counter() - t0
        logger.info("[PERF] getReportDashboard cascade_levels CALL=%.1fms INCLUDE=%.1fms", t_call * 1000, t_dep * 1000)

        # 2. 获取 LLM 结果
        t0 = time.perf_counter()
        call_results = _list_community_results_impl(project_db, tid, 'CALL')
        t_call_res = time.perf_counter() - t0
        t0 = time.perf_counter()
        dep_results = _list_community_results_impl(project_db, tid, 'INCLUDE')
        t_dep_res = time.perf_counter() - t0
        logger.info("[PERF] getReportDashboard llm_results CALL=%.1fms INCLUDE=%.1fms", t_call_res * 1000, t_dep_res * 1000)

        # 3. 获取文件统计
        t0 = time.perf_counter()
        file_stats = _scan_file_stats_impl(project_db, pid)
        logger.info("[PERF] getReportDashboard file_stats=%.1fms", (time.perf_counter() - t0) * 1000)

        # 4. 预摘要状态
        pre_summary = {'counts': {'P0': 0, 'P1': 0, 'P2': 0, 'P4': 0}, 'total_files': 0, 'cached_count': 0, 'project_root': '', 'failed_count': _ps_failed_counts.get(tid, 0)}
        try:
            # 从 file_summaries 表直接统计缓存数（无社区数据时也能工作）
            p_rows = project_db.execute(
                "SELECT COUNT(*) as cnt FROM file_summaries WHERE project_id=?", (pid,)
            ).fetchone()
            cached = p_rows["cnt"] if p_rows else 0
            pre_summary['cached_count'] = cached

            # 尝试从社区计算总分批次（可能无社区数据，此时总文件数为 0）
            comps = _get_l0_comps(project_db, tid)
            project_root = _get_project_root(pid)
            rank_data = _compute_file_ranks(tid, project_db, comps, project_root)
            if rank_data:
                pre_summary['counts'] = rank_data.get("counts", {'P0': 0, 'P1': 0, 'P2': 0})
                pre_summary['total_files'] = len(rank_data.get("files", []))
            pre_summary['project_root'] = project_root
        except Exception as e:
            logger.warning("[getReportDashboard] preSummary failed: %s", e)

        logger.info("[PERF] getReportDashboard TOTAL=%.1fms task_id=%s", (time.perf_counter() - t_total) * 1000, tid)
        logger.info("[analysis.getReportDashboard] DONE task_id=%s", tid)
        return {
            'task': task,
            'callLevels': call_levels,
            'depLevels': dep_levels,
            'callResults': call_results,
            'depResults': dep_results,
            'fileStats': file_stats,
            'preSummary': pre_summary,
        }

    def _get_cascade_levels_impl(project_db, tid, et):
        """getCascadeLevels 内部实现（无 RPC 注册）"""
        t_sql = time.perf_counter()
        try:
            rows = project_db.execute(
                """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                           h.file_count, h.quality_score, h.edge_count,
                           (SELECT g.metadata FROM graph_doc g
                            WHERE g.task_id = h.task_id AND g.edge_type = h.edge_type AND g.comm_id = h.comm_id
                            LIMIT 1) AS metadata
                    FROM community_hierarchy h
                    WHERE h.task_id=? AND h.edge_type=?
                    ORDER BY h.comm_lv, h.comm_id""",
                (tid, et)
            ).fetchall()
            has_file_count = True
        except Exception as e:
            if 'file_count' not in str(e).lower() and 'no such column' not in str(e).lower():
                raise
            has_file_count = False
            rows = project_db.execute(
                """SELECT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count,
                           h.quality_score, h.edge_count
                   FROM community_hierarchy h
                   WHERE h.task_id=? AND h.edge_type=?
                   ORDER BY h.comm_lv, h.comm_id""",
                (tid, et)
            ).fetchall()
        logger.info("[PERF] cascade_sql %s rows=%d %.1fms", et, len(rows), (time.perf_counter() - t_sql) * 1000)

        levels_dict = {}
        for row in rows:
            if has_file_count:
                lv, comm_id, parent_id, node_count, file_count, quality, edge_count, metadata_raw = row
            else:
                lv, comm_id, parent_id, node_count, quality, edge_count = row
                file_count = 0
                metadata_raw = None
            metadata = {}
            if metadata_raw:
                try:
                    metadata = json.loads(metadata_raw)
                except (json.JSONDecodeError, TypeError):
                    pass
            if lv not in levels_dict:
                levels_dict[lv] = []
            levels_dict[lv].append({
                'id': comm_id, 'label': comm_id[:30], 'parentCommId': parent_id,
                'nodeCount': node_count or 0, 'fileCount': file_count or 0,
                'edgeCount': edge_count or 0, 'qualityScore': quality,
                'metadata': metadata,
            })

        # 1. 社区级别的文件覆盖（L0 node_list 去重）—— 精确但偏保守
        community_files = 0
        try:
            rows = project_db.execute(
                "SELECT node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv='L0'",
                (tid, et)).fetchall()
            if rows:
                uniq = set()
                for r in rows:
                    nl = json.loads(r[0]) if r[0] else []
                    for nid in nl:
                        uniq.add(str(nid))
                community_files = len(uniq)
        except Exception:
            pass

        # 2. 边级别的文件覆盖（所有有 resolved 边参与的文件）—— 避免同类文件调用、孤立节点被过滤后的低估
        edge_files = community_files
        if et in ('CALL', 'INCLUDE'):
            edge_kind = 'calls' if et == 'CALL' else 'imports'
            try:
                t_edge = time.perf_counter()
                rows = project_db.execute(
                    f"""SELECT DISTINCT COALESCE(gn.file_path, ge.source_id) as fp
                        FROM graph_edge ge
                        LEFT JOIN graph_node gn ON gn.id = ge.source_id AND gn.task_id = ge.task_id
                        WHERE ge.task_id=? AND ge.kind=? AND ge.target_id != ''
                        UNION
                        SELECT DISTINCT COALESCE(gn.file_path, ge.target_id) as fp
                        FROM graph_edge ge
                        LEFT JOIN graph_node gn ON gn.id = ge.target_id AND gn.task_id = ge.task_id
                        WHERE ge.task_id=? AND ge.kind=? AND ge.target_id != ''""",
                    (tid, edge_kind, tid, edge_kind)
                ).fetchall()
                edge_files = len(rows)
                logger.info("[PERF] cascade_edge_files %s count=%d %.1fms",
                           et, edge_files, (time.perf_counter() - t_edge) * 1000)
            except Exception:
                pass

        # 使用边级计数作为 totalUniqueFiles（更准确反映"有调用/依赖关系的文件数"）
        total_unique = max(community_files, edge_files)

        result = []
        for lv in sorted(levels_dict.keys()):
            result.append({'lv': lv, 'items': levels_dict[lv]})
        return {'levels': result, 'totalUniqueFiles': total_unique}

    def _list_community_results_impl(project_db, tid, et):
        """listCommunityResults 内部实现"""
        try:
            rows = project_db.execute(
                "SELECT * FROM community_llm_results WHERE task_id=? AND edge_type=? ORDER BY comm_lv, comm_id",
                (tid, et)).fetchall()
            return {'results': [dict(r) for r in rows]}
        except Exception:
            return {'results': []}

    def _scan_file_stats_impl(project_db, pid):
        """scanFileStats 内部实现"""
        files = project_db.fetchall(
            "SELECT file_path, file_name, language, size FROM source_files WHERE language != 'directory' ORDER BY file_path")
        extensions = {}
        for f in files:
            lang = f.get("language", "unknown")
            extensions[lang] = extensions.get(lang, 0) + 1
        return {
            'extensions': extensions,
            'totalFiles': len(files),
            'totalDirs': 0,
            'directories': [],
        }

    @server.register("analysis.getCascadeLevels")
    def get_cascade_levels(task_id=None, taskId=None, edge_type=None, edgeType=None):
        """获取级联社区层级结构
        返回格式: {levels: [{lv: 'L0', items: [{id, label, nodeCount, parentCommId}]}]}
        """
        tid = task_id or taskId
        et = edge_type or edgeType or 'CALL'
        if not tid:
            raise ValueError("task_id is required")
        logger.info("[analysis.getCascadeLevels] ENTRY task_id=%s edge_type=%s", tid, et)

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            logger.warning("[analysis.getCascadeLevels] task not found task_id=%s", tid)
            return {"levels": []}
        project_db = multi_db.get_project_db(task["project_id"])

        result = _get_cascade_levels_impl(project_db, tid, et)
        logger.info("[analysis.getCascadeLevels] DONE task_id=%s edge_type=%s", tid, et)
        return result

    @server.register("analysis.getQueryStats")
    def get_query_stats(task_id=None, taskId=None, edge_type=None, edgeType=None,
                        comm_lv=None, commLv=None, comm_ids=None, commIds=None,
                        depth=None):
        """获取查询统计: 社区数、节点数、边数"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'CALL'
        cl = comm_lv or commLv
        cids = comm_ids or commIds or []
        d = depth or 1

        if not tid or not cl:
            raise ValueError("task_id and comm_lv are required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]
        project_db = multi_db.get_project_db(project_id)

        # 收集所有需要查询的社区ID(含深度展开)
        all_comm_ids = set(cids) if cids else set()

        # 如果不指定社区, 查询该层级所有社区
        if not all_comm_ids:
            rows = project_db.execute(
                "SELECT comm_id FROM community_hierarchy WHERE task_id=? AND edge_type=? AND comm_lv=?",
                (tid, et, cl)
            ).fetchall()
            all_comm_ids = {row[0] for row in rows}

        # 深度展开子社区
        if d and d > 1:
            current_ids = set(all_comm_ids)
            for _ in range(d - 1):
                placeholders = ','.join(['?' for _ in current_ids])
                child_rows = project_db.execute(
                    f"SELECT comm_id FROM community_hierarchy WHERE task_id=? AND edge_type=? AND parent_comm_id IN ({placeholders})",
                    [tid, et] + list(current_ids)
                ).fetchall()
                new_ids = {row[0] for row in child_rows}
                all_comm_ids.update(new_ids)
                current_ids = new_ids
                if not new_ids:
                    break

        # 统计
        total_nodes = 0
        total_edges = 0
        community_count = len(all_comm_ids)

        if all_comm_ids:
            placeholders = ','.join(['?' for _ in all_comm_ids])
            doc_rows = project_db.execute(
                f"SELECT node_count, edge_count FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id IN ({placeholders})",
                [tid, et] + list(all_comm_ids)
            ).fetchall()
            for row in doc_rows:
                total_nodes += row[0] or 0
                total_edges += row[1] or 0

        return {
            'communityCount': community_count,
            'nodeCount': total_nodes,
            'edgeCount': total_edges,
        }

    @server.register("analysis.getCrossCommunityEdges")
    def get_cross_community_edges(task_id=None, taskId=None,
                                   edge_type=None, edgeType=None,
                                   comm_lv=None, commLv=None):
        """获取指定层级社区间的跨社区边（聚合计数）"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'INCLUDE'
        lv = comm_lv or commLv or 'L0'

        if not tid:
            raise ValueError("task_id is required")

        t_total = time.perf_counter()

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)

        # 获取项目根路径（用于归一化 edge 中的绝对路径）
        proj_row = multi_db.main_db.fetchone(
            "SELECT root_path FROM projects WHERE id = ?", (pid,)
        )
        project_root = (proj_row["root_path"] + "/") if proj_row and proj_row["root_path"] else ""

        edge_kind = 'calls' if et == 'CALL' else 'imports'

        # 1. Load all communities at the given level for this edge_type
        doc_rows = project_db.execute(
            "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=?",
            (tid, et, lv)
        ).fetchall()

        if not doc_rows:
            logger.info(f"[PERF] getCrossCommunityEdges TOTAL=%.1fms (no communities)",
                       (time.perf_counter() - t_total) * 1000)
            return {'crossEdges': []}

        # 2. Build node → comm_id reverse map
        # graph_doc.node_list contains file paths (without 'file:' prefix) for INCLUDE,
        # and file paths for CALL communities (after community detection aggregation).
        # graph_edge.source_id/target_id for 'imports' uses 'file:/path' format,
        # for 'calls' uses symbol hash IDs → need to resolve to file_path via graph_node.
        node_comm = {}  # normalized_key → comm_id

        for row in doc_rows:
            comm_id = row[0]
            try:
                nodes = json.loads(row[1]) if row[1] else []
            except Exception:
                nodes = []
            for nid in nodes:
                key = nid  # already a file path for INCLUDE, may be file path for CALL too
                node_comm[key] = comm_id

        logger.info(f"[getCrossCommunityEdges] loaded {len(node_comm)} nodes across {len(doc_rows)} communities")

        # 3. Load all edges for the task
        all_edges = project_db.execute(
            "SELECT source_id, target_id FROM graph_edge WHERE task_id=? AND kind=?",
            (tid, edge_kind)
        ).fetchall()

        # For CALL, pre-load symbol→file_path mapping (batch query from graph_node)
        symbol_file_map = {}
        if edge_kind == 'calls':
            # collect all unique symbol IDs from edges
            sym_ids = set()
            for edge in all_edges:
                if edge[0]: sym_ids.add(edge[0])
                if edge[1]: sym_ids.add(edge[1])
            if sym_ids:
                # batch lookup in chunks of 999 (SQLite variable limit)
                sym_list = list(sym_ids)
                batch_size = 900
                for i in range(0, len(sym_list), batch_size):
                    batch = sym_list[i:i + batch_size]
                    placeholders = ','.join(['?'] * len(batch))
                    rows = project_db.execute(
                        f"SELECT id, file_path FROM graph_node WHERE task_id=? AND id IN ({placeholders})",
                        [tid] + batch
                    ).fetchall()
                    for r in rows:
                        symbol_file_map[r[0]] = r[1] or ''

        def _rel(p: str) -> str:
            """将可能的绝对路径转为项目相对路径（匹配 node_list 格式）"""
            if not p:
                return p
            if p.startswith('file:'):
                p = p[5:]
            if project_root and p.startswith(project_root):
                p = p[len(project_root):]
            return p.lstrip('/')

        # 4. Resolve edge source/target to community keys
        def resolve_key(raw_id, edge_kind, sym_map, file_comm):
            """Resolve an edge endpoint to a community-matching key."""
            if not raw_id:
                return None
            if edge_kind == 'imports':
                key = _rel(raw_id)
                return file_comm.get(key)
            else:  # calls
                # resolve symbol ID → file_path, then match file_path in node_comm
                fpath = sym_map.get(raw_id, '')
                if fpath:
                    fpath_rel = _rel(fpath)
                    if fpath_rel in file_comm:
                        return file_comm[fpath_rel]
                # fallback: try direct lookup (some CALL node_lists may use symbol IDs)
                if raw_id in file_comm:
                    return file_comm[raw_id]
                return None

        # 5. Aggregate cross-community edges
        cross_map = {}  # (source_comm, target_comm) → count
        for edge in all_edges:
            src = edge[0] or ''
            tgt = edge[1] or ''
            if not src or not tgt:
                continue
            src_comm = resolve_key(src, edge_kind, symbol_file_map, node_comm)
            tgt_comm = resolve_key(tgt, edge_kind, symbol_file_map, node_comm)
            if not src_comm or not tgt_comm:
                continue
            if src_comm == tgt_comm:
                continue
            pair = (src_comm, tgt_comm)
            cross_map[pair] = cross_map.get(pair, 0) + 1

        cross_edges = [
            {'sourceCommId': p[0], 'targetCommId': p[1], 'edgeCount': cnt}
            for p, cnt in sorted(cross_map.items(), key=lambda x: -x[1])
        ]

        logger.info("[PERF] getCrossCommunityEdges TOTAL=%.1fms communities=%d crossEdges=%d edges=%d",
                   (time.perf_counter() - t_total) * 1000,
                   len(doc_rows), len(cross_edges), len(all_edges))

        return {'crossEdges': cross_edges}

    @server.register("analysis.getExternalStats")
    def get_external_stats(task_id=None, taskId=None):
        """获取外部依赖/调用统计: 从已有数据聚合，不需社区分析"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        t_total = time.perf_counter()

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)

        # ── 诊断: 打印任务和项目信息 ──
        try:
            node_kinds = project_db.execute(
                "SELECT kind, COUNT(*) FROM graph_node WHERE task_id=? GROUP BY kind",
                (tid,)
            ).fetchall()
            edge_kinds = project_db.execute(
                "SELECT kind, COUNT(*) FROM graph_edge WHERE task_id=? GROUP BY kind",
                (tid,)
            ).fetchall()
            logger.info("[DIAG] getExternalStats task=%s pid=%s graph_node=%s graph_edge=%s",
                       tid, pid, dict(node_kinds), dict(edge_kinds))
        except Exception as e:
            logger.warning(f"[DIAG] getExternalStats schema query failed: {e}")

        # 1. 外部依赖 — 导入名无对应 INCLUDE 边的（按文件匹配）
        #    避免相关子查询: 先批量加载已解析导入，再 Python 差集过滤
        dep_rows = []
        import_count = 0
        resolved_count = 0
        t_dep_sql = time.perf_counter()
        try:
            # 加载所有 import 节点
            import_nodes = project_db.execute(
                "SELECT name, file_path FROM graph_node WHERE task_id = ? AND kind = 'import'",
                (tid,)
            ).fetchall()
            import_count = len(import_nodes)

            # 加载已解析的 (source_file, module) 对
            resolved_pairs = set()
            edge_rows = project_db.execute(
                """SELECT gn_src.file_path, json_extract(ge.metadata, '$.module')
                   FROM graph_edge ge
                   JOIN graph_node gn_src ON gn_src.id = ge.source_id AND gn_src.task_id = ge.task_id
                   WHERE ge.task_id = ? AND ge.kind = 'imports'""",
                (tid,)
            ).fetchall()
            resolved_count = len(edge_rows)
            for er in edge_rows:
                fp = er[0] or ""
                mod = er[1] or ""
                if fp and mod:
                    resolved_pairs.add((fp, mod))

            # 过滤：未出现在 resolved_pairs 中的 import 视为外部依赖
            for imp in import_nodes:
                pkg = imp[0] or ""
                fp = imp[1] or ""
                if not pkg:
                    continue
                if (fp, pkg) not in resolved_pairs:
                    dep_rows.append((pkg, fp))
        except Exception as e:
            logger.error(f"[DIAG] getExternalStats deps query failed: {e}", exc_info=True)
            dep_rows = []
        logger.info("[PERF] getExternalStats deps_sql imported=%d resolved_edges=%d external=%d %.1fms",
                   import_count, resolved_count, len(dep_rows),
                   (time.perf_counter() - t_dep_sql) * 1000)

        dep_map = {}
        for row in dep_rows:
            pkg = row[0] or ""
            fp = row[1] or ""
            if not pkg:
                continue
            if pkg not in dep_map:
                dep_map[pkg] = {"package": pkg, "fileCount": 0, "files": []}
            dep_map[pkg]["fileCount"] += 1
            # 去重（同文件可能多次 import 同一包）
            if fp not in dep_map[pkg]["files"]:
                dep_map[pkg]["files"].append(fp)

        external_deps = sorted(dep_map.values(), key=lambda x: -x["fileCount"])
        # 限制返回前 100
        external_deps = external_deps[:100]

        # 2. 外部调用 — 未解析的调用边
        calls_sql = """
            SELECT ge.source_id, gn.file_path, ge.metadata
            FROM graph_edge ge
            LEFT JOIN graph_node gn ON gn.id = ge.source_id AND gn.task_id = ge.task_id
            WHERE ge.task_id = ? AND ge.kind = 'calls' AND ge.target_id = ''
        """
        t_call_sql = time.perf_counter()
        try:
            call_rows = project_db.execute(calls_sql, (tid,)).fetchall()
        except Exception as e:
            logger.error(f"[DIAG] getExternalStats calls query failed: {e}", exc_info=True)
            call_rows = []
        logger.info("[PERF] getExternalStats calls_sql rows=%d %.1fms", len(call_rows), (time.perf_counter() - t_call_sql) * 1000)

        project_root = ""
        try:
            root_row = multi_db.main_db.execute(
                "SELECT root_path FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            if root_row and root_row["root_path"]:
                project_root = os.path.abspath(root_row["root_path"])
        except Exception:
            pass

        call_map = {}
        for row in call_rows:
            sid = row[0] or ""
            fp = row[1] or sid
            meta_str = row[2] or "{}"
            try:
                meta = json.loads(meta_str)
            except Exception:
                meta = {}
            call_name = meta.get("expression") or meta.get("callee") or ""
            if not call_name:
                # fallback: use source file abbreviation for readability
                if sid.startswith("file:"):
                    basename = os.path.basename(sid)
                    # __init__.py / __init__.ts → 用父目录名代替，避免大量调用归入无意义名称
                    if basename in ("__init__.py", "__init__.ts", "__init__.js",
                                    "index.ts", "index.js", "index.tsx", "index.jsx"):
                        parent_dir = os.path.basename(os.path.dirname(sid.replace("file:", "", 1)))
                        call_name = parent_dir or basename
                    else:
                        call_name = basename
                elif fp and fp != sid:
                    call_name = os.path.relpath(fp, project_root) if os.path.isabs(fp) else fp
                else:
                    call_name = sid[:16]
            if call_name not in call_map:
                call_map[call_name] = {"name": call_name, "count": 0, "files": []}
            call_map[call_name]["count"] += 1
            if fp not in call_map[call_name]["files"]:
                call_map[call_name]["files"].append(fp)

        external_calls = sorted(call_map.values(), key=lambda x: -x["count"])
        external_calls = external_calls[:100]

        # 总数统计
        total_ext_deps = len(dep_rows)
        unique_ext_dep_files = len(set(row[1] for row in dep_rows if row[1]))
        total_ext_calls = len(call_rows)
        unique_ext_call_files = len(set(
            row[1] if row[1] else row[0] for row in call_rows
        ))

        # 附加: 文件 → L0 社区归属映射 (用于前端外部依赖/调用 graph 视图)
        try:
            t_comm = time.perf_counter()

            def _build_file_comm(edge_type):
                """file_path → [{communityId}] for given edge_type's L0 communities"""
                rows = project_db.execute(
                    "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv='L0'",
                    (tid, edge_type)
                ).fetchall()
                file_comm = {}
                for row in rows:
                    cid = row[0]
                    try:
                        nodes = json.loads(row[1]) if row[1] else []
                    except Exception:
                        nodes = []
                    for fp in nodes:
                        if not fp:
                            continue
                        if fp not in file_comm:
                            file_comm[fp] = []
                        already = any(c['communityId'] == cid for c in file_comm[fp])
                        if not already:
                            file_comm[fp].append({'communityId': cid})
                return file_comm

            include_file_comm = _build_file_comm('INCLUDE')
            call_file_comm    = _build_file_comm('CALL')

            # 批量加载社区 LLM 名称
            name_rows = project_db.execute(
                "SELECT comm_id, name FROM community_llm_results WHERE task_id=? AND comm_lv='L0'",
                (tid,)
            ).fetchall()
            comm_names = {row[0]: row[1] for row in name_rows if row[1]}

            def _inject_communities(items, file_comm):
                for item in items:
                    item_files = item.get('files', [])
                    item_comms = []
                    seen_cids = set()
                    for f in item_files:
                        for c in file_comm.get(f, []):
                            cid = c['communityId']
                            if cid not in seen_cids:
                                seen_cids.add(cid)
                                item_comms.append({
                                    'communityId': cid,
                                    'name': comm_names.get(cid) or None,
                                })
                    item['communities'] = item_comms

            _inject_communities(external_deps, include_file_comm)
            _inject_communities(external_calls, call_file_comm)

            logger.info("[PERF] getExternalStats community map build=%.1fms",
                       (time.perf_counter() - t_comm) * 1000)
        except Exception as e:
            logger.warning(f"[getExternalStats] community mapping failed: {e}")

        logger.info("[PERF] getExternalStats TOTAL=%.1fms deps=%d calls=%d",
                   (time.perf_counter() - t_total) * 1000,
                   total_ext_deps, total_ext_calls)

        return {
            'externalDeps': external_deps,
            'externalCalls': external_calls,
            'totalExternalDeps': total_ext_deps,
            'uniqueExternalDepFiles': unique_ext_dep_files,
            'totalExternalCalls': total_ext_calls,
            'uniqueExternalCallFiles': unique_ext_call_files,
        }

    @server.register("analysis.getCommunityNodeLists")
    def get_community_node_lists(task_id=None, taskId=None, edge_type=None, edgeType=None,
                                  comm_lv=None, commLv=None):
        """返回指定层级+edge_type 下所有社区的文件路径列表。
        返回格式: { communityId: [filePath, ...] }"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'INCLUDE'
        lv = comm_lv or commLv
        if not tid or not lv:
            raise ValueError("task_id and comm_lv are required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])

        rows = project_db.execute(
            "SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_lv=?",
            (tid, et, lv)
        ).fetchall()
        result = {}
        for row in rows:
            cid = row[0]
            try:
                nodes = json.loads(row[1]) if row[1] else []
            except Exception:
                nodes = []
            result[cid] = [str(n) for n in nodes if n]
        return result

    @server.register("analysis.getCommunityFileGraph")
    def get_community_file_graph(task_id=None, taskId=None, edge_type=None, edgeType=None,
                                  comm_id=None, commId=None):
        """返回叶子社区的文件级图数据（节点 + 边），来自 graph_doc 的 node_list / edge_list。"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'INCLUDE'
        cid = comm_id or commId
        if not tid or not cid:
            raise ValueError("task_id and comm_id are required")
        task = TaskStore(multi_db.main_db).get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_db = multi_db.get_project_db(task["project_id"])
        row = project_db.execute(
            "SELECT node_list, edge_list FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id=?",
            (tid, et, cid)
        ).fetchone()
        if not row:
            return {"nodes": [], "edges": []}
        file_nodes = set()
        try:
            raw_nodes = json.loads(row["node_list"]) if row["node_list"] else []
            file_nodes = {str(n) for n in raw_nodes if n}
        except Exception:
            pass
        file_edges = []
        try:
            raw_edges = json.loads(row["edge_list"]) if row["edge_list"] else []
            for e in raw_edges:
                src = str(e.get("source", ""))
                tgt = str(e.get("target", ""))
                if src and tgt:
                    file_edges.append({"source": src, "target": tgt,
                                       "direction": e.get("direction", "")})
        except Exception:
            pass
        nodes = []
        for fp in sorted(file_nodes):
            fname = fp.rstrip("/").split("/")[-1] if "/" in fp else fp
            nodes.append({"id": fp, "label": fname, "filePath": fp})
        return {"nodes": nodes, "edges": file_edges}

    # ==================== 架构 Agent 操作 ====================

    def _get_project_root(pid):
        try:
            root_row = multi_db.main_db.execute(
                "SELECT root_path FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            result = root_row["root_path"] if root_row else ""
            return str(result or "")
        except Exception as e:
            logger.warning("[_get_project_root] FAILED pid=%r error=%s", pid, e)
            return ""

    def _get_project_summary(pid):
        try:
            row = multi_db.main_db.execute(
                "SELECT summary FROM projects WHERE id = ?", (pid,)
            ).fetchone()
            return str(row["summary"] or "") if row else ""
        except Exception:
            return ""

    def _make_agent_history_cb(project_id, project_db, task_id, action):
        from store.analysis_store import AnalysisStore
        import json as _json
        def _cb(state_dict):
            try:
                s = AnalysisStore(project_db)
                import datetime as _dt
                def _ts(v):
                    try: return _dt.datetime.fromtimestamp(v).isoformat() if v else None
                    except: return None
                steps_str = _json.dumps(state_dict.get("steps", []), ensure_ascii=False)
                s.save_agent_task_history({
                    "project_id": project_id,
                    "task_id": task_id,
                    "agent_id": state_dict["agent_id"],
                    "action": action,
                    "status": state_dict["status"],
                    "steps": steps_str,
                    "message": state_dict.get("message", ""),
                    "error": state_dict.get("error", ""),
                    "created_at": _ts(state_dict.get("created_at")),
                    "finished_at": _ts(state_dict.get("finished_at")),
                })
            except Exception as e:
                logger.warning(f"[AgentHistory] save failed for {state_dict.get('agent_id', '?')}: {e}")
        return _cb

    @server.register("analysis.startOverview")
    def start_overview(task_id=None, taskId=None, force=False):
        """启动整体架构概览生成 (OverviewWorkflow 入口)"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        logger.info(f"[startOverview] task_id={tid}")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = _get_project_root(pid)
        project_summary = _get_project_summary(pid)
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
                    missing.append(f"{et} {lv}: {analyzed}/{comm_count} 未分析")
        if missing:
            raise ValueError(f"前置依赖不满足: {'; '.join(missing)}。请先用 /analyze_components 分析后再试。")

        # ── 检查是否已生成（跳过）──
        if not force:
            existing = project_db.execute(
                "SELECT id FROM report_subdocs WHERE task_id=? AND comm_id='overall' AND (title='架构概览文档' OR template_id='overview')",
                (tid,)
            ).fetchone()
            if existing:
                logger.info(f"[startOverview] overview already exists, skipping (use --force to regenerate)")
                return {"taskId": tid, "success": True, "agentTaskId": None, "skipped": True}

        # ── 构建上下文 ──
        from agent_workflow.router import create_default_router
        router = create_default_router(
            project_root=project_root, project_db=project_db, multi_db=multi_db,
            task_id=tid, project_summary=project_summary,
        )
        context = {
            "task_id": tid, "project_id": pid,
            "project_name": project_name,
            "project_summary": project_summary,
        }

        # ── 完成回调：保存概览文档 ──
        def _on_overview_complete(state_dict):
            _make_agent_history_cb(pid, project_db, tid, "overview")(state_dict)
            try:
                overview = (state_dict.get("result") or {}).get("overview", "")
                if overview:
                    from report_tree_service import save_overall_doc
                    save_overall_doc(multi_db, tid, "架构概览文档", overview)
                    logger.info(f"[startOverview] saved overview doc for task {tid}, len={len(overview)}")
            except Exception as e:
                logger.warning(f"[startOverview] failed to save overview doc: {e}")

        agent_id = router.dispatch("overview", tid, context,
            on_complete=_on_overview_complete)

        return {"taskId": tid, "success": True, "agentTaskId": agent_id, "skipped": False}

    @server.register("analysis.getAgentProgress")
    def get_agent_progress(agent_task_id=None, agentTaskId=None):
        aid = agent_task_id or agentTaskId
        if not aid:
            raise ValueError("agent_task_id is required")
        from agent_workflow.agent_queue import get_global_queue
        queue = get_global_queue()
        result = queue.get_progress(aid)
        if not result:
            return {"found": False}
        return {**result, "found": True}

    @server.register("analysis.cancelAgentTask")
    def cancel_agent_task(agent_task_id=None, agentTaskId=None):
        aid = agent_task_id or agentTaskId
        if not aid:
            raise ValueError("agent_task_id is required")
        from agent_workflow.agent_queue import get_global_queue
        queue = get_global_queue()
        ok = queue.cancel(aid)
        return {"cancelled": ok}

    @server.register("analysis.getAgentTaskHistory")
    def get_agent_task_history(task_id=None, taskId=None, offset=0, limit=10):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        from store.analysis_store import AnalysisStore
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
        from store.analysis_store import AnalysisStore
        s = AnalysisStore(project_db)
        s.clear_agent_task_history(pid, tid)
        return {"success": True}

    # ==================== 文件预摘要 ====================

    def _resolve_node_list_items(items: list, task_id: str, project_db) -> dict[str, list[str]]:
        """批量将 node_list 条目解析为文件路径。返回 item → [resolved_path] 映射。"""
        import os as _os
        result: dict[str, list[str]] = {}
        unresolved_ids: list[str] = []
        for item in items:
            if not item or not isinstance(item, str):
                continue
            if _os.path.isabs(item) or '/' in item:
                result[item] = [item]
            else:
                unresolved_ids.append(item)
        if unresolved_ids:
            placeholders = ",".join("?" for _ in unresolved_ids)
            try:
                for row in project_db.execute(
                    f"SELECT id, file_path FROM graph_node WHERE id IN ({placeholders}) AND task_id=? AND file_path!=''",
                    (*unresolved_ids, task_id)
                ).fetchall():
                    result.setdefault(row["id"], []).append(row["file_path"])
            except Exception:
                pass
        return result

    def _compute_file_ranks(task_id: str, project_db, components: list,
                             project_root: str = "") -> dict:
        """计算文件重要度评分并分批次。"""
        from collections import Counter
        import json as _rj
        import os as _os

        # 1. 收集所有组件 node_list → 文件路径（批查询消除 N+1）
        file_to_comms: dict[str, set[str]] = {}
        file_edges: Counter = Counter()
        file_sizes: dict[str, int] = {}
        comm_quality: dict[str, float] = {}

        # 1a. 批查询所有组件的 node_list
        cid_list = [c.get("id", "") for c in components if c.get("id")]
        doc_map: dict[str, str] = {}
        if cid_list:
            placeholders = ",".join("?" for _ in cid_list)
            try:
                for row in project_db.execute(
                    f"SELECT comm_id, node_list FROM graph_doc WHERE task_id=? AND comm_id IN ({placeholders})",
                    (task_id, *cid_list)
                ).fetchall():
                    doc_map[row["comm_id"]] = row["node_list"]
            except Exception:
                pass

        # 1b. 先收集所有 node_list item，统一批解析
        all_cid_items: dict[str, list] = {}
        for c in components:
            cid = c.get("id", "")
            node_list_json = doc_map.get(cid, "")
            if not node_list_json:
                continue
            try:
                raw = _rj.loads(node_list_json) if isinstance(node_list_json, str) else node_list_json
                all_cid_items[cid] = raw
            except Exception:
                pass
        # 去重收集所有待解析 item
        all_items = list({item for items in all_cid_items.values() for item in items if isinstance(item, str) and item})
        path_map = _resolve_node_list_items(all_items, task_id, project_db)

        for c in components:
            cid = c.get("id", "")
            meta = c.get("metadata", {}) or {}
            comm_quality[cid] = float(meta.get("qualityScore", 0) or 0)
            for item in all_cid_items.get(cid, []):
                for resolved in path_map.get(item, []):
                    file_to_comms.setdefault(resolved, set()).add(cid)

        # 2. 查文件大小（node_list 存绝对路径，source_files 存相对路径）
        if file_to_comms:
            try:
                rel_keys = [
                    _os.path.relpath(fp, project_root) if project_root and _os.path.isabs(fp) else fp
                    for fp in file_to_comms
                ]
                logger.info("[_compute_file_ranks] size_query project_root=%r n_files=%d first_abs=%r first_rel=%r",
                           project_root, len(file_to_comms),
                           next(iter(file_to_comms), '') if file_to_comms else '',
                           rel_keys[0] if rel_keys else '')
                rel_to_size = {}
                for row in project_db.execute(
                    "SELECT file_path, size FROM source_files WHERE file_path IN ({})".format(
                        ",".join("?" for _ in rel_keys)
                    ), rel_keys
                ).fetchall():
                    rel_to_size[row["file_path"]] = row["size"] or 0
                logger.info("[_compute_file_ranks] source_files matched=%d", len(rel_to_size))
                # 映射回绝对路径（scoring loop 用绝对路径做 key）
                for abs_fp, rel_fp in zip(file_to_comms, rel_keys):
                    file_sizes[abs_fp] = rel_to_size.get(rel_fp, 0)
                logger.info("[_compute_file_ranks] file_sizes nonzero=%d",
                           sum(1 for v in file_sizes.values() if v > 0))
            except Exception as e:
                logger.warning("[_compute_file_ranks] size lookup failed: %s", e)

        # 3. 查依赖边数（dependencies.source_file 是文件路径文本）
        try:
            for row in project_db.execute(
                "SELECT d.source_file, COUNT(*) as cnt FROM dependencies d "
                "JOIN graph_node g ON g.file_path = d.source_file AND g.task_id = ? "
                "WHERE d.source_file IN ({}) GROUP BY d.source_file".format(
                    ",".join("?" for _ in file_to_comms)
                ), (task_id,) + tuple(file_to_comms.keys())
            ).fetchall():
                file_edges[row["source_file"]] = row["cnt"]
        except Exception:
            pass

        # 4. 计算评分（size 分桶 + quality 微调）；file_path 统一为项目相对路径
        from agent_workflow.path_utils import to_rel
        scored = []
        for fp, comms in file_to_comms.items():
            cross = len(comms)
            edges = file_edges.get(fp, 0)
            size = file_sizes.get(fp, 0)
            max_quality = max((comm_quality.get(c, 0) for c in comms), default=0)
            size_score = (1 if size > 10000 else 0) * 15 + \
                         (1 if size > 50000 else 0) * 15 + \
                         (1 if size > 100000 else 0) * 10
            score = size_score + int(max_quality * 100)
            scored.append({
                "file_path": to_rel(fp, project_root), "score": score, "cross": cross,
                "edges": edges, "size": size, "is_large": 1 if size > 10000 else 0,
                "quality": max_quality, "batch": "",
            })

        # 按评分降序排列
        scored.sort(key=lambda x: (-x["score"], -x["size"]))

        # 百分位分批（前30% P0, 中30% P1, 后40% P2；边界同分不截断）
        total = len(scored)
        p0_end = max(1, int(total * 0.30))
        p1_end = max(p0_end + 1, int(total * 0.60))
        while p0_end < total and scored[p0_end]["score"] == scored[p0_end - 1]["score"]:
            p0_end += 1
        while p1_end < total and scored[p1_end]["score"] == scored[p1_end - 1]["score"]:
            p1_end += 1
        for i, item in enumerate(scored):
            if i < p0_end:
                item["batch"] = "P0"
            elif i < p1_end:
                item["batch"] = "P1"
            else:
                item["batch"] = "P2"

        # 5. P4: 任务范围内未被任何社区覆盖的文件
        scored_paths = {f["file_path"] for f in scored}
        p4_files: list[dict] = []
        try:
            for row in project_db.execute(
                "SELECT file_path FROM source_files WHERE language != 'directory'"
            ).fetchall():
                rp = row["file_path"]
                if rp not in scored_paths:
                    p4_files.append({
                        "file_path": rp, "score": 0, "cross": 0,
                        "edges": 0, "size": 0, "is_large": 0,
                        "quality": 0, "batch": "P4",
                    })
        except Exception:
            pass
        p4_files.sort(key=lambda x: x["file_path"])
        scored.extend(p4_files)

        return {
            "files": scored,
            "counts": {"P0": p0_end, "P1": p1_end - p0_end, "P2": total - p1_end, "P4": len(p4_files)},
        }

    def _get_l0_comps(project_db, tid):
        """获取 L0 社区列表，INCLUDE 为空时回退到 CALL。"""
        for et in ("INCLUDE", "CALL"):
            cascades = _get_cascade_levels_impl(project_db, tid, et)
            l0_items = []
            for l in cascades.get("levels", []):
                if l.get("lv") == "L0":
                    l0_items = l.get("items", [])
                    break
            if l0_items:
                return [{"id": it.get("id", ""), "metadata": {"qualityScore": it.get("qualityScore", 0)}}
                        for it in l0_items]
        return []

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
        project_root = _get_project_root(pid)

        # 内存缓存 rank_data（L0 组件和排名在分析完成后不变）
        cache_key = f"ranks:{tid}"
        rank_data = _rank_cache.get(cache_key)
        if rank_data is None:
            comps = _get_l0_comps(project_db, tid)
            rank_data = _compute_file_ranks(tid, project_db, comps, project_root)
            _rank_cache[cache_key] = rank_data

        # 查已缓存文件数 + 按批次统计（每次轮询只查 COUNT）
        cached_count = 0
        batch_cached = {"P0": 0, "P1": 0, "P2": 0, "P4": 0}
        try:
            cached_rows = project_db.execute(
                "SELECT file_path FROM file_summaries WHERE project_id=?", (pid,)
            ).fetchall()
            cached_set = {r[0] for r in cached_rows}
            cached_count = len(cached_set)
            for f in rank_data["files"]:
                if f["file_path"] in cached_set:
                    batch_cached[f["batch"]] += 1
        except Exception:
            pass

        return {
            "counts": rank_data["counts"], "total_files": len(rank_data["files"]),
            "cached_count": cached_count, "batch_cached": batch_cached,
            "project_root": project_root,
            "failed_count": _ps_failed_counts.get(tid, 0),
        }

    @server.register("analysis.listPreSummaryFiles")
    def list_pre_summary_files(task_id=None, taskId=None, batch="P0",
                                page=1, page_size=20):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_db = multi_db.get_project_db(pid)
        project_root = _get_project_root(pid)

        cache_key = f"ranks:{tid}"
        rank_data = _rank_cache.get(cache_key)
        if rank_data is None:
            comps = _get_l0_comps(project_db, tid)
            rank_data = _compute_file_ranks(tid, project_db, comps, project_root)
            _rank_cache[cache_key] = rank_data
        batch_files = [f for f in rank_data["files"] if f["batch"] == batch]
        total = len(batch_files)
        start = (page - 1) * page_size
        end = start + page_size
        page_items = batch_files[start:end]

        # 缓存状态标记（file_path 已为相对路径，直接查询）
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
        result = _chain_start_pre_summary(tid, pid, project_db, batches, 0, limit, subagent_concurrency)
        agent_task_id = result.get("agentTaskId", "") if result else ""
        file_count = result.get("fileCount", 0) if result else 0
        return {"success": True, "batches": batches, "total": len(batches), "agentTaskId": agent_task_id, "fileCount": file_count}

    def _launch_pre_summary_batch(tid, pid, project_db, batch="P0", limit=0,
                                   subagent_concurrency=None, on_complete=None):

        comps = _get_l0_comps(project_db, tid)

        project_root = _get_project_root(pid)
        rank_data = _compute_file_ranks(tid, project_db, comps, project_root)
        batch_files = [f["file_path"] for f in rank_data["files"]
                       if f["batch"] == batch]
        if limit > 0:
            batch_files = batch_files[:limit]
        if not batch_files:
            return {"success": False, "error": f"批次 {batch} 无文件"}

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

        from agent_workflow.router import create_default_router
        project_summary = _get_project_summary(pid)
        router = create_default_router(
            project_root=project_root,
            project_db=project_db,
            multi_db=multi_db,
            task_id=tid,
            project_summary=project_summary,
        )

        # 重置前次运行的失败计数
        try:
            from agent_workflow.sub_agent import SubAgent
            SubAgent.reset_failed(tid)
        except Exception:
            pass

        cb = on_complete if on_complete else (lambda state: logger.info(f"[startPreSummary] done: {state}"))
        # 同时保存到 agent_task_history，前端通过 getAgentTaskHistory 可查到
        history_cb = _make_agent_history_cb(pid, project_db, tid, "presummary")
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
            from store.analysis_store import AnalysisStore
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

        from agent_workflow.agent_queue import get_global_queue
        queue = get_global_queue()
        return {"success": True, "agentTaskId": agent_id,
                "fileCount": len(batch_files)}

    def _chain_start_pre_summary(tid, pid, project_db, batches, idx=0, limit=0, subagent_concurrency=1):
        """链式顺序启动预摘要批次：前一批完成后触发下一批。
        返回第一批的启动结果（含 agentTaskId），后续批次通过回调链式触发。
        """
        if idx >= len(batches):
            logger.info("[chainPreSummary] all batches done: %s", batches)
            return {}
        batch = batches[idx]
        logger.info("[chainPreSummary] starting batch %s (%d/%d)", batch, idx + 1, len(batches))

        def _chain_cb(state):
            fc = state.get("failed_count", 0)
            if fc:
                _ps_failed_counts[tid] = fc
            st = state.get("status", "")
            if st in ("cancelled", "failed"):
                logger.info("[chainPreSummary] batch %s %s, stopping chain", batch, st)
                return
            logger.info("[chainPreSummary] batch %s done, starting next", batch)
            _chain_start_pre_summary(tid, pid, project_db, batches, idx + 1, limit, subagent_concurrency)

        first_result = _launch_pre_summary_batch(tid, pid, project_db, batch, limit, subagent_concurrency, on_complete=_chain_cb)
        return first_result or {}

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
        project_root = _get_project_root(pid)

        # 优先用相对路径查找（file_summaries 存储格式）
        query_path = file_path
        if project_root and file_path.startswith(project_root):
            query_path = file_path[len(project_root):].lstrip("/")

        from agent_workflow.file_summary_cache import FileSummaryCache
        cache = FileSummaryCache(project_db, pid)
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

        from agent_workflow.file_summary_cache import FileSummaryCache
        cache = FileSummaryCache(project_db, pid)
        deleted = cache.delete(file_path)
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
        project_root = _get_project_root(pid)

        context = {"task_id": tid, "project_id": pid, "files": [file_path]}

        from agent_workflow.router import create_default_router
        project_summary = _get_project_summary(pid)
        router = create_default_router(
            project_root=project_root, project_db=project_db,
            multi_db=multi_db, task_id=tid, project_summary=project_summary,
        )
        agent_id = router.dispatch("presummary_files", tid, context)
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
                return {"success": False, "error": f"max_turns 必须是整数 (1-30)，收到: {raw_turns}"}
        if turns < 1 or turns > 30:
            return {"success": False, "error": f"max_turns 必须在 1-30 之间，收到: {turns}"}

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
                    return {"success": False, "error": f"摘要模型未配置: {summary_model}"}
            except Exception as e:
                return {"success": False, "error": f"摘要模型校验失败: {e}"}

        try:
            store = TaskStore(multi_db.main_db)
            task = store.get_task(tid)
            if not task:
                raise ValueError(f"Task {tid} not found")
            pid = task["project_id"]
            project_db = multi_db.get_project_db(pid)
            project_root = _get_project_root(pid)
            project_summary = _get_project_summary(pid)

            logger.info(f"[analyzeComponents] task_id={tid} components={len(comps)}")

            # ── 富上下文构建：为每个 community 组件加载 node_list → 文件路径 + 关键符号 ──
            import json as _json
            enriched_comps = []
            fp_map = {}
            existing_results = {}
            try:
                from store.analysis_store import AnalysisStore as _AS3
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
                    "SELECT comm_id, component_type FROM community_llm_results WHERE task_id=?",
                    (tid,)
                ).fetchall()
                for r in rows:
                    existing_results[r["comm_id"]] = dict(r)
            except Exception:
                pass

            # ── 跳过已分析组件（除非 force=True）──
            if not force:
                analyzed_ids = set(existing_results.keys())
                filtered = []
                for c in comps:
                    cid = c.get("id", "")
                    if c.get("type") == "community" and cid.startswith("comm-"):
                        if cid in analyzed_ids or f"community:{cid}" in analyzed_ids:
                            continue
                    else:
                        key = f"{c.get('type', '')}:{cid}"
                        if key in analyzed_ids:
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
                edge_label = {"incl": "依赖关系 (INCLUDE)", "call": "调用关系 (CALL)"}.get(edge_kind, "关系")

                # 构建社区元数据（供 CommunityInfoIngredient）
                comm_meta = {
                    "nodeCount": meta.get("nodeCount", 0),
                    "fileCount": meta.get("fileCount", 0),
                    "qualityScore": meta.get("qualityScore"),
                    "edgeCount": doc["edge_count"] if doc else 0,
                    "edgeLabel": edge_label,
                }

                # 构建 CollectContext
                from context.assembly import CollectContext
                from context.recipes import (
                    RECIPE_COMPONENT_ANALYSIS,
                    RECIPE_COMPONENT_ANALYSIS_AGENTIC,
                )
                from context.registry import get_assembler

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
                        f"\n任务ID: {tid}"
                        f"\n工具引导: 使用 summarize_file 读取并摘要关键文件; "
                        f"get_community_subgraph 查看完整子图结构"
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

            from agent_workflow.router import create_default_router
            from store.analysis_store import AnalysisStore

            # 构建组件→(edge_type, comm_lv) 查找表
            comp_edge_lv = {}
            for ec in enriched_comps:
                cid = ec["id"]
                if ec.get("type") == "community" and cid.startswith("comm-"):
                    parts = cid.split("-")
                    et = {"incl": "INCLUDE", "call": "CALL"}.get(parts[2] if len(parts) > 2 else "", "INCLUDE")
                    lv = parts[3] if len(parts) > 3 else "L0"
                else:
                    et = ""
                    lv = "L0"
                comp_edge_lv[cid] = (et, lv)

            def _save_fn(result):
                try:
                    s = AnalysisStore(project_db)
                    comp_id = result.get("component_id", "")
                    comp_type = result.get("component_type", "community")
                    aname = result.get("analyzed_name", "") or comp_id
                    asummary = result.get("functional_summary", "")
                    et, lv = comp_edge_lv.get(comp_id, ("", "L0"))
                    s.bulk_insert_llm_results([{
                        "task_id": result.get("task_id", tid),
                        "edge_type": et,
                        "comm_lv": lv,
                        "comm_id": comp_id,
                        "name": aname,
                        "summary": asummary,
                        "component_type": comp_type,
                        "status": result.get("status", "completed"),
                    }])
                    logger.info(f"[analyzeComponents] _save_fn saved community_llm_results: {comp_id} status={result.get('status','completed')}")
                except Exception as e:
                    logger.error(f"[analyzeComponents] _save_fn failed: {e}", exc_info=True)

            router = create_default_router(
                project_root=project_root, project_db=project_db, multi_db=multi_db,
                task_id=tid, project_summary=project_summary,
                llm_model_id="", save_result_fn=_save_fn,
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
            if agentic_mode:
                context["_save_fn"] = _save_fn
                context["max_turns"] = turns
                context["subagent_concurrency"] = sub_conc
                if summary_model:
                    context["summary_model_id"] = summary_model
            for c in context["components"]:
                logger.info(
                    f"[analyzeComponents] component id={c['id']} type={c['type']} "
                    f"metadata={c['metadata']}"
                )

            route_action = "agentic_analyze_components" if agentic_mode else "analyze_components"
            agent_id = router.dispatch(route_action, tid, context,
                on_complete=_make_agent_history_cb(pid, project_db, tid, route_action))
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
        project_root = _get_project_root(pid)
        project_summary = _get_project_summary(pid)
        project_name = task.get("name") or pid
        et = edge_type or edgeType or "INCLUDE"
        lv = level or "L0"
        mid = model_id or modelId or ""

        result = _get_cascade_levels_impl(project_db, tid, et)
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

        from agent_workflow.llm_adapter import create_llm_chat_fn
        from agent_workflow.router import create_default_router
        from store.analysis_store import AnalysisStore

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

        router = create_default_router(
            project_root=project_root, project_db=project_db, multi_db=multi_db,
            task_id=tid, project_summary=project_summary,
            llm_model_id=mid, save_result_fn=_save_fn,
        )
        base_context = {
            "task_id": tid, "edge_type": et, "level": lv,
            "project_name": project_name, "project_summary": project_summary,
            "communities": communities,
        }
        try:
            agent_id = router.dispatch_nl(text, tid, base_context, llm_fn)
            return {"taskId": tid, "success": True, "agentTaskId": agent_id,
                    "mode": "nl", "input": text[:100]}
        except ValueError as e:
            return {"taskId": tid, "success": False, "error": str(e),
                    "mode": "nl", "input": text[:100]}

    @server.register("analysis.listTimeline")
    def list_timeline(project_id=None, projectId=None):
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")
        project_db = multi_db.get_project_db(pid)
        if not project_db:
            return []
        _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
        return project_db.fetchall(
            "SELECT * FROM arch_timeline WHERE project_id = ? ORDER BY created_at DESC",
            (pid,))

    @server.register("analysis.getTimelineEntry")
    def get_timeline_entry(timeline_id=None, timelineId=None):
        tid = timeline_id or timelineId
        if not tid:
            raise ValueError("timeline_id is required")
        for pid_row in multi_db.main_db.fetchall("SELECT id FROM projects"):
            pdb = multi_db.get_project_db(pid_row["id"])
            if not pdb:
                continue
            _ensure_table(pdb, "arch_timeline", _ARCH_TIMELINE_DDL)
            _ensure_table(pdb, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
            entry = pdb.fetchone("SELECT * FROM arch_timeline WHERE id = ?", (tid,))
            if entry:
                comms = pdb.fetchall(
                    "SELECT * FROM arch_timeline_communities WHERE timeline_id = ? ORDER BY community_id",
                    (tid,))
                return {
                    "entry": {
                        "id": entry["id"], "taskId": entry["task_id"],
                        "projectId": entry["project_id"], "type": entry["type"],
                        "alias": entry["alias"], "timestamp": entry["timestamp"],
                        "versionTag": entry["version_tag"],
                        "sourceVersion": entry["source_version"],
                        "communityCount": entry["community_count"],
                        "totalFiles": entry["total_files"],
                        "gitBranch": entry["git_branch"],
                        "gitCommit": entry["git_commit"],
                        "gitTag": entry["git_tag"],
                        "exported": entry["exported"],
                        "isActive": bool(entry["is_active"]),
                    },
                    "communities": [{
                        "communityId": c["community_id"],
                        "edgeType": c["edge_type"], "level": c["level"],
                        "name": c["name"], "summary": c["summary"],
                        "mermaid": c["mermaid"], "plantuml": c["plantuml"],
                        "nodeCount": c["node_count"], "fileCount": c["file_count"],
                        "qualityScore": c["quality_score"],
                        "nodeList": json.loads(c["node_list"]) if c["node_list"] else [],
                        "fileList": json.loads(c["file_list"]) if c["file_list"] else [],
                        "edgeList": json.loads(c["edge_list"]) if c["edge_list"] else [],
                    } for c in comms],
                }
        return {"entry": None, "communities": []}

    @server.register("analysis.startArchTrack")
    def start_arch_track(task_id=None, taskId=None, tag=None):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")
        version_id = tag or f"v-{int(time.time())}"
        logger.info(f"[startArchTrack] task_id={tid} version={version_id}")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_root = _get_project_root(pid)
        project_db = multi_db.get_project_db(pid)

        _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
        _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)

        communities = _get_cascade_levels_impl(project_db, tid, "INCLUDE")
        l0_items = []
        for l in communities.get("levels", []):
            if l.get("lv") == "L0":
                l0_items = l.get("items", [])
                break

        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        timeline_id = str(uuid.uuid4())
        project_db.execute("""
            INSERT INTO arch_timeline
                (id, task_id, project_id, type, version_tag, timestamp,
                 community_count, is_active)
            VALUES (?,?,?,?,?,?,?,?)
        """, (timeline_id, tid, pid, 'archtrack', version_id, ts,
              len(l0_items), 0))
        for c in l0_items:
            project_db.execute("""
                INSERT INTO arch_timeline_communities
                    (timeline_id, community_id, edge_type, level,
                     node_count, quality_score)
                VALUES (?,?,?,?,?,?)
            """, (timeline_id, c.get("id", ""), "INCLUDE", "L0",
                  c.get("nodeCount", 0), c.get("qualityScore", 0)))
        project_db.commit()

        l0_for_ctx = [{"communityId": c.get("id", ""), "name": c.get("label", ""),
                        "node_count": c.get("nodeCount", 0),
                        "quality_score": c.get("qualityScore", 0)}
                       for c in l0_items]
        try:
            from agent_workflow.router import create_default_router
            router = create_default_router(project_root=project_root, project_db=project_db,
                                           multi_db=multi_db, task_id=tid)
            agent_id = router.dispatch("track_start", tid, {
                "action": "start", "version_id": version_id, "tag": version_id,
                "communities": l0_for_ctx, "trigger": "manual",
            })
            logger.info(f"[startArchTrack] enqueued agent={agent_id}")
        except Exception as e:
            logger.warning(f"[startArchTrack] RouterHarness failed: {e}")

        return {"versionId": version_id, "timelineId": timeline_id}

    @server.register("analysis.stopArchTrack")
    def stop_arch_track(task_id=None, taskId=None, tag=None):
        tid = task_id or taskId
        logger.info(f"[stopArchTrack] task_id={tid}")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pid = task["project_id"]
        project_root = _get_project_root(pid)
        project_db = multi_db.get_project_db(pid)

        _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
        _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)

        prev_entries = project_db.fetchall(
            "SELECT * FROM arch_timeline WHERE project_id = ? AND type = 'archtrack' ORDER BY created_at DESC LIMIT 1",
            (pid,))

        if len(prev_entries) < 1:
            version_id = tag or f"v-{int(time.time())}"
            ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            communities = _get_cascade_levels_impl(project_db, tid, "INCLUDE")
            l0_items = []
            for l in communities.get("levels", []):
                if l.get("lv") == "L0":
                    l0_items = l.get("items", [])
                    break
            timeline_id = str(uuid.uuid4())
            project_db.execute("""
                INSERT INTO arch_timeline
                    (id, task_id, project_id, type, version_tag, timestamp, community_count, is_active)
                VALUES (?,?,?,?,?,?,?,?)
            """, (timeline_id, tid, pid, 'archtrack', version_id, ts, len(l0_items), 0))
            project_db.commit()
            return {"versionId": version_id, "summary": "第一个快照，无对比基准",
                    "risk": "low", "added": len(l0_items), "removed": 0, "changed": 0}

        prev_entry = prev_entries[0]
        prev_v = prev_entry["version_tag"] or prev_entry["id"]
        version_id = tag or f"v-{int(time.time())}"
        ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        communities = _get_cascade_levels_impl(project_db, tid, "INCLUDE")
        l0_items = []
        for l in communities.get("levels", []):
            if l.get("lv") == "L0":
                l0_items = l.get("items", [])
                break

        prev_comms = project_db.fetchall(
            "SELECT * FROM arch_timeline_communities WHERE timeline_id = ?",
            (prev_entry["id"],))
        prev_ids = {pc["community_id"] for pc in prev_comms}
        curr_ids = {c.get("id", "") for c in l0_items}

        added = len(curr_ids - prev_ids)
        removed = len(prev_ids - curr_ids)
        changed = len(curr_ids & prev_ids)
        risk = "high" if removed > 0 else ("medium" if added > 5 else "low")

        timeline_id = str(uuid.uuid4())
        project_db.execute("""
            INSERT INTO arch_timeline
                (id, task_id, project_id, type, version_tag, source_version, timestamp,
                 community_count, is_active)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (timeline_id, tid, pid, 'archtrack', version_id, prev_v, ts,
              len(l0_items), 0))
        for c in l0_items:
            project_db.execute("""
                INSERT INTO arch_timeline_communities
                    (timeline_id, community_id, edge_type, level,
                     node_count, quality_score)
                VALUES (?,?,?,?,?,?)
            """, (timeline_id, c.get("id", ""), "INCLUDE", "L0",
                  c.get("nodeCount", 0), c.get("qualityScore", 0)))
        project_db.commit()

        l0_for_ctx = [{"communityId": c.get("id", ""), "name": c.get("label", ""),
                        "node_count": c.get("nodeCount", 0),
                        "quality_score": c.get("qualityScore", 0)}
                       for c in l0_items]
        prev_for_ctx = [{"communityId": pc["community_id"], "name": pc["community_id"],
                          "node_count": pc["node_count"],
                          "quality_score": pc["quality_score"]}
                         for pc in prev_comms]
        try:
            from agent_workflow.router import create_default_router
            router = create_default_router(project_root=project_root, project_db=project_db,
                                           multi_db=multi_db, task_id=tid)
            agent_id = router.dispatch("track_stop", tid, {
                "action": "stop", "version_id": version_id, "tag": version_id,
                "communities": l0_for_ctx,
                "previous_communities": prev_for_ctx,
                "previous_version": prev_v, "trigger": "manual",
            })
            logger.info(f"[stopArchTrack] enqueued agent={agent_id}")
        except Exception as e:
            logger.warning(f"[stopArchTrack] RouterHarness failed: {e}")

        summary = f"新增 {added} 个社区，删除 {removed} 个，{changed} 个未变"
        return {"versionId": version_id, "timelineId": timeline_id, "summary": summary,
                "risk": risk, "added": added, "removed": removed, "changed": changed}

    # ==================== 子文档 CRUD ====================

    @server.register("report.createSubDoc")
    def create_sub_doc(task_id=None, taskId=None, edge_type=None, edgeType=None,
                       comm_id=None, commId=None, title=None, content=None,
                       template_id=None, templateId=None,
                       id=None, docId=None):
        """创建分析报告子文档"""
        tid = task_id or taskId
        et = edge_type or edgeType or 'CALL'
        cid = comm_id or commId
        tpl = template_id or templateId
        provided_id = id or docId

        if not tid or not title or not content:
            raise ValueError("task_id, title, and content are required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]
        project_db = multi_db.get_project_db(project_id)

        doc_id = provided_id or f"subdoc-{uuid.uuid4().hex[:12]}"
        now = time.strftime('%Y-%m-%d %H:%M:%S')

        # 清理同一 (task_id, edge_type, comm_id) 的旧子文档
        if tid and et:
            if cid:
                project_db.execute(
                    "DELETE FROM report_subdocs WHERE task_id=? AND edge_type=? AND comm_id=? AND id!=?",
                    (tid, et, cid, doc_id)
                )
            else:
                project_db.execute(
                    "DELETE FROM report_subdocs WHERE task_id=? AND edge_type=? AND comm_id IS NULL AND id!=?",
                    (tid, et, doc_id)
                )

        project_db.execute(
            "INSERT INTO report_subdocs (id, task_id, edge_type, comm_id, title, content, template_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (doc_id, tid, et, cid, title, content, tpl, now, now)
        )
        project_db.commit()

        return {'id': doc_id}

    @server.register("report.listSubDocs")
    def list_sub_docs(task_id=None, taskId=None, comm_id=None, commId=None):
        """列出报告子文档"""
        tid = task_id or taskId
        cid = comm_id or commId

        if not tid:
            raise ValueError("task_id is required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        project_id = task["project_id"]
        project_db = multi_db.get_project_db(project_id)

        if cid:
            rows = project_db.execute(
                "SELECT id, title, template_id, created_at, updated_at FROM report_subdocs WHERE task_id=? AND comm_id=? ORDER BY created_at DESC",
                (tid, cid)
            ).fetchall()
        else:
            rows = project_db.execute(
                "SELECT id, title, template_id, created_at, updated_at FROM report_subdocs WHERE task_id=? ORDER BY created_at DESC",
                (tid,)
            ).fetchall()

        return [
            {
                'id': row[0],
                'title': row[1],
                'template_id': row[2],
                'created_at': row[3],
                'updated_at': row[4],
            }
            for row in rows
        ]

    def _find_subdoc_project(multi_db, sub_doc_id):
        """在 projects 表中遍历查找子文档所属项目 ID"""
        projects = multi_db.main_db.fetchall("SELECT id FROM projects")
        for proj in projects:
            pid = proj["id"]
            try:
                pdb = multi_db.get_project_db(pid)
                row = pdb.fetchone(
                    "SELECT id, task_id, edge_type, comm_id, title, content, template_id, created_at, updated_at FROM report_subdocs WHERE id=?",
                    (sub_doc_id,)
                )
                if row:
                    return pid, row
            except Exception:
                continue
        return None, None

    @server.register("report.getSubDoc")
    def get_sub_doc(sub_doc_id=None, subDocId=None):
        """获取子文档内容"""
        sid = sub_doc_id or subDocId
        if not sid:
            raise ValueError("sub_doc_id is required")

        pid, row = _find_subdoc_project(multi_db, sid)
        if row:
            return {
                'id': row['id'],
                'task_id': row['task_id'],
                'edge_type': row['edge_type'],
                'comm_id': row['comm_id'],
                'title': row['title'],
                'content': row['content'],
                'template_id': row['template_id'],
                'created_at': row['created_at'],
                'updated_at': row['updated_at'],
            }

        raise ValueError(f"SubDoc {sid} not found")

    @server.register("report.updateSubDoc")
    def update_sub_doc(sub_doc_id=None, subDocId=None, title=None, content=None):
        """更新子文档"""
        sid = sub_doc_id or subDocId
        if not sid:
            raise ValueError("sub_doc_id is required")

        pid, _ = _find_subdoc_project(multi_db, sid)
        if pid:
            pdb = multi_db.get_project_db(pid)
            now = time.strftime('%Y-%m-%d %H:%M:%S')
            if content is not None:
                pdb.execute(
                    "UPDATE report_subdocs SET content=?, updated_at=? WHERE id=?",
                    (content, now, sid)
                )
            if title is not None:
                pdb.execute(
                    "UPDATE report_subdocs SET title=?, updated_at=? WHERE id=?",
                    (title, now, sid)
                )
            pdb.commit()
            return {'ok': True}

        raise ValueError(f"SubDoc {sid} not found")

    @server.register("report.deleteSubDoc")
    def delete_sub_doc(sub_doc_id=None, subDocId=None):
        """删除子文档"""
        sid = sub_doc_id or subDocId
        if not sid:
            raise ValueError("sub_doc_id is required")

        pid, _ = _find_subdoc_project(multi_db, sid)
        if pid:
            pdb = multi_db.get_project_db(pid)
            pdb.execute("DELETE FROM report_subdocs WHERE id=?", (sid,))
            pdb.commit()
            return {'ok': True}

        raise ValueError(f"SubDoc {sid} not found")

    logger.info("[task_manager] 所有 analysis.* 方法已注册")

    # 启动时恢复孤儿任务（后端异常终止后残留的 running 状态）
    try:
        orphan_store = TaskStore(multi_db.main_db)
        orphans = orphan_store._db.execute(
            "SELECT id, name FROM analysis_tasks WHERE status = 'running'"
        ).fetchall()
        recovered = 0
        for row in orphans:
            oid = row[0]
            oname = row[1]
            if not is_task_executing(oid):
                logger.warning(f"[startup] Recovering orphan task {oid} ({oname}) -> error")
                orphan_store.update_task_status(oid, "error", error="任务执行中断（后端异常终止）")
                orphan_store._db.execute(
                    "UPDATE analysis_task_runs SET status='error', error='执行中断', finished_at=datetime('now') WHERE task_id=? AND status='running'",
                    (oid,),
                )
                orphan_store._db.commit()
                recovered += 1
        if recovered:
            logger.info(f"[startup] Recovered {recovered} orphan task(s)")
    except Exception as e:
        logger.error(f"[startup] Orphan recovery failed: {e}")


# ═══════════════════════════════════════════════════════════════
#  项目 Git 信息 & 架构快照 & 图节点位置
# ═══════════════════════════════════════════════════════════════

_POSITIONS_DDL = """CREATE TABLE IF NOT EXISTS graph_node_positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL,
    edge_type TEXT NOT NULL CHECK(edge_type IN ('INCLUDE','CALL','EXTERNAL_INCLUDE','EXTERNAL_CALL')),
    drill_key TEXT NOT NULL,
    snapshot_id TEXT,
    layout_type TEXT NOT NULL CHECK(layout_type IN ('dagre','force')),
    node_id TEXT NOT NULL,
    pos_x REAL NOT NULL,
    pos_y REAL NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_gp_active_unique
    ON graph_node_positions(task_id, edge_type, drill_key, layout_type, node_id)
    WHERE snapshot_id IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_gp_snap_unique
    ON graph_node_positions(task_id, edge_type, drill_key, snapshot_id, layout_type, node_id)
    WHERE snapshot_id IS NOT NULL;
"""

_ARCH_TIMELINE_DDL = """CREATE TABLE IF NOT EXISTS arch_timeline (
    id              TEXT PRIMARY KEY,
    task_id         TEXT NOT NULL,
    project_id      TEXT NOT NULL,
    type            TEXT NOT NULL DEFAULT 'manual',
    alias           TEXT,
    timestamp       TEXT NOT NULL,
    version_tag     TEXT,
    source_version  TEXT,
    community_count INTEGER DEFAULT 0,
    total_files     INTEGER DEFAULT 0,
    git_branch      TEXT,
    git_commit      TEXT,
    git_tag         TEXT,
    exported        INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_timeline_task ON arch_timeline(task_id);
CREATE INDEX IF NOT EXISTS idx_timeline_project ON arch_timeline(project_id);
CREATE INDEX IF NOT EXISTS idx_timeline_type ON arch_timeline(type);
"""

_ARCH_TIMELINE_COMM_DDL = """CREATE TABLE IF NOT EXISTS arch_timeline_communities (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timeline_id     TEXT NOT NULL,
    community_id    TEXT NOT NULL,
    edge_type       TEXT NOT NULL,
    level           TEXT NOT NULL,
    name            TEXT,
    summary         TEXT,
    mermaid         TEXT,
    plantuml        TEXT,
    node_count      INTEGER,
    file_count      INTEGER,
    quality_score   REAL,
    node_list       TEXT,
    file_list       TEXT,
    edge_list       TEXT,
    UNIQUE(timeline_id, community_id)
);
CREATE INDEX IF NOT EXISTS idx_tl_comm_timeline ON arch_timeline_communities(timeline_id);
"""


def _ensure_project_db(multi_db, task_id: str):
    """Get the project database for a task, ensuring the DB is initialized."""
    main_db = multi_db.main_db
    row = main_db.fetchone(
        "SELECT project_id FROM analysis_tasks WHERE id = ?", (task_id,))
    if not row:
        return None
    return multi_db.get_project_db(row["project_id"])


def _ensure_table(db, table_name: str, ddl: str):
    """Create table if it doesn't exist on the given database."""
    try:
        for stmt in ddl.split(";"):
            stmt = stmt.strip()
            if stmt:
                db.execute(stmt)
        db.commit()
    except Exception as e:
        logger.warning(f"[ensure_table] failed to create {table_name}: {e}")

def _run_git(project_root: str, *args) -> str:
    """Run a git command in project_root and return stdout, or '' on failure."""
    try:
        result = subprocess.run(
            ["git"] + list(args),
            cwd=project_root, capture_output=True, text=True, timeout=10
        )
        return result.stdout.strip()
    except Exception:
        return ""


def detect_git_info(multi_db: MultiDBManager, project_id: str) -> dict:
    """Auto-detect Git information from the project's .git directory."""
    main_db = multi_db.main_db
    row = main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (project_id,))
    if not row or not row["root_path"]:
        return {"remoteUrl": "", "currentBranch": "", "currentCommit": "", "error": "project_not_found"}
    root = row["root_path"]
    if not os.path.isdir(os.path.join(root, ".git")):
        return {"remoteUrl": "", "currentBranch": "", "currentCommit": "", "error": "not_a_git_repo"}

    remote_url = _run_git(root, "remote", "get-url", "origin")
    branch = _run_git(root, "rev-parse", "--abbrev-ref", "HEAD")
    commit = _run_git(root, "rev-parse", "HEAD")
    latest_tag = _run_git(root, "describe", "--tags", "--abbrev=0")

    # list tags (last 20)
    tags_raw = _run_git(root, "tag", "--sort=-creatordate")
    tags_list = tags_raw.split("\n")[:20] if tags_raw else []

    # list branches
    branches_raw = _run_git(root, "branch", "--format=%(refname:short)")
    branches_list = branches_raw.split("\n") if branches_raw else []

    # recent commits (last 10)
    log_raw = _run_git(root, "log", "--format=%H|%s|%aI", "-n", "10")
    commits_list = []
    if log_raw:
        for line in log_raw.split("\n"):
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits_list.append({"hash": parts[0][:8], "message": parts[1], "date": parts[2]})

    result = {
        "remoteUrl": remote_url,
        "currentBranch": branch,
        "currentCommit": commit,
        "latestTag": latest_tag if latest_tag else "",
        "tags": json.dumps(tags_list),
        "branches": json.dumps(branches_list),
        "recentCommits": json.dumps(commits_list),
    }

    # persist
    main_db.execute("""
        INSERT INTO project_git_info (project_id, remote_url, current_branch, current_commit,
            latest_tag, tags, branches, recent_commits, detected_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(project_id) DO UPDATE SET
            remote_url=excluded.remote_url, current_branch=excluded.current_branch,
            current_commit=excluded.current_commit, latest_tag=excluded.latest_tag,
            tags=excluded.tags, branches=excluded.branches,
            recent_commits=excluded.recent_commits, detected_at=excluded.detected_at,
            updated_at=datetime('now')
    """, (project_id, remote_url, branch, commit, latest_tag or "",
          json.dumps(tags_list), json.dumps(branches_list),
          json.dumps(commits_list), datetime.now(timezone.utc).isoformat()))
    main_db.commit()

    return result


def save_git_info(multi_db: MultiDBManager, project_id: str, remote_url=None,
                  current_branch=None, current_commit=None, latest_tag=None,
                  tags=None, branches=None, recent_commits=None) -> dict:
    """Manually save or override Git information."""
    main_db = multi_db.main_db
    main_db.execute("""
        INSERT INTO project_git_info (project_id, remote_url, current_branch, current_commit,
            latest_tag, tags, branches, recent_commits, manually_edited, updated_at)
        VALUES (?,?,?,?,?,?,?,?,1,datetime('now'))
        ON CONFLICT(project_id) DO UPDATE SET
            remote_url=COALESCE(excluded.remote_url, project_git_info.remote_url),
            current_branch=COALESCE(excluded.current_branch, project_git_info.current_branch),
            current_commit=COALESCE(excluded.current_commit, project_git_info.current_commit),
            latest_tag=COALESCE(excluded.latest_tag, project_git_info.latest_tag),
            tags=COALESCE(excluded.tags, project_git_info.tags),
            branches=COALESCE(excluded.branches, project_git_info.branches),
            recent_commits=COALESCE(excluded.recent_commits, project_git_info.recent_commits),
            manually_edited=1, updated_at=datetime('now')
    """, (project_id, remote_url, current_branch, current_commit, latest_tag,
          tags, branches, recent_commits))
    main_db.commit()
    return {"status": "ok"}


def get_git_info(multi_db: MultiDBManager, project_id: str) -> dict:
    """Read stored Git information for a project."""
    main_db = multi_db.main_db
    row = main_db.fetchone(
        "SELECT * FROM project_git_info WHERE project_id = ?", (project_id,))
    if not row:
        return {"remoteUrl": "", "currentBranch": "", "currentCommit": ""}
    return {
        "remoteUrl": row["remote_url"] or "",
        "currentBranch": row["current_branch"] or "",
        "currentCommit": row["current_commit"] or "",
        "latestTag": row["latest_tag"] or "",
        "tags": row["tags"] or "",
        "branches": row["branches"] or "",
        "recentCommits": row["recent_commits"] or "",
        "detectedAt": row["detected_at"] or "",
        "manuallyEdited": row["manually_edited"] or 0,
    }


def check_import_status(multi_db: MultiDBManager, project_id: str) -> dict:
    main_db = multi_db.main_db
    project_db = multi_db.get_project_db(project_id)
    tasks = main_db.fetchall(
        "SELECT id FROM analysis_tasks WHERE project_id = ? AND status = 'done'", (project_id,))
    has_snapshot = False
    needs_save = False
    for t in tasks:
        row = None
        if project_db:
            row = project_db.fetchone(
                "SELECT id FROM arch_timeline WHERE task_id = ?", (t["id"],))
        if row:
            has_snapshot = True
        else:
            needs_save = True
    return {"hasSnapshot": has_snapshot, "needsSavePrompt": needs_save}


def cleanup_task_snapshots(multi_db: MultiDBManager, task_id: str) -> dict:
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"deleted": 0}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
    _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
    project_db.execute(
        "DELETE FROM graph_node_positions WHERE task_id = ?", (task_id,))
    deleted_entries = project_db.fetchall(
        "SELECT id FROM arch_timeline WHERE task_id = ?", (task_id,))
    for s in deleted_entries:
        project_db.execute(
            "DELETE FROM arch_timeline_communities WHERE timeline_id = ?", (s["id"],))
    project_db.execute(
        "DELETE FROM arch_timeline WHERE task_id = ?", (task_id,))
    project_db.commit()
    return {"deleted": len(deleted_entries)}


def _resolve_file_list(multi_db: MultiDBManager, project_id: str, node_list_json: str) -> list:
    """Given a JSON node_list (list of graph_node IDs), return deduped file_path list."""
    try:
        node_ids = json.loads(node_list_json) if isinstance(node_list_json, str) else node_list_json
    except (json.JSONDecodeError, TypeError):
        return []
    if not node_ids:
        return []
    project_db = multi_db.get_project_db(project_id)
    if not project_db:
        return []
    placeholders = ",".join("?" * len(node_ids))
    rows = project_db.fetchall(
        f"SELECT DISTINCT file_path FROM graph_node WHERE id IN ({placeholders})",
        tuple(str(nid) for nid in node_ids))
    return sorted(r["file_path"] for r in rows if r["file_path"])


def save_snapshot(multi_db: MultiDBManager, task_id: str, project_id: str, alias=None) -> dict:
    main_db = multi_db.main_db
    project_db = multi_db.get_project_db(project_id)
    if not project_db:
        return {"error": "project_db_not_found"}

    _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
    _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)

    git_row = main_db.fetchone(
        "SELECT current_branch, current_commit, latest_tag FROM project_git_info WHERE project_id = ?",
        (project_id,))
    git_branch = git_row["current_branch"] if git_row else None
    git_commit = git_row["current_commit"] if git_row else None
    git_tag = git_row["latest_tag"] if git_row else None

    comms = project_db.fetchall("""
        SELECT comm_id, edge_type, comm_lv, node_count, file_count, quality_score
        FROM community_hierarchy
        WHERE task_id = ? AND comm_lv = 'L0'
        ORDER BY edge_type, comm_id
    """, (task_id,))

    total_files_set = set()
    timeline_id = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for c in comms:
        doc_row = project_db.fetchone(
            "SELECT node_list, edge_list FROM graph_doc WHERE task_id = ? AND comm_id = ? AND comm_lv = ?",
            (task_id, c["comm_id"], c["comm_lv"]))
        node_list = doc_row["node_list"] if doc_row else "[]"
        edge_list = doc_row["edge_list"] if doc_row else "[]"

        file_list = _resolve_file_list(multi_db, project_id, node_list)
        for fp in file_list:
            total_files_set.add(fp)

        llm_row = project_db.fetchone(
            "SELECT name, summary FROM community_llm_results"
            " WHERE task_id=? AND comm_id=? AND comm_lv=?",
            (task_id, c["comm_id"], c["comm_lv"]))
        name = llm_row.get("name") if llm_row else None
        summary = llm_row.get("summary") if llm_row else None

        project_db.execute("""
            INSERT INTO arch_timeline_communities
                (timeline_id, community_id, edge_type, level, name, summary, mermaid, plantuml, node_count,
                 file_count, quality_score, node_list, file_list, edge_list)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (timeline_id, c["comm_id"], c["edge_type"], c["comm_lv"], name,
              summary, "", "",
              c["node_count"] or 0, len(file_list), c["quality_score"],
              node_list if isinstance(node_list, str) else json.dumps(node_list),
              json.dumps(file_list),
              edge_list if isinstance(edge_list, str) else json.dumps(edge_list)))

    total_files = len(total_files_set)
    community_count = len(comms)

    project_db.execute(
        "UPDATE arch_timeline SET is_active = 0 WHERE task_id = ? AND is_active = 1",
        (task_id,))

    project_db.execute("""
        INSERT INTO arch_timeline
            (id, task_id, project_id, type, alias, timestamp, git_branch, git_commit, git_tag,
             community_count, total_files, is_active)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (timeline_id, task_id, project_id, 'manual', alias, timestamp,
          git_branch, git_commit, git_tag, community_count, total_files, 1))
    project_db.commit()

    return {"snapshotId": timeline_id, "status": "ok",
            "communityCount": community_count, "totalFiles": total_files}


def get_snapshot(multi_db: MultiDBManager, task_id: str, snapshot_id: str = None) -> dict:
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"snapshot": None}
    _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
    _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
    if snapshot_id:
        row = project_db.fetchone(
            "SELECT * FROM arch_timeline WHERE id = ?", (snapshot_id,))
    else:
        row = project_db.fetchone(
            "SELECT * FROM arch_timeline WHERE task_id = ? AND is_active = 1",
            (task_id,))
    if not row:
        return {"snapshot": None}

    communities = project_db.fetchall(
        "SELECT * FROM arch_timeline_communities WHERE timeline_id = ? ORDER BY edge_type, community_id",
        (row["id"],))

    return {"snapshot": {
        "id": row["id"],
        "taskId": row["task_id"],
        "type": row["type"],
        "alias": row["alias"],
        "projectId": row["project_id"],
        "timestamp": row["timestamp"],
        "versionTag": row["version_tag"],
        "sourceVersion": row["source_version"],
        "gitBranch": row["git_branch"],
        "gitCommit": row["git_commit"],
        "gitTag": row["git_tag"],
        "communityCount": row["community_count"],
        "totalFiles": row["total_files"],
        "exported": row["exported"],
        "isActive": bool(row["is_active"]),
        "communities": [{
            "communityId": c["community_id"],
            "edgeType": c["edge_type"],
            "level": c["level"],
            "name": c["name"],
            "summary": c["summary"],
            "mermaid": c["mermaid"],
            "plantuml": c["plantuml"],
            "nodeCount": c["node_count"],
            "fileCount": c["file_count"],
            "qualityScore": c["quality_score"],
            "nodeList": json.loads(c["node_list"]) if c["node_list"] else [],
            "fileList": json.loads(c["file_list"]) if c["file_list"] else [],
            "edgeList": json.loads(c["edge_list"]) if c["edge_list"] else [],
        } for c in communities]
    }}


def delete_snapshot(multi_db: MultiDBManager, task_id: str, snapshot_id: str = None) -> dict:
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"deleted": 0}
    _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
    _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
    if snapshot_id:
        project_db.execute(
            "DELETE FROM arch_timeline_communities WHERE timeline_id = ?", (snapshot_id,))
        project_db.execute(
            "DELETE FROM arch_timeline WHERE id = ?", (snapshot_id,))
        project_db.commit()
        return {"deleted": 1}
    snaps = project_db.fetchall(
        "SELECT id FROM arch_timeline WHERE task_id = ?", (task_id,))
    for s in snaps:
        project_db.execute(
            "DELETE FROM arch_timeline_communities WHERE timeline_id = ?", (s["id"],))
    project_db.execute(
        "DELETE FROM arch_timeline WHERE task_id = ?", (task_id,))
    project_db.commit()
    return {"deleted": len(snaps)}


def export_snapshots(multi_db: MultiDBManager, task_id: str) -> dict:
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"exported": 0}
    _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
    _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
    row = project_db.fetchone(
        "SELECT * FROM arch_timeline WHERE task_id = ? AND is_active = 1", (task_id,))
    if not row:
        return {"exported": 0}

    proj = multi_db.main_db.fetchone(
        "SELECT root_path FROM projects WHERE id = ?", (row["project_id"],))
    if not proj or not proj["root_path"]:
        return {"error": "project_not_found"}

    export_dir = os.path.join(proj["root_path"], ".topocode", "archive")
    os.makedirs(export_dir, exist_ok=True)

    communities = project_db.fetchall(
        "SELECT * FROM arch_timeline_communities WHERE timeline_id = ?", (row["id"],))

    ts_suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_file = os.path.join(export_dir, f"tl_{ts_suffix}.jsonl")

    entry_data = {
        "id": row["id"], "taskId": row["task_id"], "type": row["type"],
        "alias": row["alias"], "timestamp": row["timestamp"],
        "versionTag": row["version_tag"], "sourceVersion": row["source_version"],
        "gitBranch": row["git_branch"], "gitCommit": row["git_commit"],
        "communityCount": row["community_count"], "totalFiles": row["total_files"],
        "communities": [{
            "communityId": c["community_id"],
            "edgeType": c["edge_type"], "level": c["level"],
            "name": c["name"], "summary": c["summary"],
            "mermaid": c["mermaid"], "plantuml": c["plantuml"],
            "nodeCount": c["node_count"], "fileCount": c["file_count"],
            "qualityScore": c["quality_score"],
            "fileList": json.loads(c["file_list"]) if c["file_list"] else [],
        } for c in communities],
    }
    with open(archive_file, "w", encoding="utf-8") as f:
        f.write(json.dumps(entry_data, ensure_ascii=False) + "\n")

    with open(os.path.join(export_dir, "index.jsonl"), "a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps({
                "id": row["id"], "taskId": row["task_id"], "type": row["type"],
                "alias": row["alias"], "timestamp": row["timestamp"],
                "gitBranch": row["git_branch"], "gitCommit": row["git_commit"],
                "communityCount": row["community_count"], "totalFiles": row["total_files"],
                "file": f"tl_{ts_suffix}.jsonl",
            }, ensure_ascii=False) + "\n")
            f.flush()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    project_db.execute(
        "UPDATE arch_timeline SET exported = 1 WHERE id = ?", (row["id"],))
    project_db.commit()

    return {"exported": len(communities),
            "dir": export_dir, "file": f"tl_{ts_suffix}.jsonl"}


def compare_snapshots(multi_db: MultiDBManager, snapshot_id_a: str = None,
                      snapshot_id_b: str = None, task_id_a: str = None,
                      task_id_b: str = None) -> dict:
    def _load_by_id(sid):
        for pid_row in multi_db.main_db.fetchall("SELECT id FROM projects"):
            pdb = multi_db.get_project_db(pid_row["id"])
            if not pdb:
                continue
            _ensure_table(pdb, "arch_timeline", _ARCH_TIMELINE_DDL)
            _ensure_table(pdb, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
            meta = pdb.fetchone("SELECT * FROM arch_timeline WHERE id=?", (sid,))
            if meta:
                comms = pdb.fetchall(
                    "SELECT * FROM arch_timeline_communities WHERE timeline_id=? ORDER BY community_id", (sid,))
                return meta, comms
        return None, None

    def _load_active(tid):
        pdb = _ensure_project_db(multi_db, tid)
        if not pdb:
            return None, None
        _ensure_table(pdb, "arch_timeline", _ARCH_TIMELINE_DDL)
        _ensure_table(pdb, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
        meta = pdb.fetchone(
            "SELECT * FROM arch_timeline WHERE task_id=? AND is_active=1", (tid,))
        if not meta:
            return None, None
        comms = pdb.fetchall(
            "SELECT * FROM arch_timeline_communities WHERE timeline_id=? ORDER BY community_id",
            (meta["id"],))
        return meta, comms

    if task_id_a:
        meta_a, comms_a = _load_active(task_id_a)
    else:
        meta_a, comms_a = _load_by_id(snapshot_id_a)
    if task_id_b:
        meta_b, comms_b = _load_active(task_id_b)
    else:
        meta_b, comms_b = _load_by_id(snapshot_id_b)
    if not meta_a or not meta_b:
        return {"error": "snapshot_not_found"}

    return _compare_community_sets(meta_a, comms_a, meta_b, comms_b)


def save_positions(multi_db: MultiDBManager, task_id: str, edge_type: str, drill_key: str,
                   layout_type: str, positions: list, snapshot_id=None) -> dict:
    """Batch save node positions (UPSERT per node)."""
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"saved": 0, "error": "project_db_not_found"}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    saved = 0
    for p in positions:
        project_db.execute("""
            INSERT OR REPLACE INTO graph_node_positions
                (task_id, edge_type, drill_key, snapshot_id, layout_type, node_id, pos_x, pos_y)
            VALUES (?,?,?,?,?,?,?,?)
        """, (task_id, edge_type, drill_key, snapshot_id, layout_type,
              p.get("nodeId", p.get("node_id", "")), p.get("x", 0), p.get("y", 0)))
        saved += 1
    project_db.commit()
    return {"saved": saved}


def load_positions(multi_db: MultiDBManager, task_id: str, edge_type: str, drill_key: str,
                   layout_type: str, snapshot_id=None) -> dict:
    """Load saved node positions."""
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"positions": {}}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    rows = project_db.fetchall(
        """SELECT node_id, pos_x, pos_y FROM graph_node_positions
           WHERE task_id=? AND edge_type=? AND drill_key=? AND layout_type=?
             AND snapshot_id IS ?""",
        (task_id, edge_type, drill_key, layout_type, snapshot_id))
    result = {}
    for r in rows:
        result[r["node_id"]] = {"x": r["pos_x"], "y": r["pos_y"]}
    logger.info(
        f"[loadPositions] task={task_id[:8]} edge={edge_type} drill={drill_key}"
        f" layout={layout_type} snap={snapshot_id!r} → rows={len(rows)}"
    )
    return {"positions": result}


def list_position_keys(multi_db: MultiDBManager, project_id: str) -> dict:
    """List all saved position key summaries for a project."""
    main_db = multi_db.main_db
    task_rows = main_db.fetchall(
        "SELECT id FROM analysis_tasks WHERE project_id = ?", (project_id,))
    task_ids = [r["id"] for r in task_rows]
    if not task_ids:
        return {"keys": []}
    project_db = multi_db.get_project_db(project_id)
    if not project_db:
        return {"keys": []}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    result = []
    for tid in task_ids:
        rows = project_db.fetchall(
            """SELECT edge_type, drill_key, layout_type, COUNT(*) AS cnt
               FROM graph_node_positions
               WHERE task_id = ? AND snapshot_id IS NULL
               GROUP BY edge_type, drill_key, layout_type""",
            (tid,))
        for r in rows:
            result.append({
                "taskId": tid,
                "edgeType": r["edge_type"],
                "drillKey": r["drill_key"],
                "layoutType": r["layout_type"],
                "count": r["cnt"],
            })
    return {"keys": result}


def clear_positions(multi_db: MultiDBManager, task_id: str, edge_type: str, drill_key: str,
                    layout_type: str) -> dict:
    """Clear all saved positions for a given key."""
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"deleted": 0}
    _ensure_table(project_db, "graph_node_positions", _POSITIONS_DDL)
    cursor = project_db.execute(
        """DELETE FROM graph_node_positions
           WHERE task_id=? AND edge_type=? AND drill_key=? AND layout_type=?""",
        (task_id, edge_type, drill_key, layout_type))
    deleted = cursor.rowcount if hasattr(cursor, 'rowcount') else 0
    project_db.commit()
    return {"deleted": deleted}


def list_archived_snapshots(multi_db: MultiDBManager, project_id: str) -> dict:
    main_db = multi_db.main_db
    row = main_db.fetchone(
        "SELECT root_path FROM projects WHERE id = ?", (project_id,))
    if not row or not row["root_path"]:
        return {"snapshots": []}

    index_file = os.path.join(row["root_path"], ".topocode", "archive", "index.jsonl")
    if not os.path.exists(index_file):
        return {"snapshots": []}

    snapshots = []
    with open(index_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                s = json.loads(line)
                snapshots.append({
                    "id": s.get("id", ""),
                    "type": s.get("type"),
                    "alias": s.get("alias"),
                    "taskId": s.get("taskId", ""),
                    "timestamp": s.get("timestamp", ""),
                    "gitBranch": s.get("gitBranch"),
                    "gitCommit": s.get("gitCommit"),
                    "communityCount": s.get("communityCount", 0),
                    "totalFiles": s.get("totalFiles", 0),
                    "file": s.get("file", ""),
                })
            except json.JSONDecodeError:
                continue

    return {"snapshots": snapshots}


def _load_archived_entry(project_root: str, snapshot_id: str) -> dict:
    index_file = os.path.join(project_root, ".topocode", "archive", "index.jsonl")
    if not os.path.exists(index_file):
        return {}
    file_name = None
    with open(index_file, "r", encoding="utf-8") as f:
        for line in f:
            try:
                s = json.loads(line.strip())
                if s.get("id") == snapshot_id or s.get("alias") == snapshot_id:
                    file_name = s.get("file", "")
                    break
            except json.JSONDecodeError:
                continue
    if not file_name:
        return {}
    archive_path = os.path.join(project_root, ".topocode", "archive", file_name)
    if not os.path.exists(archive_path):
        return {}
    with open(archive_path, "r", encoding="utf-8") as f:
        return json.loads(f.readline())


def compare_with_archived(multi_db: MultiDBManager, task_id: str, project_id: str,
                          archived_id: str) -> dict:
    project_db = multi_db.get_project_db(project_id)
    main_db = multi_db.main_db
    proj = main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (project_id,))
    if not proj or not proj["root_path"]:
        return {"error": "project_not_found"}

    db_snap = None
    db_communities = []
    if project_db:
        _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
        _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
        db_snap = project_db.fetchone(
            "SELECT * FROM arch_timeline WHERE task_id = ? AND is_active = 1", (task_id,))
        if db_snap:
            db_communities = project_db.fetchall(
                "SELECT * FROM arch_timeline_communities WHERE timeline_id = ? ORDER BY community_id",
                (db_snap["id"],))
    if not db_snap:
        return {"error": "current_snapshot_not_found"}

    archived_entry = _load_archived_entry(proj["root_path"], archived_id)
    if not archived_entry:
        return {"error": "archived_snapshot_not_found"}

    archived_communities = archived_entry.get("communities", [])
    archived_comms_for_cmp = [{
        "community_id": c.get("communityId", ""),
        "edge_type": c.get("edgeType", ""),
        "level": c.get("level", ""),
        "name": c.get("name"),
        "node_count": c.get("nodeCount", 0),
        "file_count": c.get("fileCount", 0),
        "quality_score": c.get("qualityScore"),
        "file_list": json.dumps(c.get("fileList", [])),
    } for c in archived_communities]

    return _compare_community_sets(db_snap, db_communities, archived_entry, archived_comms_for_cmp)


def promote_timeline_entry(multi_db: MultiDBManager, task_id: str, timeline_id: str) -> dict:
    project_db = _ensure_project_db(multi_db, task_id)
    if not project_db:
        return {"error": "project_db_not_found"}
    _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
    entry = project_db.fetchone(
        "SELECT id FROM arch_timeline WHERE id = ? AND type = 'archtrack'", (timeline_id,))
    if not entry:
        return {"error": "timeline_entry_not_found_or_not_archtrack"}
    project_db.execute(
        "UPDATE arch_timeline SET is_active = 0 WHERE task_id = ? AND is_active = 1",
        (task_id,))
    project_db.execute(
        "UPDATE arch_timeline SET type = 'manual', is_active = 1 WHERE id = ?",
        (timeline_id,))
    project_db.commit()
    return {"success": True}


def timeline_gc(multi_db: MultiDBManager, project_id: str, retention: int = 50) -> dict:
    project_db = multi_db.get_project_db(project_id)
    if not project_db:
        return {"deleted": 0}
    _ensure_table(project_db, "arch_timeline", _ARCH_TIMELINE_DDL)
    _ensure_table(project_db, "arch_timeline_communities", _ARCH_TIMELINE_COMM_DDL)
    rows = project_db.fetchall(
        "SELECT id FROM arch_timeline WHERE project_id = ? AND type = 'archtrack' ORDER BY created_at DESC",
        (project_id,))
    if len(rows) <= retention:
        return {"deleted": 0}
    ids_to_delete = [r["id"] for r in rows[retention:]]
    placeholders = ",".join("?" * len(ids_to_delete))
    project_db.execute(
        f"DELETE FROM arch_timeline_communities WHERE timeline_id IN ({placeholders})",
        ids_to_delete)
    project_db.execute(
        f"DELETE FROM arch_timeline WHERE id IN ({placeholders})",
        ids_to_delete)
    project_db.commit()
    return {"deleted": len(ids_to_delete)}


def _compare_community_sets(meta_a, comms_a, meta_b, comms_b) -> dict:
    """Shared comparison logic used by compare_snapshots and compare_with_archived."""
    def _cid(c):
        return c.get("community_id", c.get("cid", ""))

    cids_a = {_cid(c) for c in comms_a}
    cids_b = {_cid(c) for c in comms_b}
    intersection = cids_a & cids_b
    union = cids_a | cids_b
    community_jaccard = len(intersection) / len(union) if union else 0

    match_items = []
    total_files_a = meta_a.get("total_files", 0) or 0
    total_files_b = meta_b.get("totalFiles", 0) or 0  # JSONL uses camelCase
    files_a_set = set()
    files_b_set = set()

    for cid in intersection:
        ca = next((c for c in comms_a if _cid(c) == cid), None)
        cb = next((c for c in comms_b if _cid(c) == cid), None)
        fl_a = _parse_file_list(ca)
        fl_b = _parse_file_list(cb)
        files_a_set.update(fl_a)
        files_b_set.update(fl_b)
        shared = fl_a & fl_b
        file_jaccard = len(shared) / len(fl_a | fl_b) if (fl_a | fl_b) else 0
        match_items.append({
            "communityId": cid,
            "nameA": ca.get("name") if ca else None,
            "nameB": cb.get("name") if cb else None,
            "fileCountA": len(fl_a), "fileCountB": len(fl_b),
            "filesShared": len(shared),
            "filesAdded": len(fl_b - fl_a),
            "filesRemoved": len(fl_a - fl_b),
            "jaccard": round(file_jaccard, 4),
        })

    only_a = [{"communityId": cid, "name": next((c.get("name") for c in comms_a if _cid(c) == cid), None)}
              for cid in (cids_a - cids_b)]
    only_b = [{"communityId": cid, "name": next((c.get("name") for c in comms_b if _cid(c) == cid), None)}
              for cid in (cids_b - cids_a)]

    avg_file_jaccard = (sum(m["jaccard"] for m in match_items) / len(match_items)) if match_items else 0.0
    files_shared = files_a_set & files_b_set

    def _get(meta, key, fallback_key=None):
        return meta.get(key) or (meta.get(fallback_key) if fallback_key else None) or 0

    return {
        "a": {"id": meta_a.get("id", ""), "alias": meta_a.get("alias"),
              "communityCount": _get(meta_a, "community_count", "communityCount"),
              "totalFiles": _get(meta_a, "total_files", "totalFiles")},
        "b": {"id": meta_b.get("id", ""), "alias": meta_b.get("alias"),
              "communityCount": _get(meta_b, "communityCount", "community_count"),
              "totalFiles": _get(meta_b, "totalFiles", "total_files")},
        "communityMatches": match_items,
        "communitiesOnlyInA": only_a,
        "communitiesOnlyInB": only_b,
        "overall": {
            "communityJaccard": round(community_jaccard, 4),
            "avgFileJaccard": round(avg_file_jaccard, 4),
            "totalFilesA": total_files_a,
            "totalFilesB": total_files_b,
            "filesShared": len(files_shared),
        },
    }


def _parse_file_list(community: dict | None) -> set:
    """Parse file_list from a community record (SQLite or JSONL)."""
    if not community:
        return set()
    fl = community.get("file_list", "")
    if not fl:
        return set()
    if isinstance(fl, str):
        try:
            return set(json.loads(fl))
        except (json.JSONDecodeError, TypeError):
            return set()
    if isinstance(fl, list):
        return set(fl)
    return set()
