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

# ==================== Feature Flag: 新 Query 分析管线 ====================
# v2: 已全面切换到 TreeSitterWalker + ResolutionEngine，旧管线已移除
USE_NEW_PARSER = True  # 固定为 True，保留以兼容旧引用

# ==================== 线程池 ====================
parse_executor = ThreadPoolExecutor(
    max_workers=PARSE_WORKERS,
    thread_name_prefix=PARSE_THREAD_PREFIX,
)

# ==================== 停止标志 ====================
_stop_flags: Dict[str, bool] = {}
_executing_tasks: set = set()  # 正在执行的任务 ID 集合

logger = logging.getLogger(__name__)
# ==================== 任务串行队列 ====================
# 确保同一时间只有一个分析任务在执行，避免资源竞争和 SQLite 事务冲突
_task_queue: asyncio.Queue | None = None
_queue_consumer: asyncio.Task | None = None


async def _run_next_task():
    """队列消费者：一次取一个任务执行，完成后取下一个"""
    global _task_queue
    while True:
        coro = await _task_queue.get()
        try:
            await coro
        except Exception as e:
            logger.error(f"[QUEUE] 任务执行异常: {e}", exc_info=True)
        finally:
            _task_queue.task_done()


async def enqueue_analysis_task(server, multi_db, task_id: str, run_id: str, start_time: float):
    """将分析任务提交到串行队列，排队等待执行"""
    global _task_queue, _queue_consumer

    if _task_queue is None:
        _task_queue = asyncio.Queue(maxsize=100)

    if _queue_consumer is None or _queue_consumer.done():
        _queue_consumer = asyncio.create_task(_run_next_task())

    # 入队即标记为执行中，防止 stop_task 误判为孤儿任务
    _executing_tasks.add(task_id)
    coro = _execute_task(server, multi_db, task_id, run_id, start_time)
    await _task_queue.put(coro)





def set_stop_flag(task_id: str):
    """设置任务停止标志"""
    _stop_flags[task_id] = True


def clear_stop_flag(task_id: str):
    """清除任务停止标志"""
    _stop_flags.pop(task_id, None)


def should_stop(task_id: str) -> bool:
    """检查是否应该停止"""
    return _stop_flags.get(task_id, False)


def _edge_to_dict(edge):
    """Convert Edge dataclass to plain dict"""
    return {
        "source": edge.source, "target": edge.target,
        "kind": edge.kind.value if hasattr(edge.kind, 'value') else str(edge.kind),
        "line": edge.line, "col": edge.col,
        "file_path": edge.file_path,
        "provenance": edge.provenance.value if hasattr(edge.provenance, 'value') else str(edge.provenance),
        "metadata": edge.metadata,
    }


