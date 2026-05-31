# parsers/languages/dependence_parser/extractor_factory.py
"""
依赖图提取器工厂模块

提供统一的依赖图提取器创建接口，支持多语言依赖分析。
使用工厂模式 + 策略模式，根据语言名称返回对应的依赖提取器实例。
"""
import logging
from typing import Dict, Type, Optional, List, Any, Tuple, Set
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class DependencyExtractor(ABC):
    """
    依赖图提取器抽象基类
    
    定义依赖提取的标准接口，各语言需实现自己的提取器。
    依赖包括：#include (C/C++), import (Python/Java), require (JS), use (Perl/Ruby) 等
    """
    
    @abstractmethod
    def get_required_node_types(self) -> List[str]:
        """
        获取依赖相关的 AST 节点类型
        
        Returns:
            节点类型列表，如 ['preproc_include'] (C), ['import_statement'] (Python)
        """
        pass
    
    @abstractmethod
    def extract_dependencies(self, nodes: List[Dict]) -> Tuple[List[Dict], Set[str]]:
        """
        从 AST 节点提取依赖关系
        
        Args:
            nodes: AST 节点列表
            
        Returns:
            (dependencies, system_targets)
            - dependencies: 依赖列表，每项包含 from_file_id, target, is_angle_bracket
            - system_targets: 系统库/外部库目标集合
        """
        pass
    
    @abstractmethod
    def is_system_include(self, target: str) -> bool:
        """
        判断是否为系统库引用（已废弃，保留向后兼容）
        
        Args:
            target: 依赖目标字符串
            
        Returns:
            True 如果是系统库
        """
        pass
    
    def is_internal_dependency(
        self,
        target: str,
        project_files_by_basename: Dict[str, List[int]]
    ) -> Tuple[bool, Optional[int]]:
        """
        判断该依赖是否指向项目内部文件
        
        默认实现：按 basename 匹配（适用于 C/C++）。
        子类可重写以支持其他语言（如 Python 按模块路径，Go 按 import path）。

        返回：(is_internal: bool, matched_file_id: int or None)
        """
        import os
        basename = os.path.basename(target)
        matched_ids = project_files_by_basename.get(basename, [])
        if matched_ids:
            return True, matched_ids[0]  # 取第一个匹配
        return False, None
    
    def get_language(self) -> str:
        """获取提取器支持的语言名称"""
        return self.__class__.__name__.replace('DependencyExtractor', '').lower()


class DependencyExtractorRegistry:
    """
    依赖图提取器注册表
    
    管理所有可用的依赖图提取器，支持动态注册和查询。
    """
    
    _extractors: Dict[str, Type[DependencyExtractor]] = {}
    
    @classmethod
    def register(cls, lang: str, extractor_class: Type[DependencyExtractor]):
        """
        注册语言对应的提取器
        
        Args:
            lang: 语言名称
            extractor_class: 提取器类
        """
        cls._extractors[lang] = extractor_class
        logger.info(f"Registered DependencyExtractor for language: {lang}")
    
    @classmethod
    def get_extractor(cls, lang: str) -> Optional[DependencyExtractor]:
        """
        获取语言对应的提取器实例
        
        Args:
            lang: 语言名称
            
        Returns:
            提取器实例，如果语言不支持则返回 None
        """
        extractor_class = cls._extractors.get(lang)
        if not extractor_class:
            logger.warning(f"No DependencyExtractor found for language: {lang}")
            return None
        return extractor_class()
    
    @classmethod
    def get_registered_languages(cls) -> List[str]:
        """获取所有已注册的语言列表"""
        return list(cls._extractors.keys())
    
    @classmethod
    def is_language_supported(cls, lang: str) -> bool:
        """检查语言是否有对应的提取器"""
        return lang in cls._extractors


# 装饰器：用于自动注册提取器
def register_dependency_extractor(lang: str):
    """
    装饰器：注册依赖图提取器
    
    使用示例:
        @register_dependency_extractor('python')
        class PythonImportExtractor(DependencyExtractor):
            ...
    """
    def decorator(cls: Type[DependencyExtractor]) -> Type[DependencyExtractor]:
        DependencyExtractorRegistry.register(lang, cls)
        return cls
    return decorator


# 导入并注册所有语言提取器
# 使用延迟导入避免循环引用
_extractors_registered = False

def _register_all_extractors():
    """注册所有依赖提取器（延迟导入）"""
    global _extractors_registered
    if _extractors_registered:
        return
    
    # C/C++
    from .c_dependence_parser import CIncludeExtractor
    DependencyExtractorRegistry.register('c', CIncludeExtractor)
    DependencyExtractorRegistry.register('c_header', CIncludeExtractor)
    DependencyExtractorRegistry.register('cpp', CIncludeExtractor)
    DependencyExtractorRegistry.register('cpp_header', CIncludeExtractor)

    # Python
    from .python_dependence_parser import PythonImportExtractor
    DependencyExtractorRegistry.register('python', PythonImportExtractor)

    # Java
    from .java_dependence_parser import JavaImportExtractor
    DependencyExtractorRegistry.register('java', JavaImportExtractor)

    # JavaScript/TypeScript
    from .javascript_dependence_parser import JavaScriptRequireExtractor
    DependencyExtractorRegistry.register('javascript', JavaScriptRequireExtractor)
    DependencyExtractorRegistry.register('typescript', JavaScriptRequireExtractor)

    # Go
    from .go_dependence_parser import GoModExtractor
    DependencyExtractorRegistry.register('go', GoModExtractor)

    # Rust
    from .rust_dependence_parser import RustModExtractor
    DependencyExtractorRegistry.register('rust', RustModExtractor)
    
    _extractors_registered = True


# 便捷函数
def get_dependency_extractor(lang: str) -> Optional[DependencyExtractor]:
    """便捷函数：获取依赖图提取器"""
    # 确保提取器已注册
    _register_all_extractors()
    return DependencyExtractorRegistry.get_extractor(lang)


def get_supported_dependency_languages() -> List[str]:
    """便捷函数：获取支持的语言列表"""
    _register_all_extractors()
    return DependencyExtractorRegistry.get_registered_languages()
