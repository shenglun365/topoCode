"""PHP LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _php_visibility(node: SyntaxNode) -> str | None:
    text = node.text.decode() if hasattr(node, 'text') else ""
    if "public" in text: return "public"
    if "private" in text: return "private"
    if "protected" in text: return "protected"
    return None


def _php_is_static(node: SyntaxNode) -> bool:
    for c in node.named_children:
        if c and c.type == "static_modifier":
            return True
    return False


def _php_extract_import(node: SyntaxNode, source: str) -> dict | None:
    if node.type == "namespace_use_declaration":
        name_node = node.child_by_field_name("name")
        if name_node:
            return {"module_name": source[name_node.start_byte:name_node.end_byte]}
        for c in node.named_children:
            if c.type == "qualified_name" or c.type == "namespace_name":
                return {"module_name": source[c.start_byte:c.end_byte]}
    return None


PHP = LanguageExtractor(
    function_types=("function_definition",),
    class_types=("class_declaration", "trait_declaration"),
    method_types=("method_declaration",),
    interface_types=("interface_declaration",),
    enum_types=("enum_declaration",),
    import_types=("namespace_use_declaration",),
    call_types=("function_call_expression", "member_call_expression", "scoped_call_expression"),
    variable_types=("assignment_expression",),
    field_types=("property_declaration",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    extract_visibility=_php_visibility,
    is_static=_php_is_static,
    extract_import=_php_extract_import,
)
