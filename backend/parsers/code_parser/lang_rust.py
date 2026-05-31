# parsers/languages/code_parser/lang_rust.py
"""
Rust 语言 AST 配置

基于 tree-sitter-rust 的节点类型定义。
支持 Rust 2015/2018/2021 Edition。

参考：https://github.com/tree-sitter/tree-sitter-rust
"""
from .lang_base import LanguageConfig

# ============================================================================
# 重要节点类型
# ============================================================================

IMPORTANT_NODE_TYPES_SET = {
    # === 顶层结构 ===
    'source_file',                # Rust 源文件
    
    # === 模块和导入 ===
    'mod_item',                   # mod 模块
    'use_declaration',            # use 导入
    'use_tree',                   # 导入树
    'use_wildcard',               # use *
    'use_as_clause',              # use x as y
    'use_list',                   # 导入列表 {a, b}
    'crate_visibility',           # crate 可见性
    'super_visibility',           # super 可见性
    
    # === 函数定义 ===
    'function_item',              # fn 函数
    'function_signature_item',    # 函数签名 (trait 中)
    'parameters',                 # 参数列表
    'parameter',                  # 参数
    'variadic_parameter',         # 可变参数
    'closure_parameters',         # 闭包参数
    'where_clause',               # where 子句
    'where_predicate',            # where 谓词
    
    # === 异步和协程 ===
    'unsafe_block',               # unsafe 块
    'async_block',                # async 块
    'await_expression',           # await
    'try_block',                  # try 块
    'try_expression',             # ? 表达式
    
    # === 闭包 ===
    'closure_expression',         # 闭包表达式
    'capture_list',               # 捕获列表
    
    # === 结构体 ===
    'struct_item',                # struct 项
    'struct_field_declaration',   # 字段声明
    'struct_field_declaration_list', # 字段列表
    'ordered_field_declaration',  # 有序字段 (元组 struct)
    'field_initializer',          # 字段初始化器
    
    # === 枚举 ===
    'enum_item',                  # enum 项
    'enum_variant',               # 枚举变体
    'field_declaration',          # 字段声明
    
    # === 特征和实现 ===
    'trait_item',                 # trait 项
    'impl_item',                  # impl 项
    'associated_type',            # 关联类型
    'associated_constant',        # 关联常量
    'type_binding',               # 类型绑定
    
    # === 泛型 ===
    'type_parameters',            # 类型参数
    'type_parameter',             # 类型参数
    'lifetime_parameter',         # 生命周期参数
    'const_parameter',            # 常量参数
    'generic_arguments',          # 泛型实参
    'type_arguments',             # 类型实参
    'lifetime_arguments',         # 生命周期实参
    
    # === 类型定义 ===
    'type_alias',                 # type 别名
    'type_identifier',            # 类型标识符
    'primitive_type',             # 原始类型 (i32, String 等)
    'reference_type',             # 引用类型 (&T)
    'pointer_type',               # 指针类型 (*T)
    'array_type',                 # 数组类型
    'slice_type',                 # 切片类型
    'tuple_type',                 # 元组类型
    'unit_type',                  # 单元类型 ()
    'never_type',                 # never 类型 (!)
    'qualified_type',             # 限定类型 (<T as Trait>::Item)
    'macro_type',                 # 宏类型
    
    # === 常量和静态变量 ===
    'constant_item',              # const 常量
    'static_item',                # static 静态变量
    'mutable_specifier',          # mut 可变说明符
    
    # === 标识符和字面量 ===
    'identifier',                 # 标识符
    'field_identifier',           # 字段标识符
    'type_identifier',            # 类型标识符
    'lifetime_identifier',        # 生命周期标识符 ('a)
    'crate_identifier',           # crate 标识符
    'self_identifier',            # self
    'super_identifier',           # super
    'line_string',                # 行字符串 ("...")
    'raw_string_literal',         # 原始字符串 (r"...")
    'byte_string',                # 字节字符串 (b"...")
    'char_literal',               # 字符字面量
    'byte_literal',               # 字节字面量
    'integer_literal',            # 整数
    'float_literal',              # 浮点数
    'boolean_literal',            # true/false
    'underscore',                 # _ 通配符
    
    # === 表达式 ===
    'assignment_expression',      # 赋值表达式
    'compound_assignment_expr',   # 复合赋值 (+=, -=等)
    'call_expression',            # 调用表达式
    'method_invocation',          # 方法调用
    'field_expression',           # 字段表达式
    'array_expression',           # 数组表达式
    'tuple_expression',           # 元组表达式
    'index_expression',           # 索引表达式
    'range_expression',           # 范围表达式 (.., ..=)
    'cast_expression',            # as 转换
    
    # === 运算符表达式 ===
    'binary_expression',          # 二元表达式
    'unary_expression',           # 一元表达式
    'reference_expression',       # &表达式
    'dereference_expression',     # *表达式
    'negation_expression',        # -表达式
    'logical_not_expression',     # !表达式
    
    # === 控制流表达式 ===
    'if_expression',              # if 表达式
    'if_let_expression',          # if let 表达式
    'else_clause',                # else 子句
    'match_expression',           # match 表达式
    'match_arm',                  # match 分支
    'match_pattern',              # match 模式
    'match_arms',                 # match 分支列表
    'wildcard_pattern',           # _ 通配符模式
    'ref_pattern',                # ref 模式
    'mutable_pattern',            # mut 模式
    'struct_pattern',             # struct 模式
    'tuple_struct_pattern',       # 元组 struct 模式
    'slice_pattern',              # 切片模式
    'rest_pattern',               # .. 剩余模式
    'range_pattern',              # 范围模式
    'or_pattern',                 # | 或模式
    'tuple_pattern',              # 元组模式
    'const_block',                # const 块
    
    # === 循环 ===
    'loop_expression',            # loop 循环
    'while_expression',           # while 循环
    'for_expression',             # for 循环
    'break_expression',           # break
    'continue_expression',        # continue
    'return_expression',          # return
    'yield_expression',           # yield
    'label',                      # 标签
    
    # === 块和语句 ===
    'block',                      # 代码块 {}
    'expression_statement',       # 表达式语句
    'let_declaration',            # let 声明
    'let_condition',              # let 条件
    'let_else',                   # let-else
    
    # === 宏 ===
    'macro_invocation',           # 宏调用 (macro!)
    'macro_rule',                 # 宏规则
    'macro_definition',           # 宏定义 (macro_rules!)
    'token_tree',                 # token 树
    'fragment_specifier',         # 片段说明符
    
    # === 属性 ===
    'attribute',                  # 属性 (#[...])
    'inner_attribute',            # 内部属性 (#![...])
    'outer_attribute',            # 外部属性
    'meta_item',                  # 元数据项
    
    # === 可见性 ===
    'visibility_modifiers',       # 可见性修饰符
    'public_modifier',            # pub
    
    # === 其他 ===
    'unsafe_keyword',             # unsafe
    'async_keyword',              # async
    'dyn_keyword',                # dyn
    'move_keyword',               # move
    'ref_keyword',                # ref
    'mut_keyword',                # mut
    'static_keyword',             # static
    'const_keyword',              # const
    'extern_modifier',            # extern
    'abi_string',                 # ABI 字符串
}

