# parsers/languages/code_parser/lang_python.py
"""
Python 语言 AST 配置

基于 tree-sitter-python 的节点类型定义。
支持 Python 3.6-3.12+ 版本。

参考：https://github.com/tree-sitter/tree-sitter-python
"""
from .lang_base import LanguageConfig

# ============================================================================
# 重要节点类型
# ============================================================================

IMPORTANT_NODE_TYPES_SET = {
    # === 顶层结构 ===
    'module',                     # Python 模块 (整个文件)
    
    # === 导入 ===
    'import_statement',           # import 语句
    'import_from_statement',      # from ... import 语句
    'import_prefix',              # 导入前缀 (. 表示相对导入)
    'relative_import',            # 相对导入
    'wildcard_import',            # from x import *
    'aliased_import',             # import x as y
    
    # === 类定义 ===
    'class_definition',           # class 定义
    'class_body',                 # class 体
    'class_pattern',              # class 模式 (match-case)
    'super',                      # super()
    
    # === 函数定义 ===
    'function_definition',        # def 函数定义
    'parameters',                 # 参数列表
    'parameter',                  # 参数
    'default_parameter',          # 默认参数
    'typed_parameter',            # 类型注解参数
    'typed_default_parameter',    # 带类型的默认参数
    'tuple_parameter',            # 元组参数 (已废弃)
    'lambda_parameters',          # Lambda 参数
    'list_splat',                 # 列表解包 (*args)
    'dictionary_splat',           # 字典解包 (**kwargs)
    
    # === 异步 ===
    'async_function_definition',  # async def
    'async_for',                  # async for
    'async_with',                 # async with
    'await',                      # await
    
    # === 装饰器 ===
    'decorator',                  # @decorator
    'decorated_definition',       # 被装饰的定义
    
    # === 赋值 ===
    'assignment',                 # 赋值语句
    'augmented_assignment',       # 增强赋值 (+=, -=等)
    'named_expression',           # 海象运算符 (:=)
    'type_alias',                 # 类型别名 (Python 3.12+)
    
    # === 控制流 ===
    'if_statement',               # if 语句
    'elif_clause',                # elif 子句
    'else_clause',                # else 子句
    'for_statement',              # for 循环
    'while_statement',            # while 循环
    'match_statement',            # match 语句 (Python 3.10+)
    'case_clause',                # case 子句
    'case_pattern',               # case 模式
    
    # === 异常处理 ===
    'try_statement',              # try 语句
    'except_clause',              # except 子句
    'except_group_clause',        # except* 子句 (Python 3.11+)
    'finally_clause',             # finally 子句
    'raise_statement',            # raise 语句
    'assert_statement',           # assert 语句
    
    # === 循环控制 ===
    'return_statement',           # return 语句
    'break_statement',            # break 语句
    'continue_statement',         # continue 语句
    'pass_statement',             # pass 语句
    
    # === 上下文管理器 ===
    'with_statement',             # with 语句
    'with_clause',                # with 子句
    'with_item',                  # with 项
    
    # === 表达式语句 ===
    'expression_statement',       # 表达式语句
    'yield',                      # yield
    'yield_from',                 # yield from
    
    # === 字面量 ===
    'string',                     # 字符串
    'string_content',             # 字符串内容
    'escape_sequence',            # 转义序列
    'escape_interpolation',       # f-string 插值
    'format_specifier',           # 格式说明符
    'integer',                    # 整数
    'float',                      # 浮点数
    'true',                       # True
    'false',                      # False
    'none',                       # None
    'bytes',                      # bytes
    'raw_string',                 # 原始字符串 r"..."
    
    # === 标识符 ===
    'identifier',                 # 标识符
    'type_identifier',            # 类型标识符
    'attribute',                  # 属性访问 (obj.attr)
    'keyword_identifier',         # 关键字标识符
    
    # === 表达式 ===
    'call',                       # 函数调用
    'call_argument',              # 调用参数
    'subscript',                  # 下标 (x[0])
    'slice',                      # 切片 (x[1:2])
    'list',                       # 列表
    'list_comprehension',         # 列表推导式
    'set_comprehension',          # 集合推导式
    'dictionary_comprehension',   # 字典推导式
    'generator_expression',       # 生成器表达式
    'tuple',                      # 元组
    'set',                        # 集合
    'dictionary',                 # 字典
    'pair',                       # 字典键值对
    'parenthesized_expression',   # 括号表达式
    
    # === 运算符表达式 ===
    'binary_operator',            # 二元运算符
    'not_operator',               # not
    'unary_operator',             # 一元运算符 (+, -, ~)
    'comparison_operator',        # 比较运算符
    'boolean_operator',           # 逻辑运算符 (and, or)
    'assignment_expression',      # 赋值表达式 (:=)
    'conditional_expression',     # 条件表达式 (a if cond else b)
    
    # === 模式匹配 (Python 3.10+) ===
    'match_pattern',              # 匹配模式
    'as_pattern',                 # as 模式
    'or_pattern',                 # or 模式
    'class_pattern',              # class 模式
    'capture_pattern',            # 捕获模式
    'wildcard_pattern',           # 通配符模式 (_)
    
    # === 其他 ===
    'exec_statement',             # exec 语句 (Python 2)
    'print_statement',            # print 语句 (Python 2)
    'global_statement',           # global 语句
    'nonlocal_statement',         # nonlocal 语句
    'delete_statement',           # del 语句
    'future_import_statement',    # from __future__ import
}

