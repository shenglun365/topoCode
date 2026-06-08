"""Java LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _java_visibility(node: SyntaxNode) -> str | None:
    for i in range(node.child_count):
        c = node.child(i)
        if c and c.type == "modifiers":
            t = c.text.decode() if hasattr(c, 'text') else ""
            if "public" in t: return "public"
            if "private" in t: return "private"
            if "protected" in t: return "protected"
    return None


def _java_is_static(node: SyntaxNode) -> bool:
    for i in range(node.child_count):
        c = node.child(i)
        if c and c.type == "modifiers":
            t = c.text.decode() if hasattr(c, 'text') else ""
            if "static" in t:
                return True
    return False


def _java_extract_import(node: SyntaxNode, source: str) -> dict | None:
    for c in node.named_children:
        if c.type == "scoped_identifier":
            return {"module_name": source[c.start_byte:c.end_byte]}
    return None


def _java_extract_package(node: SyntaxNode, source: str) -> str | None:
    for c in node.named_children:
        if c.type in ("scoped_identifier", "identifier"):
            return source[c.start_byte:c.end_byte].strip()
    return None


JAVA = LanguageExtractor(
    function_types=(),
    class_types=("class_declaration",),
    method_types=("method_declaration", "constructor_declaration"),
    interface_types=("interface_declaration",),
    enum_types=("enum_declaration",),
    enum_member_types=("enum_constant",),
    import_types=("import_declaration",),
    call_types=("method_invocation",),
    instantiation_types=("object_creation_expression",),
    variable_types=("local_variable_declaration",),
    field_types=("field_declaration",),
    package_types=("package_declaration",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    return_field="type",
    extract_visibility=_java_visibility,
    is_static=_java_is_static,
    extract_import=_java_extract_import,
    extract_package=_java_extract_package,
)
