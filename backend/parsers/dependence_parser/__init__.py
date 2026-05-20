# parsers/dependence_parser/__init__.py
"""
依赖图提取器模块

导出基类和便捷函数
"""
from .extractor_factory import (
    DependencyExtractor,
    DependencyExtractorRegistry,
    get_dependency_extractor,
    get_supported_dependency_languages,
    register_dependency_extractor,
)

__all__ = [
    'DependencyExtractor',
    'DependencyExtractorRegistry',
    'get_dependency_extractor',
    'get_supported_dependency_languages',
    'register_dependency_extractor',
]
