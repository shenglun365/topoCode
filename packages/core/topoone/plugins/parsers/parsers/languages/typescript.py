"""TypeScript LanguageExtractor

Inherits JavaScript extractor patterns, adds type-specific types.
"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor
from .javascript import _js_is_async, _js_is_static, _js_is_exported, _js_extract_import


def _ts_get_visibility(node: SyntaxNode) -> str | None:
    for i in range(node.child_count):
        c = node.child(i)
        if c and c.type == "accessibility_modifier":
            t = c.text.decode() if hasattr(c, 'text') else ""
            if t in ("public", "private", "protected"):
                return t
    return None


def _ts_is_const(node: SyntaxNode) -> bool:
    if node.type == "lexical_declaration":
        for i in range(node.child_count):
            c = node.child(i)
            if c and c.type == "const":
                return True
    return False


def _ts_resolve_body(node: SyntaxNode, body_field: str) -> SyntaxNode | None:
    if node.type == "public_field_definition":
        for i in range(node.named_child_count):
            c = node.named_child(i)
            if c and c.type in ("arrow_function", "function_expression"):
                return c.child_by_field_name(body_field)
    # 默认: 普通函数/方法的 body 字段(statement_block)。
    # 此前恒返回 None → TS 函数体内 calls/instantiates/refs 从未被提取(缺陷修复)。
    for i in range(node.child_count):
        c = node.child(i)
        if c is not None and node.field_name_for_child(i) == body_field:
            return c
    return None


def _ts_extract_param(node: SyntaxNode, source: str) -> dict | None:
    """parameter: `x: Foo` — pattern 为标识符才有类型可推断（解构模式跳过）"""
    name_node = node.child_by_field_name("pattern") or node.child_by_field_name("name")
    type_node = node.child_by_field_name("type")
    if name_node is None or type_node is None or name_node.type not in ("identifier", "shorthand_property_identifier"):
        return None
    return {
        "name": source[name_node.start_byte:name_node.end_byte],
        "type": source[type_node.start_byte:type_node.end_byte],
    }


TYPESCRIPT = LanguageExtractor(
    function_types=("function_declaration", "arrow_function", "function_expression"),
    class_types=("class_declaration", "abstract_class_declaration"),
    method_types=("method_definition", "public_field_definition"),
    interface_types=("interface_declaration",),
    enum_types=("enum_declaration",),
    enum_member_types=("property_identifier", "enum_assignment"),
    type_alias_types=("type_alias_declaration",),
    import_types=("import_statement",),
    call_types=("call_expression",),
    instantiation_types=("new_expression",),
    variable_types=("lexical_declaration", "variable_declaration"),
    property_types=("property_signature",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    return_field="return_type",
    is_async=_js_is_async,
    is_static=_js_is_static,
    is_const=_ts_is_const,
    is_exported=_js_is_exported,
    extract_import=_js_extract_import,
    extract_param=_ts_extract_param,
    extract_visibility=_ts_get_visibility,
    resolve_body=_ts_resolve_body,
)
