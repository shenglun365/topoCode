# parsers/languages/code_parser/lang_ts.py
"""
TypeScript 语言 AST 配置

基于 tree-sitter-typescript 的节点类型定义。
支持 TypeScript 4.x/5.x 版本。

参考：https://github.com/tree-sitter/tree-sitter-typescript
"""
from .lang_base import LanguageConfig

# TypeScript 配置继承 JavaScript，并添加类型相关节点
IMPORTANT_NODE_TYPES_SET = {
    # === 继承 JavaScript 的所有节点 ===
    'program',
    'import_statement', 'export_statement',
    'function_declaration', 'arrow_function', 'async_function_declaration',
    'class_declaration', 'method_definition',
    'variable_declaration', 'variable_declarator',
    'identifier', 'property_identifier',
    'string', 'number', 'template_string',
    'call_expression', 'new_expression', 'member_expression',
    'assignment_expression', 'binary_expression',
    'if_statement', 'for_statement', 'while_statement',
    'switch_statement', 'try_statement',
    'return_statement', 'throw_statement',
    'object', 'array',
    'arguments',                  # 参数列表
    'sequence_expression',        # 序列表达式
    'spread_element',             # 展开元素
    'escape_sequence',            # 转义序列
    'regex_flags',                # 正则标志
    'await',                      # await 关键字
    'function',                   # function 关键字
    'comment',                    # 注释
    
    # === TypeScript 特有类型注解 ===
    'type_annotation',              # 类型注解 (: Type)
    'type_identifier',              # 类型标识符
    'predefined_type',              # 预定义类型 (string, number, boolean 等)
    'union_type',                   # 联合类型 (A | B)
    'intersection_type',            # 交叉类型 (A & B)
    'tuple_type',                   # 元组类型
    'array_type',                   # 数组类型 (T[])
    'generic_type',                 # 泛型类型 (Array<T>)
    'type_arguments',               # 类型参数
    'type_parameters',              # 类型参数声明
    'type_parameter',               # 类型参数
    'type_constraint',              # 类型约束 (extends)
    'default_type',                 # 默认类型
    
    # === 类型别名和接口 ===
    'type_alias_declaration',       # type 别名
    'interface_declaration',        # interface 声明
    'interface_body',               # interface 体
    'interface_heritage_clause',    # extends/implements
    'implements_clause',            # implements 子句
    'extends_clause',                # extends 子句
    
    # === 枚举和命名空间 ===
    'enum_declaration',             # enum 声明
    'enum_body',                    # enum 体
    'enum_member',                  # enum 成员
    'namespace_declaration',        # namespace 声明
    'module_declaration',           # module 声明
    'internal_module',              # 内部模块
    'external_module',              # 外部模块
    
    # === 函数特有 ===
    'return_type_annotation',       # 返回类型注解
    'optional_parameter',           # 可选参数 (?)
    'rest_parameter',               # 剩余参数
    'parameter_property',           # 参数属性 (public x: number)
    
    # === 类成员特有 ===
    'accessibility_modifier',       # public/protected/private
    'static_modifier',              # static
    'abstract_modifier',            # abstract
    'readonly_modifier',            # readonly
    'override_modifier',            # override
    'declare_modifier',             # declare
    'async_modifier',               # async
    'decorator',                    # 装饰器
    
    # === 类型特有表达式 ===
    'type_assertion',               # 类型断言 (<T>x or x as T)
    'as_expression',                # as 表达式
    'satisfies_expression',         # satisfies 表达式 (TS 4.9+)
    'non_null_expression',          # 非空断言 (x!)
    'instantiation_expression',     # 实例化表达式
    
    # === 导入/导出特有 ===
    'import_type',                  # import type
    'export_type',                  # export type
    'type_only_import_clause',      # type-only import
    'type_only_export_clause',      # type-only export
    'require_call',                 # require()
    
    # === 特有字面量 ===
    'literal_type',                 # 字面量类型
    'string_type',                  # 字符串类型
    'number_type',                  # 数字类型
    'boolean_type',                 # 布尔类型
    'bigint_type',                  # BigInt 类型
    'symbol_type',                  # symbol 类型
    'any_type',                     # any 类型
    'unknown_type',                 # unknown 类型
    'void_type',                    # void 类型
    'never_type',                   # never 类型
    'null_type',                    # null 类型
    'undefined_type',               # undefined 类型
    
    # === 关键字（单独节点） ===
    'from', 'import', 'export', 'as', 'else', 'static', 'new', 'typeof',
    'void', 'class', 'extends', 'in', 'instanceof', 'try', 'catch',
    'case', 'default', 'while', 'do', 'for', 'of', 'delete', 'break', 'switch',
    
    # === 特有模式 ===
    'type_predicate',               # 类型谓词 (is Type)
    'asserts_clause',               # asserts 子句
    'indexed_access_type',          # 索引访问类型
    'conditional_type',             # 条件类型 (T extends U ? X : Y)
    'infer_clause',                 # infer 子句
    'template_literal_type',        # 模板字面量类型
    'string_template_type',         # 字符串模板类型
    'keyof_type',                   # keyof 类型
    'lookup_type',                  # 查找类型
    'parenthesized_type',           # 括号类型
    'object_type',                  # 对象类型
    'object_member',                # 对象成员
    'property_signature',           # 属性签名
    'method_signature',             # 方法签名
    'call_signature',               # 调用签名
    'construct_signature',          # 构造函数签名
    'index_signature',              # 索引签名
    
    # === 映射类型 ===
    'mapped_type',                  # 映射类型
    'mapped_type_clause',           # 映射类型子句
    'conditional_type_clause',      # 条件类型子句
    'readonly_type',                # readonly 类型
    'optional_type',                # optional 类型
    
    # === 其他 ===
    'import_equals_declaration',    # import x = require()
    'import_require_clause',        # import require 子句
    'external_module_reference',    # 外部模块引用
    'named_imports',                # 命名导入
    'named_exports',                # 命名导出
    'export_specifier',             # 导出说明符
    'import_specifier',             # 导入说明符
    'export_assignment',            # export =
    'this_type',                    # this 类型
    'existential_type',             # 存在类型
    
    # === JSX (TypeScript React) ===
    'jsx_element',                  # JSX 元素
    'jsx_self_closing_element',     # JSX 自关闭元素
    'jsx_opening_element',          # JSX 开始标签
    'jsx_closing_element',          # JSX 结束标签
    'jsx_attribute',                # JSX 属性
    'jsx_expression',               # JSX 表达式
    'jsx_text',                     # JSX 文本
    'jsx_namespace_name',           # JSX 命名空间名称
    'jsx_fragment',                 # JSX Fragment
}

