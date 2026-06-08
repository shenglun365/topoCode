"""C# LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _csharp_visibility(node: SyntaxNode) -> str | None:
    for c in node.named_children:
        if c and c.type == "modifier":
            t = c.text.decode() if hasattr(c, 'text') else ""
            if "public" in t: return "public"
            if "private" in t: return "private"
            if "protected" in t: return "protected"
            if "internal" in t: return "internal"
    return None


def _csharp_is_static(node: SyntaxNode) -> bool:
    for c in node.named_children:
        if c and c.type == "modifier" and hasattr(c, 'text'):
            if "static" in c.text.decode():
                return True
    return False


def _csharp_import(node: SyntaxNode, source: str) -> dict | None:
    for c in node.named_children:
        if c.type in ("identifier", "qualified_name"):
            return {"module_name": source[c.start_byte:c.end_byte]}
    return None


CSHARP = LanguageExtractor(
    class_types=("class_declaration",),
    struct_types=("struct_declaration",),
    interface_types=("interface_declaration",),
    enum_types=("enum_declaration",),
    method_types=("method_declaration", "constructor_declaration"),
    import_types=("using_directive",),
    call_types=("invocation_expression",),
    instantiation_types=("object_creation_expression",),
    variable_types=("variable_declaration", "local_declaration_statement"),
    field_types=("field_declaration",),
    property_types=("property_declaration",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    extract_visibility=_csharp_visibility,
    is_static=_csharp_is_static,
    extract_import=_csharp_import,
)
