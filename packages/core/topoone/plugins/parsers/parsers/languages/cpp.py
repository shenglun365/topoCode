"""C++ LanguageExtractor"""
import re
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _cpp_extract_import(node: SyntaxNode, source: str) -> dict | None:
    if node.type == "preproc_include":
        text = source[node.start_byte:node.end_byte].strip()
        m = re.search(r'[<"]([^>"]+)[>"]', text)
        if m:
            return {"module_name": m.group(1)}
    return None


def _cpp_is_misparsed(name: str, node) -> bool:
    """C++ macros can cause tree-sitter to misparse namespace blocks as functions"""
    if not name or len(name) < 3:
        return False
    return name.isupper() and "_" in name


CPP = LanguageExtractor(
    function_types=("function_definition",),
    class_types=("class_specifier",),
    struct_types=("struct_specifier",),
    enum_types=("enum_specifier",),
    type_alias_types=("type_definition", "alias_declaration"),
    import_types=("preproc_include", "using_declaration"),
    call_types=("call_expression",),
    instantiation_types=("new_expression",),
    variable_types=("declaration",),
    name_field="declarator",        # C++ uses declarator not name field
    body_field="body",
    params_field="parameters",
    is_misparsed_function=_cpp_is_misparsed,
    extract_import=_cpp_extract_import,
)
