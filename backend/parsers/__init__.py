"""
parsers — 基于 tree-sitter 的源码解析器

架构:
- code_parser/: 语言配置 + tree-sitter 解析器工厂
- call_parser/: 调用图提取器（按语言）
- dependence_parser/: 依赖图提取器（按语言）
- symbol_parser/: 符号提取器（按语言）
- languages/: 语言处理器门面

数据存储: SQLite (通过 store 层)
"""
