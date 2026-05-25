"""
Analyst Runner — 6 步分析流程执行器

对应原 full_analyst.py 的 Celery chain，改为同步执行。
- _execute_task: asyncio 协程，提交到 ThreadPoolExecutor
- _do_parse: 6 步分析流程（线程池中阻塞执行）
- _update_progress: 进度更新 + ZMQ PUB 推送
"""
import asyncio
import concurrent.futures
import logging
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, Any, Optional

from config import (
    PARSE_WORKERS, PARSE_THREAD_PREFIX, PROGRESS_INTERVAL,
    COMMUNITY_MIN_NODE_INCLUDE, COMMUNITY_MIN_NODE_CALL,
)

# ==================== 线程池 ====================
parse_executor = ThreadPoolExecutor(
    max_workers=PARSE_WORKERS,
    thread_name_prefix=PARSE_THREAD_PREFIX,
)

# ==================== 停止标志 ====================
_stop_flags: Dict[str, bool] = {}
_executing_tasks: set = set()  # 正在执行的任务 ID 集合

logger = logging.getLogger(__name__)


def set_stop_flag(task_id: str):
    """设置任务停止标志"""
    _stop_flags[task_id] = True


def clear_stop_flag(task_id: str):
    """清除任务停止标志"""
    _stop_flags.pop(task_id, None)


def should_stop(task_id: str) -> bool:
    """检查是否应该停止"""
    return _stop_flags.get(task_id, False)


def is_task_executing(task_id: str) -> bool:
    """检查任务是否正在线程池中执行"""
    return task_id in _executing_tasks


# ==================== 进度回调 ====================

def _update_progress(server, multi_db, task_id: str, run_id: str,
                     current: int, total: int):
    """
    更新进度: SQLite + ZMQ PUB 推送

    Args:
        server: ZMQServer 实例（有 publish 方法）
        multi_db: MultiDBManager 实例（复用连接）
        task_id: 任务 ID
        run_id: 运行 ID
        current: 当前处理到第几个文件
        total: 总文件数
    """
    progress = int(current * 100 / total) if total > 0 else 0

    # 更新任务进度 (execute() 已自动 commit)
    multi_db.main_db.execute("""
        UPDATE analysis_tasks
        SET progress = ?, current = ?, updated_at = datetime('now')
        WHERE id = ?
    """, (progress, current, task_id))

    # 更新运行记录进度 (execute() 已自动 commit)
    multi_db.main_db.execute("""
        UPDATE analysis_task_runs
        SET progress = ?, current = ?
        WHERE id = ?
    """, (progress, current, run_id))

    # 推送 ZMQ 事件
    if server:
        server.publish("task", "progress", {
            "taskId": task_id,
            "runId": run_id,
            "progress": progress,
            "total": total,
            "current": current,
        })


# ==================== 6 步分析流程 ====================

