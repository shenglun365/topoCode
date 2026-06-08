"""Swift LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _swift_classify(node: SyntaxNode) -> str:
    """Swift reuses class_declaration for classes, structs, and some enums"""
    # Check children for distinguishing keywords
    text = node.text.decode() if hasattr(node, 'text') else ""
    if text.startswith("struct"):
        return "struct"
    if text.startswith("enum"):
        return "enum"
    if text.startswith("protocol"):
        return "protocol"
    return "class"


SWIFT = LanguageExtractor(
    function_types=("function_declaration",),
    class_types=("class_declaration",),
    interface_types=("protocol_declaration",),
    struct_types=("struct_declaration",),
    enum_types=("enum_declaration",),
    method_types=("function_declaration",),
    type_alias_types=("typealias_declaration",),
    import_types=("import_declaration",),
    call_types=("call_expression",),
    variable_types=("property_declaration", "variable_declaration"),
    name_field="name",
    body_field="body",
    params_field="parameters",
    classify_class=_swift_classify,
    methods_are_top_level=True,
)
