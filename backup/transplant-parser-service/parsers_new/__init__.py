"""
parsers_new — 基于 tree-sitter 的全新解析器

完全重写，不依赖原有 parsers/ 的 MongoDB 代码。
直接操作 SQLite（通过 AnalysisStore）。
"""
from .language_registry import LanguageRegistry
from .base import LanguageProcessor

__all__ = [
    "LanguageRegistry",
    "LanguageProcessor",
]
