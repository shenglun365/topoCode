# parsers/languages/call_parser/java_call_parser.py
"""
Java 调用图提取器

实现 Java 语言的方法调用识别和提取逻辑。

支持的调用语法:
- 静态方法调用：Class.method()
- 实例方法调用：obj.method()
- 构造函数调用：new Class()
- super 调用：super.method()
- this 调用：this.method()

架构:
- 使用 CallGraphExtractor 抽象基类
- 使用 JavaOOPMethodResolver 处理面向对象特性
- 与 C 语言提取器完全独立
"""
from typing import Dict, Any, Optional, List
from .extractor_factory import CallGraphExtractor, register_call_extractor
from .java_oop_resolver import JavaOOPMethodResolver


@register_call_extractor('java')
class JavaCallExtractor(CallGraphExtractor):
    """Java 方法调用提取器"""
    
    CALL_EXPRESSION_TYPES = {'method_invocation', 'object_creation_expression'}
    FUNCTION_DEFINITION_TYPES = {'method_declaration', 'constructor_declaration'}
    
    def extract(self, proj_id: int, nodes_by_file: Dict[int, Dict[int, Dict]]) -> List[Dict[str, Any]]:


        # 初始化 Java OOP 解析器
        oop_resolver = JavaOOPMethodResolver(proj_id, graph_node_coll, base_node_coll)

        call_edges = []
        for file_id, nodes in nodes_by_file.items():
            file_edges = self._extract_file_calls(proj_id, file_id, nodes, oop_resolver)
            call_edges.extend(file_edges)

        return call_edges
    
    def _build_global_method_map(self, proj_id: int, graph_node_coll) -> Dict[str, Dict]:
        """
        构建全局方法映射
        
        为了支持 Java 方法匹配，使用两种键：
        1. 简单方法名 -> 所有同名方法（用于快速查找）
        2. 文件 ID+ 方法名 -> 具体方法（用于精确匹配）
        """
        method_map = {}
        method_by_file = {}  # 按文件 ID 索引

        # 查询 Java 方法（symbol_node_type: method_name）
        method_nodes = graph_node_coll.find(
            {"proj_id": proj_id, "symbol_node_type": "method_name"},
            {"method_name": 1, "def_file_id": 1, "def_node_id": 1, "_id": 0}
        )
        for rec in method_nodes:
            name = rec["method_name"]
            file_id = rec["def_file_id"]
            node_id = rec["def_node_id"]
            
            # 简单方法名映射（可能有多个）
            if name not in method_map:
                method_map[name] = []
            method_map[name].append({
                "file_id": file_id,
                "node_id": node_id
            })
            
            # 文件 ID+ 方法名映射（精确）
            key = f"{file_id}:{name}"
            method_by_file[key] = {
                "file_id": file_id,
                "node_id": node_id
            }

        # 也查询 C/C++ 函数（symbol_node_type: func_name）
        func_nodes = graph_node_coll.find(
            {"proj_id": proj_id, "symbol_node_type": "func_name"},
            {"func_name": 1, "def_file_id": 1, "def_node_id": 1, "_id": 0}
        )
        for rec in func_nodes:
            name = rec["func_name"]
            file_id = rec["def_file_id"]
            node_id = rec["def_node_id"]
            
            if name not in method_map:
                method_map[name] = []
            method_map[name].append({
                "file_id": file_id,
                "node_id": node_id
            })
            
            key = f"{file_id}:{name}"
            method_by_file[key] = {
                "file_id": file_id,
                "node_id": node_id
            }

        return {"by_name": method_map, "by_file_name": method_by_file}
    
    def _extract_file_calls(
        self,
        proj_id: int,
        file_id: int,
        nodes: Dict[int, Dict],
        oop_resolver: JavaOOPMethodResolver
    ) -> List[Dict[str, Any]]:
        """
        提取单个文件的调用边
        
        Args:
            proj_id: 项目 ID
            file_id: 文件 ID
            nodes: 当前文件的 AST 节点映射
            oop_resolver: Java OOP 方法解析器
        
        Returns:
            调用边列表
        """
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

            # 使用 OOP 解析器解析方法调用
            call_context = self._build_call_context(node, nodes)
            callee_file_id, callee_node_id, callee_type = oop_resolver.resolve_method_call(
                callee_name=callee_name,
                caller_file_id=file_id,
                call_context=call_context
            )

            edge.update({
                "callee_file_id": callee_file_id,
                "callee_node_id": callee_node_id,
                "callee_type": callee_type
            })

            call_edges.append(edge)

        return call_edges
    
    def _build_call_context(self, call_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        """
        构建调用上下文，用于重载消歧
        
        Args:
            call_node: 调用表达式节点
            all_nodes: 当前文件的所有节点映射
        
        Returns:
            调用上下文字典，包含参数类型等信息
        """
        # TODO: 从调用节点提取参数类型信息
        # 目前返回 None，后续可以扩展
        return None
    
    def is_call_expression(self, node: Dict) -> bool:
        return node.get("type") in self.CALL_EXPRESSION_TYPES
    
    def extract_callee_name(self, call_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从调用节点提取被调用方法名

        Java 的方法调用节点结构：
        method_invocation:
          - name: 方法名
          - arguments: 参数列表
          - (可选) object: 调用对象

        refs 数组结构分析:
        - 对于链式调用：DashScopeApi.builder().apiKey(...)
          refs = ['DashScopeApi', 'builder', 'apiKey', ...]
          最后一个标识符才是当前调用的方法名

        - 对于简单调用：System.getenv()
          refs = ['System', 'getenv']
          最后一个标识符是方法名
        """
        # 首先尝试从 refs 提取
        refs = call_node.get("refs", [])
        if refs and len(refs) > 0:
            # 关键修复：refs 数组包含调用链上的所有标识符
            # 最后一个标识符才是当前调用的方法名
            # 例如：refs = ['DashScopeApi', 'builder'] -> 方法名是 'builder'
            #      refs = ['System', 'getenv'] -> 方法名是 'getenv'
            last_ref = refs[-1]
            if last_ref and len(last_ref) > 0:  # 确保非空
                return last_ref

        # 尝试从 name 字段获取
        name = call_node.get("name")
        if name:
            return name

        # 从子节点中查找 identifier
        call_id = call_node["node_id"]
        for node in all_nodes.values():
            if (node.get("type") == "identifier" and
                node.get("scope_node_id") == call_id):
                return node.get("name")

        return None
    
    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        """
        查找包含该节点的函数定义
        
        Java 中方法可以嵌套在类中，所以需要查找 method_declaration 或 constructor_declaration
        """
        scope = node.get("scope_node_id")
        while scope is not None and scope != 1 and scope in all_nodes:
            parent_node = all_nodes[scope]
            parent_type = parent_node.get("type")
            
            # Java 使用 method_declaration 和 constructor_declaration
            if parent_type in self.FUNCTION_DEFINITION_TYPES:
                return parent_node
            
            # 如果到了 class/interface/enum 级别，停止向上查找
            if parent_type in {'class_declaration', 'interface_declaration', 'enum_declaration'}:
                # 继续查找，因为方法可能嵌套在内部类中
                pass
            
            scope = parent_node.get("scope_node_id")
        return None
    
    def extract_function_name(self, func_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从函数定义节点提取函数名
        
        Java 的方法声明节点结构：
        method_declaration:
          - modifiers
          - type_parameters
          - type_identifier (返回类型)
          - identifier (方法名) <- 这是我们要找的
          - formal_parameters
          - body
        """
        # 首先尝试直接从 name 字段获取
        name = func_node.get("name")
        if name:
            return name
        
        # 如果没有 name 字段，从子节点中查找 identifier
        func_id = func_node["node_id"]
        for node in all_nodes.values():
            # 查找直接子节点中的 identifier
            if (node.get("type") == "identifier" and 
                node.get("scope_node_id") == func_id and
                func_id in node.get("def_node_id", [])):
                return node.get("name")
        
        # 备用方案：查找同一作用域内的 identifier
        for node in all_nodes.values():
            if (node.get("type") == "identifier" and 
                node.get("scope_node_id") == func_id):
                return node.get("name")
        
        return None
