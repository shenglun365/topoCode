"""
Analyst Runner — 6 步分析流程执行器

对应原 full_analyst.py 的 Celery chain，改为同步执行。
- _execute_task: asyncio 协程，提交到 ThreadPoolExecutor
- _do_parse: 6 步分析流程（线程池中阻塞执行）
- _update_progress: 进度更新 + ZMQ PUB 推送
"""
import asyncio
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

    # 更新任务进度
    multi_db.main_db.execute("""
        UPDATE analysis_tasks
        SET progress = ?, current = ?, updated_at = datetime('now')
        WHERE id = ?
    """, (progress, current, task_id))
    multi_db.main_db.commit()

    # 更新运行记录进度
    multi_db.main_db.execute("""
        UPDATE analysis_task_runs
        SET progress = ?, current = ?
        WHERE id = ?
    """, (progress, current, run_id))
    multi_db.main_db.commit()

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

    使用 transplant-parser-service/parsers/ 架构:
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
    import json
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

    # 解析配置字段
    scopes = json.loads(task["scopes"]) if task.get("scopes") else []
    extensions = json.loads(task["extensions"]) if task.get("extensions") else []
    exclude_dirs = json.loads(task["exclude_dirs"]) if task.get("exclude_dirs") else []
    report_types = json.loads(task["report_types"]) if task.get("report_types") else []

    # 获取项目根路径
    project = task_store.get_project(project_id)
    proj_path = project.get("root_path", "") if project else ""

    # 2. 清理旧数据（重运行时）
    logger.info(f"[PARSE] 清理任务 {task_id} 的旧数据")
    analysis_store.clear_task_data(task_id)

    # 3. 获取文件列表
    files = analysis_store.list_source_files(
        scopes=scopes,
        extensions=extensions,
        exclude_dirs=exclude_dirs,
    )
    total = len(files)
    logger.info(f"[PARSE] 共 {total} 个文件待分析")

    if total == 0:
        logger.warning(f"[PARSE] 没有文件需要分析")
        return {"files_processed": 0, "skipped_files": 0}

    # 4. 按语言分组
    files_by_lang = {}
    for f in files:
        lang = f.get("language")
        if lang:
            files_by_lang.setdefault(lang, []).append(f)

    language_stats = {}
    processed = 0
    skipped = 0
    logs = []

    def _log(msg: str):
        logs.append({"timestamp": datetime.utcnow().isoformat(), "message": msg})
        logger.info(f"[PARSE] {msg}")

    # ==================== Step 1: AST 解析 ====================
    _log("Step 1: AST 解析开始")
    total_ast_nodes = 0

    for lang, file_list in files_by_lang.items():
        _log(f"处理语言 {lang}: {len(file_list)} 个文件")
        lang_nodes = 0

        for f in file_list:
            if should_stop(task_id):
                _log("检测到停止标志，中断解析")
                break

            try:
                # 构建绝对路径
                abs_path = os.path.join(proj_path, f["file_path"]) if proj_path else f["file_path"]

                node_count = parse_file(
                    source_file_path=abs_path,
                    project_db=project_db,
                    task_id=task_id,
                    proj_path=proj_path,
                )
                if node_count == -1:
                    skipped += 1
                else:
                    processed += 1
                    language_stats[lang] = language_stats.get(lang, 0) + 1

                # 文件级进度检查
                if processed % PROGRESS_INTERVAL == 0:
                    _update_progress(server, multi_db, task_id, run_id, processed, total)

            except Exception as e:
                _log(f"解析失败 {f['file_path']}: {e}")

        if should_stop(task_id):
            break

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

    # ==================== Step 5: 社区分析 ====================
    _log("Step 5: 社区分析开始")
    total_communities = 0
    best_call_community_id = None
    best_dep_community_id = None

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
            best = analysis_store.get_best_community(task_id, "INCLUDE")
            if best:
                best_dep_community_id = best["comm_id"]
            _log(f"INCLUDE 社区分析完成: {comm_result.get('community_count', 0)} 个社区")
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
            best = analysis_store.get_best_community(task_id, "CALL")
            if best:
                best_call_community_id = best["comm_id"]
            _log(f"CALL 社区分析完成: {comm_result.get('community_count', 0)} 个社区")
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
        "language_stats": language_stats,
        "files_processed": processed,
        "skipped_files": skipped,
        "best_call_community_id": best_call_community_id,
        "best_dep_community_id": best_dep_community_id,
        "logs": logs,
        "summary": (
            f"分析完成: {processed} 个文件, {total_ast_nodes} 个 AST 节点, "
            f"{total_call_edges} 条调用边, {total_dep_edges} 条依赖边, "
            f"{total_communities} 个社区, 耗时 {duration_ms}ms"
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
            task_store.update_task_status(task_id, "stopped",
                                          progress=result.get("progress", 0))
            task_store.finish_run(run_id, "stopped")
            if server:
                server.publish("task", "stopped", {
                    "taskId": task_id, "runId": run_id, "status": "stopped",
                })
        else:
            task_store.update_task_status(task_id, "done", progress=100)
            task_store.finish_run(run_id, "done")
            if server:
                server.publish("task", "complete", {
                    "taskId": task_id, "runId": run_id,
                    "status": "done", "progress": 100,
                })

        clear_stop_flag(task_id)
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
        raise
