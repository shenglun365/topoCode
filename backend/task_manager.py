"""
Task Manager — 13 个 analysis.* 后端方法

通过 @server.register 注册到 RPC 服务器。
"""
import asyncio
import json
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
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        if task["status"] == "running":
            raise RuntimeError(f"Task {tid} is already running")

        # 创建运行记录
        run = store.create_run(tid, {
            "scope": task.get("scope"),
            "scopes": task.get("scopes", []),
            "extensions": task.get("extensions", []),
            "exclude_dirs": task.get("exclude_dirs", []),
            "report_types": task.get("report_types", []),
        })

        # 更新任务状态
        store.update_task_status(tid, "running", progress=0)

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
            raise ValueError(f"Task {tid} not found")
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
            project_db.commit()
            logger.info(f"[analysis.deleteTask] Cleared analysis data for task {tid} in project {project_id}")
        except Exception as e:
            logger.warning(f"[analysis.deleteTask] Failed to clear project data: {e}")

        # 删除主库中的任务（CASCADE 删除 runs/reports/history）
        return store.delete_task(tid)

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
            store.update_task_status(tid, "stopped")

        # 发布事件
        server.publish("task", "stopped", {
            "taskId": tid,
            "runId": task.get("last_run_id"),
            "status": "stopped",
        })

        logger.info(f"[analysis.stopTask] task={tid}")
        return {"taskId": tid, "status": "stopped"}

    @server.register("analysis.reRunTask")
    async def re_run_task(task_id=None, taskId=None):
        tid = task_id or taskId
        if not tid:
            raise ValueError("task_id is required")

        store = TaskStore(multi_db.main_db)
        task = store.get_task(tid)
        if not task:
            raise ValueError(f"Task {tid} not found")
        if task["status"] == "running":
            raise RuntimeError(f"Task {tid} is already running")

        # 复用当前配置创建新运行
        run = store.create_run(tid, {
            "scope": task.get("scope"),
            "scopes": task.get("scopes", []),
            "extensions": task.get("extensions", []),
            "exclude_dirs": task.get("exclude_dirs", []),
            "report_types": task.get("report_types", []),
        })

        store.update_task_status(tid, "running", progress=0)

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

    # ==================== 报告 Tab 接口 ====================

    @server.register("analysis.getAvailableLevels")
    def get_available_levels(task_id=None, taskId=None, edge_type=None, edgeType=None):
        """获取任务实际生成的社区层级列表"""
        tid = task_id or taskId
        et = edge_type or edgeType
        if not tid:
            raise ValueError("task_id is required")

        project_db = multi_db.get_project_db(tid)
        rows = project_db.execute(
            "SELECT DISTINCT comm_lv FROM graph_doc WHERE task_id=? ORDER BY comm_lv",
            (tid,)
        ).fetchall()
        levels = [row[0] for row in rows]

        # 如果没有指定 edge_type，返回所有层级
        # 如果指定了，过滤对应边类型的层级
        if et:
            rows = project_db.execute(
                "SELECT DISTINCT comm_lv FROM graph_doc WHERE task_id=? AND edge_type=? ORDER BY comm_lv",
                (tid, et)
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

        project_db = multi_db.get_project_db(tid)

        # 查询选中的社区
        if ids and len(ids) > 0:
            placeholders = ','.join(['?' for _ in ids])
            rows = project_db.execute(
                f"SELECT comm_id, node_list, edge_list, node_count, edge_count, quality_score, description FROM graph_doc WHERE task_id=? AND comm_lv=? AND comm_id IN ({placeholders})",
                [tid, lv] + ids
            ).fetchall()
        else:
            # 返回该层级所有社区
            rows = project_db.execute(
                "SELECT comm_id, node_list, edge_list, node_count, edge_count, quality_score, description FROM graph_doc WHERE task_id=? AND comm_lv=? ORDER BY quality_score DESC",
                (tid, lv)
            ).fetchall()

        nodes = []
        edges = []
        communities = []

        for row in rows:
            comm_id = row[0]
            node_list = json.loads(row[1]) if row[1] else []
            edge_list = json.loads(row[2]) if row[2] else []
            node_count = row[3] or 0
            edge_count = row[4] or 0
            quality_score = row[5] or 0
            description = row[6] or ''

            # 添加社区节点
            communities.append({
                'comm_id': comm_id,
                'node_count': node_count,
                'edge_count': edge_count,
                'quality_score': quality_score,
                'description': description,
            })

            # 添加节点和边
            for node in node_list:
                nodes.append({
                    'id': f'n_{node}',
                    'label': str(node),
                    'comm_id': comm_id,
                    'type': 'symbol',
                })
            for edge in edge_list:
                if isinstance(edge, list) and len(edge) >= 2:
                    edges.append({
                        'id': f'e_{edge[0]}_{edge[1]}',
                        'source': f'n_{edge[0]}',
                        'target': f'n_{edge[1]}',
                        'type': et or 'CALL',
                    })

            # 深度展开：查询子社区
            if d > 1:
                child_rows = project_db.execute(
                    "SELECT comm_id, node_list, edge_list, node_count, comm_lv FROM graph_doc WHERE task_id=? AND parent_comm_id=?",
                    (tid, comm_id)
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
                                "SELECT comm_id, node_list, edge_list, node_count FROM graph_doc WHERE task_id=? AND parent_comm_id=?",
                                (tid, child_comm_id)
                            ).fetchall()
                            child_rows = grandchild_rows
                        else:
                            # 最深层，直接添加符号节点
                            for node in child_node_list:
                                nodes.append({
                                    'id': f'n_{child_comm_id}_{node}',
                                    'label': str(node),
                                    'comm_id': child_comm_id,
                                    'type': 'symbol',
                                })
                            for edge in (child_edge_list or []):
                                if isinstance(edge, list) and len(edge) >= 2:
                                    edges.append({
                                        'id': f'e_{child_comm_id}_{edge[0]}_{edge[1]}',
                                        'source': f'n_{child_comm_id}_{edge[0]}',
                                        'target': f'n_{child_comm_id}_{edge[1]}',
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

        project_db = multi_db.get_project_db(tid)

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

        project_db = multi_db.get_project_db(tid)

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