# ============================================================================
# 名称节点类型
# ============================================================================

IS_NAME_NODE_TYPES = {
    'identifier',                 # 普通标识符
    'type_identifier',            # 类型标识符
    'attribute',                  # 属性名
    'keyword_identifier',         # 关键字标识符
    'function_name',              # 函数名
    'class_name',                 # 类名
    'parameter_name',             # 参数名
    'variable_name',              # 变量名
    'module_name',                # 模块名
    'exception_name',             # 异常名
}

# ============================================================================
# 作用域创建类型
# ============================================================================

SCOPE_CREATING_TYPES = {
    "module",                     # 模块级作用域
    "function_definition",        # 函数作用域
    "async_function_definition",  # 异步函数作用域
    "class_definition",           # 类作用域
    "lambda",                     # Lambda 作用域
    "for_statement",              # for 循环作用域 (Python 中 for 不创建新作用域)
    "if_statement",               # if 作用域 (Python 中 if 不创建新作用域)
    "with_statement",             # with 作用域
    "except_clause",              # except 作用域
    "match_statement",            # match 作用域
    "case_clause",                # case 作用域
    "list_comprehension",         # 推导式作用域
    "set_comprehension",
    "dictionary_comprehension",
    "generator_expression",
}

# ============================================================================
# 定义上下文类型
# ============================================================================

DEFINING_CONTEXT_TYPES = {
    # 函数/方法
    "function_definition",
    "async_function_definition",
    
    # 类
    "class_definition",
    
    # 变量/赋值
    "assignment",
    "named_expression",
    "type_alias",
    
    # 参数
    "parameter",
    "default_parameter",
    "typed_parameter",
    "typed_default_parameter",
    
    # 导入
    "import_statement",
    "import_from_statement",
    
    # 异常
    "except_clause",
    
    # 模式匹配
    "capture_pattern",
}

# ============================================================================
# 节点类型到操作的映射
# ============================================================================

NODE_TYPE_TO_OP = {
    # === 定义操作 ===
    'function_definition': 'def',
    'async_function_definition': 'def',
    'class_definition': 'def',
    'parameter': 'def',
    'default_parameter': 'def',

    # === 导入操作 ===
    'import_statement': 'import',
    'import_from_statement': 'import',
    'wildcard_import': 'import',

    # === 调用操作 ===
    'call': 'call',
    'await': 'call',

    # === 赋值操作 ===
    'assignment': 'assign',
    'augmented_assignment': 'assign',
    'named_expression': 'assign',

    # === 算术操作 ===
    'binary_operator': 'arith',
    'unary_operator': 'arith',

    # === 比较操作 ===
    'comparison_operator': 'compare',

    # === 逻辑操作 ===
    'boolean_operator': 'logic',
    'not_operator': 'logic',

    # === 类型操作 ===
    'typed_parameter': 'type',
    'type_alias': 'type',
    
    # === 控制流 ===
    'return_statement': 'return',
    'if_statement': 'control',
    'elif_clause': 'control',
    'else_clause': 'control',
    'for_statement': 'control',
    'while_statement': 'control',
    'match_statement': 'control',
    'case_clause': 'control',
    'break_statement': 'control',
    'continue_statement': 'control',
    
    # === 异常处理 ===
    'raise_statement': 'throw',
    'try_statement': 'try',
    'except_clause': 'catch',
    'except_group_clause': 'catch',
    'finally_clause': 'finally',
    'assert_statement': 'assert',
    
    # === 条件操作 ===
    'conditional_expression': 'cond',
    
    # === Lambda ===
    'lambda': 'lambda',
    
    # === 生成器 ===
    'yield': 'yield',
    'yield_from': 'yield',
    
    # === 上下文管理 ===
    'with_statement': 'with',

    # === 解包 ===
    'list_splat': 'unpack',
    'dictionary_splat': 'unpack',
}

# ============================================================================
# 名称提取规则
# ============================================================================

NAME_EXTRACT_RULES = {
    # 函数定义
    "function_definition": ["identifier"],
    "lambda_function": [],  # lambda 没有名称
    
    # 类定义
    "class_definition": ["identifier"],
    
    # 变量定义
    "assignment": ["identifier"],  # 从左侧提取
    "named_expression": ["identifier"],  # := 操作符
    
    # 导入
    "import_statement": ["identifier"],
    "import_from_statement": ["identifier"],
    "dotted_name": ["identifier"],
    
    # 装饰器
    "decorator": ["identifier"],
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
