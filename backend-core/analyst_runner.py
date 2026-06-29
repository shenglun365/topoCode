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
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Any, Optional, List

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
_executing_tasks: set = set()  # 正在执行的任务 ID 集合（内存，启动时从 CacheStore 恢复）

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
    try:
        multi_db.cache_store.add_executing_task(task_id)
    except Exception:
        pass
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


def _extract_import_dependencies(analysis_store, task_id: str, all_tables, proj_path: str = "",
                                 progress_callback=None, stop_check=None) -> list:
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
    # 注意: all_tables 中 node.file_path 为绝对路径, DB 中为相对路径,
    #       统一用相对路径索引以匹配 DB 查回的 source_file
    file_index: dict[str, str] = {}       # file_path → node_id
    stem_index: dict[str, list[str]] = {} # stem → [node_id]
    suffix_index: dict[str, str] = {}     # path_suffix → node_id
    file_language: dict[str, str] = {}    # file_path → language_key

    def _rel(fp: str) -> str:
        return os.path.relpath(fp, proj_path) if proj_path and os.path.isabs(fp) else fp

    for table in all_tables:
        lang = table.language or ""
        for node in table.nodes:
            if node.kind.value == "file":
                fp = _rel(node.file_path)
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
    import time as _tim
    _t0 = _tim.perf_counter()
    _total_imports = len(import_nodes)
    logger.info("[_extract_import_dependencies] processing %d import nodes", _total_imports)
    for idx, imp in enumerate(import_nodes):
        if stop_check and stop_check():
            logger.info("[_extract_import_dependencies] stopped at import %d/%d", idx, _total_imports)
            break
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
        # ── Rust 模块路径解析 ──
        # Rust use 语句格式: crate::module::Type, super::sibling, self::local
        # 模块名使用 :: 分隔，需转换为文件路径: module::sub::Type → src/module/sub.rs
        if not target_id and source_file.endswith('.rs'):
            crate_root = None
            src_dir = source_dir if source_dir else str(Path(source_file).parent)
            cur = Path(src_dir)
            for _ in range(8):
                if (cur / 'Cargo.toml').is_file():
                    crate_root = str(cur)
                    break
                cur = cur.parent
            if not crate_root and proj_path and (Path(proj_path) / 'Cargo.toml').is_file():
                crate_root = proj_path
            if not crate_root:
                parts = Path(source_file).parts
                for i, p in enumerate(parts):
                    if p == 'src' and i > 0:
                        crate_root = str(Path(*parts[:i]))
                        break

            if crate_root:
                mod_raw = module_name
                if mod_raw.startswith('::'):
                    pass  # external crate, skip
                else:
                    base_dirs: list[str] = []
                    is_super = mod_raw.startswith('super::')
                    if mod_raw.startswith('crate::'):
                        mod_raw = mod_raw[7:]
                        base_dirs.append(os.path.join(crate_root, 'src'))
                    elif mod_raw.startswith('self::'):
                        mod_raw = mod_raw[6:]
                        base_dirs.append(src_dir)
                    elif mod_raw.startswith('super::'):
                        up = 0
                        while mod_raw.startswith('super::'):
                            up += 1
                            mod_raw = mod_raw[7:]
                        base = src_dir
                        for _ in range(up):
                            base = str(Path(base).parent)
                        base_dirs.append(base)
                    else:
                        base_dirs.append(src_dir)
                        base_dirs.append(os.path.join(crate_root, 'src'))

                    path_part = mod_raw.replace('::', '/').rstrip('/')
                    segments = path_part.split('/')
                    for base in base_dirs:
                        if target_id:
                            break
                        for i in range(len(segments), 0, -1):
                            partial = '/'.join(segments[:i])
                            candidates = [
                                os.path.join(base, partial + '.rs'),
                                os.path.join(base, partial, 'mod.rs'),
                            ]
                            for cand in candidates:
                                cand_norm = os.path.normpath(cand)
                                target_id = file_index.get(cand_norm)
                                if target_id:
                                    break
                                target_id = suffix_index.get(os.path.splitext(cand_norm)[0])
                                if target_id:
                                    break
                            if target_id:
                                break

                    # super:: 回退: 单段路径为父模块中的 item (如 super::Type)，尝试父模块文件
                    if not target_id and is_super and len(segments) <= 2:
                        for base in base_dirs:
                            if target_id:
                                break
                            # 父模块文件: 在 base / .. 的同名 .rs 或 base / mod.rs
                            parent_candidates = [
                                os.path.normpath(str(Path(base)) + '.rs'),
                                os.path.normpath(os.path.join(base, 'mod.rs')),
                            ]
                            # 另外: 如果当前在 src/ 下，父模块可能是 lib.rs / main.rs
                            src_dir_abs = os.path.join(crate_root, 'src')
                            if os.path.normpath(base) == os.path.normpath(src_dir_abs):
                                parent_candidates.extend([
                                    os.path.join(src_dir_abs, 'lib.rs'),
                                    os.path.join(src_dir_abs, 'main.rs'),
                                ])
                            for pc in parent_candidates:
                                target_id = file_index.get(pc)
                                if target_id:
                                    break
                                target_id = suffix_index.get(os.path.splitext(pc)[0])
                                if target_id:
                                    break

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
                # 候选使用相对路径匹配 file_index (DB 和索引都用相对路径)
                candidates = [
                    # 单文件包: pkg/foo.go
                    inner + ".go",
                    # 目录包: pkg/foo/foo.go
                    os.path.join(inner, pkg_name + ".go"),
                    # 测试文件: pkg/foo/foo_test.go
                    os.path.join(inner, pkg_name + "_test.go"),
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
                    dir_prefix = inner + "/"
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

        if (idx + 1) % 2000 == 0:
            _elapsed = _tim.perf_counter() - _t0
            logger.info("[_extract_import_dependencies] %d/%d import nodes (%.1fs, edges=%d)",
                        idx + 1, _total_imports, _elapsed, len(edges))
            if progress_callback:
                progress_callback(idx + 1, _total_imports)

    if progress_callback:
        progress_callback(_total_imports, _total_imports)
    logger.info("[_extract_import_dependencies] done %d imports in %.1fs → %d edges",
                _total_imports, _tim.perf_counter() - _t0, len(edges))
    return edges


def is_task_executing(task_id: str) -> bool:
    """检查任务是否正在线程池中执行"""
    return task_id in _executing_tasks


# ==================== 进度回调 ====================

def _update_progress(server, multi_db, task_id: str, run_id: str,
                     current: int = 0, total: int = 100, progress: float = None,
                     eta: str = ""):
    """
    更新进度: SQLite + ZMQ PUB 推送

    Args:
        server: ZMQServer 实例（有 publish 方法）
        multi_db: MultiDBManager 实例（复用连接）
        task_id: 任务 ID
        run_id: 运行 ID
        current: 当前处理到第几个文件（文件解析阶段）
        total: 总文件数
        progress: 覆盖进度值（0.00-100.00），为 None 时从 current/total 计算
        eta: 预估剩余时间文本
    """
    if progress is None:
        progress = (current * 100.0 / total) if total > 0 else 0.0

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
            "eta": eta,
        })


