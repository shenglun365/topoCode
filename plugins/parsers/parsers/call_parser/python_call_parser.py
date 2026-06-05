# parsers/languages/call_parser/python_call_parser.py
"""
Python 调用图提取器

实现 Python 语言的函数/方法调用识别和提取逻辑。

支持的调用语法:
- 函数调用：func()
- 方法调用：obj.method()
- 类方法调用：Class.method()
- 内置函数调用：len(), print()
- Lambda 调用
- 可调用对象调用

调用类型:
- 直接调用：在同一作用域内定义的函数
- 模块调用：从其他模块导入的函数
- 方法调用：类实例的方法
- 内置调用：Python 内置函数
"""
from typing import Dict, Any, Optional, List
from .extractor_factory import CallGraphExtractor, register_call_extractor


@register_call_extractor('python')
class PythonCallExtractor(CallGraphExtractor):
    """
    Python 函数/方法调用提取器
    
    支持识别:
    - 普通函数调用：func()
    - 方法调用：obj.method()
    - 类方法调用：Class.method()
    - 内置函数调用：len(), str()
    - 装饰器调用
    """
    
    # Python 调用表达式的 AST 节点类型
    CALL_EXPRESSION_TYPES = {'call'}
    
    # Python 函数定义的节点类型
    FUNCTION_DEFINITION_TYPES = {'function_definition', 'async_function_definition'}
    CLASS_DEFINITION_TYPES = {'class_definition'}
    
    # Python 内置函数列表
    BUILTIN_FUNCTIONS = {
        'abs', 'all', 'any', 'ascii', 'bin', 'bool', 'breakpoint', 'bytearray',
        'bytes', 'callable', 'chr', 'classmethod', 'compile', 'complex',
        'delattr', 'dict', 'dir', 'divmod', 'enumerate', 'eval', 'exec',
        'filter', 'float', 'format', 'frozenset', 'getattr', 'globals',
        'hasattr', 'hash', 'help', 'hex', 'id', 'input', 'int', 'isinstance',
        'issubclass', 'iter', 'len', 'list', 'locals', 'map', 'max',
        'memoryview', 'min', 'next', 'object', 'oct', 'open', 'ord', 'pow',
        'print', 'property', 'range', 'repr', 'reversed', 'round', 'set',
        'setattr', 'slice', 'sorted', 'staticmethod', 'str', 'sum', 'super',
        'tuple', 'type', 'vars', 'zip', '__import__',
    }
    
    # Python 内置类型 (可作为构造函数调用)
    BUILTIN_TYPES = {
        'int', 'float', 'complex', 'str', 'bytes', 'bytearray',
        'list', 'tuple', 'range', 'set', 'frozenset', 'dict',
        'bool', 'object', 'type',
    }
    
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
        global_func_map = self._build_global_function_map_from_ast(nodes_by_file)
        
        # 构建全局类定义映射
        global_class_map = self._build_global_class_map_from_ast(nodes_by_file)
        
        # 提取调用边
        call_edges = []
        
        for file_id, nodes in nodes_by_file.items():
            file_edges = self._extract_file_calls(
                proj_id=proj_id,
                file_id=file_id,
                nodes=nodes,
                func_map=global_func_map,
                class_map=global_class_map
            )
            call_edges.extend(file_edges)
        
        return call_edges
    


    def extract_class_name(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """从类定义节点提取类名"""
        return node.get("name") or (node.get("refs", [None])[0] if node.get("refs") else None)

    def _extract_file_calls(
        self,
        proj_id: int,
        file_id: int,
        nodes: Dict[int, Dict],
        func_map: Dict[str, Dict],
        class_map: Dict[str, Dict]
    ) -> List[Dict[str, Any]]:
        """提取单个文件的调用边"""
        call_edges = []
        
        for node in nodes.values():
            if not self.is_call_expression(node):
                continue
            
            # 提取被调用名
            callee_name = self.extract_callee_name(node, nodes)
            if not callee_name:
                continue
            
            # 查找调用者函数
            caller_func_node = self.find_enclosing_function(node, nodes)
            if not caller_func_node:
                continue
            
            caller_name = self.extract_function_name(caller_func_node, nodes)
            if not caller_name:
                continue
            
            # 确定调用类型
            call_type = self._determine_call_type(callee_name, node, func_map, class_map)
            
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
                "call_type": call_type,
            }
            
            # 解析被调用方
            if callee_name in func_map:
                callee_info = func_map[callee_name]
                edge.update({
                    "callee_file_id": callee_info["file_id"],
                    "callee_node_id": callee_info["node_id"],
                    "callee_type": "function"
                })
            elif callee_name in class_map:
                # 类构造函数调用
                callee_info = class_map[callee_name]
                edge.update({
                    "callee_file_id": callee_info["file_id"],
                    "callee_node_id": callee_info["node_id"],
                    "callee_type": "constructor"
                })
            elif self._is_builtin(callee_name):
                edge.update({
                    "callee_file_id": None,
                    "callee_node_id": None,
                    "callee_type": "builtin"
                })
            else:
                edge.update({
                    "callee_file_id": None,
                    "callee_node_id": None,
                    "callee_type": "external_or_unknown"
                })
            
            call_edges.append(edge)
        
        return call_edges
    
    def _determine_call_type(
        self,
        callee_name: str,
        call_node: Dict,
        func_map: Dict[str, Dict],
        class_map: Dict[str, Dict]
    ) -> str:
        """
        确定调用类型
        
        Returns:
            调用类型：direct, method, class, builtin, external
        """
        if self._is_builtin(callee_name):
            return "builtin"
        
        if callee_name in func_map:
            return "direct"
        
        if callee_name in class_map:
            return "constructor"
        
        # 检查是否是方法调用 (通过调用者的 refs 判断)
        refs = call_node.get("refs", [])
        if refs and len(refs) > 1:
            return "method"
        
        return "external"
    
    def _is_builtin(self, name: str) -> bool:
        """判断是否为内置函数或类型"""
        return name in self.BUILTIN_FUNCTIONS or name in self.BUILTIN_TYPES
    
    def is_call_expression(self, node: Dict) -> bool:
        """判断节点是否为调用表达式"""
        return node.get("type") in self.CALL_EXPRESSION_TYPES
    
    def extract_callee_name(self, call_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从调用节点提取被调用函数名
        
        策略:
        1. 优先从 refs 字段提取第一个元素
        2. 回退到查找子节点中的 identifier
        """
        # 优先从 refs 提取
        refs = call_node.get("refs", [])
        if refs and len(refs) > 0:
            name = refs[0]
            if name and len(name) > 0:  # 确保非空
                # 处理属性访问 (obj.method) - 只取最后一个部分
                return name.split(".")[-1] if "." in name else name

        # 回退：查找子节点中的 identifier
        for node in all_nodes.values():
            if node.get("scope_node_id") == call_node["node_id"]:
                if node.get("type") == "identifier":
                    return node.get("name")

        return None
    
    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        """
        查找包含该节点的函数定义
        
        通过作用域链向上查找，直到找到 function_definition 节点
        """
        scope = node.get("scope_node_id")
        while scope is not None and scope != 1 and scope in all_nodes:
            parent_node = all_nodes[scope]
            if parent_node.get("type") in self.FUNCTION_DEFINITION_TYPES:
                return parent_node
            scope = parent_node.get("scope_node_id")
        return None
    
    def extract_function_name(self, func_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从函数定义节点提取函数名
        
        策略:
        1. 查找同一作用域内的 identifier 节点
        2. 优先匹配 function 名称
        """
        func_id = func_node["node_id"]
        
        # 查找同一作用域内的 identifier 候选
        candidates = [
            n for n in all_nodes.values()
            if n.get("type") == "identifier"
            and n.get("scope_node_id") == func_id
            and func_id in n.get("def_node_id", [])
        ]
        
        if not candidates:
            # 尝试从 name 字段获取
            return func_node.get("name")
        
        # 按位置排序，取第一个
        candidates.sort(key=lambda x: (x["start"][0], x["start"][1]))
        return candidates[0].get("name")
