# parsers/languages/code_parser/lang_cpp.py
"""
C++ 语言 AST 配置

基于 tree-sitter-cpp 的节点类型定义。
支持 C++98/C++11/C++14/C++17/C++20/C++23 标准。

参考：https://github.com/tree-sitter/tree-sitter-cpp
"""
from .lang_base import LanguageConfig

# ============================================================================
# 重要节点类型
# ============================================================================
# C++ 配置包含所有 C 语言节点，再加上 C++ 特有节点

IMPORTANT_NODE_TYPES_SET = {
    # === 继承自 C 语言的核心节点 ===
    # 函数相关
    'function_definition',
    'function_declarator',
    'qualified_identifier',  # C++ 特有的限定标识符 (如 std::vector)
    
    # 声明相关
    'declaration',
    'declaration_statement',
    'type_definition',
    'field_declaration',
    'parameter_declaration',
    'init_declarator',
    'pointer_declarator',
    'array_declarator',
    'reference_declarator',  # C++ 引用声明器
    'attributed_declarator',
    
    # 复合类型
    'struct_specifier',
    'union_specifier',
    'enum_specifier',
    'enumerator',
    'enumerator_list',
    
    # C++ 特有类型
    'class_specifier',       # class/struct 定义
    'class_body',            # class 体
    'base_class_clause',     # 基类子句 (: public Base)
    'inheritance_clause',    # 继承子句
    
    # 命名空间
    'namespace_definition',  # namespace 定义
    'named_namespace_definition',
    'unnamed_namespace_definition',
    'namespace_alias',       # namespace 别名
    'namespace_body',
    
    # 模板
    'template_declaration',  # template<typename T>
    'template_type_parameter',
    'template_non_type_parameter',
    'template_template_parameter',
    'template_parameter_list',
    'template_instantiation',
    'template_function',
    'template_class',
    
    # 类型说明符
    'storage_class_specifier',
    'type_specifier',
    'type_identifier',
    'primitive_type',
    'sized_type_descriptor',
    'type_descriptor',
    'type_qualifier',
    'macro_type_specifier',
    'auto',                  # auto 类型
    'decltype',              # decltype
    
    # 使用声明
    'using_declaration',     # using namespace std;
    'using_directive',       # using std::cout;
    'type_alias_declaration',  # using T = int;
    
    # 预处理指令
    'preproc_def',
    'preproc_function_def',
    'preproc_include',
    'preproc_if',
    'preproc_ifdef',
    'preproc_elif',
    'preproc_else',
    'preproc_endif',
    'preproc_call',
    'preproc_defined',
    'preproc_arg',
    
    # 标识符和字符串
    'identifier',
    'system_lib_string',
    'string_literal',
    'raw_string_literal',    # C++11 原始字符串 R"(...)"
    'field_identifier',
    'statement_identifier',
    'null',
    'nullptr',               # C++11 nullptr
    'this',                  # this 指针
    
    # 表达式
    'call_expression',
    'assignment_expression',
    'binary_expression',
    'unary_expression',
    'conditional_expression',
    'cast_expression',
    'sizeof_expression',
    'alignof_expression',    # C++11 alignof
    'typeid_expression',     # typeid
    'comma_expression',
    'subscript_expression',
    'field_expression',
    'pointer_field_expression',  # -> 操作符
    'update_expression',
    'parenthesized_expression',
    'compound_literal_expression',
    
    # C++ 特有表达式
    'new_expression',        # new 表达式
    'new_declarator',
    'placement_new_clause',
    'delete_expression',     # delete 表达式
    'lambda_expression',     # C++11 lambda
    'lambda_capture_clause',
    'throw_expression',      # throw 表达式
    'noexcept',              # noexcept
    'co_await_expression',   # C++20 coroutine
    'co_yield_expression',
    'co_return_expression',
    
    # 字面量
    'number_literal',
    'char_literal',
    'string_literal',
    'concatenated_string',
    'boolean_literal',       # true/false
    'user_defined_literal',  # C++11 用户定义字面量
    
    # 控制流语句
    'if_statement',
    'for_statement',
    'range_based_for_statement',  # C++11 范围 for
    'while_statement',
    'do_statement',
    'switch_statement',
    'case_statement',
    'return_statement',
    'break_statement',
    'continue_statement',
    'goto_statement',
    'labeled_statement',
    
    # 其他语句
    'expression_statement',
    'compound_statement',
    'empty_statement',
    'try_statement',         # try-catch
    'catch_clause',
    'throw_statement',
    
    # 顶层结构
    'translation_unit',
    
    # C++ 特有结构
    'linkage_specification',  # extern "C"
    'static_assert_declaration',  # static_assert
    'concept_declaration',    # C++20 concept
    'requires_clause',        # C++20 requires
    'requires_expression',

    # 类成员相关
    'access_specifier',       # public:/private:/protected:
    'friend_declaration',     # friend
    'member_initializer',     # 成员初始化器
    'member_initializer_list', # 构造函数初始化列表
    'constructor_declarator', # 构造函数
    'destructor_declarator',  # 析构函数
    'operator_name',          # operator+ 等
    'operator_cast',          # operator int()
    'virtual_specifier',      # override/final

    # 属性
    'attribute',
    'attributes',
    'attribute_declaration',

    # 注释 (可选)
    'comment',
}