# ==================== 分析管线上下文 ====================

@dataclass
class PipelineContext:
    """跨步骤共享的分析管线状态"""
    server: Any
    multi_db: Any
    task_id: str
    run_id: str
    start_time: float
    # 步骤 0: 任务上下文（_load_task_context 填充）
    task: dict = field(default_factory=dict)
    project_id: str = ""
    project_db: Any = None
    analysis_store: Any = None
    emitter: Any = None
    proj_path: str = ""
    report_types: list = field(default_factory=list)
    # 步骤 1 产物
    all_tables: list = field(default_factory=list)
    processed: int = 0
    skipped: int = 0
    language_stats: dict = field(default_factory=dict)
    # 步骤 2 产物
    resolved_edges: list = field(default_factory=list)
    total_call_edges: int = 0
    total_dep_edges: int = 0
    total_extends_edges: int = 0
    total_implements_edges: int = 0
    total_type_of_edges: int = 0
    # 步骤 4 产物
    framework_edges_list: list = field(default_factory=list)
    total_framework_edges: int = 0
    total_synthetic_edges: int = 0
    # 步骤 5 产物
    total_communities: int = 0
    total_hubs: int = 0
    total_orphans: int = 0
    best_call_community_id: Optional[str] = None
    best_dep_community_id: Optional[str] = None
    # 日志
    logs: list = field(default_factory=list)
    # 停止标志
    stopped: bool = False
    # ETA 追踪
    _last_progress_time: float = 0.0
    _last_progress_value: float = 0.0

    def _format_eta(self, remaining_sec: float) -> str:
        if remaining_sec <= 0 or remaining_sec > 86400:
            return ""
        if remaining_sec < 60:
            return f"{int(remaining_sec)}s"
        if remaining_sec < 3600:
            return f"{int(remaining_sec // 60)}m{int(remaining_sec % 60)}s"
        return f"{int(remaining_sec // 3600)}h{int((remaining_sec % 3600) // 60)}m"

    def log(self, msg: str):
        self.logs.append({"timestamp": datetime.utcnow().isoformat(), "message": msg})
        logger.info(f"[PARSE] {msg}")

    def report_progress(self, progress: float):
        now = time.time()
        eta = ""
        if self._last_progress_time > 0 and progress > self._last_progress_value:
            dt = now - self._last_progress_time
            dp = progress - self._last_progress_value
            speed = dp / dt if dt > 0 else 0
            if speed > 0.001:
                remaining = (100.0 - progress) / speed
                eta = self._format_eta(remaining)
        self._last_progress_time = now
        self._last_progress_value = progress
        _update_progress(self.server, self.multi_db, self.task_id, self.run_id,
                         progress=progress, eta=eta)


