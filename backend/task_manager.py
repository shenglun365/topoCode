"""
Task Manager — 13 个 analysis.* 后端方法

通过 @server.register 注册到 RPC 服务器。
"""
import asyncio
import json
import os
import time
import uuid
import logging
from typing import Optional

from store.connection import MultiDBManager
from store.task_store import TaskStore
from store.analysis_store import AnalysisStore
from analyst_runner import _execute_task, set_stop_flag, clear_stop_flag, is_task_executing

logger = logging.getLogger(__name__)

# 字段映射 (camelCase → snake_case)
_FIELD_MAP = {
    "excludeDirs": "exclude_dirs",
    "reportTypes": "report_types",
    "patternType": "pattern_type",
    "selectedExtensions": "selected_extensions",
}


def register_analysis_methods(server, multi_db: MultiDBManager):
    """将所有 analysis.* 方法注册到 RPC 服务器"""

    @server.register("analysis.listTasks")
    def list_tasks(project_id=None, projectId=None):
        pid = project_id or projectId
        if not pid:
            raise ValueError("project_id is required")
        store = TaskStore(multi_db.main_db)
        return store.list_tasks(pid)

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
        asyncio.create_task(_execute_task(server, multi_db, tid, run["id"], start_time))

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

        # 清理项目库中的分析数据（保留 base_node AST 数据）
        project_id = task["project_id"]
        try:
            project_db = multi_db.get_project_db(project_id)
            project_db.execute("DELETE FROM graph_node WHERE task_id = ?", (tid,))
            project_db.execute("DELETE FROM graph_doc WHERE task_id = ?", (tid,))
            project_db.execute("DELETE FROM community_hierarchy WHERE task_id = ?", (tid,))
            project_db.execute("DELETE FROM community_llm_results WHERE task_id = ?", (tid,))
            project_db.commit()
            logger.info(f"[analysis.deleteTask] Cleared analysis data for task {tid} in project {project_id}")
        except Exception as e:
            logger.warning(f"[analysis.deleteTask] Failed to clear project data: {e}")

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
            "base_node", "graph_node", "graph_doc", "community_hierarchy",
            "community_llm_results",
            "ast_data", "dependencies", "call_chains", "components", "ai_qa"
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
        proj_db_path = os.path.join(multi_db.data_dir, f"{project_id}.db")
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
            "community_llm_results", "graph_node", "graph_doc", "base_node",
            "components", "ai_qa",
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
        if tasks:
            counts["tasks"] = len(tasks)
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
                task_store.delete_task(task["id"])
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
        if task["status"] in ("running", "queued"):
            raise RuntimeError(f"Task {tid} is already {task['status']}")

        # 复用当前配置创建新运行
        run = store.create_run(tid, {
            "scope": task.get("scope"),
            "scopes": task.get("scopes", []),
            "extensions": task.get("extensions", []),
            "exclude_dirs": task.get("exclude_dirs", []),
            "report_types": task.get("report_types", []),
        })

        store.update_task_status(tid, "running", progress=0, error="")

        start_time = time.time()
        asyncio.create_task(_execute_task(server, multi_db, tid, run["id"], start_time))

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

            # 1. 按 scopes/exclude/pattern 过滤的文件（不含 selectedExtensions）— 用于完整 extensions 分布
            files_for_extensions = store.list_source_files(
                scopes=final_scopes,
                exclude_dirs=exclude_dirs,
                pattern_type=pattern_type,
                pattern=pattern,
            )
            logger.debug(f"[scan_file_stats] {len(files_for_extensions)} files for extensions distribution")

            # 2. 按所有条件过滤的文件（含 selectedExtensions）— 用于 totalFiles
            files_for_count = store.list_source_files(
                scopes=final_scopes,
                extensions=selected_extensions,
                exclude_dirs=exclude_dirs,
                pattern_type=pattern_type,
                pattern=pattern,
            )
            logger.debug(f"[scan_file_stats] filtered {len(files_for_count)} files for totalFiles")

            # 3. 全量文件 — 用于构建完整目录树（不受 scopes 影响）
            all_files = store.list_source_files()
            logger.debug(f"[scan_file_stats] total {len(all_files)} files for directory tree")

        except Exception as e:
            logger.error(f"[scan_file_stats] error: {e}")
            files_for_extensions = []
            files_for_count = []
            all_files = []

        # 文件分布统计（基于 scopes/exclude/pattern 过滤，不含 selectedExtensions — 保证所有类型可见）
        extensions = {}
        for f in files_for_extensions:
            lang = f.get("language", "unknown")
            extensions[lang] = extensions.get(lang, 0) + 1

        # 完整目录树（基于全量文件，不受 scopes 影响）
        dir_tree: dict = {}
        for f in all_files:
            dir_path = f.get("file_path", "")
            if dir_path:
                parts = dir_path.split("/")
                current = dir_tree
                for part in parts[:-1]:  # 跳过文件名，只处理目录
                    if part not in current:
                        current[part] = {}
                    current = current[part]

        # 将树形结构展平为前端可用的格式
        def flatten_dir_tree(tree: dict, prefix: str = "") -> list:
            result = []
            for name, children in sorted(tree.items()):
                path = f"{prefix}/{name}" if prefix else name
                node = {
                    "name": name,
                    "path": path,
                    "children": flatten_dir_tree(children, path) if children else [],
                }
                result.append(node)
            return result

        def count_all_dirs(tree: dict) -> int:
            """递归计算目录树中的节点总数"""
            count = len(tree)
            for children in tree.values():
                count += count_all_dirs(children)
            return count

        dir_list = flatten_dir_tree(dir_tree)
        total_dirs = count_all_dirs(dir_tree)

        return {
            "extensions": extensions,
            "totalFiles": len(files_for_count),
            "totalDirs": total_dirs,
            "directories": dir_list,
        }

    # ==================== 社区 LLM 结果 ====================

    @server.register("analysis.saveCommunityResult")
    def save_community_result(task_id=None, taskId=None, edge_type=None, edgeType=None,
                                comm_lv=None, commLv=None, comm_id=None, commId=None,
                                name=None, summary=None, mermaid=None, plantuml=None,
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
        logger.info("[analysis.saveCommunityResult] validated name=%s summary_len=%d mermaid_len=%d plantuml_len=%d model_id=%s template_id=%s",
                     name, len(summary or ''), len(mermaid or ''), len(plantuml or ''), mid, tpid)
        validated = {
            "task_id": tid, "edge_type": et, "comm_lv": cl, "comm_id": cid,
            "name": name, "summary": summary,
            "mermaid": mermaid, "plantuml": plantuml,
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

            node_id 格式:
              - CALL:  file-{hash}:{funcName}  (如 file-abc123:constructor)
              - INCLUDE: file-{hash} 或裸 hash (如 file-abc123, abc123)
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

            # 解析 node_id → (file_hash, func_name)
            pairs = []
            for nid in all_node_ids:
                if ':' in nid:
                    fh, fn = nid.split(':', 1)
                    pairs.append((fh.strip(), fn.strip()))
                else:
                    pairs.append((nid, None))

            # 从 graph_node 批量查询节点元数据
            # 构建 (file_id, func_name) → graph_node row 的映射
            gn_rows = project_db.execute(
                "SELECT id, caller_file_id, caller_func_name, callee_file_id, callee_name,"
                "       file_id, func_name, class_name, method_name, symbol_node_type"
                " FROM graph_node WHERE task_id=?",
                (tid,)
            ).fetchall()

            # 构建两个索引: (file_id, func_name) → row
            caller_index = {}  # (caller_file_id, caller_func_name) → row
            callee_index = {}  # (callee_file_id, callee_name) → row
            file_index = {}    # (file_id,) → row (for INCLUDE)
            for row in gn_rows:
                cfi = str(row['caller_file_id'] or '')
                cfn = str(row['caller_func_name'] or '')
                cai = str(row['callee_file_id'] or '')
                can = str(row['callee_name'] or '')
                fi = str(row['file_id'] or '')
                fn = str(row['func_name'] or '')
                if cfi and cfi != 'None' and cfn and cfn != 'None':
                    caller_index[(cfi, cfn)] = row
                if cai and cai != 'None' and can and can != 'None':
                    callee_index[(cai, can)] = row
                if fi and fi != 'None' and fn and fn != "None":
                    file_index[(fi, fn)] = row

            # 为每个 node_id 查询元数据
            for nid in all_node_ids:
                label = nid
                file_id = ''
                file_path = ''
                graph_node_id = None
                symbol_name = ''

                if ':' in nid:
                    fh, fn_name = nid.split(':', 1)
                    fh, fn_name = fh.strip(), fn_name.strip()

                    # 先按 caller 查找
                    row = caller_index.get((fh, fn_name))
                    if not row:
                        # 再按 callee 查找
                        row = callee_index.get((fh, fn_name))
                    if not row:
                        # 最后按 file+func 查找
                        row = file_index.get((fh, fn_name))

                    if row:
                        graph_node_id = row['id']
                        file_id = str(row['caller_file_id'] or row['file_id'] or fh)
                        symbol_name = fn_name
                        # 构建实名标签
                        file_name = file_name_map.get(file_id, '')
                        if file_name:
                            label = f'{file_name}::{symbol_name}'
                        else:
                            label = f'{fh}::{symbol_name}'
                        if row['class_name']:
                            label = f'{row["class_name"]}.{symbol_name} ({file_name or fh})'
                else:
                    # 无冒号：裸 file_id（INCLUDE 类型或 file-hash）
                    fh = nid
                    # 尝试用 file-hash 查找
                    file_name = file_name_map.get(fh, '')
                    if file_name:
                        label = file_name
                        file_id = fh
                    else:
                        # 可能是去掉 "file-" 前缀的 hash，尝试补全
                        prefixed = f'file-{fh}'
                        file_name = file_name_map.get(prefixed, '')
                        if file_name:
                            label = file_name
                            file_id = prefixed
                        else:
                            label = fh
                            file_id = fh

                if file_id:
                    file_path = file_path_map.get(file_id, '')

                ref_map[nid] = {
                    'label': label,
                    'fileId': file_id,
                    'filePath': file_path,
                    'graphNodeId': graph_node_id,
                    'symbolName': symbol_name,
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
            """将语法级节点汇聚到文件级：去重 + 合并边，用 source_files 实名"""
            file_nodes = {}
            for node_id in _nodes:
                clean_id = node_id.split(':')[0] if ':' in (node_id or '') else node_id
                if bad_id(clean_id):
                    continue
                if clean_id not in file_nodes:
                    # 从 source_files / ref_map 获取标签（多种 ID 格式兼容）
                    label = file_name_map.get(clean_id, '')
                    if not label:
                        # 尝试 file- 前缀补全
                        label = file_name_map.get(f'file-{clean_id}', '')
                    if not label and clean_id.startswith('file-'):
                        # 尝试去掉 file- 前缀
                        label = file_name_map.get(clean_id[5:], '')
                    if not label:
                        # 尝试 ref_map（原始 node_id 或干净 ID）
                        label = ref_map.get(clean_id, {}).get('label', '')
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
            "SELECT symbol_node_type, func_name, class_name, method_name, macro_name, file_id FROM graph_node WHERE task_id=? AND id=?",
            (tid, sid)
        ).fetchone()

        if not row:
            # 尝试按名称搜索
            row = project_db.execute(
                "SELECT symbol_node_type, func_name, class_name, method_name, macro_name, file_id FROM graph_node WHERE task_id=? AND (func_name=? OR class_name=? OR method_name=? OR macro_name=?)",
                (tid, sid, sid, sid, sid)
            ).fetchone()

        if not row:
            return None

        symbol_type = row[0]
        func_name = row[1]
        class_name = row[2]
        method_name = row[3]
        macro_name = row[4]
        file_id = row[5]

        # 获取文件路径
        file_path = ''
        if file_id:
            file_row = project_db.execute(
                "SELECT file_path FROM source_files WHERE id=?",
                (file_id,)
            ).fetchone()
            file_path = file_row[0] if file_row else ''

        # 查询 AST 节点获取行号
        start_line = 1
        end_line = 20
        ast_row = project_db.execute(
            "SELECT start, end FROM base_node WHERE file_id=? AND name=? LIMIT 1",
            (file_id, func_name or method_name or class_name or macro_name)
        ).fetchone()

        if ast_row:
            try:
                start_line = int(ast_row[0].split(',')[0])
                end_line = int(ast_row[1].split(',')[0])
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
            'name': func_name or method_name or class_name or macro_name or sid,
            'class_name': class_name,
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
            "SELECT symbol_node_type, caller_func_name, caller_file_id, callee_name, callee_file_id, call_site_node_id, include_path, is_system FROM graph_node WHERE task_id=? AND id=?",
            (tid, eid)
        ).fetchone()

        if not row:
            # 尝试通过 source/target 查找
            row = project_db.execute(
                "SELECT symbol_node_type, caller_func_name, caller_file_id, callee_name, callee_file_id, call_site_node_id, include_path, is_system FROM graph_node WHERE task_id=? AND (caller_func_name=? OR callee_name=?)",
                (tid, source_id, target_id)
            ).fetchone()

        if not row:
            return None

        symbol_type = row[0]

        if symbol_type == 'call_relation':
            return {
                'edge_id': eid,
                'edge_type': 'CALL',
                'source': {
                    'name': row[1],  # caller_func_name
                    'file_id': row[2],  # caller_file_id
                },
                'target': {
                    'name': row[3],  # callee_name
                    'file_id': row[4],  # callee_file_id
                },
                'call_site_node_id': row[5],
            }
        elif symbol_type == 'dependence':
            return {
                'edge_id': eid,
                'edge_type': 'DEPENDENCE',
                'include_path': row[6],
                'is_system': row[7],
            }

        return None

    # ==================== 级联社区查询 ====================

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
        project_id = task["project_id"]
        project_db = multi_db.get_project_db(project_id)

        rows = project_db.execute(
            """SELECT DISTINCT h.comm_lv, h.comm_id, h.parent_comm_id, h.node_count, h.quality_score, COALESCE(g.edge_count, 0)
               FROM community_hierarchy h
               LEFT JOIN graph_doc g ON g.task_id = h.task_id AND g.edge_type = h.edge_type AND g.comm_id = h.comm_id
               WHERE h.task_id=? AND h.edge_type=?
               ORDER BY h.comm_lv, h.comm_id""",
            (tid, et)
        ).fetchall()
        logger.info("[analysis.getCascadeLevels] query returned %d rows task_id=%s edge_type=%s", len(rows), tid, et)

        levels_dict: dict[str, list] = {}
        for row in rows:
            lv, comm_id, parent_id, node_count, quality, edge_count = row
            if lv not in levels_dict:
                levels_dict[lv] = []
            levels_dict[lv].append({
                'id': comm_id,
                'label': comm_id[:30],
                'parentCommId': parent_id,
                'nodeCount': node_count or 0,
                'edgeCount': edge_count or 0,
                'qualityScore': quality,
            })

        result = []
        for lv in sorted(levels_dict.keys()):
            result.append({
                'lv': lv,
                'items': levels_dict[lv],
            })
        logger.info("[analysis.getCascadeLevels] DONE task_id=%s edge_type=%s levels=%s total_items=%d",
                     tid, et, sorted(levels_dict.keys()),
                     sum(len(v) for v in levels_dict.values()))

        return {'levels': result}

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

    @server.register("report.savePipelineState")
    def save_pipeline_state(task_id=None, taskId=None, state_json=None, stateJson=None):
        """保存 pipeline 运行状态到 report_subdocs"""
        tid = task_id or taskId
        raw = state_json or stateJson
        if not tid:
            raise ValueError("task_id is required")
        if not raw:
            raise ValueError("state_json is required")
        if isinstance(raw, dict):
            raw = json.dumps(raw)

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pdb = multi_db.get_project_db(task["project_id"])

        doc_id = f"pipeline-state-{tid}"
        now = time.strftime('%Y-%m-%d %H:%M:%S')
        pdb.execute(
            "INSERT OR REPLACE INTO report_subdocs (id, task_id, edge_type, comm_id, title, content, created_at, updated_at) VALUES (?, ?, '', '__pipeline_state__', ?, ?, ?, ?)",
            (doc_id, tid, 'Pipeline State', raw, now, now)
        )
        pdb.commit()
        return {'ok': True, 'id': doc_id}

    @server.register("report.loadPipelineState")
    def load_pipeline_state(task_id=None, taskId=None):
        """从 report_subdocs 恢复 pipeline 运行状态"""
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        pdb = multi_db.get_project_db(task["project_id"])

        row = pdb.execute(
            "SELECT content FROM report_subdocs WHERE id=?",
            (f"pipeline-state-{tid}",)
        ).fetchone()

        if row:
            return {'state': json.loads(row[0]) if row[0] else None}
        return {'state': None}

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
