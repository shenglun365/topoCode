"""C LanguageExtractor"""
import re
from tree_sitter import Node as SyntaxNode

from ..core.node_types import NodeKind
from . import LanguageExtractor

_NAME_FIELDS = ("declarator", "name")          # C 双字段: 声明用 declarator, 预处理用 name
_UNWRAP_TYPES = ("pointer_declarator", "function_declarator",
                 "array_declarator", "field_declarator", "init_declarator")
_IDENT_TYPES = ("identifier", "type_identifier", "field_identifier")


def _c_extract_name(node: SyntaxNode, source: str) -> str | None:
    """declarator → name 字段 fallback(覆盖 preproc_function_def/preproc_def),
    解包指针/函数/数组声明器到最终标识符。"""
    for field in _NAME_FIELDS:
        n = node.child_by_field_name(field)
        while n is not None and n.type in _UNWRAP_TYPES:
            inner = n.child_by_field_name("declarator") or n.named_child(0)
            if inner is None:
                break
            n = inner
        if n is not None and n.type in _IDENT_TYPES:
            return source[n.start_byte:n.end_byte]
    return None


def _c_resolve_type_alias_kind(node: SyntaxNode, source: str) -> NodeKind | None:
    """typedef struct/union/enum {...} Name → 按真实类型建节点(非 type_alias)。
    nginx 615 个 typedef struct 中绝大多数是匿名 struct+typedef 别名形态。"""
    type_child = node.child_by_field_name("type")
    if type_child is None:
        return None
    if type_child.type in ("struct_specifier", "union_specifier"):
        return NodeKind.STRUCT
    if type_child.type == "enum_specifier":
        return NodeKind.ENUM
    return None


def _c_is_const(node: SyntaxNode) -> bool:
    return node.type == "preproc_def"       # 对象宏(#define NGX_OK 0)一律常量


def _c_extract_import(node: SyntaxNode, source: str) -> dict | None:
    if node.type == "preproc_include":
        text = source[node.start_byte:node.end_byte].strip()
        m = re.search(r'[<"]([^>"]+)[>"]', text)
        if m:
            return {"module_name": m.group(1)}
    return None


C = LanguageExtractor(
    function_types=("function_definition", "preproc_function_def"),   # 类函数宏即符号(ngx_memcpy 等)
    struct_types=("struct_specifier",),      # 独立 struct 定义; typedef 内嵌由 resolve_type_alias_kind 接管
    enum_types=("enum_specifier",),
    enum_member_types=("enumerator",),       # enum 成员(NGX_BUSY = -4)
    type_alias_types=("type_definition",),
    import_types=("preproc_include",),
    call_types=("call_expression",),
    variable_types=("declaration", "preproc_def"),   # 对象宏 → 常量
    field_types=("field_declaration",),      # struct 字段
    name_field="declarator",        # C uses declarator not name field
    body_field="body",
    params_field="parameters",
    extract_name=_c_extract_name,
    extract_import=_c_extract_import,
    resolve_type_alias_kind=_c_resolve_type_alias_kind,
    is_const=_c_is_const,
)
