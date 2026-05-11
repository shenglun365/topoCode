# parsers/languages/code_parser/lang_js.py
"""
JavaScript 语言 AST 配置

基于 tree-sitter-javascript 的节点类型定义。
支持 ES5/ES6/ES2017-ES2023 标准。

参考：https://github.com/tree-sitter/tree-sitter-javascript
"""
from .lang_base import LanguageConfig

# ============================================================================
# 重要节点类型
# ============================================================================

IMPORTANT_NODE_TYPES_SET = {
    # === 顶层结构 ===
    'program',                    # 整个 JS 文件
    
    # === 导入/导出 ===
    'import_statement',           # import 语句
    'import_clause',              # import 子句
    'named_imports',              # 命名导入 { x, y }
    'import_specifier',           # 导入说明符
    'import_namespace_specifier', # * as x
    'import_attribute',           # import attributes
    'from_clause',                # from 子句
    'export_statement',           # export 语句
    'export_clause',              # export 子句
    'named_exports',              # 命名导出
    'export_specifier',           # 导出说明符
    'export_alias',               # 导出别名
    'declaration',                # export declaration
    
    # === 函数定义 ===
    'function_declaration',       # function 声明
    'function_expression',        # function 表达式
    'formal_parameters',          # 形式参数
    'arguments',                  # 参数列表
    'optional_parameter',         # 可选参数
    'rest_pattern',               # 剩余参数 (...args)
    'default_parameter',          # 默认参数
    'arrow_function',             # 箭头函数
    'generator_function',         # generator 函数 (function*)
    'async_function_declaration', # async function
    'async_arrow_function',       # async 箭头函数
    
    # === 类定义 ===
    'class_declaration',          # class 声明
    'class_body',                 # class 体
    'class_heritage',             # class 继承 (extends)
    'method_definition',          # 方法定义
    'getter_method',              # getter
    'setter_method',              # setter
    'static_block',               # static 块
    'field_definition',           # 字段定义
    
    # === 变量声明 ===
    'variable_declaration',       # var/let/const 声明
    'variable_declarator',        # 变量声明器
    'lexical_declaration',        # let/const 声明
    
    # === 标识符和字面量 ===
    'identifier',                 # 标识符
    'property_identifier',        # 属性标识符
    'private_property_identifier', # 私有属性 (#field)
    'shorthand_property_identifier', # 简写属性
    'string',                     # 字符串
    'string_fragment',            # 字符串片段
    'template_string',            # 模板字符串
    'template_substitution',      # 模板替换 ${}
    'number',                     # 数字
    'big_int',                    # BigInt
    'regex',                      # 正则表达式
    'regex_flags',                # 正则标志
    'true',                       # true
    'false',                      # false
    'null',                       # null
    'undefined',                  # undefined
    'escape_sequence',            # 转义序列 (\n, \t 等)
    
    # === 表达式 ===
    'expression_statement',       # 表达式语句
    'assignment_expression',      # 赋值表达式
    'augmented_assignment_expression', # 增强赋值
    'call_expression',            # 调用表达式
    'new_expression',             # new 表达式
    'member_expression',          # 成员表达式 (obj.prop)
    'subscript_expression',       # 下标表达式 (obj[0])
    'chain_expression',           # 链表达式 (a?.b)
    'optional_chain',             # 可选链
    'sequence_expression',        # 序列表达式 (a, b, c)
    'spread_element',             # 展开元素 (...expr)
    
    # === 运算符表达式 ===
    'binary_expression',          # 二元表达式
    'unary_expression',           # 一元表达式
    'update_expression',          # 更新表达式 (++/--)
    'ternary_expression',         # 三元表达式
    'logical_expression',         # 逻辑表达式
    'equality_expression',        # 相等表达式
    'relational_expression',      # 关系表达式
    'shift_expression',           # 移位表达式
    'additive_expression',        # 加法表达式
    'multiplicative_expression',  # 乘法表达式
    'exponentiation_expression',  # 指数表达式
    'instanceof_expression',      # instanceof
    'in_expression',              # in 表达式
    'yield_expression',           # yield
    
    # === 对象和数组 ===
    'object',                     # 对象字面量
    'object_assignment_pattern',  # 对象赋值模式
    'pair',                       # 键值对
    'shorthand_property_identifier_pattern',
    'array',                      # 数组字面量
    'array_pattern',              # 数组模式
    
    # === 解构 ===
    'destructuring_pattern',      # 解构模式
    'object_pattern',             # 对象解构
    'array_pattern',              # 数组解构
    'rest_pattern',               # 剩余模式
    
    # === 控制流 ===
    'if_statement',               # if 语句
    'else_clause',                # else 子句
    'switch_statement',           # switch 语句
    'switch_case',                # switch case
    'switch_default',             # switch default
    'switch_body',                # switch 体
    'for_statement',              # for 循环
    'for_in_statement',           # for...in
    'for_of_statement',           # for...of
    'while_statement',            # while 循环
    'do_statement',               # do-while
    'continue_statement',         # continue
    'break_statement',            # break
    'return_statement',           # return
    'throw_statement',            # throw
    'try_statement',              # try
    'catch_clause',               # catch
    'finally_clause',             # finally
    'with_statement',             # with (已废弃)
    'debugger_statement',         # debugger
    
    # === 其他语句 ===
    'empty_statement',            # 空语句 (;)
    'labeled_statement',          # 标签语句
    'statement_block',            # 语句块 {}
    'expression_statement',       # 表达式语句
    
    # === Promise/Async ===
    'await_expression',           # await 表达式
    'await',                      # await 关键字
    'promise',                    # Promise
    'yield_expression',           # yield 表达式

    # === 注释 ===
    'comment',                    # 注释
    
    # === 模块 ===
    'export_statement',           # export
    'import_statement',           # import
    'namespace_export',           # export *
    'namespace_import',           # import *
    
    # === 关键字（单独节点） ===
    'function',                   # function 关键字
    'from',                       # from 关键字
    'import',                     # import 关键字
    'export',                     # export 关键字
    'as',                         # as 关键字
    'else',                       # else 关键字
    'static',                     # static 关键字
    'new',                        # new 关键字
    'typeof',                     # typeof 操作符
    'void',                       # void 操作符
    'class',                      # class 关键字
    'extends',                    # extends 关键字
    'in',                         # in 操作符
    'instanceof',                 # instanceof 操作符
    'try',                        # try 关键字
    'catch',                      # catch 关键字
    'case',                       # case 关键字
    'default',                    # default 关键字
    'while',                      # while 关键字
    'do',                         # do 关键字
    'for',                        # for 关键字
    'of',                         # of 关键字
    'delete',                     # delete 操作符
    'break',                      # break 关键字
    'switch',                     # switch 关键字
    
    # === JSX (React) ===
    'jsx_element',                # JSX 元素 <Component>...</Component>
    'jsx_self_closing_element',   # JSX 自关闭元素 <Component />
    'jsx_opening_element',        # JSX 开始标签 <Component>
    'jsx_closing_element',        # JSX 结束标签 </Component>
    'jsx_attribute',              # JSX 属性 <Component attr="value" />
    'jsx_expression',             # JSX 表达式 <Component>{expr}</Component>
    'jsx_text',                   # JSX 文本 <Component>text</Component>
    'jsx_namespace_name',         # JSX 命名空间名称 <ns:Component>
    'jsx_fragment',               # JSX Fragment <>...</>

    # === 其他 ===
    'parenthesized_expression',   # 括号表达式
    'eval_expression',            # eval
    'meta_property',              # new.target, import.meta
}

