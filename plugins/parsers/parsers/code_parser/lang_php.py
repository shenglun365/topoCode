# config/lang_php.py
from .lang_base import LanguageConfig

IMPORTANT_NODE_TYPES_SET = {
    'program',
    'function_definition', 'method_declaration',
    'class_declaration', 'interface_declaration', 'trait_declaration',
    'formal_parameters', 'simple_parameter',
    'variable_name', 'name',
    'function_call_expression', 'member_call_expression',
    'assignment_expression',
    'binary_expression', 'unary_op_expression',
    'if_statement', 'for_statement', 'while_statement', 'foreach_statement',
    'switch_statement',
    'return_statement', 'break_statement', 'continue_statement',
    'compound_statement',
    'use_declaration',
    'namespace_definition',
}

IS_NAME_NODE_TYPES = {'name', 'variable_name'}

SCOPE_CREATING_TYPES = {
    "program",
    "function_definition",
    "method_declaration",
    "class_declaration",
    "compound_statement",
}

DEFINING_CONTEXT_TYPES = {
    "function_definition",
    "class_declaration",
    "use_declaration",
    "assignment_expression",  # $x = ...
}

NODE_TYPE_TO_OP = {
    'function_definition': 'def',
    'class_declaration': 'def',
    'assignment_expression': 'assign',
    'function_call_expression': 'call',
    'member_call_expression': 'call',
    'binary_expression': 'arith',
    'return_statement': 'return',
    'if_statement': 'control',
    'for_statement': 'control',
    'foreach_statement': 'control',
}

NAME_EXTRACT_RULES = {
    # 函数定义
    "function_definition": ["name"],
    "method_declaration": ["name"],

    # 类/接口/Trait
    "class_declaration": ["name"],
    "interface_declaration": ["name"],
    "trait_declaration": ["name"],

    # 变量/属性
    "assignment_expression": ["variable_name"],

    # 导入
    "use_declaration": ["name"],

    # 命名空间
    "namespace_definition": ["name"],
}

CONFIG = LanguageConfig(
    important_node_types=IMPORTANT_NODE_TYPES_SET,
    is_name_node_types=IS_NAME_NODE_TYPES,
    scope_creating_types=SCOPE_CREATING_TYPES,
    defining_context_types=DEFINING_CONTEXT_TYPES,
    node_type_to_op=NODE_TYPE_TO_OP,
    name_extract_rules=NAME_EXTRACT_RULES,
)