def _load_task_context(server, multi_db, task_id) -> PipelineContext:
    """加载任务配置、创建 stores/emitter、获取文件列表"""
    from store.task_store import TaskStore
    from store.analysis_store import AnalysisStore
    from parsers.core.emitter import GraphEmitter

    task_store = TaskStore(multi_db.main_db)
    task = task_store.get_task(task_id)
    if not task:
        raise ValueError(f"Task {task_id} not found")

    pid = task["project_id"]
    pdb = multi_db.get_project_db(pid)
    a_store = AnalysisStore(pdb)

    row = multi_db.main_db.fetchone("SELECT root_path FROM projects WHERE id = ?", (pid,))
    proj_path = row["root_path"] if row else ""

    ctx = PipelineContext(
        server=server, multi_db=multi_db, task_id=task_id,
        run_id="", start_time=time.time(),
        task=task, project_id=pid, project_db=pdb,
        analysis_store=a_store,
        emitter=GraphEmitter(a_store, task_id, project_root=proj_path),
        proj_path=proj_path,
        report_types=task.get("report_types") or [],
    )

    return ctx


def _step1_parse_ast(ctx: PipelineContext) -> PipelineContext:
    """Step 1: AST 解析 + 符号提取 (并行) — 进度 5→65"""
    from parsers.core.walker import TreeSitterWalker, _detect_language
    from parsers.core.symbol_model import FileSymbolTable
    from parsers.languages import EXTRACTORS
    from parsers.language_loader import get_parser
    from concurrent.futures import ThreadPoolExecutor, as_completed

    a_store = ctx.analysis_store
    task = ctx.task
    task_id = ctx.task_id

    scopes = task.get("scopes") or []
    extensions = task.get("extensions") or []
    exclude_dirs = task.get("exclude_dirs") or []
    pattern_type = task.get("pattern_type")
    pattern = task.get("pattern")

    files = a_store.list_source_files(
        scopes=scopes, extensions=extensions, exclude_dirs=exclude_dirs,
        pattern_type=pattern_type, pattern=pattern,
    )
    total = len(files)
    ctx.log(f"共 {total} 个文件待分析")

    if total == 0:
        ctx.log("没有文件需要分析")
        return ctx

    ctx.log(f"清理任务 {task_id} 的旧数据")
    a_store.clear_task_data(task_id)

    files_by_lang = {}
    for f in files:
        lang = f.get("language")
        if lang:
            files_by_lang.setdefault(lang, []).append(f)

    ctx.language_stats = {lang: len(fl) for lang, fl in files_by_lang.items()}
    ctx.log(f"语言分布: {ctx.language_stats}")

    def _parse_one(lang, f, abs_path):
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
            rel_path = os.path.relpath(abs_path, ctx.proj_path)
            table.file_path = rel_path
            return ("ok", table)
        except Exception as e:
            logger.exception(f"Parse error {abs_path}: {e}")
            return ("error", None)

    all_tasks = []
    for lang, file_list in files_by_lang.items():
        for f in file_list:
            abs_path = os.path.join(ctx.proj_path, f["file_path"]) if ctx.proj_path else f["file_path"]
            all_tasks.append((lang, f, abs_path))

    ctx.log(f"共 {len(all_tasks)} 个文件待解析")

    ctx.report_progress(5)
    ctx.log("Step 1: AST 解析开始")

    with ThreadPoolExecutor(max_workers=PARSE_WORKERS) as file_executor:
        batch_size = PARSE_WORKERS * 2
        for batch_start in range(0, len(all_tasks), batch_size):
            if should_stop(task_id):
                ctx.log("检测到停止标志，中断解析")
                ctx.stopped = True
                return ctx

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
                    ctx.log(f"解析任务异常: {e}")
                    continue

                if status == "ok" and table:
                    ctx.processed += 1
                    ctx.all_tables.append(table)
                elif status in ("no_extractor", "no_parser", "too_large", "file_missing"):
                    ctx.skipped += 1

                if ctx.processed % PROGRESS_INTERVAL == 0:
                    scaled = 5.0 + (ctx.processed * 60.0 / total) if total > 0 else 5.0
                    ctx.report_progress(round(scaled, 2))

    if should_stop(task_id):
        ctx.log("AST 解析被用户停止")
        ctx.stopped = True
        return ctx

    # 批量写入所有节点的 graph_node（移出线程池，减少 SQLite 锁竞争）
    if ctx.all_tables:
        ctx.log(f"批量写入 {len(ctx.all_tables)} 个文件的解析结果到 graph_node ...")
        for table in ctx.all_tables:
            ctx.emitter.write_nodes(table)

    ctx.log(f"AST 解析完成 - 处理 {ctx.processed} 个文件，跳过 {ctx.skipped} 个")
    ctx.report_progress(65)
    return ctx


