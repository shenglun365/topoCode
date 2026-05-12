"""
CallGraphExtractor — 通用调用图提取器基类
"""
from typing import List, Dict


class BaseCallGraphExtractor:
    """
    通用调用图提取器 — 从 AST 节点中提取函数调用关系

    子类覆盖 CALL_EXPR_TYPE 来指定调用表达式的节点类型。
    """

    # 子类覆盖: 调用表达式的 AST 节点类型
    CALL_EXPR_TYPE: str = "call_expression"

    def extract(self, task_id: str, analysis_store) -> List[Dict]:
        """从 base_node 表中提取调用关系"""
        call_nodes = analysis_store.get_nodes_by_type(self.CALL_EXPR_TYPE)
        edges = []

        # 构建函数名 → 节点映射
        func_map = {}
        for func in analysis_store.get_symbols(task_id, "function"):
            name = func.get("func_name")
            if name:
                func_map[name] = func

        for call in call_nodes:
            callee_name = call.get("name")
            if not callee_name:
                # 尝试从子节点找被调用函数名
                callee_name = self._resolve_callee_name(call, analysis_store)

            callee = func_map.get(callee_name, {})
            edges.append({
                "task_id": task_id,
                "symbol_node_type": "call_relation",
                "caller_file_id": call.get("file_id"),
                "caller_func_name": None,  # 需从 scope 推断
                "caller_node_id": call.get("node_id"),
                "callee_name": callee_name,
                "callee_file_id": callee.get("file_id"),
                "callee_node_id": callee.get("id"),
                "callee_type": "function" if callee else "external_or_unknown",
                "call_site_node_id": call.get("node_id"),
                "call_site_file_id": call.get("file_id"),
            })

        if edges:
            analysis_store.bulk_insert_graph_nodes(edges)

        return edges

    def _resolve_callee_name(self, call_node: Dict,
                             analysis_store) -> str:
        """解析被调用函数名"""
        # 默认返回节点名
        return call_node.get("name", "unknown") or "unknown"
