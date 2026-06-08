"""JavaScript LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _js_is_async(node: SyntaxNode) -> bool:
    for i in range(node.child_count):
        c = node.child(i)
        if c and c.type == "async":
            return True
    return False


def _js_is_static(node: SyntaxNode) -> bool:
    for i in range(node.child_count):
        c = node.child(i)
        if c and c.type == "static":
            return True
    return False


def _js_extract_import(node: SyntaxNode, source: str) -> dict | None:
    source_node = node.child_by_field_name("source")
    if source_node:
        mod = source[source_node.start_byte:source_node.end_byte].strip("'\"")
        if mod:
            return {"module_name": mod}
    return None


def _js_is_exported(node: SyntaxNode, source: str) -> bool:
    cur = node.parent
    while cur:
        if cur.type == "export_statement":
            return True
        cur = cur.parent
    return False


JAVASCRIPT = LanguageExtractor(
    function_types=("function_declaration", "arrow_function", "function_expression"),
    class_types=("class_declaration",),
    method_types=("method_definition",),
    import_types=("import_statement",),
    call_types=("call_expression",),
    instantiation_types=("new_expression",),
    variable_types=("lexical_declaration", "variable_declaration"),
    field_types=("field_definition",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    is_async=_js_is_async,
    is_static=_js_is_static,
    is_exported=_js_is_exported,
    extract_import=_js_extract_import,
)
