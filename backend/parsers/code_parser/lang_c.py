# parsers/languages/code_parser/lang_c.py
"""
C 语言 AST 配置

基于 tree-sitter-c 的节点类型定义。
支持 C89/C99/C11/C17/C23 标准。

参考: https://github.com/tree-sitter/tree-sitter-c
"""
from .lang_base import LanguageConfig

# ============================================================================
# 重要节点类型
# ============================================================================
# 这些节点是代码分析和文档生成的核心，包括:
# - 函数定义和声明
# - 类型定义和声明
# - 预处理指令
# - 控制流语句
# - 表达式

IMPORTANT_NODE_TYPES_SET = {
    # === 函数相关 ===
    'function_definition',          # 函数定义
    'function_declarator',          # 函数声明器
    'function_call',                # 函数调用 (某些版本)
    
    # === 声明相关 ===
    'declaration',                  # 声明
    'declaration_statement',        # 声明语句
    'type_definition',              # 类型定义 (typedef)
    'type_declaration',             # 类型声明
    'field_declaration',            # 字段声明 (struct/union 内)
    'parameter_declaration',        # 参数声明
    'init_declarator',              # 初始化声明器
    'pointer_declarator',           # 指针声明器
    'array_declarator',             # 数组声明器
    'attributed_declarator',       # 属性声明器
    
    # === 复合类型 ===
    'struct_specifier',             # struct 说明符
    'union_specifier',              # union 说明符
    'enum_specifier',               # enum 说明符
    'enumerator',                   # 枚举常量
    'enumerator_list',              # 枚举常量列表
    
    # === 类型说明符 ===
    'storage_class_specifier',      # 存储类说明符 (extern, static 等)
    'type_specifier',               # 类型说明符
    'type_identifier',              # 类型标识符
    'primitive_type',               # 原始类型 (int, char 等)
    'sized_type_descriptor',        # 带大小的类型描述符
    'type_descriptor',              # 类型描述符
    'type_qualifier',               # 类型限定符 (const, volatile 等)
    'macro_type_specifier',         # 宏类型说明符
    
    # === 预处理指令 ===
    'preproc_def',                  # 预处理定义 (#define)
    'preproc_function_def',         # 预处理函数定义 (#define F(x))
    'preproc_include',              # 预处理包含 (#include)
    'preproc_if',                   # #if
    'preproc_ifdef',                # #ifdef
    'preproc_elif',                 # #elif
    'preproc_else',                 # #else
    'preproc_endif',                # #endif
    'preproc_call',                 # 预处理调用 (#pragma 等)
    'preproc_defined',              # defined()
    'preproc_arg',                  # 预处理参数
    
    # === 标识符和字符串 ===
    'identifier',                   # 标识符
    'system_lib_string',            # 系统库字符串 (<stdio.h>)
    'string_literal',               # 字符串字面量
    'field_identifier',             # 字段标识符
    'statement_identifier',         # 语句标识符 (label)
    'null',                         # NULL
    
    # === 表达式 ===
    'call_expression',              # 调用表达式
    'assignment_expression',        # 赋值表达式
    'binary_expression',            # 二元表达式
    'unary_expression',             # 一元表达式
    'conditional_expression',       # 条件表达式 (?:)
    'cast_expression',              # 强制类型转换
    'sizeof_expression',            # sizeof 表达式
    'comma_expression',             # 逗号表达式
    'subscript_expression',         # 下标表达式 ([])
    'field_expression',             # 字段表达式 (.)
    'update_expression',            # 更新表达式 (++/--)
    'parenthesized_expression',     # 括号表达式
    'compound_literal_expression',  # 复合字面量
    
    # === 字面量 ===
    'number_literal',               # 数字字面量
    'char_literal',                 # 字符字面量
    'string_literal',               # 字符串字面量
    'concatenated_string',          # 连接字符串
    
    # === 控制流语句 ===
    'if_statement',                 # if 语句
    'for_statement',                # for 循环
    'while_statement',              # while 循环
    'do_statement',                 # do-while 循环
    'switch_statement',             # switch 语句
    'case_statement',               # case 语句
    'return_statement',             # return 语句
    'break_statement',              # break 语句
    'continue_statement',           # continue 语句
    'goto_statement',               # goto 语句
    'labeled_statement',            # 标签语句
    
    # === 其他语句 ===
    'expression_statement',         # 表达式语句
    'compound_statement',           # 复合语句 ({})
    'empty_statement',              # 空语句 (;)
    
    # === 顶层结构 ===
    'translation_unit',             # 翻译单元 (整个文件)
    
    # === 其他 ===
    'linkage_specification',        # 链接说明 (extern "C")
    'attribute',                    # 属性
    'attributes',                   # 属性列表
    'comment',                      # 注释 (可选)
    'type_cast',                    # 类型转换
}

