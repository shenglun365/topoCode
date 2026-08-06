"""incremental_runner.py — KB 版本更新的逐环节增量执行（P1 起）。

设计（KB 语义）：
  - 以文件级 delta（A/M/D）为输入，只处理变更文件，未变化数据不动。
  - 每次写分析表前，把被覆盖/删除的旧行归档到对应 *_history（δ 归档）。
  - AST（必更）：A/M 文件重新解析，符号 upsert；D 文件删除符号。
  - 图（必更）：保留"两端都在未变文件"的旧边；对变更文件重新解析引用，
    与未变符号(从 graph_node 重建 stub)组成完整符号宇宙。
  - 预摘要 / 组件 / LLM：P2/P3 实现，当前为 planned 占位。

已知限制（文件粒度增量）：
  - 图增量中，'未变文件 → 变更文件' 的跨文件边可能因未变文件未重新解析而缺失；
    完整正确性可走全量任务重跑（analysis.runTask）。
"""

import json
import logging
import os
from typing import Optional

from sqlite_ctx import MultiDBManager, SQLiteContext

logger = logging.getLogger(__name__)

# 各环节历史表（与活表同名 + _history）
ANALYSIS_TABLES = [
    "graph_node", "graph_edge", "graph_doc", "community_hierarchy",
    "community_llm_results", "file_summaries", "ast_data",
    "dependencies", "call_chains",
]

PARSED_TABLES = ["graph_node", "graph_edge"]


def _parse_one_file(abs_path: str, lang_key: str, proj_path: str):
    """解析单个文件 → FileSymbolTable（复用 walker）。"""
    from parsers.core.walker import TreeSitterWalker
    from parsers.languages import EXTRACTORS
    from parsers.language_loader import get_parser

    if lang_key == "c_header":
        lang_key = "c"
    extractor = EXTRACTORS.get(lang_key)
    if extractor is None:
        return None
    parser = get_parser(lang_key)
    if parser is None:
        return None
    if not os.path.exists(abs_path):
        return None
    src_bytes = open(abs_path, "rb").read()
    if len(src_bytes) > 500 * 1024:
        return None
    walker = TreeSitterWalker(abs_path, src_bytes, lang_key, extractor)
    table = walker.extract()
    table.file_path = os.path.relpath(abs_path, proj_path)
    return table


def _parse_changed_files(proj_path: str, delta: dict) -> dict:
    """解析 A/M 文件，返回 {file_path: FileSymbolTable}。"""
    from parsers.languages import EXTRACTORS
    from version_sync_service import EXT_LANG
    tables: dict = {}
    for path in (delta.get("added", []) + delta.get("modified", [])):
        ext = os.path.splitext(path)[1].lower()
        lang_key = EXT_LANG.get(ext, "")
        if not lang_key or lang_key not in EXTRACTORS:
            continue
        abs_path = os.path.join(proj_path, path)
        try:
            table = _parse_one_file(abs_path, lang_key, proj_path)
        except Exception as e:
            logger.warning(f"[inc] parse failed {path}: {e}")
            table = None
        if table:
            tables[path] = table
    return tables


def _node_file_map(project_db: SQLiteContext, task_id: str) -> dict:
    """{node_id: file_path}（该任务的全部 graph_node）。"""
    rows = project_db.fetchall(
        "SELECT id, file_path FROM graph_node WHERE task_id = ?", (task_id,))
    return {r["id"]: r["file_path"] for r in rows}


def _stub_tables(project_db: SQLiteContext, task_id: str,
                 excluded_files: set) -> dict:
    """从 graph_node 重建未变文件的 FileSymbolTable stub（无 unresolved_refs）。"""
    from parsers.core.symbol_model import FileSymbolTable, Node
    from parsers.core.node_types import NodeKind

    rows = project_db.fetchall(
        "SELECT * FROM graph_node WHERE task_id = ?", (task_id,))
    by_file: dict = {}
    for r in rows:
        fp = r["file_path"]
        if fp in excluded_files:
            continue
        try:
            kind = NodeKind(r["kind"])
        except ValueError:
            continue
        try:
            decorators = json.loads(r["decorators"]) if r["decorators"] else None
        except (TypeError, ValueError):
            decorators = None
        try:
            tp = json.loads(r["type_parameters"]) if r["type_parameters"] else None
        except (TypeError, ValueError):
            tp = None
        table = by_file.get(fp)
        if table is None:
            table = FileSymbolTable(file_path=fp, language=r["language"] or "")
            by_file[fp] = table
        table.nodes.append(Node(
            id=r["id"], kind=kind, name=r["name"], qualified_name=r["qualified_name"],
            file_path=fp, language=r["language"] or "",
            start_line=r["start_line"], start_col=r["start_col"],
            end_line=r["end_line"], end_col=r["end_col"],
            signature=r["signature"] or None, visibility=r["visibility"] or None,
            is_exported=bool(r["is_exported"]), is_async=bool(r["is_async"]),
            is_static=bool(r["is_static"]), docstring=r["docstring"] or None,
            decorators=decorators, type_parameters=tp,
        ))
    return by_file


def _archive_and_clear(project_db: SQLiteContext, table: str,
                       where_sql: str, params: tuple) -> int:
    """把活表旧行归档到 *_history 后删除。返回归档数。"""
    hist = f"{table}_history"
    cols = [r["name"] for r in project_db.execute(f"PRAGMA table_info({table})").fetchall()]
    col_list = ", ".join(f'"{c}"' for c in cols)
    project_db.execute(
        f'INSERT OR REPLACE INTO {hist} ({col_list}, version_to) '
        f'SELECT {col_list}, NULL FROM {table} WHERE {where_sql}',
        params,
    )
    cur = project_db.execute(f"DELETE FROM {table} WHERE {where_sql}", params)
    return cur.rowcount if cur else 0


