"""
DuckDBReader — 列式引擎加速 OLAP 只读查询

替代 SQLite 的跨表 JOIN/聚合/递归查询。DuckDB 直接 ATTACH SQLite 文件读取，
无需数据复制。

使用方式:
    reader = DuckDBReader(multi_db)
    ranks = reader.compute_file_ranks(task_id, project_db_label, components, root)
    levels = reader.get_cascade_levels(task_id, project_db_label, edge_type)
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class DuckDBReader:
    """DuckDB 只读查询加速器。"""

    def __init__(self, multi_db):
        import duckdb
        self._conn = duckdb.connect(':memory:')
        self._multi_db = multi_db
        self._attached: set[str] = set()
        self._db_paths: dict[str, str] = {}

    def _attach(self, label: str, path: str):
        """按需 ATTACH SQLite 数据库。"""
        if label in self._attached:
            return
        db_name = label.replace(':', '_').replace('-', '_')
        try:
            self._conn.execute(
                f"ATTACH '{path}' AS {db_name} (TYPE sqlite)"
            )
            self._attached.add(label)
            self._db_paths[label] = path
        except Exception as e:
            logger.warning(f"[DuckDB] ATTACH {label} failed: {e}")

    def _pdb_name(self, pid: str) -> str:
        return f"project_{pid.replace('-', '_')}"

    def _attach_project(self, pid: str):
        label = f"project:{pid}"
        if label in self._attached:
            return
        pdb = self._multi_db.get_project_db(pid)
        self._attach(label, pdb.db_path)

    def _rows(self, sql: str, params=()) -> list[dict]:
        """执行 DuckDB 查询，返回 dict 列表。"""
        try:
            result = self._conn.execute(sql, params)
            cols = [d[0] for d in result.description]
            return [dict(zip(cols, row)) for row in result.fetchall()]
        except Exception as e:
            logger.warning(f"[DuckDB] query failed: {e} | SQL={sql[:120]}")
            return []

    # ── 预定义查询 ─────────────────────────────────────────────────────

    def compute_file_ranks(
        self, task_id: str, pid: str, components: list, project_root: str,
    ) -> dict:
        """
        替代 _compute_file_ranks() — 一次 hash join 计算文件排名。
        返回: {"files": [...], "counts": {...}}
        """
        import os as _os
        self._attach_project(pid)
        pdb = self._pdb_name(pid)
        _rel = (lambda ap: _os.path.relpath(ap, project_root)
                if project_root and ap.startswith(project_root) else ap)

        # 收集 L0 文件
        l0_files = set()
        for comp in components:
            nl = comp.get("node_list", [])
            if isinstance(nl, list):
                for nid in nl:
                    if isinstance(nid, str) and nid.strip() and nid != 'None':
                        l0_files.add(nid)

        if not l0_files:
            return {"files": [], "counts": {}}

        # DuckDB: 一次查询解决文件大小
        placeholders = ','.join(f"'{fp}'" for fp in l0_files)
        dep_rows = self._rows(
            f"SELECT d.source_file, COUNT(*) AS cnt "
            f"FROM {pdb}.dependencies d "
            f"JOIN {pdb}.graph_node g "
            f"ON g.file_path = d.source_file AND g.task_id = ? "
            f"WHERE d.source_file IN ({placeholders}) "
            f"GROUP BY d.source_file",
            (task_id,)
        )
        dep_map = {r["source_file"]: r["cnt"] for r in dep_rows}

        # DuckDB: 批量查文件大小
        size_rows = self._rows(
            f"SELECT file_path, size FROM {pdb}.source_files "
            f"WHERE file_path IN ({placeholders})"
        )
        size_map = {r["file_path"]: r["size"] or 0 for r in size_rows}

        files = []
        counts = {"P0": 0, "P1": 0, "P2": 0}
        for fp in sorted(l0_files):
            rel = _rel(fp) if project_root else fp
            dep_count = dep_map.get(fp, dep_map.get(rel, 0))
            fsize = size_map.get(fp, size_map.get(rel, 0))
            score = dep_count * 10 + fsize // 1024
            if score >= 50:
                batch = "P0"
            elif score >= 10 or dep_count >= 2:
                batch = "P1"
            else:
                batch = "P2"
            counts[batch] += 1
            files.append({
                "path": fp, "rel": rel,
                "dep_count": dep_count, "size": fsize,
                "batch": batch, "score": score,
            })
        return {"files": files, "counts": counts}

    def get_cascade_levels(
        self, task_id: str, pid: str, edge_type: str,
    ) -> list[dict]:
        """
        替代 _get_cascade_levels_impl() — single LEFT JOIN 替代 N+1 相关子查询。
        """
        self._attach_project(pid)
        pdb = self._pdb_name(pid)

        rows = self._rows(
            f"SELECT h.comm_lv, h.comm_id, h.parent_comm_id, "
            f"h.node_count, h.file_count, h.quality_score, h.edge_count, "
            f"g.metadata "
            f"FROM {pdb}.community_hierarchy h "
            f"LEFT JOIN {pdb}.graph_doc g "
            f"ON g.task_id = h.task_id AND g.edge_type = h.edge_type "
            f"AND g.comm_id = h.comm_id "
            f"WHERE h.task_id = ? AND h.edge_type = ? "
            f"ORDER BY h.comm_lv, h.comm_id",
            (task_id, edge_type)
        )
        return rows

    def get_external_imports(
        self, task_id: str, pid: str,
    ) -> list[dict]:
        """
        替代 get_external_stats 中的 import/deps 查询。
        一次 JOIN 查询替代 3+ SQLite 查询。
        """
        self._attach_project(pid)
        pdb = self._pdb_name(pid)

        rows = self._rows(
            f"SELECT gn_src.file_path, ge.metadata "
            f"FROM {pdb}.graph_edge ge "
            f"JOIN {pdb}.graph_node gn_src "
            f"ON gn_src.id = ge.source_id AND gn_src.task_id = ge.task_id "
            f"WHERE ge.task_id = ? AND ge.kind = 'imports'",
            (task_id,)
        )
        return rows

    def count_by_extensions(
        self, pid: str, scopes: list, extensions: list, exclude_dirs: list,
    ) -> list[dict]:
        """替代 count_by_extensions — vectorized GROUP BY。"""
        self._attach_project(pid)
        pdb = self._pdb_name(pid)
        parts = ["SELECT language, COUNT(*) AS cnt FROM "
                 f"{pdb}.source_files WHERE 1=1"]
        params = []
        if scopes:
            placeholders = ','.join('?' * len(scopes))
            parts.append(f"AND scope IN ({placeholders})")
            params.extend(scopes)
        if extensions:
            like_clauses = ' OR '.join(
                f"file_path LIKE ?" for _ in extensions
            )
            parts.append(f"AND ({like_clauses})")
            params.extend(f"%{ext}" for ext in extensions)
        if exclude_dirs:
            for d in exclude_dirs:
                parts.append(f"AND file_path NOT LIKE ?")
                params.append(f"{d}%")
        parts.append("GROUP BY language")
        return self._rows(' '.join(parts), tuple(params))

    def extract_call_edges(
        self, task_id: str, pid: str, file_path: str, limit: int = 50,
    ) -> list[dict]:
        """
        替代 SubAgent._extract_call_edges — hash join 替代 3-way nested loop。
        """
        self._attach_project(pid)
        pdb = self._pdb_name(pid)
        return self._rows(
            f"SELECT g1.name AS src, g2.name AS tgt, d.type "
            f"FROM {pdb}.dependencies d "
            f"JOIN {pdb}.graph_node g1 "
            f"ON g1.id = d.source_id AND g1.task_id = ? "
            f"JOIN {pdb}.graph_node g2 "
            f"ON g2.id = d.target_id AND g2.task_id = ? "
            f"WHERE g1.file_path = ? AND g2.file_path = ? "
            f"LIMIT ?",
            (task_id, task_id, file_path, file_path, limit),
        )

    def get_call_chain_bfs(
        self, task_id: str, pid: str, source_id: str, max_depth: int = 5,
    ) -> list[dict]:
        """
        替代 GetCallChainTool BFS 循环 — 递归 CTE 一次查询。
        """
        self._attach_project(pid)
        pdb = self._pdb_name(pid)
        return self._rows(
            f"WITH RECURSIVE chain AS ( "
            f"  SELECT source_id, target_id, 1 AS depth "
            f"  FROM {pdb}.dependencies "
            f"  WHERE source_id = ? AND task_id = ? "
            f"  UNION ALL "
            f"  SELECT d.source_id, d.target_id, c.depth + 1 "
            f"  FROM {pdb}.dependencies d "
            f"  JOIN chain c ON d.source_id = c.target_id "
            f"  WHERE c.depth < ? "
            f") "
            f"SELECT * FROM chain ORDER BY depth",
            (source_id, task_id, max_depth),
        )

    def get_usage_stats(
        self, model_id: str = "", start_date: str = "", end_date: str = "",
    ) -> list[dict]:
        """替代 getUsageStats — hash join 加速。"""
        main_path = self._multi_db.main_db.db_path
        self._attach("main", main_path)
        main_db = self._db_paths.get("main", "main").replace('-', '_')
        sql = (
            f"SELECT d.*, m.name AS model_name "
            f"FROM {main_db}.model_daily_usage d "
            f"JOIN {main_db}.model_configs m ON d.model_id = m.id "
            f"WHERE 1=1"
        )
        params = []
        if model_id:
            sql += " AND d.model_id = ?"
            params.append(model_id)
        if start_date:
            sql += " AND d.date >= ?"
            params.append(start_date)
        if end_date:
            sql += " AND d.date <= ?"
            params.append(end_date)
        sql += " ORDER BY d.date DESC, m.name"
        return self._rows(sql, tuple(params))

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
