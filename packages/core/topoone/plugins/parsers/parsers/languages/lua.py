"""Lua/Luau LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _lua_is_exported(node: SyntaxNode, source: str) -> bool:
    """Lua: check if function is assigned to a non-local variable"""
    parent = node.parent
    if parent and parent.type == "assignment_statement":
        var_list = next((c for c in parent.named_children if c.type == "variable_list"), None)
        if var_list:
            first = var_list.named_child(0)
            if first and first.type == "identifier":
                return True
    return False


LUA = LanguageExtractor(
    function_types=("function_declaration",),
    call_types=("function_call",),
    variable_types=("variable_declaration",),
    import_types=(),  # require() calls are handled by extract_bare_call in walker
    name_field="name",
    body_field="body",
    params_field="parameters",
    methods_are_top_level=True,
    is_exported=_lua_is_exported,
)