# ============================================================================
# 名称节点类型
# ============================================================================

IS_NAME_NODE_TYPES = {
    'identifier',                 # 普通标识符
    'property_identifier',        # 属性标识符
    'private_property_identifier', # 私有属性
    'type_identifier',            # 类型标识符 (JSDoc)
    'function_name',              # 函数名
    'class_name',                 # 类名
    'variable_name',              # 变量名
    'parameter_name',             # 参数名
    'method_name',                # 方法名
    'label_name',                 # 标签名
    'string',                     # 字符串字面量（用于 import 模块路径）
    'string_fragment',            # 字符串片段（用于 import 模块路径）
    'jsx_namespace_name',         # JSX 命名空间名称
}

# ============================================================================
# 作用域创建类型
# ============================================================================

SCOPE_CREATING_TYPES = {
    "program",                    # 全局作用域
    "function_declaration",       # 函数作用域
    "function_expression",        # 函数表达式作用域
    "arrow_function",             # 箭头函数作用域
    "generator_function",         # generator 作用域
    "async_function_declaration", # async 函数作用域
    "class_declaration",          # 类作用域
    "method_definition",          # 方法作用域
    "statement_block",            # 块作用域
    "for_statement",              # for 循环作用域
    "for_in_statement",           # for...in 作用域
    "for_of_statement",           # for...of 作用域
    "if_statement",               # if 作用域
    "switch_statement",           # switch 作用域
    "catch_clause",               # catch 作用域
    "object",                     # 对象字面量作用域
}

