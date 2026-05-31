# parsers/languages/code_parser/lang_java.py
"""
Java 语言 AST 配置

基于 tree-sitter-java 的节点类型定义。
支持 Java 8/11/17/21 LTS 版本。

参考：https://github.com/tree-sitter/tree-sitter-java
"""
from .lang_base import LanguageConfig

# ============================================================================
# 重要节点类型
# ============================================================================

IMPORTANT_NODE_TYPES_SET = {
    # === 顶层结构 ===
    'program',                    # 整个 Java 文件
    'compilation_unit',           # 编译单元

    # === 包和导入 ===
    'package_declaration',        # package 声明
    'package_identifier',         # 包标识符（package com.example.foo 中的 com/example/foo）
    'import_declaration',         # import 声明
    'import',                     # import 关键字节点
    'static_import',              # static import

    # === 类/接口/枚举 ===
    'class_declaration',          # class 声明
    'class_body',                 # class 体
    'interface_declaration',      # interface 声明
    'interface_body',             # interface 体
    'enum_declaration',           # enum 声明
    'enum_body',                  # enum 体
    'enum_constant',              # enum 常量
    'record_declaration',         # Java 14+ record

    # === 继承/实现关系（高风险缺失） ===
    'extends_opt',                # extends 子句（类继承）
    'extends_interfaces',         # extends 接口列表
    'super_interfaces',           # implements 接口列表
    'superclass',                 # 父类类型引用

    # === 成员声明 ===
    'field_declaration',          # 字段声明
    'variable_declarator',        # 变量声明器
    'method_declaration',         # 方法声明
    'method_body',                # 方法体
    'constructor_declaration',    # 构造函数声明
    'constructor_body',           # 构造函数体（高风险缺失）
    'initializer_block',          # 初始化块
    'static_initializer',         # 静态初始化块

    # === 参数和类型 ===
    'formal_parameters',          # 形参列表容器（高风险缺失）
    'formal_parameter',           # 形式参数
    'spread_parameter',           # 可变参数 (String... args)
    'receiver_parameter',         # 接收者参数
    'type_parameters',            # 类型参数 (<T>)
    'type_parameter',             # 类型参数
    'type_arguments',             # 类型参数 (List<String>)
    'wildcard',                   # 通配符 (?)
    'type_bound',                 # 类型边界 (extends)

    # === 类型相关 ===
    'type_identifier',            # 类型标识符
    'generic_type',               # 泛型类型
    'array_type',                 # 数组类型
    'dimension_expr',             # 维度表达式
    'integral_type',              # 整数类型
    'floating_point_type',        # 浮点类型
    'boolean_type',               # boolean 类型
    'void_type',                  # void 类型

    # === 标识符和字面量 ===
    'identifier',                 # 标识符
    'field_identifier',           # 字段标识符
    'type_identifier',            # 类型标识符
    'label_identifier',           # 标签标识符
    'scoped_identifier',          # 全限定名（高风险缺失，如 java.util.List）
    'null_literal',               # null
    'boolean_literal',            # true/false
    'string_literal',             # 字符串字面量
    'character_literal',          # 字符字面量
    'integer_literal',            # 整数
    'decimal_integer_literal',
    'hex_integer_literal',
    'octal_integer_literal',
    'binary_integer_literal',
    'floating_point_literal',     # 浮点数
    'decimal_floating_point_literal',
    'hex_floating_point_literal',

    # === 表达式 ===
    'assignment_expression',      # 赋值表达式
    'binary_expression',          # 二元表达式
    'unary_expression',           # 一元表达式
    'update_expression',          # 更新表达式 (++/--)
    'cast_expression',            # 强制类型转换
    'instanceof_expression',      # instanceof
    'ternary_expression',         # 三元表达式 (?:)
    'parenthesized_expression',   # 括号表达式

    # === 方法调用和对象创建 ===
    'method_invocation',          # 方法调用
    'argument_list',              # 参数列表（高风险缺失）
    'object_creation_expression', # new 对象
    'new',                        # new 关键字（高风险缺失）
    'array_creation_expression',  # new 数组
    'qualified_name',             # 限定名 (a.b.c)
    'field_access',               # 字段访问 (.field)
    'array_access',               # 数组访问 ([])
    'method_reference',           # 方法引用 (::)
    'lambda_expression',          # Lambda 表达式
    'lambda_parameters',          # Lambda 参数

    # === 特殊对象 ===
    'super',                      # super
    'this',                       # this

    # === 语句 ===
    'statement',
    'block',                      # 代码块 {}
    'expression_statement',       # 表达式语句
    'declaration_statement',      # 声明语句
    'if_statement',               # if 语句
    'else_clause',                # else 子句
    'for_statement',              # for 循环
    'enhanced_for_statement',     # 增强 for 循环 (for-each)
    'while_statement',            # while 循环
    'do_statement',               # do-while 循环
    'switch_statement',           # switch 语句
    'switch_block',               # switch 块
    'switch_block_statement_group',
    'switch_label',               # case/default 标签
    'case_statement',
    'return_statement',           # return 语句
    'break_statement',            # break 语句
    'continue_statement',         # continue 语句
    'throw_statement',            # throw 语句
    'try_statement',              # try 语句
    'try_with_resources_statement',  # try-with-resources
    'resource',                   # try-with-resources 资源
    'catch_clause',               # catch 子句
    'finally_clause',             # finally 子句
    'synchronized_statement',     # synchronized

    # === 异常声明 ===
    'throws',                     # throws 子句（中风险缺失）

    # === 注解 ===
    'annotation',                 # 注解 (@Annotation)
    'marker_annotation',          # 标记注解
    'normal_annotation',          # 普通注解
    'single_element_annotation',  # 单元素注解
    'annotation_type_declaration', # 注解类型声明
    'annotation_type_body',
    'annotation_type_element_declaration',

    # === 修饰符 ===
    'modifiers',                  # 修饰符
    'public', 'protected', 'private',
    'static', 'final', 'abstract', 'synchronized',
    'volatile', 'transient', 'native',
    'strictfp',

    # === 其他 ===
    'permits',                    # permits (sealed class)
    'sealed_class',               # 密封类
    'non_sealed_class',           # 非密封类
    'pattern_matching',           # 模式匹配 (Java 16+)
    'text_block',                 # 文本块 (Java 15+)
    'underscore_literal',         # 数字分隔符
}

