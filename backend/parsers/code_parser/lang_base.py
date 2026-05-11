# parsers/languages/lang_base.py
from typing import Set, Dict, FrozenSet, List, Optional

class LanguageConfig:
    __slots__ = (
        "_important_node_types",
        "_is_name_node_types",
        "_scope_creating_types",
        "_defining_context_types",
        "_node_type_to_op",
        "_name_extract_rules",
    )

    def __init__(
        self,
        important_node_types: Set[str],
        is_name_node_types: Set[str],
        scope_creating_types: Set[str],
        defining_context_types: Set[str],
        node_type_to_op: Dict[str, str],
        name_extract_rules: Optional[Dict[str, List[str]]] = None,
    ):
        # 转为不可变类型
        self._important_node_types = frozenset(important_node_types)
        self._is_name_node_types = frozenset(is_name_node_types)
        self._scope_creating_types = frozenset(scope_creating_types)
        self._defining_context_types = frozenset(defining_context_types)
        self._node_type_to_op = dict(node_type_to_op)  # 若需只读，可用 types.MappingProxyType
        self._name_extract_rules = dict(name_extract_rules) if name_extract_rules else {}

    @property
    def important_node_types(self) -> FrozenSet[str]:
        return self._important_node_types

    @property
    def is_name_node_types(self) -> FrozenSet[str]:
        return self._is_name_node_types

    @property
    def scope_creating_types(self) -> FrozenSet[str]:
        return self._scope_creating_types

    @property
    def defining_context_types(self) -> FrozenSet[str]:
        return self._defining_context_types

    @property
    def node_type_to_op(self) -> Dict[str, str]:
        return self._node_type_to_op  # 或返回 MappingProxyType(self._node_type_to_op)

    @property
    def name_extract_rules(self) -> Dict[str, List[str]]:
        """
        名称提取规则：节点类型 -> 子节点类型列表（优先级顺序）
        
        用于在 AST 解析阶段从子节点提取函数名、类名等
        例如：{"function_declaration": ["identifier", "function_name"]}
        """
        return self._name_extract_rules