def _do_parse(server, multi_db, task_id: str, run_id: str,
              start_time: float) -> Dict[str, Any]:
    """
    线程池中的阻塞执行函数 — 6 步分析流程

    使用 backend/parsers/ 架构:
    - parser.parse_file() → AST 解析
    - extract_global_symbols() → 符号提取
    - extract_call_graph() → 调用图
    - extract_dependency_graph() → 依赖图
    - analyze_communities() → 社区分析

    Args:
        server: ZMQServer 实例
        multi_db: MultiDBManager 实例
        task_id: 任务 ID
        run_id: 运行 ID
        start_time: 开始时间戳

    Returns:
        分析结果摘要
    """
    import os

    from store.task_store import TaskStore
    from store.analysis_store import AnalysisStore
    from parsers.db_adapter import SQLiteAdapter
    from parsers.parser import parse_file
    from parsers.extract_global_symbols import extract_global_symbols
    from parsers.extract_call_graph import extract_call_graph
    from parsers.extract_dependency_graph import extract_dependency_graph
    from community_analysis import analyze_communities

    task_store = TaskStore(multi_db.main_db)

    # 1. 加载任务配置
    task = task_store.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    project_id = task["project_id"]
    project_db = multi_db.get_project_db(project_id)
    analysis_store = AnalysisStore(project_db)
    adapter = SQLiteAdapter(project_db, task_id)

    # 调试日志：确认两个 store 是否共享连接
    logger.info(f"[PARSE] [DEBUG] task_id={task_id}, project_id={project_id}")
    logger.info(f"[PARSE] [DEBUG] analysis_store._db id={id(analysis_store._db)}, adapter._store._db id={id(adapter._store._db)}, same={analysis_store._db is adapter._store._db}")

    # 解析配置字段（TaskStore.get_task 已通过 _parse_task_row 反序列化，无需再次 json.loads）
    scopes = task.get("scopes") or []
    extensions = task.get("extensions") or []
    exclude_dirs = task.get("exclude_dirs") or []
    pattern_type = task.get("pattern_type")
    pattern = task.get("pattern")
    report_types = task.get("report_types") or []

    # 获取项目根路径
    project = multi_db.main_db.fetchone(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    )
    proj_path = project.get("root_path", "") if project else ""

    # 2. 获取文件列表
    files = analysis_store.list_source_files(
        scopes=scopes,
        extensions=extensions,
        exclude_dirs=exclude_dirs,
        pattern_type=pattern_type,
        pattern=pattern,
    )
    total = len(files)
    logger.info(f"[PARSE] 共 {total} 个文件待分析")

    if total == 0:
        logger.warning(f"[PARSE] 没有文件需要分析")
        return {"files_processed": 0, "skipped_files": 0}

    # 3. 检查是否有旧报告（有则保留 base_node AST 数据，跳过重解析）
    prev_report = task_store._db.execute(
        "SELECT * FROM analysis_reports WHERE task_id = ?", (task_id,)
    ).fetchone()
    skip_ast = False
    if prev_report:
        skip_ast = True
        logger.info(f"[PARSE] 存在旧报告，保留 base_node AST 数据，跳过重解析")

    # 4. 清理旧数据（符号/调用图/依赖图/社区 — 总是重新计算）
    logger.info(f"[PARSE] 清理任务 {task_id} 的旧数据")
    analysis_store.clear_task_data(task_id)

    # 4. 按语言分组
    files_by_lang = {}
    for f in files:
        lang = f.get("language")
        if lang:
            files_by_lang.setdefault(lang, []).append(f)

    language_stats = {lang: len(fl) for lang, fl in files_by_lang.items()}
    logger.info(f"[PARSE] [DEBUG] 语言分布: {language_stats}")
    processed = 0
    skipped = 0
    logs = []

    def _log(msg: str):
        logs.append({"timestamp": datetime.utcnow().isoformat(), "message": msg})
        logger.info(f"[PARSE] {msg}")

    # ==================== Step 1: AST 解析（并行） ====================
    if skip_ast:
        _log("Step 1: AST 解析跳过（保留已有 base_node 数据）")
        processed = total  # 标记所有文件已处理
    else:
        _log(f"Step 1: AST 解析开始（并行，{PARSE_WORKERS} 个工作线程）")
        total_ast_nodes = 0

        # 构建所有文件的解析任务
        all_tasks = []
        for lang, file_list in files_by_lang.items():
            for f in file_list:
                abs_path = os.path.join(proj_path, f["file_path"]) if proj_path else f["file_path"]
                all_tasks.append((lang, f, abs_path))

        _log(f"共 {len(all_tasks)} 个文件待解析")

        def _parse_one(lang, f, abs_path):
            """同步解析单个文件（在线程池中执行）"""
            if should_stop(task_id):
                return (lang, f, 'stopped')
            try:
                result = parse_file(
                    source_file_path=abs_path,
                    project_db=project_db,
                    task_id=task_id,
                    proj_path=proj_path,
                )
                return (lang, f, result)
            except Exception as e:
                return (lang, f, f"error: {e}")

        # 使用 ThreadPoolExecutor 并行解析（同步上下文）
        with ThreadPoolExecutor(max_workers=PARSE_WORKERS) as file_executor:
            # 分批提交，每批最多 PARSE_WORKERS * 2 个任务
            batch_size = PARSE_WORKERS * 2
            for batch_start in range(0, len(all_tasks), batch_size):
                if should_stop(task_id):
                    _log("检测到停止标志，中断解析")
                    break

                batch = all_tasks[batch_start:batch_start + batch_size]
                _log(f"提交批次 {(batch_start // batch_size) + 1}: {len(batch)} 个文件")

                # 提交批次内所有任务
                futures = {
                    file_executor.submit(_parse_one, lang, f, abs_path): (lang, f)
                    for lang, f, abs_path in batch
                }

                # 等待批次完成并收集结果
                for future in concurrent.futures.as_completed(futures):
                    if should_stop(task_id):
                        _log("检测到停止标志，中断解析")
                        break

                    try:
                        lang, f, node_count = future.result()
                    except Exception as e:
                        _log(f"解析任务异常: {e}")
                        continue

                    if node_count == 'stopped':
                        continue
                    elif str(node_count).startswith('error:'):
                        _log(f"解析失败 {f['file_path']}: {node_count}")
                        continue
                    elif node_count == -1:
                        skipped += 1
                    else:
                        processed += 1
                        language_stats[lang] = language_stats.get(lang, 0) + 1

                    # 文件级进度检查
                    if processed % PROGRESS_INTERVAL == 0:
                        _update_progress(server, multi_db, task_id, run_id, processed, total)

        if should_stop(task_id):
            _log("AST 解析被用户停止")
            return {"files_processed": processed, "skipped_files": skipped, "stopped": True}

        _log(f"AST 解析完成 - 处理 {processed} 个文件，跳过 {skipped} 个")

    # 统计 AST 节点总数
    row = analysis_store.count_nodes()
    total_ast_nodes = row if isinstance(row, int) else (row[0] if row else 0)
    _log(f"AST 节点总数: {total_ast_nodes}")

    # ==================== Step 2: 符号提取 ====================
    _log("Step 2: 符号提取开始")
    total_symbols = 0
    try:
        total_symbols = extract_global_symbols(adapter)
        _log(f"符号提取完成: {total_symbols} 个符号")
    except Exception as e:
        _log(f"符号提取失败: {e}")

    # ==================== Step 3: 调用图提取 ====================
    _log("Step 3: 调用图提取开始")
    total_call_edges = 0
    try:
        call_edges = extract_call_graph(adapter)
        total_call_edges = len(call_edges)
        _log(f"调用图提取完成: {total_call_edges} 条调用边")
    except Exception as e:
        _log(f"调用图提取失败: {e}")

    # ==================== Step 4: 依赖图提取 ====================
    _log("Step 4: 依赖图提取开始")
    total_dep_edges = 0
    try:
        dep_edges = extract_dependency_graph(adapter)
        total_dep_edges = len(dep_edges)
        _log(f"依赖图提取完成: {total_dep_edges} 条依赖边")
    except Exception as e:
        _log(f"依赖图提取失败: {e}")

    # 调试日志：确认边是否写入数据库
    dep_check = analysis_store.get_dep_edges(task_id)
    call_check = analysis_store.get_call_edges(task_id)
    _log(f"[DEBUG] 数据库验证: dep_edges_in_db={len(dep_check)}, call_edges_in_db={len(call_check)}")

    # ==================== Step 5: 社区分析 ====================
    _log("Step 5: 社区分析开始")
    total_communities = 0
    total_hubs = 0
    total_orphans = 0
    best_call_community_id = None
    best_dep_community_id = None

    # 调试日志：确认 task_id 和 analysis_store
    _log(f"[DEBUG] 社区分析参数: task_id={task_id}, analysis_store id={id(analysis_store)}, report_types={report_types}")

    # 根据 report_types 配置选择分析类型
    if "dependency" in report_types or "full" in report_types:
        try:
            from community_analysis import analyze_communities
            comm_result = analyze_communities(
                task_id=task_id,
                analysis_store=analysis_store,
                edge_type="INCLUDE",
                min_node_cnt=COMMUNITY_MIN_NODE_INCLUDE,
            )
            total_communities += comm_result.get("community_count", 0)
            total_hubs += comm_result.get("hub_count", 0)
            total_orphans += comm_result.get("orphan_count", 0)
            best = analysis_store.get_best_community(task_id, "INCLUDE")
            if best:
                best_dep_community_id = best["comm_id"]
            _log(f"INCLUDE 社区分析完成: {comm_result.get('community_count', 0)} 个社区"
                 f" (枢纽={total_hubs}, 孤立={total_orphans})")
        except Exception as e:
            _log(f"INCLUDE 社区分析失败: {e}")

    if "callChain" in report_types or "full" in report_types:
        try:
            from community_analysis import analyze_communities
            comm_result = analyze_communities(
                task_id=task_id,
                analysis_store=analysis_store,
                edge_type="CALL",
                min_node_cnt=COMMUNITY_MIN_NODE_CALL,
            )
            total_communities += comm_result.get("community_count", 0)
            total_hubs += comm_result.get("hub_count", 0)
            total_orphans += comm_result.get("orphan_count", 0)
            best = analysis_store.get_best_community(task_id, "CALL")
            if best:
                best_call_community_id = best["comm_id"]
            _log(f"CALL 社区分析完成: {comm_result.get('community_count', 0)} 个社区"
                 f" (枢纽={total_hubs}, 孤立={total_orphans})")
        except Exception as e:
            _log(f"CALL 社区分析失败: {e}")

    # ==================== Step 6: 结果汇总 ====================
    _log("Step 6: 结果汇总")
    duration_ms = int((time.time() - start_time) * 1000)

    # 统计总数
    total_ast_nodes = analysis_store.count_nodes()
    total_symbols = analysis_store.count_by_task_and_type(task_id)

    report = {
        "id": str(uuid.uuid4()),
        "task_id": task_id,
        "run_id": run_id,
        "total_ast_nodes": total_ast_nodes,
        "total_symbols": total_symbols,
        "total_call_edges": total_call_edges,
        "total_dep_edges": total_dep_edges,
        "total_communities": total_communities,
        "total_hubs": total_hubs,
        "total_orphans": total_orphans,
        "language_stats": language_stats,
        "files_processed": processed,
        "skipped_files": skipped,
        "best_call_community_id": best_call_community_id,
        "best_dep_community_id": best_dep_community_id,
        "logs": logs,
        "summary": (
            f"分析完成: {processed} 个文件, {total_ast_nodes} 个 AST 节点, "
            f"{total_call_edges} 条调用边, {total_dep_edges} 条依赖边, "
            f"{total_communities} 个社区"
            f"{f', {total_hubs} 枢纽' if total_hubs else ''}"
            f"{f', {total_orphans} 孤立' if total_orphans else ''}"
            f", 耗时 {duration_ms}ms"
        ),
    }

    # 写入分析报告
    task_store.upsert_report(report)

    # 更新最终进度
    _update_progress(server, multi_db, task_id, run_id, total, total)

    _log(f"分析完成，耗时 {duration_ms}ms")

    return report


