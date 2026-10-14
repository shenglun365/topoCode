"""semantic_service —— 代码解析/符号提取/关系提取/社区分析公共服务(KB 与 architect 共用)。

架构裁决(用户): 不复刻、不分叉——本模块是**薄编排层**, 直调 analyst_runner
的原 Step 函数(_step1.._step5), KB 与 architect 字面上跑同一批代码; 数据宿主
由调用方决定:
- KB 自身管线: analyst_runner 6 步(任务外壳)不动, 仍是唯一事实源;
- architect: import 直调 run_pipeline(同包同环境), 结果落 arch.db;
- 本服务缺省内存库即抛(零持久化)——KB 不存 architect 的数据, 反之亦然。

社区划分含 L0~L5 全层级(INCLUDE/CALL 两线 + UNIFIED 合并, 递归深度与
min_node_cnt 全部来自 KB config 单源), 无任何本地裁剪/限制。

裸导入守护: _step5 用 `from community_analysis import ...`(依赖插件目录
sys.path 注入, KB 进程由 PluginManager 满足)——本服务显式注入并断言可用,
**禁止静默跳过社区分析**(静默=与 KB 结果不一致的隐形分叉)。
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_TASK = "buildgraph"          # 内存库任务轴占位 id(库即抛, 不与真实任务冲突)
_PLUGIN_ROOT = Path(__file__).resolve().parent.parent / "plugins"


def _ensure_plugin_paths() -> None:
    """插件目录注入 sys.path(幂等)——community_analysis/parsers 裸导入的前提。"""
    for sub in ("community", "parsers"):
        d = str(_PLUGIN_ROOT / sub)
        if os.path.isdir(d) and d not in sys.path:
            sys.path.insert(0, d)


def _assert_community_available() -> None:
    """社区插件可用性断言(绝不静默跳过)。"""
    _ensure_plugin_paths()
    try:
        import community_analysis  # noqa: F401
        import unified_merge  # noqa: F401
    except ImportError as e:  # pragma: no cover
        raise RuntimeError(
            f"community 插件不可用({e})——社区分析将被跳过, 禁止静默继续") from e


def _preset_source_files(db, project_root: str, files: List[str]) -> int:
    """内存库预置 source_files(Step1 的 list_source_files 原样取出)。

    language 用 parsers 的 _detect_language 判定(与 KB 导入扫描同源), 非
    代码文件不入表(Step1 按 language 分组解析)。"""
    _ensure_plugin_paths()
    from parsers.core.walker import _detect_language
    rows = []
    for rel in files or []:
        rel = rel.replace(os.sep, "/")
        lang = _detect_language(os.path.join(project_root, rel))
        if not lang:
            continue
        rows.append((f"sf:{rel}", rel, os.path.basename(rel), lang))
    if rows:
        with db._lock:
            db._conn and db._conn.executemany(
                "INSERT OR REPLACE INTO source_files "
                "(id, file_path, file_name, language) VALUES (?,?,?,?)", rows)
            db._conn.commit()
    return len(rows)


def run_pipeline(project_root: str, files: List[str], *, store=None,
                 task_id: str = _TASK) -> dict:
    """端到端语义管线(解析→符号→关系→社区, 原函数直调, 零持久化缺省)。

    Args:
        project_root: 项目根绝对路径。
        files: 相对路径清单(非代码文件自动忽略——与 KB 扫描同源判定)。
        store: 可注入 AnalysisStore(KB 未来复用传磁盘库); 缺省内存库即抛。
        task_id: 库内任务轴 id(缺省 buildgraph 占位)。

    Returns:
        {nodes, edges, components, levels, counts, stats}
        components: UNIFIED 组件树全层级[{commId, level("L0".."L5"), parentId,
        files, nodeCount, fileCount, qualityScore}]。
    """
    _assert_community_available()
    project_root = os.path.abspath(project_root or ".")
    if not os.path.isdir(project_root):
        raise ValueError(f"projectRoot not found: {project_root}")

    from topoone.db.manager import SQLiteContext
    from topoone.db.schema.project import PROJECT_DB_TABLES_SQL
    from topoone.engine.store.analysis_store import AnalysisStore
    from parsers.core.emitter import GraphEmitter
    from topoone.engine import analyst_runner as AR

    own_db = store is None
    db = SQLiteContext(":memory:", label="kb:semantic_service") if own_db else None
    if own_db:
        db.executescript(PROJECT_DB_TABLES_SQL)
    target_db = store._db if store is not None else db
    a_store = store if store is not None else AnalysisStore(db)

    n_files = _preset_source_files(target_db, project_root, files)

    ctx = AR.PipelineContext(server=None, multi_db=None, task_id=task_id,
                             run_id="", start_time=0.0)
    ctx.task = {"scopes": [], "extensions": [], "exclude_dirs": []}
    ctx.project_id = ""
    ctx.analysis_store = a_store
    ctx.proj_path = project_root
    ctx.report_types = ["full"]
    ctx.emitter = GraphEmitter(a_store, task_id, project_root=project_root)
    ctx.report_progress = lambda p: None  # no-op(无任务/无 ZMQ)

    if n_files == 0:
        return {"nodes": [], "edges": [], "components": [], "levels": 0,
                "counts": {}, "stats": {"processed": 0, "skipped": len(files or [])}}

    ctx = AR._step1_parse_ast(ctx)
    ctx = AR._step2_resolve_references(ctx)
    ctx = AR._step3_extract_imports(ctx)
    ctx = AR._step4_synthesize_frameworks(ctx)
    ctx = AR._step5_detect_communities(ctx)

    return _collect_result(a_store, task_id, ctx)


def _collect_result(a_store, task_id: str, ctx) -> dict:
    """从库读回节点/边/UNIFIED 组件树(全层级)。"""
    nodes = a_store.get_graph_nodes(task_id) or []
    edges = a_store.get_graph_edges(task_id) or []
    id2file = {}
    for n in nodes:
        fp = n.get("file_path") or ""
        if fp:
            id2file[n.get("id")] = fp
    components = []
    for d in a_store.get_communities(task_id, "UNIFIED") or []:
        try:
            members = d.get("node_list") or []
            if isinstance(members, str):
                import json as _json
                members = _json.loads(members or "[]")
        except Exception:  # noqa: BLE001
            members = []
        files: List[str] = []
        for m in members:
            fp = id2file.get(m) or (m if isinstance(m, str) and
                                    ("/" in m or "." in m) else "")
            if fp and fp not in files:
                files.append(fp)
        files.sort()
        components.append({
            "commId": d.get("comm_id"), "level": d.get("comm_lv"),
            "parentId": d.get("parent_comm_id") or "",
            "files": files,
            "nodeCount": int(d.get("node_count") or len(members)),
            "fileCount": int(d.get("file_count") or len(files)),
            "qualityScore": d.get("quality_score") or 0,
        })
    components.sort(key=lambda c: (str(c["level"]), -int(c["nodeCount"])))
    return {
        "nodes": nodes, "edges": edges, "components": components,
        "levels": _max_level(components),
        "counts": {
            "inputFiles": ctx.processed + ctx.skipped,
            "parsed": ctx.processed, "skipped": ctx.skipped,
            "nodes": len(nodes), "edges": len(edges),
            "calls": ctx.total_call_edges, "imports": ctx.total_dep_edges,
            "framework": ctx.total_framework_edges,
            "synthetic": ctx.total_synthetic_edges,
            "communities": ctx.total_communities,
        },
        "stats": {"task_id": task_id},
    }


def _max_level(components: List[dict]) -> int:
    lv = 0
    for c in components:
        s = str(c.get("level") or "L0")
        if s[1:].isdigit():
            lv = max(lv, int(s[1:]))
    return lv
