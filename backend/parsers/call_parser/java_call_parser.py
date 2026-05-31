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


@register_call_extractor('java')
class JavaCallExtractor(CallGraphExtractor):
    """Java 方法调用提取器"""
    
    CALL_EXPRESSION_TYPES = {'method_invocation', 'object_creation_expression'}
    FUNCTION_DEFINITION_TYPES = {'method_declaration', 'constructor_declaration'}

    
    def extract(self, proj_id: int, nodes_by_file: Dict[str, Dict[str, Dict]]) -> List[Dict[str, Any]]:
        # 构建全局方法定义映射（从 AST 节点中提取）
        method_def_map = self._build_method_def_map(nodes_by_file)

        call_edges = []
        for file_id, nodes in nodes_by_file.items():
            file_edges = self._extract_file_calls(proj_id, file_id, nodes, method_def_map)
            call_edges.extend(file_edges)

        return call_edges


    def _build_method_def_map(self, nodes_by_file: Dict[str, Dict[str, Dict]]) -> Dict[str, Dict]:
        """
        从 AST 节点中构建方法定义映射

        修复:
        1. 增加类上下文: "ClassName.methodName" -> {file_id, node_id, class_name}
        2. 支持同名方法: 保留所有定义, 不再互相覆盖
        3. 同时索引简写名: "methodName" -> 第一个匹配的定义 (fallback)

        Returns:
            method_name -> {file_id, node_id, class_name, is_static}
            键格式优先 "ClassName.methodName", 其次 "methodName"
        """
        # 第一步: 构建类名映射 (node_id -> class_name)
        class_map: Dict[int, str] = {}  # class_declaration node_id -> class_name
        class_scope_ranges: List[tuple] = []  # (class_node_id, class_name, file_id)

        for file_id, nodes in nodes_by_file.items():
            for node_id, node in nodes.items():
                if node.get("type") in ("class_declaration", "interface_declaration", "enum_declaration"):
                    class_name = self.extract_function_name(node, nodes)
                    if class_name:
                        class_map[node_id] = class_name
                        class_scope_ranges.append((node_id, class_name, file_id))

        # 第二步: 构建方法映射
        method_map: Dict[str, Dict] = {}
        method_map_all: Dict[str, List[Dict]] = {}  # 保留所有同名方法

        for file_id, nodes in nodes_by_file.items():
            for node_id, node in nodes.items():
                if node.get("type") in self.FUNCTION_DEFINITION_TYPES:
                    name = self.extract_function_name(node, nodes)
                    if not name:
                        continue

                    # 查找所属类
                    enclosing_class = self._find_enclosing_class_node(node, nodes, class_map)
                    class_name = enclosing_class[0] if enclosing_class else None

                    # 判断是否静态方法
                    is_static = self._is_static_method(node, nodes)

                    def_info = {
                        "file_id": file_id,
                        "node_id": node_id,
                        "class_name": class_name,
                        "is_static": is_static,
                    }

                    # 优先用 "ClassName.methodName" 作为键
                    if class_name:
                        full_key = f"{class_name}.{name}"
                        if full_key not in method_map:
                            method_map[full_key] = def_info
                            method_map_all.setdefault(full_key, []).append(def_info)

                    # 简写名作为 fallback (保留第一个)
                    if name not in method_map:
                        method_map[name] = def_info
                        method_map_all.setdefault(name, []).append(def_info)

        return method_map



    def _find_enclosing_class_node(self, node: Dict, nodes: Dict[int, Dict],
                                     class_map: Dict[int, str]) -> Optional[tuple]:
        """
        查找节点所属的类声明节点

        Returns:
            (class_name, class_node_id) or None
        """
        scope = node.get("scope_node_id")
        while scope is not None:
            if scope in class_map:
                return (class_map[scope], scope)
            parent = nodes.get(scope)
            if not parent:
                break
            scope = parent.get("scope_node_id")
        return None

    def _is_static_method(self, method_node: Dict, nodes: Dict[int, Dict]) -> bool:
        """判断方法是否为 static"""
        # 检查子节点中是否有 modifiers 包含 static
        method_id = method_node["node_id"]
        for child in nodes.values():
            if child.get("scope_node_id") == method_id and child.get("type") == "modifiers":
                child_refs = child.get("refs", [])
                if isinstance(child_refs, str):
                    import json
                    try:
                        child_refs = json.loads(child_refs)
                    except:
                        child_refs = []
                if "static" in child_refs:
                    return True
                # 也检查 child 的子节点类型
                for grandchild in nodes.values():
                    if grandchild.get("scope_node_id") == child["node_id"]:
                        if grandchild.get("type") == "static":
                            return True
        return False
    

    def _extract_file_calls(
        self,
        proj_id: int,
        file_id: int,
        nodes: Dict[int, Dict],
        method_def_map: Dict[str, Dict],
    ) -> List[Dict[str, Any]]:
        """
        提取单个文件的调用边

        修复:
        1. 提取调用点的对象类型, 构建 "ClassName.methodName" 精确匹配
        2. 区分 this.method() / super.method() / Class.staticMethod() / obj.method()
        3. 区分构造函数调用 (object_creation_expression)

        Args:
            proj_id: 项目 ID
            file_id: 文件 ID
            nodes: 当前文件的 AST 节点映射
            method_def_map: 全局方法定义映射 (键: "ClassName.method" 和 "method")

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

            # 尝试解析 callee 定义位置 - 多策略匹配
            callee_info = None
            resolved_name = callee_name

            # 策略 1: 提取调用点的对象类型, 构建 "ClassName.methodName"
            object_type = self._extract_call_object_type(node, nodes)
            if object_type:
                qualified_name = f"{object_type}.{callee_name}"
                callee_info = method_def_map.get(qualified_name)
                if callee_info:
                    resolved_name = qualified_name

            # 策略 2: 直接方法名匹配 (fallback)
            if not callee_info:
                callee_info = method_def_map.get(callee_name)

            # 策略 3: 如果是构造函数调用, 尝试匹配类名
            if not callee_info and node.get("type") == "object_creation_expression":
                # object_creation_expression 的 callee_name 通常是类名
                # 尝试匹配 constructor_declaration
                callee_info = method_def_map.get(callee_name)

            # 确定调用类型
            call_type = "method"
            if node.get("type") == "object_creation_expression":
                call_type = "constructor"
            elif object_type and callee_info and callee_info.get("is_static"):
                call_type = "static"
            elif not callee_info:
                call_type = "external_or_unknown"

            edge = {
                "proj_id": proj_id,
                "symbol_node_type": "call_relation",
                "caller_file_id": file_id,
                "caller_func_name": caller_name,
                "caller_node_id": caller_func_node["node_id"],
                "callee_name": resolved_name,
                "call_site_node_id": node["node_id"],
                "call_site_file_id": file_id,
                "callee_file_id": callee_info["file_id"] if callee_info else None,
                "callee_node_id": callee_info["node_id"] if callee_info else None,
                "callee_type": call_type,
            }

            call_edges.append(edge)

        return call_edges

    def _extract_call_object_type(self, call_node: Dict, nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从调用节点提取对象类型

        支持:
        - this.method() -> 返回当前类名 (从调用点向上查找)
        - super.method() -> 返回父类名 (从调用点向上查找)
        - Class.staticMethod() -> 返回 Class
        - obj.method() -> 尝试从 obj 的声明推断类型

        Returns:
            对象类型名, 如果无法推断则返回 None
        """
        call_id = call_node["node_id"]

        # 查找直接子节点中的对象引用
        for child in nodes.values():
            if child.get("scope_node_id") == call_id:
                child_type = child.get("type")

                # this.method()
                if child_type == "this":
                    # 向上查找当前类
                    enclosing = self._find_enclosing_class_node(call_node, nodes, {})
                    if enclosing:
                        # 从 class_map 获取类名 - 这里需要另一种方式
                        # 向上查找 class_declaration
                        scope = call_node.get("scope_node_id")
                        while scope:
                            parent = nodes.get(scope)
                            if parent and parent.get("type") in ("class_declaration", "interface_declaration"):
                                return self.extract_function_name(parent, nodes)
                            scope = parent.get("scope_node_id") if parent else None
                    return None

                # super.method()
                elif child_type == "super":
                    # 向上查找父类 - 简化处理, 返回 "super" 作为标记
                    return "super"

                # Class.staticMethod() - scoped_identifier 或 identifier
                elif child_type == "scoped_identifier":
                    return child.get("name")

                elif child_type == "identifier":
                    # 可能是 Class.staticMethod() 或 obj.method()
                    # 如果是大写开头, 可能是类名
                    name = child.get("name")
                    if name and name[0].isupper():
                        return name
                    # 否则尝试查找该变量的声明类型
                    var_type = self._infer_variable_type(child, nodes)
                    if var_type:
                        return var_type

        return None

    def _infer_variable_type(self, var_node: Dict, nodes: Dict[int, Dict]) -> Optional[str]:
        """
        推断变量的声明类型

        通过查找变量定义节点来获取其类型。
        简化实现: 在同一文件中查找同名变量的类型声明。
        """
        var_name = var_node.get("name")
        if not var_name:
            return None

        # 在当前文件节点中查找变量声明
        for node in nodes.values():
            if node.get("type") in ("variable_declarator", "formal_parameter"):
                node_name = node.get("name")
                if node_name == var_name:
                    # 向上查找类型
                    parent_id = node.get("scope_node_id")
                    while parent_id:
                        parent = nodes.get(parent_id)
                        if not parent:
                            break
                        # 类型通常在 parent 的子节点 type_identifier 中
                        for child in nodes.values():
                            if (child.get("scope_node_id") == parent_id and
                                child.get("type") == "type_identifier"):
                                return child.get("name")
                        # 也检查 parent 本身的 name
                        if parent.get("type") == "type_identifier":
                            return parent.get("name")
                        parent_id = parent.get("scope_node_id")

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

        - 对于全限定名调用：java.util.Objects.requireNonNull(...)
          refs = ['java', 'util', 'Objects', 'requireNonNull']
          最后一个标识符是方法名，但需要 scoped_identifier 来保留完整路径
        """
        import json

        # 首先尝试从 refs 提取
        refs_raw = call_node.get("refs", [])
        # 从 SQLite 读取的 refs 是 JSON 字符串，需要解析
        if isinstance(refs_raw, str):
            try:
                refs = json.loads(refs_raw)
            except (json.JSONDecodeError, TypeError):
                refs = []
        else:
            refs = refs_raw

        if refs and len(refs) > 0:
            # 关键修复：refs 数组包含调用链上的所有标识符
            # 最后一个标识符才是当前调用的方法名
            # 例如：refs = ['DashScopeApi', 'builder'] -> 方法名是 'builder'
            #      refs = ['System', 'getenv'] -> 方法名是 'getenv'
            #      refs = ['java', 'util', 'Objects', 'requireNonNull'] -> 方法名是 'requireNonNull'
            last_ref = refs[-1]
            if last_ref and len(last_ref) > 0:  # 确保非空
                return last_ref

        # 尝试从 name 字段获取
        name = call_node.get("name")
        if name:
            return name

        # 从子节点中查找 scoped_identifier（全限定名，优先级高于 identifier）
        call_id = call_node["node_id"]
        for node in all_nodes.values():
            if (node.get("type") == "scoped_identifier" and
                node.get("scope_node_id") == call_id):
                return node.get("name")

        # 从子节点中查找 identifier
        for node in all_nodes.values():
            if (node.get("type") == "identifier" and
                node.get("scope_node_id") == call_id):
                return node.get("name")

        return None
    
    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        """
        查找包含该节点的函数定义

        Java 中方法可以嵌套在类中，所以需要查找 method_declaration 或 constructor_declaration
        也支持 constructor_body 作为有效的作用域
        """
        scope = node.get("scope_node_id")
        while scope is not None and scope != 1 and scope in all_nodes:
            parent_node = all_nodes[scope]
            parent_type = parent_node.get("type")

            # Java 使用 method_declaration 和 constructor_declaration
            if parent_type in self.FUNCTION_DEFINITION_TYPES:
                return parent_node

            # constructor_body 内的调用也属于构造函数
            if parent_type == "constructor_body":
                # 向上查找 constructor_declaration
                grand_scope = parent_node.get("scope_node_id")
                if grand_scope and grand_scope in all_nodes:
                    grand_parent = all_nodes[grand_scope]
                    if grand_parent.get("type") == "constructor_declaration":
                        return grand_parent

            # 如果到了 class/interface/enum 级别，继续向上查找（内部类场景）
            if parent_type in {'class_declaration', 'interface_declaration', 'enum_declaration'}:
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