# ============================================================================
# 名称节点类型
# ============================================================================

IS_NAME_NODE_TYPES = {
    'identifier',                 # 普通标识符
    'type_identifier',            # 类型标识符
    'field_identifier',           # 字段标识符
    'label_identifier',           # 标签标识符
    'package_identifier',         # 包标识符
    'method_name',                # 方法名
    'class_name',                 # 类名
    'enum_constant_name',         # 枚举常量名
    'annotation_name',            # 注解名
    'parameter_name',             # 参数名
    'local_variable_name',        # 局部变量名
}

# ============================================================================
# 作用域创建类型
# ============================================================================

SCOPE_CREATING_TYPES = {
    "program",                    # 文件级作用域
    "compilation_unit",
    "package_declaration",        # 包作用域
    "class_declaration",          # 类作用域
    "interface_declaration",      # 接口作用域
    "enum_declaration",           # 枚举作用域
    "record_declaration",         # record 作用域
    "method_declaration",         # 方法作用域
    "constructor_declaration",    # 构造函数作用域
    "block",                      # 代码块作用域
    "for_statement",              # for 循环作用域
    "enhanced_for_statement",     # 增强 for 作用域
    "while_statement",            # while 作用域
    "if_statement",               # if 作用域
    "switch_statement",           # switch 作用域
    "try_statement",              # try 作用域
    "catch_clause",               # catch 作用域
    "lambda_expression",          # Lambda 作用域
    "annotation_type_declaration", # 注解类型作用域
}

# ============================================================================
# 定义上下文类型
# ============================================================================

