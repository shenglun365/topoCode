# parsers/languages/c_family/__init__.py
"""
C/C++ 共享模块

提供 C 和 C++ 语言处理器的共享逻辑：
- AST 解析（使用 tree-sitter-c 和 tree-sitter-cpp）
- 工具函数

架构:
- ast_parser.py: 共享 AST 解析逻辑
- utils.py: 共享工具函数
"""
from .ast_parser import CFamilyASTParser
from .utils import get_tree_sitter_language

__all__ = [
    'CFamilyASTParser',
    'get_tree_sitter_language',
]
