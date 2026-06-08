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


KOTLIN = LanguageExtractor(
    class_types=("class_declaration", "object_declaration"),
    method_types=("function_declaration",),
    interface_types=("class_declaration",),
    enum_types=("class_declaration",),
    import_types=("import_header",),
    call_types=("call_expression",),
    variable_types=("property_declaration",),
    package_types=("package_header",),
    name_field="name",
    body_field="body",
    params_field="value_parameters",
    classify_class=_kotlin_classify,
    extract_visibility=_kotlin_visibility,
    extract_package=_kotlin_package,
)
