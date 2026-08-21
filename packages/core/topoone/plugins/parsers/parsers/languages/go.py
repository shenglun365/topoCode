"""Go LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor
from ..core.node_types import NodeKind


def _go_resolve_type_alias(node: SyntaxNode, source: str) -> NodeKind | None:
    """Go type_spec wraps struct/interface definitions"""
    type_child = node.child_by_field_name("type")
    if type_child:
        if type_child.type == "struct_type":
            return NodeKind.STRUCT
        if type_child.type == "interface_type":
            return NodeKind.INTERFACE
    return None


def _go_get_receiver(node: SyntaxNode, source: str) -> str | None:
    """Extract receiver type name from method declaration"""
    recv = node.child_by_field_name("receiver")
    if recv:
        for c in recv.named_children:
            if c.type == "type_identifier":
                return source[c.start_byte:c.end_byte]
            if c.type == "pointer_type":
                for cc in c.named_children:
                    if cc.type == "type_identifier":
                        return source[cc.start_byte:cc.end_byte]
    return None


def _go_is_exported(node: SyntaxNode, source: str) -> bool:
    """Go 导出规则: 大写字母开头的名称"""
    name_node = node.child_by_field_name("name")
    if name_node:
        return source[name_node.start_byte:name_node.start_byte + 1].isupper()
    return False


GO = LanguageExtractor(
    function_types=("function_declaration",),
    method_types=("method_declaration",),
    type_alias_types=("type_spec", "type_declaration"),
    import_types=("import_declaration",),
    call_types=("call_expression",),
    variable_types=("var_declaration", "short_var_declaration", "const_declaration"),
    field_types=("field_declaration",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    methods_are_top_level=True,
    resolve_type_alias_kind=_go_resolve_type_alias,
    extract_receiver=_go_get_receiver,
    is_exported=_go_is_exported,
)