DEFINING_CONTEXT_TYPES = {
    # 类/接口/枚举
    "class_declaration",
    "interface_declaration",
    "enum_declaration",
    "record_declaration",
    "annotation_type_declaration",
    
    # 方法/构造函数
    "method_declaration",
    "constructor_declaration",
    "annotation_type_element_declaration",
    
    # 字段/变量
    "field_declaration",
    "variable_declarator",
    "formal_parameter",
    "spread_parameter",
    "receiver_parameter",
    "resource",
    "local_variable_declaration",
    
    # 枚举/注解
    "enum_constant",
    
    # 包
    "package_declaration",
}

# ============================================================================
# 节点类型到操作的映射
# ============================================================================

NODE_TYPE_TO_OP = {
    # === 定义操作 ===
    'class_declaration': 'def',
    'interface_declaration': 'def',
    'enum_declaration': 'def',
    'record_declaration': 'def',
    'method_declaration': 'def',
    'constructor_declaration': 'def',
    'constructor_body': 'def',
    'field_declaration': 'def',
    'variable_declarator': 'def',
    'formal_parameter': 'def',
    'formal_parameters': 'def',
    'enum_constant': 'def',
    'annotation_type_declaration': 'def',
    'annotation_type_element_declaration': 'def',
    'package_declaration': 'def',

    # === 导入操作 ===
    'import_declaration': 'import',
    'import': 'import',
    'static_import': 'import',

    # === 调用操作 ===
    'method_invocation': 'call',
    'object_creation_expression': 'call',  # new
    'new': 'call',
    'array_creation_expression': 'call',
    'method_reference': 'call',

    # === 赋值操作 ===
    'assignment_expression': 'assign',
    'variable_declarator': 'assign',  # 声明时初始化

    # === 算术操作 ===
    'binary_expression': 'arith',
    'unary_expression': 'arith',
    'update_expression': 'arith',

    # === 类型操作 ===
    'cast_expression': 'cast',
    'instanceof_expression': 'instanceof',
    'type_parameters': 'type',
    'type_arguments': 'type',
    'scoped_identifier': 'type_ref',  # 全限定名引用

    # === 继承/实现关系 ===
    'extends_opt': 'extends',
    'extends_interfaces': 'implements',
    'super_interfaces': 'implements',
    'superclass': 'extends',

    # === 控制流 ===
    'return_statement': 'return',
    'if_statement': 'control',
    'for_statement': 'control',
    'enhanced_for_statement': 'control',
    'while_statement': 'control',
    'do_statement': 'control',
    'switch_statement': 'control',
    'case_statement': 'control',
    'break_statement': 'control',
    'continue_statement': 'control',

    # === 异常处理 ===
    'throw_statement': 'throw',
    'throws': 'throws',
    'try_statement': 'try',
    'catch_clause': 'catch',
    'finally_clause': 'finally',

    # === 条件操作 ===
    'ternary_expression': 'cond',

    # === Lambda ===
    'lambda_expression': 'lambda',

    # === 同步 ===
    'synchronized_statement': 'sync',

    # === 参数列表 ===
    'argument_list': 'arg_list',
}

# ============================================================================
# 名称提取规则
# ============================================================================

NAME_EXTRACT_RULES = {
    # 方法定义
    "method_declaration": ["identifier"],
    "method_invocation": ["identifier", "scoped_identifier"],
    "constructor_declaration": ["identifier"],

    # 类定义
    "class_declaration": ["identifier"],
    "interface_declaration": ["identifier"],
    "enum_declaration": ["identifier"],
    "record_declaration": ["identifier"],

    # 变量/字段定义
    "variable_declarator": ["identifier"],
    "field_declaration": ["identifier"],
    "formal_parameter": ["identifier"],

    # 导入
    "import_declaration": ["identifier", "scoped_identifier"],
    "package_declaration": ["identifier", "scoped_identifier"],

    # 全限定名
    "scoped_identifier": ["identifier"],

    # 对象创建
    "object_creation_expression": ["type_identifier", "scoped_identifier", "generic_type"],

    # 继承/实现
    "extends_opt": ["type_identifier", "scoped_identifier"],
    "extends_interfaces": ["type_identifier", "scoped_identifier"],
    "super_interfaces": ["type_identifier", "scoped_identifier"],
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
