# parsers/languages/java/__init__.py
"""
Java 语言处理器模块

提供 Java 语言的完整处理功能：
- AST 解析
- 符号提取
- 调用图提取
- 依赖图提取
"""
from .processor import JavaLanguageProcessor

__all__ = ['JavaLanguageProcessor']
