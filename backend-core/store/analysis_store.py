"""
AnalysisStore — 项目库 CRUD 操作

管理 source_files, base_node, graph_node, graph_doc, community_hierarchy
"""
import json
import logging
import re
from typing import Optional, List, Dict

from config import BATCH_INSERT_SIZE

from .connection import SQLiteContext

logger = logging.getLogger(__name__)


def _deserialize_node(node: Dict) -> Dict:
    """反序列化节点中的 JSON 字段（refs, def_node_id 等）"""
    if 'refs' in node and isinstance(node['refs'], str):
        try:
            node['refs'] = json.loads(node['refs'])
        except (json.JSONDecodeError, TypeError):
            node['refs'] = []

    # def_node_id 写入时 str(list) 转成了 "[5]" 格式，需要反序列化回 list
    if 'def_node_id' in node and isinstance(node['def_node_id'], str):
        val = node['def_node_id']
        if val and val.startswith('['):
            try:
                node['def_node_id'] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                node['def_node_id'] = []
        elif not val:
            node['def_node_id'] = []

    return node


class AnalysisStore:
    """项目库分析数据表的 CRUD 封装"""

    def __init__(self, project_db: SQLiteContext):
        self._db = project_db

    # ==================== source_files (v2 高性能查询) ====================

    # 数据库迁移：确保索引存在
    _indexes_ensured = False

    def _ensure_indexes(self):
        """确保 source_files 表存在必要的索引（幂等）"""
        if AnalysisStore._indexes_ensured:
            return
        try:
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sf_language ON source_files(language)"
            )
            self._db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sf_file_path ON source_files(file_path)"
            )
            self._db.commit()
            AnalysisStore._indexes_ensured = True
        except Exception:
            pass

    @staticmethod
    def _build_where_clause(scopes=None, extensions=None, exclude_dirs=None,
                            pattern_type=None, pattern=None):
        """
        构建通用 WHERE 条件 + 参数，返回 (where_clause: str, params: list, wildcard_scopes: list, use_pattern: bool)
        供 list_source_files / count_source_files / list_file_paths 复用
        """
        conditions = ["language != 'directory'"]
        params = []
        wildcard_scopes = []

        if scopes:
            scope_conditions = []
            for s in scopes:
                if '*' in s or '?' in s:
                    wildcard_scopes.append(s)
                    like_pat = s.replace('**', '%').replace('*', '%').replace('?', '_')
                    scope_conditions.append("file_path LIKE ?")
                    params.append(like_pat)
                else:
                    scope_conditions.append("file_path LIKE ?")
                    params.append(f"{s}%" if not s.endswith("%") else s)
            if scope_conditions:
                conditions.append(f"({' OR '.join(scope_conditions)})")

        if extensions:
            ext_clauses = " OR ".join(["language = ?"] * len(extensions))
            conditions.append(f"({ext_clauses})")
            params.extend(extensions)

        if exclude_dirs:
            for d in exclude_dirs:
                conditions.append("file_path NOT LIKE ?")
                params.append(f"%{d}%")

        use_pattern = bool(pattern and pattern_type in ('glob', 'regex'))
        where = " AND ".join(conditions) if conditions else "1=1"
        return where, params, wildcard_scopes, use_pattern

    def count_by_extensions(self, scopes=None, extensions=None, exclude_dirs=None,
                            pattern_type=None, pattern=None) -> Dict[str, int]:
        """
        COUNT(*) GROUP BY language — 用于扩展名分布柱状图，不拉全量行
        """
        self._ensure_indexes()
        where, params, wildcard_scopes, use_pattern = self._build_where_clause(
            scopes=scopes, extensions=extensions, exclude_dirs=exclude_dirs,
            pattern_type=pattern_type, pattern=pattern,
        )
        # 有通配符 scope 或 pattern 时必须回退到全量拉取进行 Python 后过滤
        if wildcard_scopes or use_pattern:
            files = self.list_source_files(
                scopes=scopes, extensions=extensions, exclude_dirs=exclude_dirs,
                pattern_type=pattern_type, pattern=pattern,
            )
            counts: Dict[str, int] = {}
            for f in files:
                lang = f.get("language", "unknown")
                counts[lang] = counts.get(lang, 0) + 1
            return counts

        rows = self._db.execute(
            f"SELECT language, COUNT(*) AS cnt FROM source_files WHERE {where} GROUP BY language",
            params,
        ).fetchall()
        return {r["language"]: r["cnt"] for r in rows}

    def count_files(self, scopes=None, extensions=None, exclude_dirs=None,
                    pattern_type=None, pattern=None) -> int:
        """
        SELECT COUNT(*) — 用于 totalFiles，不拉全量行
        """
        self._ensure_indexes()
        where, params, wildcard_scopes, use_pattern = self._build_where_clause(
            scopes=scopes, extensions=extensions, exclude_dirs=exclude_dirs,
            pattern_type=pattern_type, pattern=pattern,
        )
        if wildcard_scopes or use_pattern:
            files = self.list_source_files(
                scopes=scopes, extensions=extensions, exclude_dirs=exclude_dirs,
                pattern_type=pattern_type, pattern=pattern,
            )
            return len(files)

        row = self._db.execute(
            f"SELECT COUNT(*) AS cnt FROM source_files WHERE {where}",
            params,
        ).fetchone()
        return row["cnt"] if row else 0

    def list_file_paths(self, scopes=None, extensions=None, exclude_dirs=None,
                        pattern_type=None, pattern=None) -> List[str]:
        """
        SELECT file_path — 用于目录树构建 + 目录文件数统计，只取路径列
        """
        self._ensure_indexes()
        where, params, wildcard_scopes, use_pattern = self._build_where_clause(
            scopes=scopes, extensions=extensions, exclude_dirs=exclude_dirs,
            pattern_type=pattern_type, pattern=pattern,
        )
        if wildcard_scopes or use_pattern:
            files = self.list_source_files(
                scopes=scopes, extensions=extensions, exclude_dirs=exclude_dirs,
                pattern_type=pattern_type, pattern=pattern,
            )
            return [f.get("file_path", "") for f in files]

        rows = self._db.execute(
            f"SELECT file_path FROM source_files WHERE {where}",
            params,
        ).fetchall()
        return [r["file_path"] for r in rows]

    # ==================== source_files（旧版兼容） ====================

    def list_source_files(self, scopes: List[str] = None,
                          extensions: List[str] = None,
                          exclude_dirs: List[str] = None,
                          pattern_type: str = None,
                          pattern: str = None) -> List[Dict]:
        """
        获取源文件列表（应用过滤条件）

        scopes 支持 glob 通配符: *, ?, ** （含 * 或 ? 时按 glob 匹配，否则按前缀匹配）
        pattern_type: 'glob' | 'regex' | None
        pattern: 匹配 file_path 的 glob/regex 模式

        Returns:
            [{"id", "file_path", "file_name", "language", "size", ...}, ...]
        """
        conditions = ["language != 'directory'"]
        params = []

        wildcard_scopes = []
        if scopes:
            scope_conditions = []
            for s in scopes:
                if '*' in s or '?' in s:
                    wildcard_scopes.append(s)
                    # LIKE 粗略预过滤（通配符转 %），缩小结果集
                    like_pat = s.replace('**', '%').replace('*', '%').replace('?', '_')
                    scope_conditions.append("file_path LIKE ?")
                    params.append(like_pat)
                else:
                    scope_conditions.append("file_path LIKE ?")
                    params.append(f"{s}%" if not s.endswith("%") else s)
            if scope_conditions:
                conditions.append(f"({' OR '.join(scope_conditions)})")

        if extensions:
            ext_clauses = " OR ".join(["language = ?"] * len(extensions))
            conditions.append(f"({ext_clauses})")
            params.extend(extensions)

        if exclude_dirs:
            for d in exclude_dirs:
                conditions.append("file_path NOT LIKE ?")
                params.append(f"%{d}%")

        # pattern 过滤（glob/regex）— 先执行 SQL 获取初集，再后过滤
        use_pattern = pattern and pattern_type in ('glob', 'regex')

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = self._db.execute(
            f"SELECT * FROM source_files WHERE {where}",
            params,
        ).fetchall()
        result = [dict(r) for r in rows]

        # 通配符 scope 后过滤（fnmatch 精确匹配）
        if wildcard_scopes:
            import fnmatch
            def _matches_any_scope(file_path: str) -> bool:
                for ws in wildcard_scopes:
                    if fnmatch.fnmatch(file_path, ws):
                        return True
                return False
            result = [f for f in result if _matches_any_scope(f.get("file_path", ""))]

        # pattern 后过滤
        if use_pattern:
            if pattern_type == 'glob':
                import fnmatch
                result = [f for f in result if fnmatch.fnmatch(f.get("file_path", ""), pattern)]
            elif pattern_type == 'regex':
                try:
                    prog = re.compile(pattern)
                    result = [f for f in result if prog.search(f.get("file_path", ""))]
                except re.error:
                    pass  # 无效正则，忽略

        return result

    def get_file_by_path(self, file_path: str) -> Optional[Dict]:
        row = self._db.execute(
            "SELECT * FROM source_files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return dict(row) if row else None

    def get_file_by_id(self, file_id: str) -> Optional[Dict]:
        row = self._db.execute(
            "SELECT * FROM source_files WHERE id = ?",
            (file_id,),
        ).fetchone()
        return dict(row) if row else None

    # ==================== base_node ====================
    # v2: base_node 已废弃，保留方法签名以兼容旧调用（空实现）

    def delete_nodes_by_file(self, file_id: str):
        pass

    def bulk_insert_nodes(self, nodes: List[Dict]):
        pass

    def get_nodes_by_file(self, file_id: str) -> List[Dict]:
        return []

    def get_nodes_by_type(self, node_type: str) -> List[Dict]:
        return []

    def count_nodes(self, file_id: str = None) -> int:
        return 0

    def _ensure_file_record(self, file_path: str, language: str, task_id: str):
        """确保 source_files 中存在此文件记录"""
        import os
        with self._db._lock:
            row = self._db.execute(
                "SELECT id FROM source_files WHERE file_path = ?",
                (file_path,),
            ).fetchone()
            if not row:
                import uuid
                fid = str(uuid.uuid4())[:16]
                fname = os.path.basename(file_path)
                self._db.execute(
                    "INSERT INTO source_files (id, file_path, file_name, language) VALUES (?, ?, ?, ?)",
                    (fid, file_path, fname, language),
                )
                self._db.commit()

    # ==================== graph_node (v2 重设计) ====================

    def bulk_insert_graph_nodes(self, nodes: List[Dict]):
        """批量插入图节点（v2 schema）"""
        if not nodes:
            return
        with self._db._lock:
            db = self._db.conn
            for i in range(0, len(nodes), BATCH_INSERT_SIZE):
                batch = nodes[i:i + BATCH_INSERT_SIZE]
                db.executemany("""
                    INSERT OR REPLACE INTO graph_node (
                        id, task_id, kind, name, qualified_name, file_path, file_id, language,
                        start_line, start_col, end_line, end_col,
                        signature, visibility, is_exported, is_async, is_static,
                        docstring, decorators, type_parameters
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    (
                        n["id"], n["task_id"], n["kind"], n["name"],
                        n.get("qualified_name", ""), n.get("file_path", ""),
                        n.get("file_id", ""), n.get("language", ""),
                        n["start_line"], n["start_col"], n["end_line"], n["end_col"],
                        n.get("signature", ""), n.get("visibility", ""),
                        n.get("is_exported", 0), n.get("is_async", 0), n.get("is_static", 0),
                        n.get("docstring", ""), n.get("decorators", ""), n.get("type_parameters", ""),
                    )
                    for n in batch
                ])
            self._db.commit()

    def get_graph_nodes(self, task_id: str, kind: str = None) -> List[Dict]:
        if kind:
            rows = self._db.execute(
                "SELECT * FROM graph_node WHERE task_id = ? AND kind = ?",
                (task_id, kind),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM graph_node WHERE task_id = ?",
                (task_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def count_graph_nodes(self, task_id: str, kind: str = None) -> int:
        if kind:
            row = self._db.execute(
                "SELECT COUNT(*) AS cnt FROM graph_node WHERE task_id = ? AND kind = ?",
                (task_id, kind),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT COUNT(*) AS cnt FROM graph_node WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return row["cnt"] if row else 0

    # ==================== graph_edge (v2 新表) ====================

    def bulk_insert_edges(self, edges: List[Dict]):
        """批量插入关系边"""
        if not edges:
            return
        with self._db._lock:
            db = self._db.conn
            for i in range(0, len(edges), BATCH_INSERT_SIZE):
                batch = edges[i:i + BATCH_INSERT_SIZE]
                db.executemany("""
                    INSERT OR REPLACE INTO graph_edge (
                        id, task_id, source_id, target_id, kind, provenance,
                        line, col, file_path, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, [
                    (
                        e["id"], e["task_id"], e["source_id"], e["target_id"],
                        e["kind"], e.get("provenance", "parser"),
                        e.get("line", 0), e.get("col", 0),
                        e.get("file_path", ""), e.get("metadata", ""),
                    )
                    for e in batch
                ])
            self._db.commit()

    def get_graph_edges(self, task_id: str, kind: str = None) -> List[Dict]:
        if kind:
            rows = self._db.execute(
                "SELECT * FROM graph_edge WHERE task_id = ? AND kind = ?",
                (task_id, kind),
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM graph_edge WHERE task_id = ?",
                (task_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ==================== 兼容旧 API ====================

    def get_symbols(self, task_id: str, symbol_type: str = None) -> List[Dict]:
        """兼容旧 API: 从 graph_node 查询，symbol_type → kind"""
        if symbol_type in ("call_relation", "dependence"):
            return self.get_graph_edges(task_id, "calls" if symbol_type == "call_relation" else "imports")
        return self.get_graph_nodes(task_id, symbol_type)

    def get_call_edges(self, task_id: str) -> List[Dict]:
        return self.get_graph_edges(task_id, "calls")

    def get_dep_edges(self, task_id: str) -> List[Dict]:
        return self.get_graph_edges(task_id, "imports")

    def count_by_task_and_type(self, task_id: str, symbol_type: str = None) -> int:
        if symbol_type in ("call_relation", "dependence"):
            return len(self.get_graph_edges(task_id, "calls" if symbol_type == "call_relation" else "imports"))
        return self.count_graph_nodes(task_id, symbol_type)

    # ==================== graph_doc ====================

    def delete_graph_doc_by_task(self, task_id: str):
        """删除指定任务的所有社区数据"""
        self._db.execute(
            "DELETE FROM graph_doc WHERE task_id = ?",
            (task_id,),
        )
        self._db.commit()

    def bulk_insert_communities(self, communities: List[Dict]):
        """批量插入社区分析结果"""
        db = self._db.conn
        for i in range(0, len(communities), BATCH_INSERT_SIZE):
            batch = communities[i:i + BATCH_INSERT_SIZE]
            db.executemany("""
                INSERT INTO graph_doc (
                    task_id, edge_type, comm_lv, parent_comm_id,
                    comm_id, node_list, node_count, file_count,
                    edge_list, edge_count, quality_score, description,
                    metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    c["task_id"], c["edge_type"], c["comm_lv"],
                    c.get("parent_comm_id"), c["comm_id"],
                    json.dumps(c["node_list"]) if isinstance(c["node_list"], list) else c["node_list"],
                    c["node_count"],
                    c.get("file_count", 0),
                    json.dumps(c["edge_list"]) if isinstance(c.get("edge_list"), list) else c.get("edge_list"),
                    c.get("edge_count", 0),
                    c.get("quality_score"),
                    c.get("description"),
                    c.get("metadata", "{}"),
                )
                for c in batch
            ])
        self._db.commit()

    def get_best_community(self, task_id: str, edge_type: str) -> Optional[Dict]:
        """获取 quality_score 最高的正常社区（排除 HUB/ORPHAN）"""
        row = self._db.execute("""
            SELECT * FROM graph_doc
            WHERE task_id = ? AND edge_type = ?
              AND comm_lv NOT IN ('HUB', 'ORPHAN')
            ORDER BY quality_score DESC
            LIMIT 1
        """, (task_id, edge_type)).fetchone()
        return dict(row) if row else None

    def get_communities(self, task_id: str, edge_type: str = None,
                        comm_lv: str = None) -> List[Dict]:
        conditions = ["task_id = ?"]
        params = [task_id]
        if edge_type:
            conditions.append("edge_type = ?")
            params.append(edge_type)
        if comm_lv:
            conditions.append("comm_lv = ?")
            params.append(comm_lv)
        where = " AND ".join(conditions)
        rows = self._db.execute(
            f"SELECT * FROM graph_doc WHERE {where} ORDER BY quality_score DESC",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def count_communities(self, task_id: str, edge_type: str = None) -> int:
        if edge_type:
            row = self._db.execute(
                "SELECT COUNT(*) AS cnt FROM graph_doc "
                "WHERE task_id = ? AND edge_type = ?",
                (task_id, edge_type),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT COUNT(*) AS cnt FROM graph_doc WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return row["cnt"]

    # ==================== community_hierarchy ====================

    def delete_hierarchy_by_task(self, task_id: str):
        self._db.execute(
            "DELETE FROM community_hierarchy WHERE task_id = ?",
            (task_id,),
        )
        self._db.commit()

    def bulk_insert_hierarchy(self, hierarchies: List[Dict]):
        db = self._db.conn
        for i in range(0, len(hierarchies), BATCH_INSERT_SIZE):
            batch = hierarchies[i:i + BATCH_INSERT_SIZE]
            db.executemany("""
                INSERT INTO community_hierarchy (
                    task_id, edge_type, comm_lv, comm_id,
                    parent_comm_id, node_count, file_count, edge_count, quality_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    h["task_id"], h["edge_type"], h["comm_lv"],
                    h["comm_id"], h.get("parent_comm_id"),
                    h.get("node_count"), h.get("file_count", 0),
                    h.get("edge_count", 0),
                    h.get("quality_score"),
                )
                for h in batch
            ])
        self._db.commit()

    def delete_communities(self, task_id: str, edge_type: str, comm_ids: List[str]):
        """批量删除指定社区（从 graph_doc + community_hierarchy）"""
        if not comm_ids:
            return
        placeholders = ",".join("?" * len(comm_ids))
        params = [task_id, edge_type] + comm_ids
        self._db.execute(
            f"DELETE FROM graph_doc WHERE task_id=? AND edge_type=? AND comm_id IN ({placeholders})",
            params,
        )
        self._db.execute(
            f"DELETE FROM community_hierarchy WHERE task_id=? AND edge_type=? AND comm_id IN ({placeholders})",
            params,
        )
        self._db.commit()
        logger.info(f"[AnalysisStore] delete_communities: task_id={task_id} edge_type={edge_type} count={len(comm_ids)}")

    def delete_community_llm_results(self, task_id: str, edge_type: str, comm_ids: List[str]):
        """批量删除社区的 LLM 分析结果"""
        if not comm_ids:
            return
        placeholders = ",".join("?" * len(comm_ids))
        self._db.execute(
            f"DELETE FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_id IN ({placeholders})",
            [task_id, edge_type] + comm_ids,
        )
        self._db.commit()
        logger.info(f"[AnalysisStore] delete_community_llm_results: task_id={task_id} edge_type={edge_type} count={len(comm_ids)}")

    # ==================== 清理 ====================

    def clear_task_data(self, task_id: str):
        """清理指定任务的所有分析数据（重运行时调用）"""
        with self._db._lock:
            self._db.execute(
                "DELETE FROM graph_node WHERE task_id = ?", (task_id,)
            )
            self._db.execute(
                "DELETE FROM graph_edge WHERE task_id = ?", (task_id,)
            )
            self._db.execute(
                "DELETE FROM graph_doc WHERE task_id = ?", (task_id,)
            )
            self._db.execute(
                "DELETE FROM community_hierarchy WHERE task_id = ?", (task_id,)
            )
            self._db.execute(
                "DELETE FROM community_llm_results WHERE task_id = ?", (task_id,)
            )
            self._db.execute(
                "DELETE FROM component_analysis WHERE task_id = ?", (task_id,)
            )
            self._db.commit()
        logger.info(f"[AnalysisStore] clear_task_data: task_id={task_id}")

    def clear_communities_for_task(self, task_id: str, edge_type: str):
        """
        清理指定任务和边类型的社区数据（备选方案切换时调用）
        只清除 graph_doc 和 community_hierarchy 中对应 edge_type 的数据
        """
        self._db.execute(
            "DELETE FROM graph_doc WHERE task_id = ? AND edge_type = ?",
            (task_id, edge_type)
        )
        self._db.execute(
            "DELETE FROM community_hierarchy WHERE task_id = ? AND edge_type = ?",
            (task_id, edge_type)
        )
        if edge_type:
            self._db.execute(
                "DELETE FROM community_llm_results WHERE task_id = ? AND edge_type = ?",
                (task_id, edge_type)
            )
        else:
            self._db.execute(
                "DELETE FROM community_llm_results WHERE task_id = ?", (task_id,)
            )
        self._db.commit()
        logger.info(
            f"[AnalysisStore] clear_communities_for_task: task_id={task_id}, edge_type={edge_type}"
        )

    def bulk_insert_llm_results(self, results: List[Dict]):
        from plantuml_service import validate_mermaid, validate_plantuml
        db = self._db.conn
        logger.info("[AnalysisStore] bulk_insert_llm_results ENTRY count=%d first=%s",
                     len(results), results[0].get('comm_id') if results else 'none')
        insert_rows = []
        for r in results:
            mermaid = r.get("mermaid")
            plantuml = r.get("plantuml")
            if mermaid and not validate_mermaid(mermaid):
                logger.warning("[AnalysisStore] mermaid validation failed for comm_id=%s comm_lv=%s len=%d",
                               r.get("comm_id"), r.get("comm_lv"), len(mermaid))
            if plantuml and not validate_plantuml(plantuml):
                logger.warning("[AnalysisStore] plantuml validation failed for comm_id=%s comm_lv=%s len=%d",
                               r.get("comm_id"), r.get("comm_lv"), len(plantuml))
            insert_rows.append((
                r["task_id"], r["edge_type"], r["comm_lv"], r["comm_id"],
                r.get("name"), r.get("summary"),
                mermaid if validate_mermaid(mermaid) else None,
                plantuml if validate_plantuml(plantuml) else None,
                r.get("model_id"), r.get("template_id"),
            ))
        db.executemany("""
            INSERT OR REPLACE INTO community_llm_results
                (task_id, edge_type, comm_lv, comm_id, name, summary, mermaid, plantuml, model_id, template_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, insert_rows)
        self._db.commit()
        logger.info("[AnalysisStore] bulk_insert_llm_results DONE count=%d", len(results))

    def list_llm_results(self, task_id: str, edge_type: str) -> List[Dict]:
        logger.info("[AnalysisStore] list_llm_results ENTRY task_id=%s edge_type=%s", task_id, edge_type)
        rows = self._db.execute(
            "SELECT * FROM community_llm_results WHERE task_id=? AND edge_type=? ORDER BY comm_lv, comm_id",
            (task_id, edge_type)
        ).fetchall()
        logger.info("[AnalysisStore] list_llm_results DONE task_id=%s edge_type=%s rows=%d", task_id, edge_type, len(rows))
        return [dict(r) for r in rows]

    def get_llm_result(self, task_id: str, edge_type: str, comm_lv: str, comm_id: str) -> Optional[Dict]:
        logger.info("[AnalysisStore] get_llm_result task_id=%s edge_type=%s comm_lv=%s comm_id=%s", task_id, edge_type, comm_lv, comm_id)
        row = self._db.execute(
            "SELECT * FROM community_llm_results WHERE task_id=? AND edge_type=? AND comm_lv=? AND comm_id=?",
            (task_id, edge_type, comm_lv, comm_id)
        ).fetchone()
        logger.info("[AnalysisStore] get_llm_result found=%s", row is not None)
        return dict(row) if row else None

    def update_community_name(self, task_id: str, edge_type: str, comm_lv: str, comm_id: str, name: str):
        self._db.execute(
            "UPDATE community_llm_results SET name_manual=?, updated_at=datetime('now') WHERE task_id=? AND edge_type=? AND comm_lv=? AND comm_id=?",
            (name, task_id, edge_type, comm_lv, comm_id)
        )
        self._db.commit()

    def save_component_analysis(self, result: Dict):
        self._db.execute(
            """INSERT OR REPLACE INTO component_analysis
               (task_id, component_id, component_type, analyzed_name, functional_summary, status, analyzed_at)
               VALUES (?, ?, ?, ?, ?, ?, datetime('now'))""",
            (result["task_id"], result["component_id"], result.get("component_type", "community"),
             result.get("analyzed_name"), result.get("functional_summary"),
             result.get("status", "completed"))
        )
        self._db.commit()

    def list_component_analysis(self, task_id: str, component_ids: List[str] = None) -> List[Dict]:
        if component_ids:
            placeholders = ','.join('?' * len(component_ids))
            rows = self._db.execute(
                f"SELECT * FROM component_analysis WHERE task_id=? AND component_id IN ({placeholders})",
                [task_id] + component_ids
            ).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM component_analysis WHERE task_id=?",
                (task_id,)
            ).fetchall()
        return [dict(r) for r in rows]

    def get_component_analysis(self, task_id: str, component_id: str) -> Optional[Dict]:
        row = self._db.execute(
            "SELECT * FROM component_analysis WHERE task_id=? AND component_id=?",
            (task_id, component_id)
        ).fetchone()
        return dict(row) if row else None

    # ── Agent 任务历史 ──

    def save_agent_task_history(self, record: Dict):
        self._db.execute(
            """INSERT OR REPLACE INTO agent_task_history
               (project_id, task_id, agent_id, action, status, steps, message, error, created_at, finished_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record.get("project_id", ""), record["task_id"], record["agent_id"],
             record.get("action", ""), record.get("status", "unknown"),
             record.get("steps"), record.get("message"),
             record.get("error"), record.get("created_at"), record.get("finished_at"))
        )
        self._db.commit()

    def list_agent_task_history(self, task_id: str, offset: int = 0, limit: int = 10) -> Dict:
        total = self._db.execute(
            "SELECT COUNT(*) as cnt FROM agent_task_history WHERE task_id=?",
            (task_id,)
        ).fetchone()["cnt"]
        rows = self._db.execute(
            "SELECT * FROM agent_task_history WHERE task_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (task_id, limit, offset)
        ).fetchall()
        return {"results": [dict(r) for r in rows], "total": total}

    def clear_agent_task_history(self, project_id: str, task_id: str):
        self._db.execute(
            "DELETE FROM agent_task_history WHERE project_id=? AND task_id=? "
            "AND status NOT IN ('running', 'queued')",
            (project_id, task_id)
        )
        self._db.commit()
