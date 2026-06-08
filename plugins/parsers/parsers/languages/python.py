"""Python LanguageExtractor"""
from tree_sitter import Node as SyntaxNode

from . import LanguageExtractor
from ..core.node_types import NodeKind


def _py_extract_import(node: SyntaxNode, source: str) -> dict | None:
    """从 import 节点提取模块名"""
    if node.type == "import_from_statement":
        mod = node.child_by_field_name("module_name")
        name = source[mod.start_byte:mod.end_byte] if mod else ""
        return {"module_name": name}
    if node.type == "import_statement":
        # multi-import: handled by walker fallback (dotted_name splitting)
        return None
    return None


def _py_is_async(node: SyntaxNode) -> bool:
    prev = node.prev_sibling
    return prev is not None and prev.type == "async"


PYTHON = LanguageExtractor(
    function_types=("function_definition",),
    class_types=("class_definition",),
    method_types=("function_definition",),
    import_types=("import_statement", "import_from_statement"),
    call_types=("call",),
    variable_types=("assignment",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    return_field="return_type",
    is_async=_py_is_async,
    extract_import=_py_extract_import,
)
