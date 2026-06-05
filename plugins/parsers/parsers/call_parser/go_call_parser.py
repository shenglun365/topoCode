# parsers/languages/call_parser/go_call_parser.py
"""
Go 调用图提取器

实现 Go 语言的函数/方法调用识别和提取逻辑。

支持的调用语法:
- 函数调用：func()
- 方法调用：obj.Method()
- 包函数调用：pkg.Func()
- Goroutine 调用：go func()
- 延迟调用：defer func()
"""
from typing import Dict, Any, Optional, List
from .extractor_factory import CallGraphExtractor, register_call_extractor


@register_call_extractor('go')
class GoCallExtractor(CallGraphExtractor):
    """Go 函数/方法调用提取器"""
    
    CALL_EXPRESSION_TYPES = {'call_expression', 'go_statement', 'defer_statement'}
    FUNCTION_DEFINITION_TYPES = {'function_declaration', 'method_declaration'}
    
    def extract(self, proj_id: int, nodes_by_file: Dict[str, Dict[str, Dict]]) -> List[Dict[str, Any]]:
        
        
        func_map = self._build_global_function_map_from_ast(nodes_by_file)
        
        call_edges = []
        for file_id, nodes in nodes_by_file.items():
            file_edges = self._extract_file_calls(proj_id, file_id, nodes, func_map)
            call_edges.extend(file_edges)
        
        return call_edges
    
    def _build_global_function_map_from_ast(self, nodes_by_file: Dict[int, Dict[int, Dict]]) -> Dict[str, Dict]:
        """从 AST 节点中构建全局函数映射（不依赖数据库）"""
        func_map = {}
        for file_id, nodes in nodes_by_file.items():
            for node_id, node in nodes.items():
                node_type = node.get("type", "")
                if node_type in self.FUNCTION_DEFINITION_TYPES:
                    func_name = self.extract_function_name(node, nodes)
                    if func_name:
                        func_map[func_name] = {"file_id": file_id, "node_id": node_id}
        return func_map
    
    def _extract_file_calls(self, proj_id: int, file_id: int, nodes: Dict[int, Dict], func_map: Dict[str, Dict]) -> List[Dict[str, Any]]:
        call_edges = []
        for node in nodes.values():
            if not self.is_call_expression(node):
                continue
            
            callee_name = self.extract_callee_name(node, nodes)
            if not callee_name:
                continue
            
            caller_func_node = self.find_enclosing_function(node, nodes)
            if not caller_func_node:
                continue
            
            caller_name = self.extract_function_name(caller_func_node, nodes)
            if not caller_name:
                continue
            
            edge = {
                "proj_id": proj_id,
                "symbol_node_type": "call_relation",
                "caller_file_id": file_id,
                "caller_func_name": caller_name,
                "caller_node_id": caller_func_node["node_id"],
                "callee_name": callee_name,
                "call_site_node_id": node["node_id"],
                "call_site_file_id": file_id,
            }
            
            if callee_name in func_map:
                callee_info = func_map[callee_name]
                edge.update({
                    "callee_file_id": callee_info["file_id"],
                    "callee_node_id": callee_info["node_id"],
                    "callee_type": "function"
                })
            else:
                edge.update({
                    "callee_file_id": None,
                    "callee_node_id": None,
                    "callee_type": "external_or_unknown"
                })
            
            call_edges.append(edge)
        
        return call_edges
    
    def is_call_expression(self, node: Dict) -> bool:
        return node.get("type") in self.CALL_EXPRESSION_TYPES
    
    def extract_callee_name(self, call_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        # 策略1: 直接 name 字段（AST 解析器可能已提取）
        name = call_node.get("name")
        if isinstance(name, str) and name.strip():
            # name 可能是 "fmt.Println"，取最后一段
            return name.split(".")[-1]
        # 策略2: 从 refs 中提取 — 取最后一个非空 ref（通常是函数名）
        refs = call_node.get("refs", [])
        if refs:
            # refs 可能是 ["fmt", "Println"]，取最后一个
            for ref in reversed(refs):
                if isinstance(ref, str) and ref.strip():
                    return ref.split(".")[-1]
        return None
    
    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        scope = node.get("scope_node_id")
        while scope is not None and scope != 1 and scope in all_nodes:
            parent_node = all_nodes[scope]
            if parent_node.get("type") in self.FUNCTION_DEFINITION_TYPES:
                return parent_node
            scope = parent_node.get("scope_node_id")
        return None
    
    def extract_function_name(self, func_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        # 策略1: 直接 name 字段
        name = func_node.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
        # 策略2: 从 refs 中提取
        refs = func_node.get("refs", [])
        if refs:
            for ref in refs:
                if isinstance(ref, str) and ref.strip():
                    return ref.strip()
        return None