def _ensure_history(multi_db: MultiDBManager, project_db: SQLiteContext) -> None:
    for t in ANALYSIS_TABLES:
        try:
            multi_db.ensure_history_table(project_db, t)
        except Exception:
            pass


# ── 各环节 ─────────────────────────────────────────────

def _inc_ast(multi_db: MultiDBManager, project_db: SQLiteContext,
             task_id: str, proj_path: str, delta: dict,
             changed_tables: dict) -> dict:
    """AST 增量：A/M 解析 upsert，D 删除归档。"""
    from store.analysis_store import AnalysisStore
    from parsers.core.emitter import GraphEmitter

    a_store = AnalysisStore(project_db)
    emitter = GraphEmitter(a_store, task_id, project_root=proj_path)
    archived = 0
    written = 0
    removed = 0

    for path in delta.get("added", []) + delta.get("modified", []):
        archived += _archive_and_clear(
            project_db, "graph_node",
            "task_id = ? AND file_path = ?", (task_id, path))
        table = changed_tables.get(path)
        if table:
            written += emitter.write_nodes(table)

    for path in delta.get("deleted", []):
        archived += _archive_and_clear(
            project_db, "graph_node",
            "task_id = ? AND file_path = ?", (task_id, path))
        removed += 1

    project_db.conn.commit()
    logger.info(f"[inc.ast] task={task_id} archived={archived} written={written} removed={removed}")
    return {"status": "done", "archivedRows": archived, "writtenNodes": written,
            "removedFiles": removed}


def _inc_graph(multi_db: MultiDBManager, project_db: SQLiteContext,
               task_id: str, proj_path: str, delta: dict,
               changed_tables: dict) -> dict:
    """图增量：保留未变边 + 对变更文件重解析引用。"""
    from store.analysis_store import AnalysisStore
    from parsers.core.emitter import GraphEmitter
    from parsers.core.resolver import ResolutionEngine

    changed = set(delta.get("added", [])) | set(delta.get("modified", [])) | set(delta.get("deleted", []))

    # 旧边：两端符号仍存在（AST 增量已更新/保留）→ 保留；触及已删符号 → 丢弃。
    # 空端点 = 模块/文件级边（非符号绑定），保留（源文件未变则 import 语句未变）。
    old_edges = project_db.fetchall("SELECT * FROM graph_edge WHERE task_id = ?", (task_id,))
    node_file = _node_file_map(project_db, task_id)
    keep_edges = []
    for e in old_edges:
        src_ok = not e["source_id"] or e["source_id"] in node_file
        tgt_ok = not e["target_id"] or e["target_id"] in node_file
        if src_ok and tgt_ok:
            keep_edges.append(e)
    project_db.execute("DELETE FROM graph_edge WHERE task_id = ?", (task_id,))
    project_db.conn.commit()

    # 符号宇宙 = 变更文件新表 + 未变文件 stub
    universe = dict(changed_tables)
    stubs = _stub_tables(project_db, task_id, excluded_files=changed)
    universe.update(stubs)

    a_store = AnalysisStore(project_db)
    emitter = GraphEmitter(a_store, task_id, project_root=proj_path)
    resolved = []
    try:
        resolver = ResolutionEngine()
        resolved = resolver.resolve(list(universe.values()))
    except Exception as e:
        logger.warning(f"[inc.graph] resolution failed: {e}")

    # 写回：保留边 + 新解析边
    kept_rows = [{
        "id": e["id"], "task_id": task_id, "source_id": e["source_id"],
        "target_id": e["target_id"], "kind": e["kind"],
        "provenance": e["provenance"], "line": e["line"], "col": e["col"],
        "file_path": e["file_path"], "metadata": e["metadata"] or "",
    } for e in keep_edges]
    if kept_rows:
        a_store.bulk_insert_edges(kept_rows)
    if resolved:
        emitter.write_edges(resolved)

    project_db.conn.commit()
    total = len(kept_rows) + len(resolved)
    logger.info(f"[inc.graph] task={task_id} kept={len(keep_edges)} resolved={len(resolved)} total={total}")
    return {"status": "done", "keptEdges": len(keep_edges), "newEdges": len(resolved),
            "totalEdges": total}


def _planned(status: str = "planned") -> dict:
    return {"status": status, "implemented": False}


def apply_incremental(multi_db: MultiDBManager, project_id: str, task_id: str,
                      delta: dict, stages: dict, proj_path: str = "") -> dict:
    """执行选中的环节增量。返回各环节结果。"""
    if not task_id:
        return {k: _planned("no-task") for k in stages}
    project_db = multi_db.get_project_db(project_id)
    _ensure_history(multi_db, project_db)

    results: dict = {}
    do_ast = bool(stages.get("ast"))
    do_graph = bool(stages.get("graph"))
    do_ps = bool(stages.get("presummary"))
    do_comm = bool(stages.get("community"))
    do_llm = bool(stages.get("llm"))

    changed_tables = _parse_changed_files(proj_path, delta) if (do_ast or do_graph) else {}

    if do_ast:
        results["ast"] = _inc_ast(multi_db, project_db, task_id, proj_path, delta, changed_tables)
    if do_graph:
        results["graph"] = _inc_graph(multi_db, project_db, task_id, proj_path, delta, changed_tables)
    if do_ps:
        results["presummary"] = _planned()
    if do_comm:
        results["community"] = _planned()
    if do_llm:
        results["llm"] = _planned()

    return results