def _step2_resolve_references(ctx: PipelineContext) -> PipelineContext:
    """Step 2: 跨文件引用解析 — 进度 65→72"""
    from parsers.core.resolver import ResolutionEngine
    import time as _time

    ctx.log("Step 2: 跨文件引用解析开始")
    _t0 = _time.perf_counter()

    _total_refs = sum(len(t.unresolved_refs) for t in ctx.all_tables)

    def _on_ref_progress(current, total):
        if total > 0:
            pct = 65.0 + (current / total) * 7.0
            ctx.report_progress(round(pct, 2))

    try:
        resolver = ResolutionEngine()
        _edge_counts = {"calls": 0, "imports": 0, "extends": 0, "implements": 0, "type_refs": 0}

        def _on_edge_batch(batch):
            nonlocal _edge_counts
            ctx.emitter.write_edges(batch)
            for e in batch:
                kv = e.kind.value
                if kv == "calls":
                    _edge_counts["calls"] += 1
                elif kv == "imports":
                    _edge_counts["imports"] += 1
                elif kv == "extends":
                    _edge_counts["extends"] += 1
                elif kv == "implements":
                    _edge_counts["implements"] += 1
                elif kv in ("type_of", "returns"):
                    _edge_counts["type_refs"] += 1

        ctx.resolved_edges = resolver.resolve(ctx.all_tables,
                                              progress_callback=_on_ref_progress,
                                              stop_check=lambda: should_stop(ctx.task_id),
                                              edge_callback=_on_edge_batch)
        _t1 = _time.perf_counter()
        ctx.log(f"跨文件引用解析耗时: {_t1 - _t0:.1f}s")

        # Write remaining edges from the returned list (only non-empty when resolve finishes without callback)
        if ctx.resolved_edges:
            ctx.emitter.write_edges(ctx.resolved_edges)
            for e in ctx.resolved_edges:
                kv = e.kind.value
                if kv == "calls":
                    _edge_counts["calls"] += 1
                elif kv == "imports":
                    _edge_counts["imports"] += 1
                elif kv == "extends":
                    _edge_counts["extends"] += 1
                elif kv == "implements":
                    _edge_counts["implements"] += 1
                elif kv in ("type_of", "returns"):
                    _edge_counts["type_refs"] += 1

        ctx.total_call_edges = _edge_counts["calls"]
        ctx.total_dep_edges = _edge_counts["imports"]
        ctx.total_extends_edges = _edge_counts["extends"]
        ctx.total_implements_edges = _edge_counts["implements"]
        ctx.total_type_of_edges = _edge_counts["type_refs"]

        ctx.log(f"引用解析完成: calls={ctx.total_call_edges}, imports={ctx.total_dep_edges}, "
                f"extends={ctx.total_extends_edges}, implements={ctx.total_implements_edges}, "
                f"type_refs={ctx.total_type_of_edges}")

        if should_stop(ctx.task_id):
            ctx.log("Step 2: 检测到停止标志，跨文件引用解析被中断")
            ctx.stopped = True
    except Exception as e:
        ctx.log(f"引用解析失败: {e}")

    ctx.report_progress(72.0)
    return ctx


