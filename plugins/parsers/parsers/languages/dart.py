"""Dart LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _dart_resolve_body(node: SyntaxNode, body_field: str) -> SyntaxNode | None:
    """Dart puts function_body as sibling, not child"""
    if node.type == "function_signature":
        parent = node.parent
        if parent:
            for c in parent.named_children:
                if c and c.type == "function_body":
                    return c
    return node.child_by_field_name(body_field)


DART = LanguageExtractor(
    function_types=("function_signature",),
    class_types=("class_definition", "mixin_declaration", "extension_declaration"),
    method_types=("function_signature",),
    enum_types=("enum_declaration",),
    import_types=("import_or_export",),
    call_types=("function_expression_invocation", "method_invocation"),
    variable_types=("variable_declaration",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    return_field="return_type",
    resolve_body=_dart_resolve_body,
)
