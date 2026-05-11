# parsers/languages/dependence_parser/__init__.py
"""
依赖图提取器模块

导出基类和便捷函数
"""
from .base import DependencyExtractor
from .extractor_factory import (
    DependencyExtractorRegistry,
    get_dependency_extractor,
    get_supported_dependency_languages,
    register_dependency_extractor,
)

# 延迟导入具体实现，避免循环引用
__all__ = [
    'DependencyExtractor',
    'DependencyExtractorRegistry',
    'get_dependency_extractor',
    'get_supported_dependency_languages',
    'register_dependency_extractor',
]
