"""Ruby LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor


def _ruby_extract_bare_call(node: SyntaxNode, source: str) -> str | None:
    """Ruby: bare identifiers can be method calls without parens"""
    if node.type == "identifier":
        parent = node.parent
        if parent and parent.type in ("call", "method_call"):
            return None  # let the call_expression handler deal
        if parent and parent.type == "argument_list":
            return None  # this is a parameter
        # Bare identifier in expression position = method call
        return source[node.start_byte:node.end_byte]
    return None


def _ruby_import(node: SyntaxNode, source: str) -> dict | None:
    if node.type == "call":
        text = source[node.start_byte:node.end_byte]
        if "require" in text:
            # extract the string argument
            for c in node.named_children:
                if c.type == "argument_list":
                    for a in c.named_children:
                        if a.type == "string":
                            mod = source[a.start_byte:a.end_byte].strip("\"'")
                            return {"module_name": mod}
    return None


RUBY = LanguageExtractor(
    function_types=("method",),
    class_types=("class",),
    method_types=("method",),
    import_types=("call",),  # require calls are 'call' nodes
    call_types=("call", "method_call"),
    variable_types=("assignment",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    methods_are_top_level=True,
    extract_bare_call=_ruby_extract_bare_call,
    extract_import=_ruby_import,
)
