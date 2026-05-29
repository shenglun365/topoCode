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

    # ==================== source_files ====================

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

    def delete_nodes_by_file(self, file_id: str):
        """删除指定文件的所有 AST 节点"""
        self._db.execute(
            "DELETE FROM base_node WHERE file_id = ?",
            (file_id,),
        )

    def bulk_insert_nodes(self, nodes: List[Dict]):
        """批量插入 AST 节点"""
        db = self._db.conn
        for i in range(0, len(nodes), BATCH_INSERT_SIZE):
            batch = nodes[i:i + BATCH_INSERT_SIZE]
            db.executemany("""
                INSERT INTO base_node (
                    file_id, node_id, scope_node_id, def_node_id,
                    type, name, op, refs, start, end, content_size
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    n["file_id"], n["node_id"], n.get("scope_node_id"),
                    n.get("def_node_id"), n["type"], n.get("name"),
                    n.get("op"),
                    json.dumps(n["refs"]) if isinstance(n.get("refs"), list) else n.get("refs"),
                    n["start"], n["end"], n.get("content_size"),
                )
                for n in batch
            ])
        self._db.commit()

    def get_nodes_by_file(self, file_id: str) -> List[Dict]:
        rows = self._db.execute(
            "SELECT * FROM base_node WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        return [_deserialize_node(dict(r)) for r in rows]

    def get_nodes_by_type(self, node_type: str) -> List[Dict]:
        rows = self._db.execute(
            "SELECT * FROM base_node WHERE type = ?",
            (node_type,),
        ).fetchall()
        return [_deserialize_node(dict(r)) for r in rows]

    def count_nodes(self, file_id: str = None) -> int:
        if file_id:
            row = self._db.execute(
                "SELECT COUNT(*) AS cnt FROM base_node WHERE file_id = ?",
                (file_id,),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT COUNT(*) AS cnt FROM base_node"
            ).fetchone()
        return row["cnt"]

    # ==================== graph_node ====================

    def delete_by_task(self, task_id: str):
        """删除指定任务的所有图节点"""
        self._db.execute(
            "DELETE FROM graph_node WHERE task_id = ?",
            (task_id,),
        )

    def delete_by_task_and_type(self, task_id: str, symbol_type: str):
        self._db.execute(
            "DELETE FROM graph_node WHERE task_id = ? AND symbol_node_type = ?",
            (task_id, symbol_type),
        )

    def bulk_insert_graph_nodes(self, nodes: List[Dict]):
        """批量插入图节点"""
        if not nodes:
            return
        # 统计各类型数量
        type_counts: Dict[str, int] = {}
        task_ids = set()
        for n in nodes:
            t = n.get("symbol_node_type", "unknown")
            type_counts[t] = type_counts.get(t, 0) + 1
            task_ids.add(n.get("task_id", ""))

        db = self._db.conn
        for i in range(0, len(nodes), BATCH_INSERT_SIZE):
            batch = nodes[i:i + BATCH_INSERT_SIZE]
            db.executemany("""
                INSERT INTO graph_node (
                    task_id, symbol_node_type, file_id,
                    func_name, class_name, macro_name, method_name,
                    caller_file_id, caller_func_name, caller_node_id,
                    callee_name, callee_file_id, callee_node_id, callee_type,
                    call_site_node_id, call_site_file_id,
                    include_path, is_system, extra
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    n["task_id"], n["symbol_node_type"], n.get("file_id"),
                    n.get("func_name"), n.get("class_name"),
                    n.get("macro_name"), n.get("method_name"),
                    n.get("caller_file_id"), n.get("caller_func_name"),
                    n.get("caller_node_id"), n.get("callee_name"),
                    n.get("callee_file_id"), n.get("callee_node_id"),
                    n.get("callee_type"), n.get("call_site_node_id"),
                    n.get("call_site_file_id"), n.get("include_path"),
                    n.get("is_system", 0),
                    json.dumps(n["extra"]) if isinstance(n.get("extra"), dict) else n.get("extra"),
                )
                for n in batch
            ])
        self._db.commit()
        logger.info(f"[AnalysisStore] bulk_insert_graph_nodes: task_id={list(task_ids)}, total={len(nodes)}, types={type_counts}")

    def get_symbols(self, task_id: str, symbol_type: str = None) -> List[Dict]:
        conditions = ["task_id = ?"]
        params = [task_id]
        if symbol_type:
            conditions.append("symbol_node_type = ?")
            params.append(symbol_type)
        where = " AND ".join(conditions)
        rows = self._db.execute(
            f"SELECT * FROM graph_node WHERE {where}",
            params,
        ).fetchall()
        result = [dict(r) for r in rows]
        logger.info(f"[AnalysisStore] get_symbols: task_id={task_id}, type={symbol_type}, returned={len(result)}")
        return result

    def get_call_edges(self, task_id: str) -> List[Dict]:
        return self.get_symbols(task_id, "call_relation")

    def get_dep_edges(self, task_id: str) -> List[Dict]:
        return self.get_symbols(task_id, "dependence")

    def count_by_task_and_type(self, task_id: str, symbol_type: str = None) -> int:
        if symbol_type:
            row = self._db.execute(
                "SELECT COUNT(*) AS cnt FROM graph_node "
                "WHERE task_id = ? AND symbol_node_type = ?",
                (task_id, symbol_type),
            ).fetchone()
        else:
            row = self._db.execute(
                "SELECT COUNT(*) AS cnt FROM graph_node WHERE task_id = ?",
                (task_id,),
            ).fetchone()
        return row["cnt"]

    # ==================== graph_doc ====================

    def delete_graph_doc_by_task(self, task_id: str):
        """删除指定任务的所有社区数据"""
        self._db.execute(
            "DELETE FROM graph_doc WHERE task_id = ?",
            (task_id,),
        )

    def bulk_insert_communities(self, communities: List[Dict]):
        """批量插入社区分析结果"""
        db = self._db.conn
        for i in range(0, len(communities), BATCH_INSERT_SIZE):
            batch = communities[i:i + BATCH_INSERT_SIZE]
            db.executemany("""
                INSERT INTO graph_doc (
                    task_id, edge_type, comm_lv, parent_comm_id,
                    comm_id, node_list, node_count,
                    edge_list, edge_count, quality_score, description
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    c["task_id"], c["edge_type"], c["comm_lv"],
                    c.get("parent_comm_id"), c["comm_id"],
                    json.dumps(c["node_list"]) if isinstance(c["node_list"], list) else c["node_list"],
                    c["node_count"],
                    json.dumps(c["edge_list"]) if isinstance(c.get("edge_list"), list) else c.get("edge_list"),
                    c.get("edge_count", 0),
                    c.get("quality_score"),
                    c.get("description"),
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

    def bulk_insert_hierarchy(self, hierarchies: List[Dict]):
        db = self._db.conn
        for i in range(0, len(hierarchies), BATCH_INSERT_SIZE):
            batch = hierarchies[i:i + BATCH_INSERT_SIZE]
            db.executemany("""
                INSERT INTO community_hierarchy (
                    task_id, edge_type, comm_lv, comm_id,
                    parent_comm_id, node_count, edge_count, quality_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    h["task_id"], h["edge_type"], h["comm_lv"],
                    h["comm_id"], h.get("parent_comm_id"),
                    h.get("node_count"), h.get("edge_count", 0),
                    h.get("quality_score"),
                )
                for h in batch
            ])
        self._db.commit()

    # ==================== 清理 ====================

    def clear_task_data(self, task_id: str):
        """清理指定任务的所有分析数据（重运行时调用）"""
        self._db.execute(
            "DELETE FROM graph_node WHERE task_id = ?", (task_id,)
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
