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
    
    # C 语言函数定义的节点类型
    FUNCTION_DEFINITION_TYPES = {'function_definition'}
    
    # C 语言调用表达式的节点类型
    CALL_EXPRESSION_TYPES = {'call_expression', 'preproc_call'}
    
    # C 语言标识符节点类型
    IDENTIFIER_TYPES = {'identifier'}
    
    def extract(self, proj_id: int, nodes_by_file: Dict[int, Dict[int, Dict]]) -> List[Dict[str, Any]]:
        """
        提取调用图边
        
        Args:
            proj_id: 项目 ID
            nodes_by_file: 按文件分组的 AST 节点
            
        Returns:
            调用边列表
        """
        
        
        # 构建全局函数定义映射
        global_func_def_map = self._build_global_function_map(proj_id, graph_node_coll)
        
        # 构建全局宏定义映射
        global_macro_map = self._build_global_macro_map(proj_id, graph_node_coll)
        
        # 提取调用边
        call_edges = []
        
        for file_id, nodes in nodes_by_file.items():
            file_edges = self._extract_file_calls(
                file_id, nodes, global_func_def_map, global_macro_map
            )
            call_edges.extend(file_edges)
        
        return call_edges
    
    def _build_global_function_map(self, proj_id: int, graph_node_coll) -> Dict[str, Dict]:
        """构建全局函数定义映射"""
        func_map = {}
        func_nodes = graph_node_coll.find(
            {"proj_id": proj_id, "symbol_node_type": "func_name"},
            {"func_name": 1, "def_file_id": 1, "def_node_id": 1, "_id": 0}
        )
        for rec in func_nodes:
            name = rec["func_name"]
            global_func_def_map[name] = {
                "file_id": rec["def_file_id"],
                "node_id": rec["def_node_id"]
            }
        return func_map
    
    def _build_global_macro_map(self, proj_id: int, graph_node_coll) -> Dict[str, Dict]:
        """构建全局宏定义映射"""
        macro_map = {}
        macro_nodes = graph_node_coll.find(
            {"proj_id": proj_id, "symbol_node_type": "macro_name"},
            {"macro_name": 1, "def_file_id": 1, "def_node_id": 1, "_id": 0}
        )
        for rec in macro_nodes:
            name = rec["macro_name"]
            if name not in macro_map:
                macro_map[name] = {
                    "file_id": rec["def_file_id"],
                    "node_id": rec["def_node_id"]
                }
        return macro_map
    
    def _extract_file_calls(
        self,
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

        算法:
        1. 优先从 refs 数组提取（第一个非类型名的标识符）
        2. 查找同一作用域内的 identifier 节点
        3. 回退到第一个候选标识符
        """
        # 方案 1: 从 refs 数组提取函数名
        refs = func_node.get('refs', [])
        if refs:
            # refs 中第一个标识符通常是返回类型，第二个是函数名
            # 但也可能只有一个函数名（无返回类型的旧式 C 函数）
            for i, ref in enumerate(refs):
                # 跳过常见的返回类型
                if i == 0 and ref in {'void', 'int', 'char', 'long', 'short', 'unsigned',
                                       'signed', 'float', 'double', 'size_t', 'ssize_t',
                                       'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t',
                                       'int8_t', 'int16_t', 'int32_t', 'int64_t',
                                       'bool', 'const', 'static', 'extern', 'inline'}:
                    continue
                # 找到第一个非类型名的标识符，很可能是函数名
                if ref and len(ref) > 0 and (ref[0].islower() or ref[0].isupper()):
                    return ref
        
        # 方案 2: 从 identifier 节点提取
        func_id = func_node['node_id']
        
        # 查找同一作用域内的 identifier 候选
        candidates = [
            n for n in all_nodes.values()
            if n['type'] == 'identifier'
               and n.get('scope_node_id') == func_id
        ]
        if not candidates:
            return None
        
        # 按位置排序
        candidates.sort(key=lambda x: (x['start'][0], x['start'][1]))
        
        # 返回第一个标识符作为函数名
        return candidates[0].get('name') or (candidates[0].get('refs') and candidates[0]['refs'][0])

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
        # 优先从 refs 提取
        refs = call_node.get('refs')
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