# ==================== asyncio 调度 ====================

async def _execute_task(server, multi_db, task_id: str, run_id: str,
                        start_time: float):
    """
    asyncio 协程: 提交 _do_parse 到线程池并等待完成
    """
    _executing_tasks.add(task_id)
    loop = asyncio.get_event_loop()
    try:
        result = await loop.run_in_executor(
            parse_executor,
            _do_parse,
            server, multi_db, task_id, run_id, start_time,
        )

        # 更新最终状态
        from store.task_store import TaskStore
        task_store = TaskStore(multi_db.main_db)

        if result.get("stopped"):
            task_store.update_task_status(task_id, "cancelled",
                                          progress=result.get("progress", 0), error="")
            task_store.finish_run(run_id, "cancelled")
            if server:
                server.publish("task", "stopped", {
                    "taskId": task_id, "runId": run_id, "status": "cancelled",
                })
        else:
            task_store.update_task_status(task_id, "done", progress=100, error="")
            task_store.finish_run(run_id, "done")
            if server:
                server.publish("task", "complete", {
                    "taskId": task_id, "runId": run_id,
                    "status": "done", "progress": 100,
                })

        clear_stop_flag(task_id)
        _executing_tasks.discard(task_id)
        return result

    except Exception as e:
        logger.error(f"[EXECUTE] 任务 {task_id} 执行失败: {e}", exc_info=True)

        from store.task_store import TaskStore
        task_store = TaskStore(multi_db.main_db)

        task_store.update_task_status(task_id, "error", error=str(e))
        task_store.finish_run(run_id, "error", str(e))

        if server:
            server.publish("task", "error", {
                "taskId": task_id, "runId": run_id, "error": str(e),
            })

        clear_stop_flag(task_id)
        _executing_tasks.discard(task_id)
        raise