# ============================================================================
# 名称节点类型
# ============================================================================

IS_NAME_NODE_TYPES = {
    'identifier',
    'property_identifier',
    'type_identifier',
    'predefined_type',
    'enum_member_name',
    'namespace_name',
    'interface_name',
    'type_alias_name',
    'function_name',
    'class_name',
    'method_name',
    'parameter_name',
    'variable_name',
    'string',                     # 字符串字面量（用于 import 模块路径）
    'string_fragment',            # 字符串片段（用于 import 模块路径）
    'jsx_namespace_name',         # JSX 命名空间名称
}

# ============================================================================
# 作用域创建类型
# ============================================================================

SCOPE_CREATING_TYPES = {
    "program",
    "function_declaration",
    "arrow_function",
    "async_function_declaration",
    "class_declaration",
    "interface_declaration",
    "type_alias_declaration",
    "enum_declaration",
    "namespace_declaration",
    "module_declaration",
    "method_definition",
    "statement_block",
    "for_statement",
    "if_statement",
    "switch_statement",
    "catch_clause",
    "object",
}

# ============================================================================
# 定义上下文类型
# ============================================================================

DEFINING_CONTEXT_TYPES = {
    # 函数
    "function_declaration",
    "arrow_function",
    "async_function_declaration",
    "method_definition",
    
    # 类/接口/类型
    "class_declaration",
    "interface_declaration",
    "type_alias_declaration",
    "enum_declaration",
    "enum_member",
    
    # 命名空间/模块
    "namespace_declaration",
    "module_declaration",
    
    # 变量
    "variable_declaration",
    "variable_declarator",
    "parameter_property",
    
    # 参数
    "formal_parameters",
    "optional_parameter",
    "rest_parameter",
    
    # 导入
    "import_statement",
    "import_specifier",
    "import_equals_declaration",
}

