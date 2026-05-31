# parsers/languages/code_parser/lang_go.py
"""
Go 语言 AST 配置

基于 tree-sitter-go 的节点类型定义。
支持 Go 1.18+ (包括泛型支持)。

参考：https://github.com/tree-sitter/tree-sitter-go
"""
from .lang_base import LanguageConfig

# ============================================================================
# 重要节点类型
# ============================================================================

IMPORTANT_NODE_TYPES_SET = {
    # === 顶层结构 ===
    'source_file',                # Go 源文件
    
    # === 包和导入 ===
    'package_clause',             # package 声明
    'package_identifier',         # 包标识符
    'import_declaration',         # import 声明
    'import_spec',                # 导入说明符
    'imported_package_name',      # 导入的包名
    'dot_import',                 # . 导入
    'blank_import',               # _ 导入
    
    # === 函数定义 ===
    'function_declaration',       # func 函数声明
    'function_body',              # 函数体
    'parameter_list',             # 参数列表
    'parameter_declaration',      # 参数声明
    'variadic_parameter',         # 可变参数 (...T)
    'result',                     # 返回结果
    'result_parameters',          # 返回参数列表
    
    # === 方法定义 ===
    'method_declaration',         # 方法声明
    'receiver',                   # 接收者
    'pointer_type',               # 指针类型
    
    # === 泛型 (Go 1.18+) ===
    'type_parameters',            # 类型参数
    'type_parameter_list',        # 类型参数列表
    'type_instantiation',         # 类型实例化
    'type_arguments',             # 类型实参
    
    # === 类型定义 ===
    'type_declaration',           # type 声明
    'type_spec',                  # 类型说明符
    'struct_type',                # struct 类型
    'field_declaration',          # 字段声明
    'field_declaration_list',     # 字段声明列表
    'embedded_field',             # 嵌入字段 (匿名)
    'interface_type',             # interface 类型
    'method_elem',                # 方法元素
    'type_elem',                  # 类型元素
    
    # === 常量和变量 ===
    'const_declaration',          # const 声明
    'var_declaration',            # var 声明
    'value_spec',                 # 值说明符
    'iota',                       # iota
    
    # === 短变量声明 ===
    'short_var_declaration',      # := 短变量声明
    
    # === 标识符和字面量 ===
    'identifier',                 # 标识符
    'field_identifier',           # 字段标识符
    'package_identifier',         # 包标识符
    'type_identifier',            # 类型标识符
    'label_name',                 # 标签名
    'string_literal',             # 字符串字面量
    'interpreted_string_literal', # 解释字符串 ("...")
    'raw_string_literal',         # 原始字符串 (`...`)
    'rune_literal',               # rune 字面量
    'int_literal',                # 整数
    'float_literal',              # 浮点数
    'imaginary_literal',          # 虚数
    'true',                       # true
    'false',                      # false
    'nil',                        # nil
    
    # === 表达式 ===
    'assignment_statement',       # 赋值语句
    'short_var_declaration',      # 短变量声明
    'call_expression',            # 调用表达式
    'selector_expression',        # 选择器表达式 (x.f)
    'index_expression',           # 索引表达式 (x[i])
    'slice_expression',           # 切片表达式 (x[i:j])
    'type_assertion',             # 类型断言 (x.(T))
    'type_conversion',            # 类型转换 (T(x))
    
    # === 运算符表达式 ===
    'binary_expression',          # 二元表达式
    'unary_expression',           # 一元表达式
    
    # === 复合字面量 ===
    'composite_literal',          # 复合字面量
    'literal_value',              # 字面量值
    'literal_element',            # 字面量元素
    'keyed_element',              # 键控元素
    
    # === 控制流 ===
    'if_statement',               # if 语句
    'else_clause',                # else 子句
    'for_statement',              # for 循环
    'for_clause',                 # for 子句
    'range_clause',               # range 子句
    'switch_statement',           # switch 语句
    'switch_expression',          # switch 表达式
    'case_clause',                # case 子句
    'default_case',               # default 子句
    'type_switch',                # type switch
    'type_case',                  # type case
    
    # === 其他语句 ===
    'return_statement',           # return 语句
    'break_statement',            # break 语句
    'continue_statement',         # continue 语句
    'goto_statement',             # goto 语句
    'labeled_statement',          # 标签语句
    'fallthrough_statement',      # fallthrough
    'defer_statement',            # defer
    'go_statement',               # go (goroutine)
    'send_statement',             # send (channel)
    'receive_statement',          # receive (channel)
    'expression_statement',       # 表达式语句
    'empty_statement',            # 空语句
    
    # === 块 ===
    'block',                      # 代码块 {}
    
    # === Channel 和 Select ===
    'channel_type',               # channel 类型
    'channel_operation',          # channel 操作
    'select_statement',           # select 语句
    'select_clause',              # select 子句
    'communication_case',         # 通信 case
    'default_case',               # default case
    
    # === 其他类型 ===
    'array_type',                 # 数组类型
    'slice_type',                 # 切片类型
    'map_type',                   # map 类型
    'chan_type',                  # channel 类型
    'struct_type',                # struct 类型
    'interface_type',             # interface 类型
    'function_type',              # 函数类型
    
    # === 特殊结构 ===
    'error_handling',             # err != nil 模式
    'multiple_assignment',        # 多值赋值
    'blank_identifier',           # _ 空白标识符
}

