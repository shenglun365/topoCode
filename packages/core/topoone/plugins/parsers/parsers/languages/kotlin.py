"""Kotlin LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _kotlin_visibility(node: SyntaxNode) -> str | None:
    for c in node.named_children:
        if c and c.type == "modifiers":
            t = c.text.decode() if hasattr(c, 'text') else ""
            if "public" in t: return "public"
            if "private" in t: return "private"
            if "protected" in t: return "protected"
            if "internal" in t: return "internal"
    return None


def _kotlin_classify(node: SyntaxNode) -> str:
    """Kotlin reuses class_declaration for interfaces and objects"""
    text = node.text.decode() if hasattr(node, 'text') else ""
    if text.startswith("interface"):
        return "interface"
    if text.startswith("object"):
        return "class"  # object declarations are singleton classes
    if "enum class" in text:
        return "enum"
    return "class"


def _kotlin_package(node: SyntaxNode, source: str) -> str | None:
    for c in node.named_children:
        if c.type == "identifier":
            return source[c.start_byte:c.end_byte]
    return None


def _kotlin_resolve_body(node: SyntaxNode, source: str):
    """kotlin 函数体字段是 function_body 而非 body"""
    for c in node.named_children:
        if c.type == "function_body":
            return c
    return None


def _kotlin_extract_import(node: SyntaxNode, source: str) -> dict | None:
    """import com.demo.Store — qualified_identifier 整体取文本"""
    for c in node.named_children:
        if c.type in ("qualified_identifier", "dot_qualified_expression",
                      "identifier", "simple_identifier"):
            return {"module_name": source[c.start_byte:c.end_byte]}
    return None


def _kotlin_extract_param(node: SyntaxNode, source: str) -> dict | None:
    """parameter: `x: Foo` — 标识符为名，其后 user_type/类型节点为类型"""
    name_node = None
    type_node = None
    for c in node.named_children:
        if c.type in ("identifier", "simple_identifier") and name_node is None:
            name_node = c
        elif c.type in ("user_type", "nullable_type", "function_type", "type",
                        "generic_type", "attribute"):
            type_node = c
    if name_node is None or type_node is None:
        return None
    return {
        "name": source[name_node.start_byte:name_node.end_byte],
        "type": source[type_node.start_byte:type_node.end_byte],
    }


KOTLIN = LanguageExtractor(
    class_types=("class_declaration", "object_declaration"),
    method_types=("function_declaration",),
    interface_types=("class_declaration",),
    enum_types=("class_declaration",),
    import_types=("import",),
    call_types=("call_expression",),
    variable_types=("property_declaration",),
    package_types=("package_header",),
    name_field="name",
    body_field="body",
    params_field="value_parameters",
    classify_class=_kotlin_classify,
    extract_visibility=_kotlin_visibility,
    extract_package=_kotlin_package,
    extract_import=_kotlin_extract_import,
    extract_param=_kotlin_extract_param,
    resolve_body=_kotlin_resolve_body,
)
