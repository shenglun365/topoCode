"""
AnalysisStore — 项目库 CRUD 操作

管理 source_files, base_node, graph_node, graph_doc, community_hierarchy
"""
import json
from typing import Optional, List, Dict

from ..config import BATCH_INSERT_SIZE

from .connection import SQLiteContext


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

        Returns:
            [{"id", "file_path", "file_name", "language", "size", ...}, ...]
        """
        conditions = ["language != 'directory'"]
        params = []

        if scopes:
            or_clauses = " OR ".join(["file_path LIKE ?"] * len(scopes))
            conditions.append(f"({or_clauses})")
            params.extend([f"{s}%" if not s.endswith("%") else s for s in scopes])

        if extensions:
            ext_clauses = " OR ".join(["language = ?"] * len(extensions))
            conditions.append(f"({ext_clauses})")
            params.extend(extensions)

        if exclude_dirs:
            for d in exclude_dirs:
                conditions.append("file_path NOT LIKE ?")
                params.append(f"%{d}%")

        where = " AND ".join(conditions) if conditions else "1=1"
        rows = self._db.execute(
            f"SELECT * FROM source_files WHERE {where}",
            params,
        ).fetchall()
        return [dict(r) for r in rows]

    def get_file_by_path(self, file_path: str) -> Optional[Dict]:
        row = self._db.execute(
            "SELECT * FROM source_files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return dict(row) if row else None

    def get_file_by_id(self, file_id: int) -> Optional[Dict]:
        row = self._db.execute(
            "SELECT * FROM source_files WHERE id = ?",
            (file_id,),
        ).fetchone()
        return dict(row) if row else None

    # ==================== base_node ====================

    def delete_nodes_by_file(self, file_id: int):
        """删除指定文件的所有 AST 节点"""
        self._db.execute(
            "DELETE FROM base_node WHERE file_id = ?",
            (file_id,),
        )
        self._db.commit()

    def bulk_insert_nodes(self, nodes: List[Dict]):
        """批量插入 AST 节点"""
        db = self._db.connect()
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

    def get_nodes_by_file(self, file_id: int) -> List[Dict]:
        rows = self._db.execute(
            "SELECT * FROM base_node WHERE file_id = ?",
            (file_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_nodes_by_type(self, node_type: str) -> List[Dict]:
        rows = self._db.execute(
            "SELECT * FROM base_node WHERE type = ?",
            (node_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_nodes(self, file_id: int = None) -> int:
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
        self._db.commit()

    def delete_by_task_and_type(self, task_id: str, symbol_type: str):
        self._db.execute(
            "DELETE FROM graph_node WHERE task_id = ? AND symbol_node_type = ?",
            (task_id, symbol_type),
        )
        self._db.commit()

    def bulk_insert_graph_nodes(self, nodes: List[Dict]):
        """批量插入图节点"""
        db = self._db.connect()
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
        return [dict(r) for r in rows]

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

    def delete_by_task(self, task_id: str):
        """删除指定任务的所有社区数据"""
        self._db.execute(
            "DELETE FROM graph_doc WHERE task_id = ?",
            (task_id,),
        )
        self._db.commit()

    def bulk_insert_communities(self, communities: List[Dict]):
        """批量插入社区分析结果"""
        db = self._db.connect()
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
        """获取 quality_score 最高的社区"""
        row = self._db.execute("""
            SELECT * FROM graph_doc
            WHERE task_id = ? AND edge_type = ?
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
        db = self._db.connect()
        for i in range(0, len(hierarchies), BATCH_INSERT_SIZE):
            batch = hierarchies[i:i + BATCH_INSERT_SIZE]
            db.executemany("""
                INSERT INTO community_hierarchy (
                    task_id, edge_type, comm_lv, comm_id,
                    parent_comm_id, node_count, quality_score
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, [
                (
                    h["task_id"], h["edge_type"], h["comm_lv"],
                    h["comm_id"], h.get("parent_comm_id"),
                    h.get("node_count"), h.get("quality_score"),
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
        self._db.commit()
