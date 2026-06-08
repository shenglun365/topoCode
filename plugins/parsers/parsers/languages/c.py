"""C LanguageExtractor"""
from . import LanguageExtractor

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
)
