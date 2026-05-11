# parsers/languages/__init__.py
"""
多语言处理器模块

提供统一的语言处理接口，支持：
- AST 解析
- 符号提取
- 调用图提取
- 依赖图提取

架构:
- base.py: 抽象基类定义
- language_registry.py: 语言注册表
- <language>/: 各语言处理器实现
"""
from .base import (
    ASTParser,
    SymbolExtractor,
    CallGraphExtractor,
    DependencyExtractor,
    LanguageProcessor
)
from .language_registry import LanguageRegistry

__all__ = [
    'ASTParser',
    'SymbolExtractor',
    'CallGraphExtractor',
    'DependencyExtractor',
    'LanguageProcessor',
    'LanguageRegistry',
]
