# parsers/languages/call_parser/java_oop_resolver.py
"""
Java 面向对象调用解析器

处理 Java 特有的调用识别机制：
1. 方法重载（Overloading）：同名方法，参数列表不同
2. 方法重写（Overriding）：子类重写父类方法
3. 继承关系：父类方法调用
4. 接口实现：接口方法调用
5. 泛型方法：泛型参数匹配
6. 访问控制：public/protected/private 可见性

使用策略模式，与 C 语言的简单调用识别完全分离。
"""
import logging
from typing import Dict, List, Optional, Tuple, Set, Any
from collections import defaultdict

logger = logging.getLogger(__name__)


class JavaOOPMethodResolver:
    """
    Java 面向对象方法解析器
    
    解决 Java 方法调用的复杂匹配问题，包括重载、重写、继承等。
    """
    
    def __init__(self, proj_id: int, graph_node_coll, base_node_coll):
        """
        初始化解析器

        Args:
            proj_id: 项目 ID
            graph_node_coll: graph_node 集合
            base_node_coll: base_node 集合
        """
        self.proj_id = proj_id
        self.graph_node_coll = graph_node_coll
        self.base_node_coll = base_node_coll

        # 方法索引
        self.methods_by_name: Dict[str, List[Dict]] = defaultdict(list)
        self.methods_by_file_name: Dict[str, Dict] = {}
        self.methods_by_signature: Dict[str, Dict] = {}

        # 类索引（用于构造函数解析）
        self.classes_by_name: Dict[str, List[Dict]] = defaultdict(list)
        self.classes_by_file_name: Dict[str, Dict] = {}

        # 类层次结构
        self.class_hierarchy: Dict[str, List[str]] = defaultdict(list)  # class -> [parents]
        self.class_methods: Dict[str, List[Dict]] = defaultdict(list)  # class -> [methods]

        # 构建索引
        self._build_method_index()
        self._build_class_index()
        self._build_class_hierarchy()
    
    def _build_method_index(self):
        """构建方法索引"""
        method_nodes = list(self.graph_node_coll.find(
            {"proj_id": self.proj_id, "symbol_node_type": "method_name"},
            {
                "method_name": 1,
                "def_file_id": 1,
                "def_node_id": 1,
                "start_line": 1,
                "end_line": 1,
                "_id": 0
            }
        ))

        for method in method_nodes:
            method_name = method.get("method_name")
            file_id = method.get("def_file_id")
            node_id = method.get("def_node_id")

            if not method_name or not file_id:
                continue

            method_info = {
                "method_name": method_name,
                "file_id": file_id,
                "node_id": node_id,
                "start_line": method.get("start_line", []),
                "end_line": method.get("end_line", [])
            }

            # 按名称索引（可能有多个）
            self.methods_by_name[method_name].append(method_info)

            # 按文件 + 名称索引（精确）
            key = f"{file_id}:{method_name}"
            self.methods_by_file_name[key] = method_info

    def _build_class_index(self):
        """
        构建类索引（用于构造函数解析）
        
        构造函数调用时使用类名，所以需要建立类名到类定义的映射
        """
        class_nodes = list(self.graph_node_coll.find(
            {"proj_id": self.proj_id, "symbol_node_type": "class_name"},
            {
                "class_name": 1,
                "def_file_id": 1,
                "def_node_id": 1,
                "start_line": 1,
                "end_line": 1,
                "_id": 0
            }
        ))

        for cls in class_nodes:
            class_name = cls.get("class_name")
            file_id = cls.get("def_file_id")
            node_id = cls.get("def_node_id")

            if not class_name or not file_id:
                continue

            class_info = {
                "class_name": class_name,
                "file_id": file_id,
                "node_id": node_id,
                "start_line": cls.get("start_line", []),
                "end_line": cls.get("end_line", [])
            }

            # 按名称索引（可能有多个，如内部类）
            self.classes_by_name[class_name].append(class_info)

            # 按文件 + 名称索引（精确）
            key = f"{file_id}:{class_name}"
            self.classes_by_file_name[key] = class_info
    
    def _build_class_hierarchy(self):
        """构建类层次结构"""
        class_nodes = list(self.graph_node_coll.find(
            {"proj_id": self.proj_id, "symbol_node_type": "class_name"},
            {
                "class_name": 1,
                "def_file_id": 1,
                "def_node_id": 1,
                "parent_classes": 1,  # 假设有父类信息
                "_id": 0
            }
        ))
        
        for cls in class_nodes:
            class_name = cls.get("class_name")
            file_id = cls.get("def_file_id")
            parent_classes = cls.get("parent_classes", [])
            
            if not class_name or not file_id:
                continue
            
            class_key = f"{file_id}:{class_name}"
            self.class_hierarchy[class_key] = parent_classes
    
    def resolve_method_call(
        self,
        callee_name: str,
        caller_file_id: int,
        call_context: Optional[Dict] = None
    ) -> Tuple[Optional[int], Optional[int], str]:
        """
        解析方法调用，确定被调用方法的位置

        Args:
            callee_name: 被调用方法名
            caller_file_id: 调用者文件 ID
            call_context: 调用上下文（可选），包含参数类型等信息

        Returns:
            (callee_file_id, callee_node_id, callee_type)
            - callee_file_id: 被调用方法所在文件 ID，未知则为 None
            - callee_node_id: 被调用方法节点 ID，未知则为 None
            - callee_type: 类型 ('method', 'constructor', 'external_or_unknown')
        """
        # 策略 1: 优先匹配同一文件内的方法（最常见）
        file_method_key = f"{caller_file_id}:{callee_name}"
        if file_method_key in self.methods_by_file_name:
            method_info = self.methods_by_file_name[file_method_key]
            logger.debug(f"[Java OOP] 匹配到文件内方法：{callee_name} @ file {caller_file_id}")
            return (
                method_info["file_id"],
                method_info["node_id"],
                "method"
            )

        # 策略 2: 匹配同名方法（按出现频率排序）
        if callee_name in self.methods_by_name:
            candidates = self.methods_by_name[callee_name]
            if len(candidates) == 1:
                # 只有一个候选，直接使用
                method_info = candidates[0]
                logger.debug(f"[Java OOP] 匹配到唯一方法：{callee_name} @ file {method_info['file_id']}")
                return (
                    method_info["file_id"],
                    method_info["node_id"],
                    "method"
                )
            else:
                # 多个候选，使用调用上下文进行消歧
                resolved = self._disambiguate_overloaded_methods(
                    callee_name,
                    candidates,
                    caller_file_id,
                    call_context
                )
                if resolved:
                    logger.debug(f"[Java OOP] 重载消歧后匹配：{callee_name} @ file {resolved['file_id']}")
                    return (
                        resolved["file_id"],
                        resolved["node_id"],
                        "method"
                    )
                else:
                    # 无法消歧，优先选择同一文件内的候选
                    same_file_candidates = [c for c in candidates if c["file_id"] == caller_file_id]
                    if same_file_candidates:
                        method_info = same_file_candidates[0]
                        logger.debug(f"[Java OOP] 重载消歧失败，使用同文件候选：{callee_name} @ file {method_info['file_id']}")
                        return (
                            method_info["file_id"],
                            method_info["node_id"],
                            "method"
                        )
                    # 使用第一个候选（保守策略）
                    method_info = candidates[0]
                    logger.debug(f"[Java OOP] 重载消歧失败，使用第一个：{callee_name} @ file {method_info['file_id']}")
                    return (
                        method_info["file_id"],
                        method_info["node_id"],
                        "method"
                    )

        # 策略 3: 检查是否是构造函数调用（类名匹配）
        constructor_result = self._resolve_constructor_call(callee_name, caller_file_id)
        if constructor_result:
            logger.debug(f"[Java OOP] 匹配到构造函数：{callee_name}")
            return constructor_result

        # 未找到匹配
        logger.debug(f"[Java OOP] 未找到方法：{callee_name}，标记为外部或未知")
        return (None, None, "external_or_unknown")
    
    def _disambiguate_overloaded_methods(
        self,
        method_name: str,
        candidates: List[Dict],
        caller_file_id: int,
        call_context: Optional[Dict] = None
    ) -> Optional[Dict]:
        """
        消歧重载方法
        
        Args:
            method_name: 方法名
            candidates: 候选方法列表
            caller_file_id: 调用者文件 ID
            call_context: 调用上下文
        
        Returns:
            最佳匹配的方法信息，无法消歧则返回 None
        """
        if not call_context:
            return None
        
        # TODO: 实现基于参数类型的重载消歧
        # 目前返回 None，让调用者使用保守策略
        return None
    
    def _resolve_constructor_call(
        self,
        callee_name: str,
        caller_file_id: int
    ) -> Optional[Tuple[int, int, str]]:
        """
        解析构造函数调用

        Java 中构造函数调用使用类名，如 new ClassName()
        策略：
        1. 优先匹配同一文件内的类
        2. 匹配项目中的其他类

        Args:
            callee_name: 可能是类名的方法名
            caller_file_id: 调用者文件 ID

        Returns:
            (file_id, node_id, 'constructor') 或 None
        """
        # 策略 1: 检查同一文件内的类
        file_class_key = f"{caller_file_id}:{callee_name}"
        if file_class_key in self.classes_by_file_name:
            class_info = self.classes_by_file_name[file_class_key]
            logger.debug(f"[Java OOP] 匹配到同文件构造函数：{callee_name} @ file {caller_file_id}")
            return (
                class_info["file_id"],
                class_info["node_id"],
                "constructor"
            )

        # 策略 2: 检查项目中的类（可能有多个同名类，优先返回第一个）
        if callee_name in self.classes_by_name:
            candidates = self.classes_by_name[callee_name]
            if len(candidates) == 1:
                class_info = candidates[0]
                logger.debug(f"[Java OOP] 匹配到唯一构造函数：{callee_name} @ file {class_info['file_id']}")
                return (
                    class_info["file_id"],
                    class_info["node_id"],
                    "constructor"
                )
            else:
                # 多个候选，优先选择同一文件内的
                same_file_candidates = [c for c in candidates if c["file_id"] == caller_file_id]
                if same_file_candidates:
                    class_info = same_file_candidates[0]
                    logger.debug(f"[Java OOP] 匹配到同文件构造函数（多候选）: {callee_name} @ file {class_info['file_id']}")
                    return (
                        class_info["file_id"],
                        class_info["node_id"],
                        "constructor"
                    )
                # 使用第一个候选（保守策略）
                class_info = candidates[0]
                logger.debug(f"[Java OOP] 匹配到构造函数（多候选，使用第一个）: {callee_name} @ file {class_info['file_id']}")
                return (
                    class_info["file_id"],
                    class_info["node_id"],
                    "constructor"
                )

        return None
    
    def get_method_signature(
        self,
        file_id: int,
        node_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        获取方法签名信息
        
        Args:
            file_id: 文件 ID
            node_id: 节点 ID
        
        Returns:
            方法签名字典，包含参数类型、返回类型等
        """
        # TODO: 从 base_node 中提取方法签名信息
        return None
    
    def get_inherited_methods(
        self,
        class_name: str,
        file_id: int
    ) -> List[Dict[str, Any]]:
        """
        获取继承的方法列表
        
        Args:
            class_name: 类名
            file_id: 文件 ID
        
        Returns:
            继承的方法列表
        """
        class_key = f"{file_id}:{class_name}"
        if class_key not in self.class_hierarchy:
            return []
        
        inherited = []
        parent_classes = self.class_hierarchy[class_key]
        
        for parent in parent_classes:
            # TODO: 查找父类的方法
            pass
        
        return inherited