def _step3_extract_imports(ctx: PipelineContext) -> PipelineContext:
    """Step 2.5: 文件依赖提取 — 进度 72→74"""
    ctx.log("Step 2.5: 文件依赖提取开始")
    import time as _time
    _t0 = _time.perf_counter()

    def _on_import_progress(current, total):
        if total > 0:
            pct = 72.0 + (current / total) * 2.0
            ctx.report_progress(round(pct, 2))

    if should_stop(ctx.task_id):
        ctx.log("Step 2.5: 检测到停止标志，跳过依赖提取")
        ctx.report_progress(74.0)
        return ctx

    try:
        import_edges = _extract_import_dependencies(
            ctx.analysis_store, ctx.task_id, ctx.all_tables, ctx.proj_path,
            progress_callback=_on_import_progress,
            stop_check=lambda: should_stop(ctx.task_id),
        )
        ctx.log(f"文件依赖提取耗时: {_time.perf_counter() - _t0:.1f}s, 共 {len(import_edges)} 条依赖边")
        if import_edges:
            _t1 = _time.perf_counter()
            ctx.emitter.write_edges(import_edges)
            ctx.log(f"依赖边写入耗时: {_time.perf_counter() - _t1:.1f}s")
            ctx.total_dep_edges = len(import_edges)
            ctx.log(f"文件依赖提取完成: {ctx.total_dep_edges} 条依赖边")
    except Exception as e:
        ctx.log(f"文件依赖提取失败: {e}")

    if should_stop(ctx.task_id):
        ctx.log("Step 2.5: 检测到停止标志，依赖提取被中断")
        ctx.stopped = True

    ctx.report_progress(74.0)
    return ctx


def _step4_synthesize_frameworks(ctx: PipelineContext) -> PipelineContext:
    """Step 3: 框架感知 + 动态合成 — 进度 74→77"""
    ctx.log("Step 3: 框架感知 + 动态合成开始")

    if should_stop(ctx.task_id):
        ctx.log("Step 3: 检测到停止标志，跳过框架合成")
        ctx.stopped = True
        ctx.report_progress(77.0)
        return ctx

    try:
        from parsers.frameworks import run_all as run_frameworks
        framework_edges = run_frameworks(ctx.all_tables)
        if framework_edges:
            ctx.emitter.write_edges(framework_edges)
            ctx.total_framework_edges = len(framework_edges)
            ctx.framework_edges_list = framework_edges
            ctx.log(f"框架感知完成: {ctx.total_framework_edges} 条框架边")
    except Exception as e:
        ctx.log(f"框架感知失败: {e}")

    if should_stop(ctx.task_id):
        ctx.log("Step 3: 检测到停止标志，跳过动态合成")
        ctx.stopped = True
        ctx.report_progress(77.0)
        return ctx

    try:
        from parsers.core.synthesis import DynamicSynthesizer
        synthesizer = DynamicSynthesizer()
        all_nodes = [n for t in ctx.all_tables for n in t.nodes]
        all_edges_for_synth = [_edge_to_dict(e) for e in ctx.resolved_edges]
        all_edges_for_synth += [_edge_to_dict(e) for e in ctx.framework_edges_list]
        synthetic_edges = synthesizer.synthesize(all_nodes, all_edges_for_synth, ctx.all_tables)
        if synthetic_edges:
            ctx.emitter.write_edges(synthetic_edges)
            ctx.total_synthetic_edges = len(synthetic_edges)
            ctx.log(f"动态合成完成: {ctx.total_synthetic_edges} 条合成边")
    except Exception as e:
        ctx.log(f"动态合成失败: {e}")

    ctx.report_progress(77.0)
    return ctx


