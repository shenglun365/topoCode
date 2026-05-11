# config/lang_swift.py
from .lang_base import LanguageConfig

IMPORTANT_NODE_TYPES_SET = {
    'source_file',
    'function_declaration', 'class_declaration', 'struct_declaration',
    'protocol_declaration', 'enum_declaration',
    'initializer_declaration', 'deinitializer_declaration',
    'parameter',
    'identifier', 'type_identifier',
    'function_call', 'subscript_call',
    'assignment', 'infix_operator',
    'if_statement', 'for_statement', 'while_statement', 'repeat_while_statement',
    'switch_statement',
    'return_statement', 'break_statement', 'continue_statement',
    'code_block',
    'import_declaration',
    'member_access',  # obj.property
}

IS_NAME_NODE_TYPES = {'identifier', 'type_identifier'}

SCOPE_CREATING_TYPES = {
    "source_file",
    "function_declaration",
    "class_declaration",
    "struct_declaration",
    "code_block",
}

DEFINING_CONTEXT_TYPES = {
    "function_declaration",
    "class_declaration",
    "struct_declaration",
    "enum_declaration",
    "import_declaration",
    "variable_declaration",  # var/let x = ...
}

NODE_TYPE_TO_OP = {
    'function_declaration': 'def',
    'class_declaration': 'def',
    'struct_declaration': 'def',
    'variable_declaration': 'def',
    'function_call': 'call',
    'assignment': 'assign',
    'infix_operator': 'arith',
    'return_statement': 'return',
    'if_statement': 'control',
    'for_statement': 'control',
    'while_statement': 'control',
    'switch_statement': 'control',
}

CONFIG = LanguageConfig(
    important_node_types=IMPORTANT_NODE_TYPES_SET,
    is_name_node_types=IS_NAME_NODE_TYPES,
    scope_creating_types=SCOPE_CREATING_TYPES,
    defining_context_types=DEFINING_CONTEXT_TYPES,
    node_type_to_op=NODE_TYPE_TO_OP,
)