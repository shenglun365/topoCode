# parsers/languages/call_parser/extractor_factory.py
"""
调用图提取器工厂模块

提供统一的调用图提取器创建接口，支持多语言调用图分析。
使用工厂模式 + 策略模式，根据语言名称返回对应的调用图提取器实例。
"""
import logging
from typing import Dict, Type, Optional, List, Any
from abc import ABC, abstractmethod

logger = logging.getLogger(__name__)


class CallGraphExtractor(ABC):
    """
    调用图提取器抽象基类
    
    定义调用图提取的标准接口，各语言需实现自己的提取器。
    """
    
    @abstractmethod
    def extract(self, proj_id: int, nodes_by_file: Dict[int, Dict[int, Dict]]) -> List[Dict[str, Any]]:
        """
        提取调用图边
        
        Args:
            proj_id: 项目 ID
            nodes_by_file: 按文件分组的 AST 节点 {file_id: {node_id: node_dict}}
            
        Returns:
            调用边列表，每条边包含 caller/callee 信息
        """
        pass
    
    @abstractmethod
    def is_call_expression(self, node: Dict) -> bool:
        """
        判断节点是否为调用表达式
        
        Args:
            node: AST 节点字典
            
        Returns:
            True 如果是调用表达式
        """
        pass
    
    @abstractmethod
    def extract_callee_name(self, call_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从调用节点提取被调用函数名
        
        Args:
            call_node: 调用表达式节点
            all_nodes: 当前文件的所有节点映射
            
        Returns:
            被调用函数名，无法提取则返回 None
        """
        pass
    
    @abstractmethod
    def find_enclosing_function(self, node: Dict, all_nodes: Dict[int, Dict]) -> Optional[Dict]:
        """
        查找包含该节点的函数定义节点
        
        Args:
            node: AST 节点
            all_nodes: 当前文件的所有节点映射
            
        Returns:
            包含该节点的函数定义节点，找不到则返回 None
        """
        pass
    
    @abstractmethod
    def extract_function_name(self, func_node: Dict, all_nodes: Dict[int, Dict]) -> Optional[str]:
        """
        从函数定义节点提取函数名
        
        Args:
            func_node: 函数定义节点
            all_nodes: 当前文件的所有节点映射
            
        Returns:
            函数名，无法提取则返回 None
        """
        pass
    
    def get_language(self) -> str:
        """获取提取器支持的语言名称"""
        return self.__class__.__name__.replace('CallGraphExtractor', '').lower()


class CallGraphExtractorRegistry:
    """
    调用图提取器注册表
    
    管理所有可用的调用图提取器，支持动态注册和查询。
    """
    
    _extractors: Dict[str, Type[CallGraphExtractor]] = {}
    
    @classmethod
    def register(cls, lang: str, extractor_class: Type[CallGraphExtractor]):
        """
        注册语言对应的提取器
        
        Args:
            lang: 语言名称
            extractor_class: 提取器类
        """
        cls._extractors[lang] = extractor_class
        logger.info(f"Registered CallGraphExtractor for language: {lang}")
    
    @classmethod
    def get_extractor(cls, lang: str) -> Optional[CallGraphExtractor]:
        """
        获取语言对应的提取器实例
        
        Args:
            lang: 语言名称
            
        Returns:
            提取器实例，如果语言不支持则返回 None
        """
        extractor_class = cls._extractors.get(lang)
        if not extractor_class:
            logger.warning(f"No CallGraphExtractor found for language: {lang}")
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
def register_call_extractor(lang: str):
    """
    装饰器：注册调用图提取器
    
    使用示例:
        @register_call_extractor('python')
        class PythonCallGraphExtractor(CallGraphExtractor):
            ...
    """
    def decorator(cls: Type[CallGraphExtractor]) -> Type[CallGraphExtractor]:
        CallGraphExtractorRegistry.register(lang, cls)
        return cls
    return decorator


# 延迟导入所有语言调用图提取器（避免循环导入）
_extractors_registered = False

def _register_all_call_extractors():
    """注册所有调用图提取器（延迟导入）"""
    global _extractors_registered
    if _extractors_registered:
        return
    
    # C/C++
    from .c_parser import CLanguageParser
    CallGraphExtractorRegistry.register('c', CLanguageParser)
    CallGraphExtractorRegistry.register('c_header', CLanguageParser)

    # Python
    from .python_call_parser import PythonCallExtractor
    CallGraphExtractorRegistry.register('python', PythonCallExtractor)

    # Java
    from .java_call_parser import JavaCallExtractor
    CallGraphExtractorRegistry.register('java', JavaCallExtractor)

    # JavaScript/TypeScript
    from .javascript_call_parser import JavaScriptCallExtractor
    CallGraphExtractorRegistry.register('javascript', JavaScriptCallExtractor)
    CallGraphExtractorRegistry.register('typescript', JavaScriptCallExtractor)

    # Go
    from .go_call_parser import GoCallExtractor
    CallGraphExtractorRegistry.register('go', GoCallExtractor)

    # Rust
    from .rust_call_parser import RustCallExtractor
    CallGraphExtractorRegistry.register('rust', RustCallExtractor)

    _extractors_registered = True


# 便捷函数
def get_call_graph_extractor(lang: str) -> Optional[CallGraphExtractor]:
    """便捷函数：获取调用图提取器"""
    _register_all_call_extractors()
    return CallGraphExtractorRegistry.get_extractor(lang)


def get_supported_call_graph_languages() -> List[str]:
    """便捷函数：获取支持的语言列表"""
    _register_all_call_extractors()
    return CallGraphExtractorRegistry.get_registered_languages()
