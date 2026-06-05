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

    # ==================== base_node (AST 节点) ====================

    def insert_nodes(self, nodes: List[Dict]):
        """批量插入 AST 节点 → base_node"""
        if not nodes:
            return
        self._store.bulk_insert_nodes(nodes)
        logger.debug(f"Inserted {len(nodes)} nodes to base_node")

    def find_nodes(self, file_id: str = None, node_type: str = None) -> List[Dict]:
        """查询 AST 节点"""
        import json

        def _deserialize(node: Dict) -> Dict:
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

        if file_id:
            return self._store.get_nodes_by_file(file_id)
        elif node_type:
            return self._store.get_nodes_by_type(node_type)
        else:
            # 返回所有节点 — 通过 SQL 直接查询
            cursor = self._store._db.execute("SELECT * FROM base_node")
            columns = [desc[0] for desc in cursor.description]
            return [_deserialize(dict(zip(columns, row))) for row in cursor.fetchall()]

    def count_nodes(self, file_id: str = None) -> int:
        """统计 AST 节点数"""
        return self._store.count_nodes(file_id)

    def delete_nodes_by_file(self, file_id: str):
        """删除指定文件的 AST 节点"""
        self._store.delete_nodes_by_file(file_id)

    # ==================== graph_node (符号/调用边/依赖边) ====================

    def insert_graph(self, records: List[Dict]):
        """批量插入图数据 → graph_node"""
        if not records:
            return
        # 确保每条记录都有 task_id
        for r in records:
            r.setdefault('task_id', self._task_id)
        self._store.bulk_insert_graph_nodes(records)
        logger.debug(f"Inserted {len(records)} records to graph_node")

    def find_graph(self, symbol_node_type: str = None,
                   caller_file_id: str = None,
                   callee_name: str = None) -> List[Dict]:
        """查询图数据"""
        if symbol_node_type in ('function', 'class', 'macro', 'method'):
            return self._store.get_symbols(self._task_id, symbol_node_type)
        elif symbol_node_type == 'call_relation':
            return self._store.get_call_edges(self._task_id)
        elif symbol_node_type == 'dependence':
            return self._store.get_dep_edges(self._task_id)
        else:
            # 通用查询
            query = "SELECT * FROM graph_node WHERE task_id = ?"
            params: List[Any] = [self._task_id]
            if symbol_node_type:
                query += " AND symbol_node_type = ?"
                params.append(symbol_node_type)
            cursor = self._store._db.execute(query, params)
            columns = [desc[0] for desc in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def delete_graph_by_task(self):
        """删除任务的所有图数据"""
        self._store.delete_by_task(self._task_id)

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
