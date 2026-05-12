"""
DependencyExtractor — 通用依赖图提取器基类
"""
from typing import List, Dict


class BaseDependencyExtractor:
    """
    通用依赖图提取器 — 从 AST 节点中提取文件级依赖关系

    子类覆盖 INCLUDE_NODE_TYPE 来指定导入/包含节点的 AST 类型。
    """

    # 子类覆盖: 导入/包含节点的 AST 类型
    INCLUDE_NODE_TYPE: str = "include_directive"

    def extract(self, task_id: str, analysis_store) -> List[Dict]:
        """从 base_node 表中提取依赖关系"""
        include_nodes = analysis_store.get_nodes_by_type(self.INCLUDE_NODE_TYPE)
        edges = []

        for inc in include_nodes:
            include_path = inc.get("name", "")
            edges.append({
                "task_id": task_id,
                "symbol_node_type": "dependence",
                "file_id": inc.get("file_id"),
                "include_path": include_path,
                "is_system": 1 if self._is_system_include(include_path) else 0,
            })

        if edges:
            analysis_store.bulk_insert_graph_nodes(edges)

        return edges

    def _is_system_include(self, path: str) -> bool:
        """判断是否为系统头文件"""
        if not path:
            return False
        return path.startswith("<") or path.startswith("/")
