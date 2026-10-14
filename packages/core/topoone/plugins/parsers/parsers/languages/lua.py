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


def _lua_import(node: SyntaxNode, source: str) -> dict | None:
    """require "mod" / require("mod") / local m = require("mod") → 依赖边来源"""
    if node.type != "function_call":
        return None
    fn = node.child_by_field_name("name") if node.child_by_field_name("name") is not None else None
    if fn is None:
        fn = next((c for c in node.named_children if c.type in ("identifier", "dot_index_expression", "method_index_expression")), None)
    if fn is None:
        return None
    fn_text = source[fn.start_byte:fn.end_byte]
    if fn_text.split(".")[-1] != "require":
        return None
    args = next((c for c in node.named_children if c.type == "arguments"), None)
    if args is None:
        return None
    for a in args.named_children:
        if a.type == "string":
            text = source[a.start_byte:a.end_byte].strip()
            mod = text.strip("\"'")
            if mod:
                return {"module_name": mod}
    return None


LUA = LanguageExtractor(
    function_types=("function_declaration",),
    call_types=("function_call",),
    variable_types=("variable_declaration",),
    import_types=("function_call",),  # require() → 依赖边（extract_import 过滤非 require 调用）
    extract_import=_lua_import,
    name_field="name",
    body_field="body",
    params_field="parameters",
    methods_are_top_level=True,
    is_exported=_lua_is_exported,
)