# ============================================================================
# 名称节点类型
# ============================================================================

IS_NAME_NODE_TYPES = {
    'identifier',
    'type_identifier',
    'field_identifier',
    'statement_identifier',
    'system_lib_string',
    'string_literal',               # 字符串字面量 ("myheader.h")
    'string_content',               # 字符串内容 (头文件名)
    'primitive_type',
    'qualified_identifier',         # std::vector 这样的限定名
    'operator_name',                # operator+, operator= 等
    'namespace_identifier',         # 命名空间名
    'template_name',                # 模板名
}

# ============================================================================
# 作用域创建类型
# ============================================================================

SCOPE_CREATING_TYPES = {
    "translation_unit",
    "function_definition",
    "compound_statement",
    "class_specifier",
    "struct_specifier",
    "union_specifier",
    "enum_specifier",
    "namespace_definition",
    "for_statement",
    "range_based_for_statement",
    "if_statement",
    "while_statement",
    "switch_statement",
    "lambda_expression",
    "catch_clause",
}

# ============================================================================
# 定义上下文类型
# ============================================================================

DEFINING_CONTEXT_TYPES = {
    # 函数相关
    "function_definition",
    "function_declarator",
    "constructor_declarator",
    "destructor_declarator",
    
    # 变量/参数相关
    "declaration",
    "type_definition",
    "type_alias_declaration",
    "parameter_declaration",
    "init_declarator",
    
    # 类型相关
    "class_specifier",
    "struct_specifier",
    "union_specifier",
    "enum_specifier",
    "enumerator",
    "template_declaration",
    "concept_declaration",
    
    # 字段相关
    "field_declaration",
    
    # 命名空间相关
    "namespace_definition",
    "namespace_alias",
    
    # 使用声明
    "using_declaration",
    "using_directive",
    
    # 预处理相关
    "preproc_def",
    "preproc_function_def",
}

# ============================================================================
# 节点类型到操作的映射
# ============================================================================

NODE_TYPE_TO_OP = {
    # === 定义操作 ===
    'function_definition': 'def',
    'function_declarator': 'def',
    'constructor_declarator': 'def',
    'destructor_declarator': 'def',
    'declaration': 'def',
    'type_definition': 'def',
    'type_alias_declaration': 'def',
    'parameter_declaration': 'def',
    'field_declaration': 'def',
    'class_specifier': 'def',
    'struct_specifier': 'def',
    'union_specifier': 'def',
    'enum_specifier': 'def',
    'enumerator': 'def',
    'namespace_definition': 'def',
    'template_declaration': 'def',
    'concept_declaration': 'def',
    
    # === 包含操作 ===
    'preproc_include': 'include',
    'using_directive': 'include',  # using namespace
    'using_declaration': 'include',  # using std::cout
    
    # === 调用操作 ===
    'call_expression': 'call',
    'new_expression': 'call',  # new 也是调用
    'delete_expression': 'call',  # delete 也是调用
    
    # === 赋值操作 ===
    'assignment_expression': 'assign',
    'init_declarator': 'assign',
    'member_initializer': 'assign',
    
    # === 算术操作 ===
    'binary_expression': 'arith',
    'unary_expression': 'arith',
    'update_expression': 'arith',
    
    # === 类型操作 ===
    'cast_expression': 'cast',
    'operator_cast': 'cast',
    'sizeof_expression': 'sizeof',
    'alignof_expression': 'sizeof',
    'typeid_expression': 'typeid',
    
    # === 控制流 ===
    'return_statement': 'return',
    'if_statement': 'control',
    'for_statement': 'control',
    'range_based_for_statement': 'control',
    'while_statement': 'control',
    'do_statement': 'control',
    'switch_statement': 'control',
    'case_statement': 'control',
    'break_statement': 'control',
    'continue_statement': 'control',
    'goto_statement': 'control',
    
    # === 异常处理 ===
    'throw_statement': 'throw',
    'throw_expression': 'throw',
    'try_statement': 'try',
    'catch_clause': 'catch',
    
    # === 条件操作 ===
    'conditional_expression': 'cond',
    
    # === Lambda ===
    'lambda_expression': 'lambda',
}


# ============================================================================
# 名称提取规则
# ============================================================================

NAME_EXTRACT_RULES = {
    # 函数定义
    "function_definition": ["identifier"],
    "function_declarator": ["identifier"],
    "constructor_declarator": ["identifier"],
    "destructor_declarator": ["identifier"],
    "operator_name": ["identifier"],

    # 类/结构体/枚举定义
    "class_specifier": ["identifier"],
    "struct_specifier": ["identifier"],
    "enum_specifier": ["identifier"],
    "elaborated_type": ["identifier"],

    # 变量/字段
    "field_declaration": ["identifier"],
    "init_declarator": ["identifier"],
    "preproc_function_def": ["identifier"],

    # 命名空间
    "namespace_definition": ["identifier"],
    "namespace_identifier": ["identifier"],

    # 模板
    "template_type_parameter": ["identifier"],
    "type_arguments": ["identifier"],

    # 调用
    "call_expression": ["identifier", "field_identifier"],
    "qualified_identifier": ["identifier"],

    # 导入
    "linkage_specification": ["identifier"],
    "preproc_include": ["identifier"],
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
