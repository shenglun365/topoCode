"""
数据库适配层 — 将 MongoDB 接口映射到 SQLite store

原始代码使用 MongoDB (base_node, graph_node, proj_info 集合)，
当前系统使用 SQLite 项目库 (通过 AnalysisStore)。

本模块提供统一的接口，让移植的提取器代码最小改动。
"""
import logging
from typing import List, Dict, Optional, Any

logger = logging.getLogger(__name__)


class SQLiteAdapter:
    """
    SQLite 适配层，模拟 MongoDB 集合的常用操作

    用法:
        adapter = SQLiteAdapter(project_db, task_id)
        adapter.insert_nodes(nodes)       # → base_node
        adapter.find_nodes(file_id=X)     # → base_node.find
        adapter.insert_graph(records)     # → graph_node
        adapter.find_graph(task_id=X)     # → graph_node.find
        adapter.list_files()              # → source_files
    """

    def __init__(self, project_db, task_id: str):
        """
        Args:
            project_db: SQLiteContext (项目库连接)
            task_id: 分析任务 ID
        """
        from store.analysis_store import AnalysisStore
        self._store = AnalysisStore(project_db)
        self._task_id = task_id

    # ==================== base_node (AST 节点, v2 已废弃) ====================

    def insert_nodes(self, nodes: List[Dict]):
        pass  # v2: base_node 已废弃

    def find_nodes(self, file_id: str = None, node_type: str = None) -> List[Dict]:
        return []  # v2: base_node 已废弃

    def count_nodes(self, file_id: str = None) -> int:
        return 0  # v2: base_node 已废弃

    def delete_nodes_by_file(self, file_id: str):
        pass  # v2: base_node 已废弃

    # ==================== graph_node (v2 新 API) ====================

    def insert_graph(self, records: List[Dict]):
        """批量插入图数据 → graph_node / graph_edge"""
        if not records:
            return
        for r in records:
            r.setdefault('task_id', self._task_id)
        # 按 symbol_node_type 区分节点/边
        nodes = [r for r in records if r.get('symbol_node_type') not in ('call_relation', 'dependence')]
        edges = [r for r in records if r.get('symbol_node_type') in ('call_relation', 'dependence')]
        if nodes:
            self._store.bulk_insert_graph_nodes(nodes)
        if edges:
            edge_rows = []
            for e in edges:
                edge_rows.append({
                    "id": _make_edge_id(e.get("caller_file_id", ""), e.get("callee_name", ""), e.get("symbol_node_type")),
                    "task_id": e["task_id"],
                    "source_id": e.get("caller_file_id", ""),
                    "target_id": e.get("callee_file_id", ""),
                    "kind": "calls" if e["symbol_node_type"] == "call_relation" else "imports",
                    "provenance": "parser",
                    "file_path": e.get("file_id", ""),
                })
            self._store.bulk_insert_edges(edge_rows)

    def find_graph(self, symbol_node_type: str = None) -> List[Dict]:
        if symbol_node_type in ('call_relation',):
            return self._store.get_graph_edges(self._task_id, "calls")
        if symbol_node_type in ('dependence',):
            return self._store.get_graph_edges(self._task_id, "imports")
        return self._store.get_graph_nodes(self._task_id, symbol_node_type)

    def delete_graph_by_task(self):
        self._store._db.execute("DELETE FROM graph_node WHERE task_id = ?", (self._task_id,))
        self._store._db.execute("DELETE FROM graph_edge WHERE task_id = ?", (self._task_id,))

    # ==================== source_files (文件列表) ====================

    def list_files(self, language: str = None,
                   exclude_extensions: List[str] = None) -> List[Dict]:
        """
        获取文件列表 → source_files

        Returns:
            每个元素: {id, file_path, file_name, language, size, hashcode, mtime}
        """
        files = self._store.list_source_files()
        if language:
            files = [f for f in files if f.get('language') == language]
        if exclude_extensions:
            import os
            files = [f for f in files
                     if os.path.splitext(f.get('file_path', ''))[1] not in exclude_extensions]
        return files

    def get_file_by_id(self, file_id: str) -> Optional[Dict]:
        """按 ID 获取文件"""
        return self._store.get_file_by_id(file_id)

    def get_file_by_path(self, file_path: str) -> Optional[Dict]:
        """按路径获取文件"""
        return self._store.get_file_by_path(file_path)

    # ==================== 社区分析 ====================

    def insert_communities(self, communities: List[Dict]):
        """批量插入社区数据 → graph_doc"""
        if not communities:
            return
        for c in communities:
            c.setdefault('task_id', self._task_id)
        self._store.bulk_insert_communities(communities)

    def insert_hierarchy(self, hierarchies: List[Dict]):
        """批量插入社区层级 → community_hierarchy"""
        if not hierarchies:
            return
        for h in hierarchies:
            h.setdefault('task_id', self._task_id)
        self._store.bulk_insert_hierarchy(hierarchies)

    def get_communities(self, edge_type: str = None) -> List[Dict]:
        """获取社区数据"""
        return self._store.get_communities(self._task_id, edge_type)

    def get_best_community(self, edge_type: str) -> Optional[Dict]:
        """获取最佳社区"""
        return self._store.get_best_community(self._task_id, edge_type)

    # ==================== 清理 ====================

    def clear_all(self):
        """清理任务的所有数据"""
        self._store.clear_task_data(self._task_id)


def _make_edge_id(source: str, target: str, kind: str) -> str:
    import hashlib
    raw = f"{source}->{target}:{kind}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
