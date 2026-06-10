"""Scala LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _scala_classify(node: SyntaxNode) -> str:
    text = node.text.decode() if hasattr(node, 'text') else ""
    if text.startswith("trait"):
        return "trait"
    if text.startswith("object"):
        return "class"
    if text.startswith("enum"):
        return "enum"
    return "class"


def _scala_extract_import(node: SyntaxNode, source: str) -> dict | None:
    if node.type == "import_declaration":
        path_node = node.child_by_field_name("path")
        if path_node:
            return {"module_name": source[path_node.start_byte:path_node.end_byte]}
        for c in node.named_children:
            if c.type in ("stable_identifier", "identifier"):
                return {"module_name": source[c.start_byte:c.end_byte]}
    return None


SCALA = LanguageExtractor(
    class_types=("class_definition", "object_definition", "trait_definition"),
    method_types=("function_definition",),
    enum_types=("enum_definition",),
    import_types=("import_declaration",),
    call_types=("call_expression",),
    variable_types=("val_definition", "var_definition"),
    name_field="name",
    body_field="body",
    params_field="parameters",
    classify_class=_scala_classify,
    extract_import=_scala_extract_import,
)