def _extract_import_dependencies(analysis_store, task_id: str, all_tables, proj_path: str = "") -> list:
    """从 graph_node 中 import 类型节点生成 imports 边 (依赖图)"""
    from parsers.core.symbol_model import Edge
    from parsers.core.node_types import EdgeKind, Provenance
    from parsers.languages import same_language_family
    import hashlib
    import re
    from pathlib import Path

    # ── Go 项目: 尝试读取 go.mod 获取模块名 ──
    go_mod_prefix = ""
    if proj_path:
        mod_file = os.path.join(proj_path, "go.mod")
        if not os.path.isfile(mod_file):
            # 支持 go.mod 在子目录中（如 server/go.mod）
            for root, dirs, files in os.walk(proj_path):
                if "go.mod" in files:
                    mod_file = os.path.join(root, "go.mod")
                    break
        try:
            with open(mod_file, "r", encoding="utf-8") as f:
                for line in f:
                    m = re.match(r'^\s*module\s+(\S+)', line)
                    if m:
                        go_mod_prefix = m.group(1)
                        break
        except (OSError, StopIteration):
            pass

    # 构建完整索引: file_path, stem, 路径后缀 → file_node_id
    file_index: dict[str, str] = {}       # file_path → node_id
    stem_index: dict[str, list[str]] = {} # stem → [node_id]
    suffix_index: dict[str, str] = {}     # path_suffix → node_id
    file_language: dict[str, str] = {}    # file_path → language_key

    for table in all_tables:
        lang = table.language or ""
        for node in table.nodes:
            if node.kind.value == "file":
                fp = node.file_path
                file_index[fp] = node.id
                file_language[fp] = lang
                # 反向索引: node.id → file_path（用于语言族校验）
                file_language[node.id] = lang
                stem = Path(fp).stem
                stem_index.setdefault(stem, []).append(node.id)

                # 去扩展名的路径后缀用于模块匹配
                fp_noext = os.path.splitext(fp)[0]
                suffix_index[fp_noext] = node.id

                # 也按路径分段建立后缀索引 (e.g. "core/walker" 匹配 "parsers/core/walker")
                parts = fp_noext.split("/")
                for i in range(len(parts)):
                    key = "/".join(parts[i:])
                    if key not in suffix_index:
                        suffix_index[key] = node.id

    # ── Java 项目检测 ──
    is_java_project = proj_path and any(fp.endswith(".java") for fp in file_index) if file_index else False

    # 读取所有 import 节点
    import_nodes = analysis_store.get_graph_nodes(task_id, "import")
    if not import_nodes:
        return []

    edges = []
    for imp in import_nodes:
        module_name = imp.get("name", "").strip()
        source_file = imp.get("file_path", "")
        source_id = imp.get("id", "")

        if not module_name or not source_file:
            continue

        # 使用导入文件自身的 file node ID 作为 source（而非 import 节点 ID）
        source_file_id = file_index.get(source_file)
        if not source_file_id:
            continue

        source_dir = Path(source_file).parent.as_posix() if source_file else ""
        target_id = None

        # 1. 直接 file_path 匹配
        if module_name in file_index:
            target_id = file_index[module_name]
        # 2. 相对路径: ./foo, ../bar
        elif module_name.startswith("./") or module_name.startswith("../"):
            candidate = os.path.normpath(os.path.join(source_dir, module_name))
            target_id = file_index.get(candidate) or suffix_index.get(candidate)
        # 3. C/C++ 风格: 尝试从源文件目录解析相对路径 (如 "header.h", "dir/header.h")
        #     Go 项目跳过: import "fmt" 非文件包含，同目录易误中 (fmt.go)
        if not target_id and not go_mod_prefix:
            candidate = os.path.normpath(os.path.join(source_dir, module_name))
            target_id = file_index.get(candidate) or suffix_index.get(candidate)
        # 3.5 Python 点式相对导入: .module, ..module, ...module
        #     路径式相对 (./ ../) 已在步骤2处理，此处仅处理纯点前缀
        if not target_id and module_name.startswith(".") \
                and not module_name.startswith("./") \
                and not module_name.startswith("../"):
            dots = 0
            for ch in module_name:
                if ch == '.':
                    dots += 1
                else:
                    break
            remainder = module_name[dots:]
            rel_path = remainder.replace(".", "/") if remainder else ""
            up_levels = dots - 1
            parts = Path(source_dir).parts
            if up_levels < len(parts):
                if up_levels > 0:
                    base = str(Path(*parts[:len(parts) - up_levels]))
                else:
                    base = source_dir
                if rel_path:
                    base = os.path.join(base, rel_path)
                # 依次尝试: 后缀匹配(无扩展名) / .py 文件 / __init__.py 包
                target_id = suffix_index.get(base)
                if not target_id:
                    target_id = file_index.get(base + ".py")
                if not target_id:
                    init_path = os.path.join(base, "__init__.py")
                    target_id = file_index.get(init_path)
                    if not target_id:
                        target_id = suffix_index.get(os.path.splitext(init_path)[0])
        # 4. 绝对模块路径: parsers.core.walker → 路径后缀匹配
        #     Go 项目跳过(steps 4-6): 后缀匹配易误中 stdlib 名 (fmt→.../fmt.go, net/url→.../url.go)
        if not target_id and not go_mod_prefix:
            mod_path = module_name.replace(".", "/")
            target_id = suffix_index.get(mod_path)
        # 5. 路径后缀匹配 (如 "dir/header.h" 匹配 ".../dir/header.h" 或 ".../dir/header")
        if not target_id and not go_mod_prefix:
            target_id = suffix_index.get(module_name)
            if not target_id:
                mod_noext = os.path.splitext(module_name)[0]
                target_id = suffix_index.get(mod_noext)
        # 6. Go 模块导入解析 (go.mod): github.com/my/proj/v2/pkg/foo → pkg/foo/foo.go
        #     放在 stem 之前，因为 Go 模块前缀是确定性信号，stem 匹配可能误中其他文件
        if not target_id and go_mod_prefix and module_name.startswith(go_mod_prefix):
            inner = module_name[len(go_mod_prefix):].lstrip("/")
            if inner:
                pkg_name = inner.split("/")[-1]
                candidates = [
                    # 单文件包: pkg/foo.go
                    os.path.join(proj_path, inner + ".go"),
                    # 目录包: pkg/foo/foo.go
                    os.path.join(proj_path, inner, pkg_name + ".go"),
                    # 测试文件: pkg/foo/foo_test.go
                    os.path.join(proj_path, inner, pkg_name + "_test.go"),
                ]
                for cand in candidates:
                    target_id = file_index.get(cand)
                    if target_id:
                        break
                    target_id = suffix_index.get(os.path.splitext(cand)[0])
                    if target_id:
                        break
                # 回退: 目录下任意非 test .go 文件
                if not target_id:
                    dir_prefix = os.path.join(proj_path, inner) + "/"
                    for fp, fid in file_index.items():
                        if fp.startswith(dir_prefix) and fp.endswith(".go") and not fp.endswith("_test.go"):
                            target_id = fid
                            break
                # 再次回退: 目录下任意 .go 文件 (含 test)
                if not target_id:
                    for fp, fid in file_index.items():
                        if fp.startswith(dir_prefix) and fp.endswith(".go"):
                            target_id = fid
                            break
        # 6.5 Java 内部类回退: Banner.Mode → 剥离到 Banner 级匹配
        #      仅当项目含 .java 文件时启用，不依赖模块前缀（非 module-path 语言）
        if not target_id and is_java_project:
            inner_parts = module_name.split(".")
            while len(inner_parts) > 1:
                inner_parts.pop()
                inner_path = "/".join(inner_parts)
                candidate = os.path.join(proj_path, inner_path + ".java")
                target_id = file_index.get(candidate)
                if not target_id:
                    target_id = suffix_index.get(inner_path)
                if target_id:
                    break
        # 7. stem 匹配 (fallback: os → os.py, header.h → header)
        #     Go 项目跳过 stem: stdlib 名 (fmt, net/url) 与外部模块名容易误中内部文件
        if not target_id and not go_mod_prefix:
            basename = module_name.split("/")[-1]
            stem = basename.rsplit(".", 1)[0] if "." in basename else basename
            ids = stem_index.get(stem, [])
            if len(ids) == 1:
                target_id = ids[0]

        if target_id:
            # 语言族校验: 跨族导入/依赖无意义 (e.g. Python → Java)
            src_lang = file_language.get(source_file_id, "")
            tgt_lang = file_language.get(target_id, "")
            if src_lang and tgt_lang and not same_language_family(src_lang, tgt_lang):
                continue

            edge_id = hashlib.sha256(f"{source_file_id}->{target_id}:imports".encode()).hexdigest()[:16]
            edges.append(Edge(
                source=source_file_id, target=target_id,
                kind=EdgeKind.IMPORTS,
                provenance=Provenance.RESOLUTION,
                file_path=source_file,
                metadata={"module": module_name},
            ))

    return edges


