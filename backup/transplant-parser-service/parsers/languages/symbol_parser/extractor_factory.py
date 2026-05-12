# parsers/languages/symbol_parser/extractor_factory.py
"""
符号提取器工厂模块

提供统一的符号提取器创建接口，支持多语言符号分析。
使用工厂模式 + 策略模式，根据语言名称返回对应的符号提取器实例。

符号包括：函数、变量、类、结构体、枚举、宏等定义和引用。
"""
import logging
from typing import Dict, Type, Optional, List, Any, Set
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class SymbolExtractor(ABC):
    """
    符号提取器抽象基类
    
    定义符号提取的标准接口，各语言需实现自己的提取器。
    符号是代码图中的基本节点，用于构建调用图和依赖图。
    """
    
    @abstractmethod
    def get_symbol_node_types(self) -> List[str]:
        """
        获取符号相关的 AST 节点类型
        
        Returns:
            节点类型列表，如 ['function_definition', 'declaration'] (C)
        """
        pass
    
    @abstractmethod
    def extract_symbols(self, nodes: List[Dict]) -> List[Dict[str, Any]]:
        """
        从 AST 节点提取符号信息
        
        Args:
            nodes: AST 节点列表
            
        Returns:
            符号列表，每项包含 symbol_name, symbol_type, def_node_id 等
        """
        pass
    
    @abstractmethod
    def is_definition(self, node: Dict) -> bool:
        """
        判断节点是否为定义（而非声明或引用）
        
        Args:
            node: AST 节点
            
        Returns:
            True 如果是定义
        """
        pass
    
    @abstractmethod
    def get_symbol_name(self, node: Dict) -> Optional[str]:
        """
        从节点提取符号名称
        
        Args:
            node: AST 节点
            
        Returns:
            符号名称，无法提取则返回 None
        """
        pass
    
    @abstractmethod
    def get_symbol_type(self, node: Dict) -> str:
        """
        获取符号类型（function, variable, class, macro 等）
        
        Args:
            node: AST 节点
            
        Returns:
            符号类型字符串
        """
        pass
    
    def get_scope(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        """
        获取节点的作用域
        
        默认实现：返回 scope_node_id 对应的节点
        子类可重写以支持更复杂的作用域规则
        
        Args:
            node: AST 节点
            all_nodes: 所有节点映射
            
        Returns:
            作用域节点，无法确定则返回 None
        """
        scope_id = node.get('scope_node_id')
        if scope_id and scope_id in all_nodes:
            return all_nodes[scope_id]
        return None
    
    def get_language(self) -> str:
        """获取提取器支持的语言名称"""
        return self.__class__.__name__.replace('SymbolExtractor', '').lower()


class SymbolExtractorRegistry:
    """
    符号提取器注册表
    
    管理所有可用的符号提取器，支持动态注册和查询。
    """
    
    _extractors: Dict[str, Type[SymbolExtractor]] = {}
    
    @classmethod
    def register(cls, lang: str, extractor_class: Type[SymbolExtractor]):
        """
        注册语言对应的提取器
        
        Args:
            lang: 语言名称
            extractor_class: 提取器类
        """
        cls._extractors[lang] = extractor_class
        logger.info(f"Registered SymbolExtractor for language: {lang}")
    
    @classmethod
    def get_extractor(cls, lang: str) -> Optional[SymbolExtractor]:
        """
        获取语言对应的提取器实例
        
        Args:
            lang: 语言名称
            
        Returns:
            提取器实例，如果语言不支持则返回 None
        """
        extractor_class = cls._extractors.get(lang)
        if not extractor_class:
            logger.warning(f"No SymbolExtractor found for language: {lang}")
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
def register_symbol_extractor(lang: str):
    """
    装饰器：注册符号提取器
    
    使用示例:
        @register_symbol_extractor('python')
        class PythonSymbolExtractor(SymbolExtractor):
            ...
    """
    def decorator(cls: Type[SymbolExtractor]) -> Type[SymbolExtractor]:
        SymbolExtractorRegistry.register(lang, cls)
        return cls
    return decorator


# 导入默认提取器（C 语言）
# 注意：这里先不导入具体实现，由各语言模块自行注册
# from .c_symbol_parser import CSymbolExtractor
# SymbolExtractorRegistry.register('c', CSymbolExtractor)


# 便捷函数
def get_symbol_extractor(lang: str) -> Optional[SymbolExtractor]:
    """便捷函数：获取符号提取器"""
    return SymbolExtractorRegistry.get_extractor(lang)


def get_supported_symbol_languages() -> List[str]:
    """便捷函数：获取支持的语言列表"""
    return SymbolExtractorRegistry.get_registered_languages()