def _step5_detect_communities(ctx: PipelineContext) -> PipelineContext:
    """Step 4: 社区分析 (Louvain) — 进度 77→99"""
    ctx.log("Step 4: 社区分析开始")

    try:
        from community_analysis import analyze_communities as _analyze_communities
        _community_available = True
    except ImportError:
        _analyze_communities = None
        _community_available = False
        logger.warning("community_analysis plugin not available, community analysis will be skipped")

    if should_stop(ctx.task_id):
        ctx.log("Step 4: 检测到停止标志，跳过社区分析")
        ctx.stopped = True
        ctx.report_progress(99.0)
        return ctx

    report_types = ctx.report_types
    a_store = ctx.analysis_store
    task_id = ctx.task_id

    if "dependency" in report_types or "full" in report_types:
        if _community_available:
            try:
                comm_result = _analyze_communities(
                    task_id=task_id, analysis_store=a_store,
                    edge_type="INCLUDE", min_node_cnt=COMMUNITY_MIN_NODE_INCLUDE,
                )
                ctx.total_communities += comm_result.get("community_count", 0)
                ctx.total_hubs += comm_result.get("hub_count", 0)
                ctx.total_orphans += comm_result.get("orphan_count", 0)
                best = a_store.get_best_community(task_id, "INCLUDE")
                if best:
                    ctx.best_dep_community_id = best["comm_id"]
                ctx.log(f"INCLUDE 社区分析完成: {comm_result.get('community_count', 0)} 个社区"
                        f" (枢纽={ctx.total_hubs}, 孤立={ctx.total_orphans})")
            except Exception as e:
                ctx.log(f"INCLUDE 社区分析失败: {e}")
        else:
            ctx.log("社区分析插件未安装，跳过 INCLUDE")

    if should_stop(ctx.task_id):
        ctx.log("Step 4: 检测到停止标志，跳过 CALL 社区分析")
        ctx.stopped = True
        ctx.report_progress(99.0)
        return ctx

    has_call = "callChain" in report_types or "full" in report_types
    ctx.report_progress(82.0 if has_call else 99.0)

    if has_call:
        if _community_available:
            try:
                comm_result = _analyze_communities(
                    task_id=task_id, analysis_store=a_store,
                    edge_type="CALL", min_node_cnt=COMMUNITY_MIN_NODE_CALL,
                )
                ctx.total_communities += comm_result.get("community_count", 0)
                ctx.total_hubs += comm_result.get("hub_count", 0)
                ctx.total_orphans += comm_result.get("orphan_count", 0)
                best = a_store.get_best_community(task_id, "CALL")
                if best:
                    ctx.best_call_community_id = best["comm_id"]
                ctx.log(f"CALL 社区分析完成: {comm_result.get('community_count', 0)} 个社区"
                        f" (枢纽={ctx.total_hubs}, 孤立={ctx.total_orphans})")
            except Exception as e:
                ctx.log(f"CALL 社区分析失败: {e}")
        else:
            ctx.log("社区分析插件未安装，跳过 CALL")

    ctx.report_progress(99.0)
    return ctx