# ============================================================================
# 定义上下文类型
# ============================================================================

DEFINING_CONTEXT_TYPES = {
    # 函数
    "function_declaration",
    "function_expression",
    "arrow_function",
    "generator_function",
    "async_function_declaration",
    "method_definition",
    "getter_method",
    "setter_method",
    
    # 类
    "class_declaration",
    
    # 变量
    "variable_declaration",
    "variable_declarator",
    "lexical_declaration",
    
    # 参数
    "formal_parameters",
    "optional_parameter",
    "rest_pattern",
    "default_parameter",
    
    # 导入
    "import_statement",
    "import_specifier",
    "import_namespace_specifier",
    
    # 字段
    "field_definition",
}

# ============================================================================
# 节点类型到操作的映射
# ============================================================================

NODE_TYPE_TO_OP = {
    # === 定义操作 ===
    'function_declaration': 'def',
    'function_expression': 'def',
    'arrow_function': 'def',
    'generator_function': 'def',
    'async_function_declaration': 'def',
    'class_declaration': 'def',
    'method_definition': 'def',
    'getter_method': 'def',
    'setter_method': 'def',
    'variable_declaration': 'def',
    'variable_declarator': 'def',
    'lexical_declaration': 'def',
    'field_definition': 'def',
    
    # === 导入/导出 ===
    'import_statement': 'import',
    'export_statement': 'export',
    
    # === 调用操作 ===
    'call_expression': 'call',
    'new_expression': 'call',
    'eval_expression': 'call',
    'method_reference': 'call',
    
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
    'augmented_assignment_expression': 'assign',
    'variable_declarator': 'assign',
    
    # === 算术操作 ===
    'binary_expression': 'arith',
    'unary_expression': 'arith',
    'update_expression': 'arith',
    'exponentiation_expression': 'arith',
    'sequence_expression': 'seq',
    'spread_element': 'spread',

    # === 逻辑操作 ===
    'logical_expression': 'logic',
    
    # === 比较操作 ===
    'equality_expression': 'compare',
    'relational_expression': 'compare',
    
    # === 位操作 ===
    'shift_expression': 'bitwise',
    
    # === 控制流 ===
    'return_statement': 'return',
    'if_statement': 'control',
    'else_clause': 'control',
    'switch_statement': 'control',
    'switch_case': 'control',
    'switch_default': 'control',
    'for_statement': 'control',
    'for_in_statement': 'control',
    'for_of_statement': 'control',
    'while_statement': 'control',
    'do_statement': 'control',
    'break_statement': 'control',
    'continue_statement': 'control',
    
    # === 异常处理 ===
    'throw_statement': 'throw',
    'try_statement': 'try',
    'catch_clause': 'catch',
    'finally_clause': 'finally',
    
    # === 条件操作 ===
    'ternary_expression': 'cond',
    
    # === 异步 ===
    'await_expression': 'await',
    'yield_expression': 'yield',

    # === 解构 ===
    'object_pattern': 'destructure',
    'array_pattern': 'destructure',
    'rest_pattern': 'destructure',
}

# ============================================================================
# 名称提取规则
# ============================================================================
# 用于在 AST 解析阶段从子节点提取函数名、类名等
# 格式：父节点类型 -> [子节点类型列表]（按优先级顺序）

NAME_EXTRACT_RULES = {
    # 函数定义
    "function_declaration": ["identifier", "function_name"],
    "function_expression": ["identifier", "function_name"],
    "arrow_function": [],  # 箭头函数通常没有名称，从父节点获取
    "generator_function": ["identifier", "function_name"],
    "async_function_declaration": ["identifier", "function_name"],
    
    # 方法定义
    "method_definition": ["property_identifier", "identifier", "function_name"],
    
    # 类定义
    "class_declaration": ["type_identifier", "identifier"],
    "class_expression": ["type_identifier", "identifier"],
    
    # 变量定义（用于箭头函数/函数表达式）
    "variable_declarator": ["identifier"],
    
    # 导入/导出
    "import_clause": ["identifier"],
    "export_specifier": ["identifier"],
    
    # TypeScript 特有
    "type_alias_declaration": ["type_identifier"],
    "interface_declaration": ["type_identifier"],
    "enum_declaration": ["identifier"],
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
