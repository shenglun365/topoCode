"""
analysis_utils — 分析任务通用工具函数

从 task_manager.py 中提取的模块级函数，避免嵌套作用域导致的 import 困难。
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


def get_cascade_levels_impl(project_db, tid, et, pid=None, multi_db=None):
    """getCascadeLevels 内部实现 — 优先 DuckDB，回退 SQLite"""
    t_sql = time.perf_counter()
    rows = []
    has_file_count = True

    duckdb = getattr(multi_db, 'duckdb', None) if multi_db else None
    if pid and duckdb is not None:
        try:
            duck_rows = duckdb.get_cascade_levels(tid, pid, et)
            if duck_rows:
                rows = [(r.get("comm_lv"), r.get("comm_id"),
                         r.get("parent_comm_id"), r.get("node_count"),
                         r.get("file_count"), r.get("quality_score"),
                         r.get("edge_count"), r.get("metadata"))
                        for r in duck_rows]
                logger.info("[PERF] cascade_duckdb %s rows=%d %.1fms",
                           et, len(rows), (time.perf_counter() - t_sql) * 1000)
        except Exception as e:
            logger.warning(f"[DuckDB] cascade_levels fallback to SQLite: {e}")

    if not rows:
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
                metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else metadata_raw
            except Exception:
                pass
        levels_dict.setdefault(lv, {"lv": lv, "items": []})
        levels_dict[lv]["items"].append({
            "id": comm_id, "parentId": parent_id,
            "nodeCount": node_count, "fileCount": file_count,
            "qualityScore": quality, "edgeCount": edge_count,
            "metadata": metadata,
        })

    sorted_levels = sorted(levels_dict.keys(), key=lambda x: (int(x[1:]) if x[1:].isdigit() else 0))
    return {"levels": [levels_dict[lv] for lv in sorted_levels]}


def get_l0_comps(project_db, tid, multi_db=None):
    """获取 L0 社区列表，INCLUDE 为空时回退到 CALL"""
    for et in ("INCLUDE", "CALL"):
        cascades = get_cascade_levels_impl(project_db, tid, et, multi_db=multi_db)
        l0_items = []
        for l in cascades.get("levels", []):
            if l.get("lv") == "L0":
                l0_items = l.get("items", [])
                break
        if l0_items:
            return [{"id": it.get("id", ""), "metadata": {"qualityScore": it.get("qualityScore", 0)}}
                    for it in l0_items]
    return []