def _find_target_for_import(module_name: str, source_file: str, file_index: dict, all_tables) -> str | None:
    """根据 import 模块名在项目中查找目标文件 node"""
    import os
    from pathlib import Path

    source_dir = Path(source_file).parent.as_posix() if source_file else ""

    # 直接匹配 file_path
    if module_name in file_index:
        return file_index[module_name]

    # 相对路径导入: ./foo, ../bar
    if module_name.startswith("./") or module_name.startswith("../"):
        candidate = os.path.normpath(os.path.join(source_dir, module_name))
        for table in all_tables:
            for node in table.nodes:
                if node.kind.value == "file":
                    fp = node.file_path
                    # 精确匹配规范路径
                    if fp == candidate:
                        return node.id
                    # 补齐扩展名匹配
                    fp_noext = os.path.splitext(fp)[0]
                    if fp_noext == candidate:
                        return node.id
        return None

    # 绝对模块路径: parsers.core.walker → parsers/core/walker
    for ext in (".py", ".ts", ".tsx", ".js", ".jsx", ".c", ".h", ".cpp", ".hpp", ".cc", ".cxx", ".hh", ".hxx"):
        candidate = module_name.replace(".", "/") + ext
        for table in all_tables:
            for node in table.nodes:
                if node.kind.value == "file" and node.file_path == candidate:
                    return node.id
        # 也尝试匹配路径后缀
        for table in all_tables:
            for node in table.nodes:
                if node.kind.value == "file" and node.file_path.endswith(candidate):
                    return node.id

    # 按文件名匹配 (fallback: import os → os.py, import react → react)
    module_basename = module_name.split("/")[-1].split(".")[-1]
    for table in all_tables:
        for node in table.nodes:
            if node.kind.value == "file" and Path(node.file_path).stem == module_basename:
                return node.id

    return None