# ============================================================================
# 名称节点类型
# ============================================================================

IS_NAME_NODE_TYPES = {
    'identifier',                 # 普通标识符
    'field_identifier',           # 字段标识符
    'type_identifier',            # 类型标识符
    'lifetime_identifier',        # 生命周期标识符
    'crate_identifier',           # crate 标识符
    'function_name',              # 函数名
    'method_name',                # 方法名
    'struct_name',                # struct 名
    'enum_name',                  # enum 名
    'trait_name',                 # trait 名
    'module_name',                # module 名
    'constant_name',              # 常量名
    'static_name',                # static 名
    'parameter_name',             # 参数名
    'variable_name',              # 变量名
    'enum_variant_name',          # 枚举变体名
}

# ============================================================================
# 作用域创建类型
# ============================================================================

SCOPE_CREATING_TYPES = {
    "source_file",                # 文件级作用域 (crate)
    "mod_item",                   # 模块作用域
    "function_item",              # 函数作用域
    "closure_expression",         # 闭包作用域
    "struct_item",                # struct 作用域
    "enum_item",                  # enum 作用域
    "trait_item",                 # trait 作用域
    "impl_item",                  # impl 作用域
    "block",                      # 块作用域
    "if_expression",              # if 作用域
    "if_let_expression",          # if let 作用域
    "match_expression",           # match 作用域
    "match_arm",                  # match 分支作用域
    "loop_expression",            # loop 作用域
    "while_expression",           # while 作用域
    "for_expression",             # for 作用域
    "unsafe_block",               # unsafe 块作用域
    "async_block",                # async 块作用域
}

