"""C LanguageExtractor"""
import re
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _c_extract_import(node: SyntaxNode, source: str) -> dict | None:
    if node.type == "preproc_include":
        text = source[node.start_byte:node.end_byte].strip()
        m = re.search(r'[<"]([^>"]+)[>"]', text)
        if m:
            return {"module_name": m.group(1)}
    return None


C = LanguageExtractor(
    function_types=("function_definition",),
    struct_types=("struct_specifier",),
    enum_types=("enum_specifier",),
    type_alias_types=("type_definition",),
    import_types=("preproc_include",),
    call_types=("call_expression",),
    variable_types=("declaration",),
    name_field="declarator",        # C uses declarator not name field
    body_field="body",
    params_field="parameters",
    extract_import=_c_extract_import,
)