# ============================================================================
# 名称节点类型
# ============================================================================

IS_NAME_NODE_TYPES = {
    'identifier',                 # 普通标识符
    'field_identifier',           # 字段标识符
    'package_identifier',         # 包标识符
    'type_identifier',            # 类型标识符
    'label_name',                 # 标签名
    'function_name',              # 函数名
    'method_name',                # 方法名
    'parameter_name',             # 参数名
    'variable_name',              # 变量名
    'constant_name',              # 常量名
    'type_name',                  # 类型名
}

# ============================================================================
# 作用域创建类型
# ============================================================================

SCOPE_CREATING_TYPES = {
    "source_file",                # 文件级作用域 (package)
    "function_declaration",       # 函数作用域
    "method_declaration",         # 方法作用域
    "block",                      # 块作用域
    "if_statement",               # if 作用域
    "for_statement",              # for 作用域
    "switch_statement",           # switch 作用域
    "type_switch",                # type switch 作用域
    "select_statement",           # select 作用域
    "case_clause",                # case 作用域
}

# ============================================================================
# 定义上下文类型
# ============================================================================

DEFINING_CONTEXT_TYPES = {
    # 函数/方法
    "function_declaration",
    "method_declaration",
    
    # 类型
    "type_declaration",
    "type_spec",
    "struct_type",
    "interface_type",
    
    # 常量/变量
    "const_declaration",
    "var_declaration",
    "value_spec",
    "short_var_declaration",
    
    # 参数
    "parameter_declaration",
    "variadic_parameter",
    
    # 字段
    "field_declaration",
    "embedded_field",
    
    # 包
    "package_clause",
}

# ============================================================================
# 节点类型到操作的映射
# ============================================================================

NODE_TYPE_TO_OP = {
    # === 定义操作 ===
    'function_declaration': 'def',
    'method_declaration': 'def',
    'type_declaration': 'def',
    'type_spec': 'def',
    'const_declaration': 'def',
    'var_declaration': 'def',
    'short_var_declaration': 'assign',
    'field_declaration': 'def',
    'package_clause': 'def',
    
    # === 导入操作 ===
    'import_declaration': 'import',
    'import_spec': 'import',
    
    # === 调用操作 ===
    'call_expression': 'call',
    'go_statement': 'goroutine',
    'defer_statement': 'defer',
    
    # === 赋值操作 ===
    'assignment_statement': 'assign',
    'short_var_declaration': 'assign',
       
    # === 算术操作 ===
    'binary_expression': 'arith',
    'unary_expression': 'arith',
    
    # === 类型操作 ===
    'type_assertion': 'cast',
    'type_conversion': 'cast',
    
    # === 控制流 ===
    'return_statement': 'return',
    'if_statement': 'control',
    'for_statement': 'control',
    'for_clause': 'control',
    'range_clause': 'control',
    'switch_statement': 'control',
    'switch_expression': 'control',
    'type_switch': 'control',
    'case_clause': 'control',
    'break_statement': 'control',
    'continue_statement': 'control',
    'goto_statement': 'control',
    'fallthrough_statement': 'control',
    
    # === Channel 操作 ===
    'send_statement': 'send',
    'receive_statement': 'recv',
    'select_statement': 'select',
    
    # === 特殊语句 ===
    'defer_statement': 'defer',
}

# ============================================================================
# 名称提取规则
# ============================================================================

NAME_EXTRACT_RULES = {
    # 函数定义
    "function_declaration": ["identifier"],
    "function_literal": [],  # 匿名函数
    
    # 方法定义
    "method_declaration": ["identifier"],
    
    # 类型定义
    "type_spec": ["type_identifier"],
    "type_declaration": ["type_identifier"],
    
    # 变量/常量定义
    "var_spec": ["identifier"],
    "const_spec": ["identifier"],
    "short_var_declaration": ["identifier"],
    
    # 导入
    "import_spec": ["package_identifier"],
    "import_declaration": ["package_identifier"],
    
    # 接口
    "method_spec": ["identifier"],
    "interface_type": ["type_identifier"],
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