# ============================================================================
# 节点类型到操作的映射
# ============================================================================

NODE_TYPE_TO_OP = {
    # === 定义操作 ===
    'function_declaration': 'def',
    'arrow_function': 'def',
    'async_function_declaration': 'def',
    'class_declaration': 'def',
    'interface_declaration': 'def',
    'type_alias_declaration': 'def',
    'enum_declaration': 'def',
    'enum_member': 'def',
    'namespace_declaration': 'def',
    'module_declaration': 'def',
    'method_definition': 'def',
    'variable_declaration': 'def',
    'variable_declarator': 'def',
    'property_signature': 'def',
    'method_signature': 'def',
    
    # === 导入/导出 ===
    'import_statement': 'import',
    'export_statement': 'export',
    'import_type': 'import',
    'export_type': 'export',
    
    # === 调用操作 ===
    'call_expression': 'call',
    'new_expression': 'call',
    'require_call': 'call',
    
    # === JSX 组件调用 ===
    'jsx_element': 'call',
    'jsx_self_closing_element': 'call',
    
    # === 操作符 ===
    'typeof': 'type',
    'void': 'void',
    'delete': 'delete',
    'instanceof': 'instanceof',
    'in': 'in',
    'new': 'new',

    # === 赋值操作 ===
    'assignment_expression': 'assign',
    'variable_declarator': 'assign',
    
    # === 类型操作 ===
    'type_annotation': 'type',
    'type_assertion': 'cast',
    'as_expression': 'cast',
    'satisfies_expression': 'type',
    'non_null_expression': 'type',
    
    # === 算术操作 ===
    'binary_expression': 'arith',
    'unary_expression': 'arith',
    'sequence_expression': 'seq',
    'spread_element': 'spread',

    # === 控制流 ===
    'return_statement': 'return',
    'if_statement': 'control',
    'for_statement': 'control',
    'while_statement': 'control',
    'switch_statement': 'control',
    'break_statement': 'control',
    'continue_statement': 'control',
    
    # === 异常处理 ===
    'throw_statement': 'throw',
    'try_statement': 'try',
    'catch_clause': 'catch',
    'finally_clause': 'finally',
    
    # === 条件操作 ===
    'ternary_expression': 'cond',
    'conditional_type': 'cond',
    
    # === 异步 ===
    'await_expression': 'await',
    'yield_expression': 'yield',
}


# ============================================================================
# 名称提取规则
# ============================================================================

NAME_EXTRACT_RULES = {
    # 函数定义
    "function_declaration": ["identifier"],
    "generator_function": ["identifier"],
    "function_expression": ["identifier"],
    "arrow_function": ["identifier"],
    "method_definition": ["property_identifier"],
    "pair": ["identifier"],

    # 类定义
    "class_declaration": ["identifier"],
    "class_expression": ["identifier"],
    "abstract_class": ["identifier"],

    # 接口/类型
    "interface_declaration": ["identifier"],
    "type_alias_declaration": ["identifier"],
    "type_annotation": ["identifier"],

    # 变量
    "variable_declaration": ["identifier"],
    "lexical_declaration": ["identifier"],
    "constant_declaration": ["identifier"],
    "variable_declarator": ["identifier"],

    # 模块
    "import_statement": ["identifier"],
    "import_clause": ["identifier"],
    "named_imports": ["identifier"],
    "import_specifier": ["identifier"],
    "export_statement": ["identifier"],
    "export_named_declaration": ["identifier"],

    # 调用
    "call_expression": ["identifier", "property_identifier"],
    "new_expression": ["identifier"],
    "chain_expression": ["identifier"],
    "member_expression": ["property_identifier"],
    "tagged_template_expression": ["identifier"],
}
# 创建配置对象
CONFIG = LanguageConfig(
    important_node_types=IMPORTANT_NODE_TYPES_SET,
    is_name_node_types=IS_NAME_NODE_TYPES,
    scope_creating_types=SCOPE_CREATING_TYPES,
    defining_context_types=DEFINING_CONTEXT_TYPES,
    node_type_to_op=NODE_TYPE_TO_OP,
    name_extract_rules=NAME_EXTRACT_RULES,
)

# 导出配置
__all__ = ['CONFIG']
