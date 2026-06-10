"""Objective-C LanguageExtractor"""
import re
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor
from ..core.node_types import NodeKind


def _objc_extract_import(node: SyntaxNode, source: str) -> dict | None:
    if node.type == "preproc_include":
        text = source[node.start_byte:node.end_byte].strip()
        m = re.search(r'[<"]([^>"]+)[>"]', text)
        if m:
            return {"module_name": m.group(1)}
    return None


def _objc_extract_name(node: SyntaxNode, source: str) -> str | None:
    """ObjC methods have multi-part selectors like initWithName:age:"""
    if node.type == "method_definition":
        parts = []
        for i in range(node.named_child_count):
            c = node.named_child(i)
            if c and node.field_name_for_named_child(i) == "selector":
                parts.append(source[c.start_byte:c.end_byte])
        if parts:
            return "".join(parts)
    return None


OBJC = LanguageExtractor(
    function_types=("function_definition",),
    class_types=("class_interface", "class_implementation"),
    method_types=("method_definition",),
    interface_types=("protocol_declaration",),
    struct_types=("struct_specifier",),
    enum_types=("enum_specifier",),
    import_types=("preproc_include",),
    call_types=("call_expression", "message_expression"),
    variable_types=("declaration",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    interface_kind=NodeKind.PROTOCOL,
    extract_name=_objc_extract_name,
    extract_import=_objc_extract_import,
)
