# config/lang_csharp.py
from .lang_base import LanguageConfig

IMPORTANT_NODE_TYPES_SET = {
    'compilation_unit',
    'class_declaration', 'struct_declaration', 'interface_declaration',
    'method_declaration', 'constructor_declaration',
    'parameters', 'parameter',
    'identifier',
    'invocation_expression',
    'assignment_expression',
    'binary_expression', 'prefix_unary_expression', 'postfix_unary_expression',
    'if_statement', 'for_statement', 'foreach_statement', 'while_statement',
    'switch_statement',
    'return_statement', 'break_statement', 'continue_statement',
    'block',
    'using_directive',
    'member_access_expression',  # obj.Property
}

IS_NAME_NODE_TYPES = {'identifier'}

SCOPE_CREATING_TYPES = {
    "compilation_unit",
    "class_declaration",
    "method_declaration",
    "block",
}

DEFINING_CONTEXT_TYPES = {
    "class_declaration",
    "method_declaration",
    "using_directive",
    "variable_declaration",  # var x = ... 或 explicit type
}

NODE_TYPE_TO_OP = {
    'class_declaration': 'def',
    'method_declaration': 'def',
    'variable_declaration': 'def',
    'invocation_expression': 'call',
    'assignment_expression': 'assign',
    'binary_expression': 'arith',
    'return_statement': 'return',
    'if_statement': 'control',
    'for_statement': 'control',
    'foreach_statement': 'control',
}

CONFIG = LanguageConfig(
    important_node_types=IMPORTANT_NODE_TYPES_SET,
    is_name_node_types=IS_NAME_NODE_TYPES,
    scope_creating_types=SCOPE_CREATING_TYPES,
    defining_context_types=DEFINING_CONTEXT_TYPES,
    node_type_to_op=NODE_TYPE_TO_OP,
)