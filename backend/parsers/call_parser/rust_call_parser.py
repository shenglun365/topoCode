# parsers/languages/call_parser/rust_call_parser.py
"""
Rust 调用图提取器

实现 Rust 语言的函数/方法调用识别和提取逻辑。

支持的调用语法:
- 函数调用：func()
- 方法调用：obj.method()
- 关联函数调用：Type::method()
- 泛型调用：func::<T>()
- 闭包调用：closure()
- 宏调用：macro!()
"""
from typing import Dict, Any, Optional, List
from .extractor_factory import CallGraphExtractor, register_call_extractor


@register_call_extractor('rust')
class RustCallExtractor(CallGraphExtractor):
    """Rust 函数/方法调用提取器"""
    
    CALL_EXPRESSION_TYPES = {'call_expression', 'macro_invocation'}
    FUNCTION_DEFINITION_TYPES = {'function_item', 'method_declaration'}
    
    def extract(self, proj_id: int, nodes_by_file: Dict[int, Dict[int, Dict]]) -> List[Dict[str, Any]]:
        
        
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
        refs = call_node.get("refs", [])
        if refs and len(refs) > 0:
            name = refs[0]
            if name and len(name) > 0:  # 确保非空
                # 处理路径 (如 std::mem::drop)
                return name.split("::")[-1] if "::" in name else name
        return call_node.get("name")
    
    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        scope = node.get("scope_node_id")
        while scope is not None and scope != 1 and scope in all_nodes:
            parent_node = all_nodes[scope]
            if parent_node.get("type") in self.FUNCTION_DEFINITION_TYPES:
                return parent_node
            scope = parent_node.get("scope_node_id")
        return None
    
    def extract_function_name(self, func_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        return func_node.get("name")