# ============================================================================
# 名称节点类型
# ============================================================================
# 这些节点代表代码中的"名称"，用于符号解析和引用追踪

IS_NAME_NODE_TYPES = {
    'identifier',                   # 普通标识符
    'type_identifier',              # 类型标识符
    'field_identifier',             # 字段标识符
    'statement_identifier',         # 语句标识符 (label)
    'system_lib_string',            # 系统库字符串 (<stdio.h>)
    'string_literal',               # 字符串字面量 ("myheader.h")
    'string_content',               # 字符串内容 (头文件名)
    'primitive_type',               # 原始类型名称
}

# ============================================================================
# 作用域创建类型
# ============================================================================
# 这些节点创建新的作用域，用于变量可见性分析

SCOPE_CREATING_TYPES = {
    "translation_unit",             # 文件级作用域 (全局)
    "function_definition",          # 函数作用域
    "compound_statement",           # 块作用域 ({})
    "struct_specifier",             # struct 作用域
    "union_specifier",              # union 作用域
    "enum_specifier",               # enum 作用域
    "for_statement",                # for 循环作用域
    "if_statement",                 # if 语句作用域
    "while_statement",              # while 循环作用域
    "switch_statement",             # switch 语句作用域
}

# ============================================================================
# 定义上下文类型
# ============================================================================
# 当 name 节点的父节点是这些类型时，该 name 是一个定义（而非引用）

DEFINING_CONTEXT_TYPES = {
    # 函数相关
    "function_definition",          # 函数定义
    "function_declarator",          # 函数声明器
    
    # 变量/参数相关
    "declaration",                  # 声明
    "type_definition",              # 类型定义 (typedef)
    "parameter_declaration",        # 参数声明
    "init_declarator",              # 初始化声明器
    
    # 类型相关
    "struct_specifier",             # struct 定义
    "union_specifier",              # union 定义
    "enum_specifier",               # enum 定义
    "enumerator",                   # 枚举常量定义
    
    # 字段相关
    "field_declaration",            # 字段声明
    
    # 预处理相关
    "preproc_def",                  # 宏定义
    "preproc_function_def",         # 宏函数定义
}

# ============================================================================
# 节点类型到操作的映射
# ============================================================================
# 用于生成代码操作语义标签

NODE_TYPE_TO_OP = {
    # === 定义操作 ===
    'function_definition': 'def',
    'function_declarator': 'def',
    'declaration': 'def',
    'type_definition': 'def',
    'type_definition_statement': 'def',
    'parameter_declaration': 'def',
    'init_declarator': 'def',
    'field_declaration': 'def',
    'preproc_def': 'def',
    'preproc_function_def': 'def',
    'struct_specifier': 'def',
    'union_specifier': 'def',
    'enum_specifier': 'def',
    'enumerator': 'def',
    
    # === 包含操作 ===
    'preproc_include': 'include',
    
    # === 调用操作 ===
    'call_expression': 'call',
    'preproc_call': 'call',
    
    # === 赋值操作 ===
    'assignment_expression': 'assign',
    
    # === 算术操作 ===
    'binary_expression': 'arith',
    'unary_expression': 'arith',
    'update_expression': 'arith',  # ++/--
    
    # === 类型操作 ===
    'cast_expression': 'cast',
    'sizeof_expression': 'sizeof',
    'type_descriptor': 'type',
    
    # === 控制流 ===
    'return_statement': 'return',
    'if_statement': 'control',
    'for_statement': 'control',
    'while_statement': 'control',
    'do_statement': 'control',
    'switch_statement': 'control',
    'case_statement': 'control',
    'break_statement': 'control',
    'continue_statement': 'control',
    'goto_statement': 'control',
    'labeled_statement': 'control',
    
    # === 条件操作 ===
    'conditional_expression': 'cond',
    
    # === 逻辑操作 ===
    
    # === 比较操作 ===
    
    # === 位操作 ===

    # === 内存操作 ===
}

# ============================================================================
# 名称提取规则
# ============================================================================

NAME_EXTRACT_RULES = {
    # 函数定义
    "function_definition": ["identifier", "field_identifier"],
    "function_declarator": ["identifier", "field_identifier"],
    
    # 类/结构体/联合体
    "class_specifier": ["type_identifier"],
    "struct_specifier": ["type_identifier"],
    "union_specifier": ["type_identifier"],
    "enum_specifier": ["type_identifier"],
    
    # 类型定义
    "type_definition": ["type_identifier"],
    
    # 变量定义
    "declaration": ["identifier"],
    "init_declarator": ["identifier"],
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