# ============================================================================
# 定义上下文类型
# ============================================================================

DEFINING_CONTEXT_TYPES = {
    # 函数/方法
    "function_item",
    "function_signature_item",
    "closure_expression",
    
    # 类型
    "struct_item",
    "enum_item",
    "trait_item",
    "impl_item",
    "type_alias",
    
    # 模块
    "mod_item",
    
    # 常量/静态变量
    "constant_item",
    "static_item",
    "associated_constant",
    
    # 变量
    "let_declaration",
    
    # 参数
    "parameter",
    "closure_parameters",
    
    # 字段
    "struct_field_declaration",
    "field_declaration",
    
    # 枚举变体
    "enum_variant",
    
    # 导入
    "use_declaration",
}

# ============================================================================
# 节点类型到操作的映射
# ============================================================================

NODE_TYPE_TO_OP = {
    # === 定义操作 ===
    'function_item': 'def',
    'function_signature_item': 'def',
    'struct_item': 'def',
    'enum_item': 'def',
    'trait_item': 'def',
    'impl_item': 'def',
    'type_alias': 'def',
    'mod_item': 'def',
    'constant_item': 'def',
    'static_item': 'def',
    'let_declaration': 'def',
    'struct_field_declaration': 'def',
    'enum_variant': 'def',
    'associated_type': 'def',
    'associated_constant': 'def',
    
    # === 导入操作 ===
    'use_declaration': 'import',
    
    # === 调用操作 ===
    'call_expression': 'call',
    'method_invocation': 'call',
    'macro_invocation': 'call',
    
    # === 赋值操作 ===
    'assignment_expression': 'assign',
    'compound_assignment_expr': 'assign',
    
    # === 算术操作 ===
    'binary_expression': 'arith',
    'unary_expression': 'arith',
    'range_expression': 'arith',
    
    # === 类型操作 ===
    'cast_expression': 'cast',
    'type_arguments': 'type',
    'type_binding': 'type',
    
    # === 控制流 ===
    'return_expression': 'return',
    'if_expression': 'control',
    'if_let_expression': 'control',
    'match_expression': 'control',
    'match_arm': 'control',
    'loop_expression': 'control',
    'while_expression': 'control',
    'for_expression': 'control',
    'break_expression': 'control',
    'continue_expression': 'control',
    
    # === 异步/协程 ===
    'await_expression': 'await',
    'yield_expression': 'yield',
    'async_block': 'async',
    
    # === 特殊操作 ===
    'try_expression': 'try',
    'unsafe_block': 'unsafe',
    'reference_expression': 'ref',
    'dereference_expression': 'deref',

    # === 宏 ===
    'macro_definition': 'macro',
    'macro_invocation': 'call',
}

# ============================================================================
# 名称提取规则
# ============================================================================

NAME_EXTRACT_RULES = {
    # 函数定义
    "function_item": ["identifier"],
    "function_signature_item": ["identifier"],

    # 类型定义
    "struct_item": ["type_identifier"],
    "enum_item": ["type_identifier"],
    "union_item": ["type_identifier"],
    "trait_item": ["type_identifier"],
    "impl_item": ["type_identifier"],
    "type_alias": ["type_identifier"],

    # 变量/常量定义
    "let_declaration": ["identifier"],
    "const_item": ["identifier"],
    "static_item": ["identifier"],
    "associated_constant": ["identifier"],

    # 枚举变体
    "enum_variant": ["identifier"],

    # 模块
    "mod_item": ["identifier"],

    # 导入
    "use_declaration": ["identifier"],
    "use_wildcard": ["identifier"],
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