def is_task_executing(task_id: str) -> bool:
    """检查任务是否正在线程池中执行"""
    return task_id in _executing_tasks


# ==================== 进度回调 ====================

def _update_progress(server, multi_db, task_id: str, run_id: str,
                     current: int = 0, total: int = 100, progress: int = None):
    """
    更新进度: SQLite + ZMQ PUB 推送

    Args:
        server: ZMQServer 实例（有 publish 方法）
        multi_db: MultiDBManager 实例（复用连接）
        task_id: 任务 ID
        run_id: 运行 ID
        current: 当前处理到第几个文件（文件解析阶段）
        total: 总文件数
        progress: 覆盖进度值（0-100），为 None 时从 current/total 计算
    """
    if progress is None:
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
    from parsers.core.walker import TreeSitterWalker, _detect_language
    from parsers.core.emitter import GraphEmitter
    from parsers.core.resolver import ResolutionEngine
    from parsers.core.symbol_model import FileSymbolTable
    from parsers.languages import EXTRACTORS
    from parsers.language_loader import get_parser

    # 社区分析插件（可选）
    try:
        from community_analysis import analyze_communities
        _community_available = True
    except ImportError:
        analyze_communities = None
        _community_available = False
        logger.warning("community_analysis plugin not available, community analysis will be skipped")

    task_store = TaskStore(multi_db.main_db)

    # 1. 加载任务配置
    task = task_store.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    project_id = task["project_id"]
    project_db = multi_db.get_project_db(project_id)
    analysis_store = AnalysisStore(project_db)
    emitter = GraphEmitter(analysis_store, task_id)

    # 调试日志：确认两个 store 是否共享连接
    logger.info(f"[PARSE] [DEBUG] task_id={task_id}, project_id={project_id}")
    logger.info(f"[PARSE] [DEBUG] analysis_store._db id={id(analysis_store._db)}")

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

    # 3. 清理旧数据
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

    # ── 进度分配 ──
    # Step 1 (AST parse):  5-65 (按文件比例缩放)
    # Step 2 (reference):  65-72
    # Step 2.5 (import):   72-74
    # Step 3 (framework):  74-77
    # Step 4 (INCLUDE):    77-82 (若有) / 77-99 (无 CALL)
    # Step 4 (CALL):       82-99 (若有)
    # Step 5 (summary):    99-100

    def _log(msg: str):
        logs.append({"timestamp": datetime.utcnow().isoformat(), "message": msg})
        logger.info(f"[PARSE] {msg}")

    _update_progress(server, multi_db, task_id, run_id, progress=5)

    # ==================== Step 1: AST 解析 + 符号提取 (并行) ====================
    _log(f"Step 1: AST 解析开始 (并行, {PARSE_WORKERS} 个工作线程, 支持 {len(EXTRACTORS)} 种语言)")

    all_tables: list[FileSymbolTable] = []

    def _parse_one(lang, f, abs_path):
        """同步解析单个文件（在线程池中执行）"""
        if should_stop(task_id):
            return ("stopped", None)
        try:
            lang_key = f.get("language", "")
            if lang_key == "c_header":
                lang_key = "c"
            extractor = EXTRACTORS.get(lang_key)
            if extractor is None:
                return ("no_extractor", None)

            parser = get_parser(lang_key)
            if parser is None:
                return ("no_parser", None)

            if not os.path.exists(abs_path):
                return ("file_missing", None)

            src_bytes = open(abs_path, "rb").read()
            if len(src_bytes) > 500 * 1024:
                return ("too_large", None)

            walker = TreeSitterWalker(abs_path, src_bytes, lang_key, extractor)
            table = walker.extract()

            rel_path = os.path.relpath(abs_path, proj_path)
            table.file_path = rel_path
            emitter.write_nodes(table)

            return ("ok", table)
        except Exception as e:
            logger.exception(f"Parse error {abs_path}: {e}")
            return ("error", None)

    all_tasks = []
    for lang, file_list in files_by_lang.items():
        for f in file_list:
            abs_path = os.path.join(proj_path, f["file_path"]) if proj_path else f["file_path"]
            all_tasks.append((lang, f, abs_path))

    _log(f"共 {len(all_tasks)} 个文件待解析")

    from concurrent.futures import ThreadPoolExecutor, as_completed

    with ThreadPoolExecutor(max_workers=PARSE_WORKERS) as file_executor:
        batch_size = PARSE_WORKERS * 2
        for batch_start in range(0, len(all_tasks), batch_size):
            if should_stop(task_id):
                _log("检测到停止标志，中断解析")
                break

            batch = all_tasks[batch_start:batch_start + batch_size]
            futures = {
                file_executor.submit(_parse_one, lang, f, abs_path): (lang, f)
                for lang, f, abs_path in batch
            }

            for future in as_completed(futures):
                if should_stop(task_id):
                    break
                try:
                    status, table = future.result()
                except Exception as e:
                    _log(f"解析任务异常: {e}")
                    continue

                if status == "ok" and table:
                    processed += 1
                    all_tables.append(table)
                elif status in ("no_extractor", "no_parser", "too_large", "file_missing"):
                    skipped += 1
                elif status == "stopped":
                    pass

                if processed % PROGRESS_INTERVAL == 0:
                    scaled = 5 + int(processed * 60 / total) if total > 0 else 5
                    _update_progress(server, multi_db, task_id, run_id, progress=scaled)

    if should_stop(task_id):
        _log("AST 解析被用户停止")
        return {"files_processed": processed, "skipped_files": skipped, "stopped": True}

    _log(f"AST 解析完成 - 处理 {processed} 个文件，跳过 {skipped} 个")

    _update_progress(server, multi_db, task_id, run_id, progress=65)

    # 统计节点总数
    total_ast_nodes = analysis_store.count_graph_nodes(task_id)
    _log(f"节点总数: {total_ast_nodes}")

    # ==================== Step 2: 跨文件引用解析 ====================
    _log("Step 2: 跨文件引用解析开始")
    total_call_edges = 0
    total_dep_edges = 0
    total_extends_edges = 0
    total_implements_edges = 0
    total_type_of_edges = 0

    try:
        resolver = ResolutionEngine()
        resolved_edges = resolver.resolve(all_tables)
        emitter.write_edges(resolved_edges)

        # 按类型统计
        for e in resolved_edges:
            if e.kind.value == "calls":
                total_call_edges += 1
            elif e.kind.value == "imports":
                total_dep_edges += 1
            elif e.kind.value == "extends":
                total_extends_edges += 1
            elif e.kind.value == "implements":
                total_implements_edges += 1
            elif e.kind.value in ("type_of", "returns"):
                total_type_of_edges += 1

        _log(f"引用解析完成: calls={total_call_edges}, imports={total_dep_edges}, "
             f"extends={total_extends_edges}, implements={total_implements_edges}, "
             f"type_refs={total_type_of_edges}")
    except Exception as e:
        _log(f"引用解析失败: {e}")

    _update_progress(server, multi_db, task_id, run_id, progress=72)

    # 调试日志
    dep_check = analysis_store.get_dep_edges(task_id)
    call_check = analysis_store.get_call_edges(task_id)
    _log(f"[DEBUG] 数据库验证: dep_edges={len(dep_check)}, call_edges={len(call_check)}")

    # Step 2.5: 从 import 节点生成依赖边 (imports edges)
    _log("Step 2.5: 文件依赖提取开始")
    try:
        import_dep_edges = _extract_import_dependencies(analysis_store, task_id, all_tables, proj_path)
        if import_dep_edges:
            emitter.write_edges(import_dep_edges)
            total_dep_edges = len(import_dep_edges)
            _log(f"文件依赖提取完成: {total_dep_edges} 条依赖边")
    except Exception as e:
        _log(f"文件依赖提取失败: {e}")

    _update_progress(server, multi_db, task_id, run_id, progress=74)

    # ==================== Step 3: 框架感知 + 动态合成 ====================
    _log("Step 3: 框架感知 + 动态合成开始")
    total_framework_edges = 0
    total_synthetic_edges = 0
    framework_edges_list = []
    try:
        from parsers.frameworks import run_all as run_frameworks
        framework_edges = run_frameworks(all_tables)
        if framework_edges:
            emitter.write_edges(framework_edges)
            total_framework_edges = len(framework_edges)
            framework_edges_list = framework_edges
            _log(f"框架感知完成: {total_framework_edges} 条框架边")
    except Exception as e:
        _log(f"框架感知失败: {e}")

    try:
        from parsers.core.synthesis import DynamicSynthesizer
        synthesizer = DynamicSynthesizer()
        all_nodes = [n for t in all_tables for n in t.nodes]
        # Convert Edge objects to dicts for synthesizer
        all_edges_for_synth = [_edge_to_dict(e) for e in resolved_edges]
        all_edges_for_synth += [_edge_to_dict(e) for e in framework_edges_list]
        synthetic_edges = synthesizer.synthesize(all_nodes, all_edges_for_synth, all_tables)
        if synthetic_edges:
            emitter.write_edges(synthetic_edges)
            total_synthetic_edges = len(synthetic_edges)
            _log(f"动态合成完成: {total_synthetic_edges} 条合成边")
    except Exception as e:
        _log(f"动态合成失败: {e}")

    _update_progress(server, multi_db, task_id, run_id, progress=77)

    # ==================== Step 4: 社区分析 ====================
    _log("Step 4: 社区分析开始")
    total_communities = 0
    total_hubs = 0
    total_orphans = 0
    best_call_community_id = None
    best_dep_community_id = None

    # 调试日志：确认 task_id 和 analysis_store
    _log(f"[DEBUG] 社区分析参数: task_id={task_id}, analysis_store id={id(analysis_store)}, report_types={report_types}")

    # 根据 report_types 配置选择分析类型
    if "dependency" in report_types or "full" in report_types:
        if analyze_communities is not None:
            try:
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
        else:
            _log("社区分析插件未安装，跳过 INCLUDE")

    _update_progress(server, multi_db, task_id, run_id,
                     progress=82 if ("callChain" in report_types or "full" in report_types) else 99)

    if "callChain" in report_types or "full" in report_types:
        if analyze_communities is not None:
            try:
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
        else:
            _log("社区分析插件未安装，跳过 CALL")

    _update_progress(server, multi_db, task_id, run_id, progress=99)

    # ==================== Step 5: 结果汇总 ====================
    _log("Step 5: 结果汇总")
    duration_ms = int((time.time() - start_time) * 1000)

    # 统计总数
    total_ast_nodes = analysis_store.count_graph_nodes(task_id)
    total_symbols = total_ast_nodes  # v2: 节点即符号

    report = {
        "id": str(uuid.uuid4()),
        "task_id": task_id,
        "run_id": run_id,
        "total_ast_nodes": total_ast_nodes,
        "total_symbols": total_symbols,
        "total_call_edges": total_call_edges,
        "total_dep_edges": total_dep_edges,
        "total_extends_edges": total_extends_edges,
        "total_implements_edges": total_implements_edges,
        "total_type_of_edges": total_type_of_edges,
        "total_framework_edges": total_framework_edges,
        "total_synthetic_edges": total_synthetic_edges,
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
            f"分析完成: {processed} 个文件, {total_ast_nodes} 个符号节点, "
            f"{total_call_edges} 调用, {total_dep_edges} 依赖, "
            f"{total_extends_edges} 继承, {total_implements_edges} 实现, "
            f"{total_communities} 个社区"
            f"{f', {total_hubs} 枢纽' if total_hubs else ''}"
            f"{f', {total_orphans} 孤立' if total_orphans else ''}"
            f", 耗时 {duration_ms}ms"
        ),
    }

    # 写入分析报告
    task_store.upsert_report(report)

    # 更新最终进度
    _update_progress(server, multi_db, task_id, run_id, progress=100)

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
            _save_analysis_snapshot(multi_db, task_id, task_store, result)
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


