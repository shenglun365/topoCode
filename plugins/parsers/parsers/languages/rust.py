"""Rust LanguageExtractor"""
from . import LanguageExtractor
from ..core.node_types import NodeKind


RUST = LanguageExtractor(
    function_types=("function_item",),
    struct_types=("struct_item",),
    enum_types=("enum_item",),
    enum_member_types=("enum_variant",),
    type_alias_types=("type_item",),
    import_types=("use_declaration",),
    call_types=("call_expression",),
    variable_types=("let_declaration", "const_item", "static_item"),
    field_types=("field_declaration", "struct_field_declaration"),
    interface_types=("trait_item",),
    name_field="name",
    body_field="body",
    params_field="parameters",
    interface_kind=NodeKind.TRAIT,
)
