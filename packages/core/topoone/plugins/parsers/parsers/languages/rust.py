"""Rust LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor
from ..core.node_types import NodeKind


def _rust_extract_import(node: SyntaxNode, source: str) -> dict | None:
    if node.type == "use_declaration":
        use_node = node.child_by_field_name("argument")
        if use_node:
            return {"module_name": source[use_node.start_byte:use_node.end_byte]}
        text = source[node.start_byte:node.end_byte].strip()
        if text.startswith("use ") and text.endswith(";"):
            mod = text[4:-1].strip()
            return {"module_name": mod}
    return None


RUST = LanguageExtractor(
    function_types=("function_item",),
    struct_types=("struct_item",),
    enum_types=("enum_item",),
    enum_member_types=("enum_variant",),
    type_alias_types=("type_item",),
    import_types=("use_declaration",),
    call_types=("call_expression",),
    variable_types=("let_declaration", "const_item", "static_item"),
    field_types=("field_declaration", "struct_field_declaration"),
    interface_types=("trait_item",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    interface_kind=NodeKind.TRAIT,
    extract_import=_rust_extract_import,
)