def _save_analysis_snapshot(multi_db, task_id: str, task_store, result: dict):
    """Save a ProjectSnapshot after successful analysis completion."""
    import os
    import hashlib
    from datetime import datetime

    try:
        task = task_store.get_task(task_id)
        if not task:
            logger.warning(f"[SNAPSHOT] Task {task_id} not found, skipping snapshot")
            return

        project_id = task.get("project_id", "")
        project_db = multi_db.get_project_db(project_id)
        if not project_db:
            logger.warning(f"[SNAPSHOT] Project DB not found for {project_id}")
            return

        proj_path = task.get("proj_path", "")
        if not proj_path:
            row = multi_db.main_db.fetchone(
                "SELECT root_path FROM projects WHERE id = ?", (project_id,)
            )
            proj_path = row["root_path"] if row else ""

        from change_tracker.git_adapter import GitAdapter
        git = GitAdapter(proj_path)
        commit_hash = git.get_current_commit() or "unknown"

        from change_tracker.change_model import ProjectSnapshot
        from change_tracker.snapshot_store import SnapshotStore

        snapshot_dir = os.path.join(multi_db.data_dir, "snapshots")
        store = SnapshotStore(os.path.join(snapshot_dir, "snapshots.db"))

        # Collect file hashes from source files
        file_hashes = {}
        files_processed = result.get("files_processed", 0)
        if files_processed > 0 and proj_path:
            from store.analysis_store import AnalysisStore
            analysis_store = AnalysisStore(project_db)
            source_files = analysis_store.list_source_files()
            for sf in source_files:
                fp = sf.get("file_path", "")
                abs_path = os.path.join(proj_path, fp) if proj_path else fp
                if os.path.isfile(abs_path):
                    h = hashlib.md5()
                    try:
                        with open(abs_path, "rb") as fh:
                            for chunk in iter(lambda: fh.read(65536), b""):
                                h.update(chunk)
                        file_hashes[fp] = h.hexdigest()
                    except OSError:
                        continue

        # Collect symbols from the analysis
        symbols_dict = {}
        try:
            rows = project_db.execute(
                "SELECT kind, name, start_line, file_path FROM graph_node WHERE task_id = ?", (task_id,)
            ).fetchall()
            for row in rows:
                fp = row["file_path"]
                if fp not in symbols_dict:
                    symbols_dict[fp] = []
                symbols_dict[fp].append({
                    "name": row["name"] or "",
                    "kind": row["kind"] or "",
                    "line": row["start_line"] or 0,
                })
        except Exception:
            logger.warning("[SNAPSHOT] Failed to collect symbols", exc_info=True)

        snapshot = ProjectSnapshot(
            commit_hash=commit_hash,
            timestamp=datetime.now(),
            file_hashes=file_hashes,
            symbols=symbols_dict,
            is_analyzed=True,
        )

        store.save_snapshot(proj_path or project_id, snapshot)
        logger.info(f"[SNAPSHOT] Saved snapshot for {commit_hash} ({files_processed} files)")
    except Exception as e:
        logger.warning(f"[SNAPSHOT] Failed to save snapshot: {e}")
