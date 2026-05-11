"""
SymbolExtractor — 通用符号提取器基类
"""
from typing import List, Dict


class BaseSymbolExtractor:
    """
    通用符号提取器 — 从 AST 节点中提取符号

    子类覆盖 SYMBOL_NODE_TYPES 来指定要提取的节点类型。
    """

    # 子类覆盖: 要提取的 AST 节点类型 → 符号类型映射
    SYMBOL_NODE_TYPES: Dict[str, str] = {}

    def extract(self, task_id: str, analysis_store) -> List[Dict]:
        """从 base_node 表中提取符号"""
        symbols = []

        for ast_type, symbol_type in self.SYMBOL_NODE_TYPES.items():
            nodes = analysis_store.get_nodes_by_type(ast_type)
            for node in nodes:
                symbols.append({
                    "task_id": task_id,
                    "symbol_node_type": symbol_type,
                    "file_id": node["file_id"],
                    "func_name": node["name"] if symbol_type == "function" else None,
                    "class_name": node["name"] if symbol_type == "class" else None,
                    "macro_name": node["name"] if symbol_type == "macro" else None,
                    "method_name": node["name"] if symbol_type == "method" else None,
                })

        if symbols:
            analysis_store.bulk_insert_graph_nodes(symbols)

        return symbols
