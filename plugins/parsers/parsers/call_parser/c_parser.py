# parsers/languages/call_parser/c_parser.py
"""
C 语言调用图提取器

实现 C/C++ 语言的函数调用识别和提取逻辑。
"""
from typing import Dict, Any, Optional, List
from .extractor_factory import CallGraphExtractor, register_call_extractor


@register_call_extractor('c')
@register_call_extractor('cpp')
class CLanguageParser(CallGraphExtractor):
    """
    C 语言调用图提取器
    
    支持识别:
    - 普通函数调用：func()
    - 宏调用：MACRO()
    - 函数指针调用：(*fp)()
    """
    
    # C 语言函数定义的节点类型（包含 C++ 方法）
    FUNCTION_DEFINITION_TYPES = {'function_definition', 'method_definition'}
    MACRO_DEFINITION_TYPES = {'macro_definition'}
    
    # C 语言调用表达式的节点类型
    CALL_EXPRESSION_TYPES = {'call_expression', 'preproc_call'}
    
    # C 语言标识符节点类型
    IDENTIFIER_TYPES = {'identifier'}
    
    def extract(self, proj_id: int, nodes_by_file: Dict[str, Dict[str, Dict]]) -> List[Dict[str, Any]]:
        """
        提取调用图边
        
        Args:
            proj_id: 项目 ID
            nodes_by_file: 按文件分组的 AST 节点
            
        Returns:
            调用边列表
        """
        
        
        # 构建全局函数定义映射
        global_func_def_map = self._build_global_function_map_from_ast(nodes_by_file)
        
        # 构建全局宏定义映射
        global_macro_map = self._build_global_macro_map_from_ast(nodes_by_file)
        
        # 提取调用边
        call_edges = []
        
        for file_id, nodes in nodes_by_file.items():
            file_edges = self._extract_file_calls(
                proj_id, file_id, nodes, global_func_def_map, global_macro_map
            )
            call_edges.extend(file_edges)
        
        return call_edges
    


    def _build_global_function_map_from_ast(self, nodes_by_file: Dict[str, Dict[str, Dict]]) -> Dict[str, Dict]:
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

    def _build_global_macro_map_from_ast(self, nodes_by_file: Dict[str, Dict[str, Dict]]) -> Dict[str, Dict]:
        """从 AST 节点中构建全局宏映射（不依赖数据库）"""
        macro_map = {}
        for file_id, nodes in nodes_by_file.items():
            for node_id, node in nodes.items():
                node_type = node.get("type", "")
                if node_type in ("preproc_def", "preproc_function_def"):
                    macro_name = self.extract_macro_name(node, nodes)
                    if macro_name:
                        macro_map[macro_name] = {"file_id": file_id, "node_id": node_id}
        return macro_map

    def extract_macro_name(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """从宏定义节点提取宏名"""
        name = node.get("name")
        if name:
            return name
        refs = node.get("refs", [])
        if refs:
            return refs[0]
        return None

    def _extract_file_calls(
        self,
        proj_id: int,
        file_id: int,
        nodes: Dict[int, Dict],
        func_map: Dict[str, Dict],
        macro_map: Dict[str, Dict]
    ) -> List[Dict[str, Any]]:
        """提取单个文件的调用边"""
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
            
            # 构建调用边
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
            
            # 解析被调用方
            if callee_name in func_map:
                callee_info = func_map[callee_name]
                edge.update({
                    "callee_file_id": callee_info["file_id"],
                    "callee_node_id": callee_info["node_id"],
                    "callee_type": "function"
                })
            elif callee_name in macro_map:
                macro_info = macro_map[callee_name]
                edge.update({
                    "callee_file_id": macro_info["file_id"],
                    "callee_node_id": macro_info["node_id"],
                    "callee_type": "macro"
                })
            else:
                edge.update({
                    "callee_file_id": None,
                    "callee_node_id": None,
                    "callee_type": "external_or_unknown"
                })
            
            call_edges.append(edge)
        
        return call_edges
    
    def is_function_definition(self, node: Dict) -> bool:
        """判断节点是否为函数定义"""
        return node['type'] in self.FUNCTION_DEFINITION_TYPES

    def extract_function_name(self, func_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从函数定义节点提取函数名

        策略:
        1. 优先从 identifier 子节点提取（查找 def_node_id 匹配的）
        2. 回退: 从同一作用域内的 identifier 提取
        3. 最后回退: 从 refs 数组提取（跳过常见类型名）
        """
        import json

        func_id = func_node.get('node_id')

        # 策略 1: 查找 def_node_id 匹配的 identifier（最精确）
        for node in all_nodes.values():
            if node.get('type') == 'identifier' and node.get('scope_node_id') == func_id:
                did = node.get('def_node_id')
                # 兼容 list 和字符串格式
                if isinstance(did, list) and func_id in did:
                    return node.get('name')
                elif isinstance(did, str) and did.startswith('['):
                    try:
                        did_list = json.loads(did)
                        if func_id in did_list:
                            return node.get('name')
                    except (json.JSONDecodeError, TypeError):
                        pass

        # 策略 2: 同一作用域内的所有 identifier，按位置排序取第一个
        candidates = [
            n for n in all_nodes.values()
            if n['type'] == 'identifier' and n.get('scope_node_id') == func_id
        ]
        if candidates:
            candidates.sort(key=lambda x: (x.get('start', [0, 0])[0], x.get('start', [0, 0])[1]))
            return candidates[0].get('name')

        # 策略 3: 从 refs 数组提取（跳过常见类型名）
        refs = func_node.get('refs', [])
        type_keywords = {'void', 'int', 'char', 'long', 'short', 'unsigned',
                         'signed', 'float', 'double', 'size_t', 'ssize_t',
                         'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
                         'int8_t', 'int16_t', 'int32_t', 'int64_t',
                         'bool', 'const', 'static', 'extern', 'inline'}
        for ref in refs:
            if ref and ref not in type_keywords:
                return ref

        return None

    def is_call_expression(self, node: Dict) -> bool:
        """判断节点是否为调用表达式"""
        return node['type'] in self.CALL_EXPRESSION_TYPES

    def extract_callee_name(self, call_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从调用节点提取被调用函数名

        策略:
        1. 优先从 refs 字段提取（最可靠）
        2. 回退到同行 identifier
        """
        import json

        # 优先从 refs 提取
        refs = call_node.get('refs')
        # 兼容字符串格式的 refs
        if isinstance(refs, str) and refs.startswith('['):
            try:
                refs = json.loads(refs)
            except (json.JSONDecodeError, TypeError):
                refs = []

        if refs and isinstance(refs, list) and len(refs) > 0:
            name = refs[0]
            # 处理字符串字面量
            if isinstance(name, str):
                if name.startswith('"') and name.endswith('"'):
                    return name[1:-1]
                if len(name) > 0:  # 确保非空
                    return name

        # 回退：找同一行的 identifier
        candidates = [
            n for n in all_nodes.values()
            if n['type'] == 'identifier'
            and n['start'][0] == call_node['start'][0]
            and call_node['start'][1] <= n['start'][1] <= call_node['end'][1]
        ]
        if candidates:
            cand = candidates[0]
            return cand.get('name') or (cand.get('refs') and cand['refs'][0])
        return None

    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        """
        查找包含该节点的函数定义
        
        通过作用域链向上查找，直到找到 function_definition 节点
        """
        scope = node.get('scope_node_id')
        while scope is not None and scope != 1 and scope in all_nodes:
            parent_node = all_nodes[scope]
            if parent_node['type'] in self.FUNCTION_DEFINITION_TYPES:
                return parent_node
            scope = parent_node.get('scope_node_id')
        return None