def _step6_generate_summary(ctx: PipelineContext) -> Dict[str, Any]:
    """Step 5: 结果汇总 + 报告写入 — 设置 progress=99（100 在 AI 摘要完成后由 _execute_task 设置）"""
    ctx.log("Step 5: 结果汇总")
    duration_ms = int((time.time() - ctx.start_time) * 1000)
    a_store = ctx.analysis_store
    node_count = a_store.count_graph_nodes(ctx.task_id)

    report = {
        "id": str(uuid.uuid4()),
        "task_id": ctx.task_id,
        "run_id": ctx.run_id,
        "total_ast_nodes": node_count,
        "total_symbols": node_count,
        "total_call_edges": ctx.total_call_edges,
        "total_dep_edges": ctx.total_dep_edges,
        "total_extends_edges": ctx.total_extends_edges,
        "total_implements_edges": ctx.total_implements_edges,
        "total_type_of_edges": ctx.total_type_of_edges,
        "total_framework_edges": ctx.total_framework_edges,
        "total_synthetic_edges": ctx.total_synthetic_edges,
        "total_communities": ctx.total_communities,
        "total_hubs": ctx.total_hubs,
        "total_orphans": ctx.total_orphans,
        "language_stats": ctx.language_stats,
        "files_processed": ctx.processed,
        "skipped_files": ctx.skipped,
        "best_call_community_id": ctx.best_call_community_id,
        "best_dep_community_id": ctx.best_dep_community_id,
        "logs": ctx.logs,
        "summary": (
            f"分析完成: {ctx.processed} 个文件, {node_count} 个符号节点, "
            f"{ctx.total_call_edges} 调用, {ctx.total_dep_edges} 依赖, "
            f"{ctx.total_extends_edges} 继承, {ctx.total_implements_edges} 实现, "
            f"{ctx.total_communities} 个社区"
            f"{f', {ctx.total_hubs} 枢纽' if ctx.total_hubs else ''}"
            f"{f', {ctx.total_orphans} 孤立' if ctx.total_orphans else ''}"
            f", 耗时 {duration_ms}ms"
        ),
    }

    from store.task_store import TaskStore
    task_store = TaskStore(ctx.multi_db.main_db)
    task_store.upsert_report(report)
    ctx.report_progress(99.0)
    ctx.log(f"分析完成，耗时 {duration_ms}ms")
    return report


# ==================== 6 步分析流程 — 入口 ====================

def _do_parse(server, multi_db, task_id: str, run_id: str,
              start_time: float) -> Dict[str, Any]:
    """6 步分析流程编排器 — 按顺序执行各步骤，逐步聚合结果"""

    ctx = _load_task_context(server, multi_db, task_id)
    ctx.run_id = run_id
    ctx.start_time = start_time

    ctx.log(f"[DEBUG] task_id={task_id}, project_id={ctx.project_id}")

    # Step 1: AST 解析 + 符号提取 (5→65%)
    ctx = _step1_parse_ast(ctx)
    if ctx.stopped:
        return {"files_processed": ctx.processed, "skipped_files": ctx.skipped, "stopped": True}

    node_count = ctx.analysis_store.count_graph_nodes(task_id)
    ctx.log(f"节点总数: {node_count}")

    # Step 2: 跨文件引用解析 (65→72%)
    ctx = _step2_resolve_references(ctx)
    if ctx.stopped:
        return {"files_processed": ctx.processed, "skipped_files": ctx.skipped, "stopped": True}

    # Step 2.5: 文件依赖提取 (72→74%)
    ctx = _step3_extract_imports(ctx)
    if ctx.stopped:
        return {"files_processed": ctx.processed, "skipped_files": ctx.skipped, "stopped": True}

    # Step 3: 框架感知 + 动态合成 (74→77%)
    ctx = _step4_synthesize_frameworks(ctx)
    if ctx.stopped:
        return {"files_processed": ctx.processed, "skipped_files": ctx.skipped, "stopped": True}

    # Step 4: 社区分析 (77→99%)
    ctx = _step5_detect_communities(ctx)
    if ctx.stopped:
        return {"files_processed": ctx.processed, "skipped_files": ctx.skipped, "stopped": True}

    # Step 5: 结果汇总 (99→100%)
    report = _step6_generate_summary(ctx)
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
            # 解析管线已完成，progress=99（step 6 未设 100，留待 AI 摘要后）
            # 先运行 AI 项目摘要（涉及 LLM 调用，可能耗时）
            # 前端进度此时停留在 99，让用户感知"摘要生成中"
            pid = None
            task = task_store.get_task(task_id)
            if task:
                pid = task.get("project_id")
            if pid:
                _update_progress(server, multi_db, task_id, run_id, progress=95)
                try:
                    from core_service import _do_generate_project_summary
                    await _do_generate_project_summary(multi_db, pid)
                    logger.info(f"[EXECUTE] 项目概要自动生成完成: task={task_id}")
                except Exception as _e:
                    logger.warning(f"[EXECUTE] 项目概要自动生成失败: {_e}")
            else:
                logger.info(f"[EXECUTE] 项目概要自动生成跳过: task={task_id} 无 project_id")

            # AI 摘要完成后（不论成败），标记任务完成
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
        try:
            multi_db.cache_store.remove_executing_task(task_id)
        except Exception:
            pass
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
        try:
            multi_db.cache_store.remove_executing_task(task_id)
        except Exception:
            pass
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
