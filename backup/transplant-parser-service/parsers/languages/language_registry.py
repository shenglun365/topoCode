# parsers/languages/language_registry.py
"""
语言处理器注册表

提供语言处理器的注册、查询和路由功能。

架构:
- 单例模式：全局唯一的注册表实例
- 自动注册：语言处理器模块导入时自动注册
- 扩展名路由：根据文件扩展名自动选择处理器
"""
import logging
import pathlib
from typing import Dict, Type, Optional, List
from .base import LanguageProcessor

logger = logging.getLogger(__name__)


class LanguageRegistry:
    """语言处理器注册表（单例模式）"""
    
    _instance: Optional['LanguageRegistry'] = None
    _processors: Dict[str, LanguageProcessor] = {}
    _extension_map: Dict[str, str] = {}  # 扩展名 -> 语言名
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @classmethod
    def register(cls, processor: LanguageProcessor):
        """
        注册语言处理器
        
        Args:
            processor: 语言处理器实例
            
        Example:
            >>> from .java.processor import JavaLanguageProcessor
            >>> LanguageRegistry.register(JavaLanguageProcessor())
        """
        lang = processor.language_name
        if lang in cls._processors:
            logger.warning(f"Language processor '{lang}' already registered, overriding")
        
        cls._processors[lang] = processor
        
        # 注册文件扩展名映射
        for ext in processor.file_extensions:
            ext_lower = ext.lower()
            if ext_lower in cls._extension_map:
                # 处理扩展名冲突，使用优先级高的
                existing_lang = cls._extension_map[ext_lower]
                existing_processor = cls._processors.get(existing_lang)
                if existing_processor and processor.priority > existing_processor.priority:
                    cls._extension_map[ext_lower] = lang
                    logger.info(f"Extension '{ext}' now mapped to '{lang}' (higher priority)")
            else:
                cls._extension_map[ext_lower] = lang
        
        logger.info(f"Registered language processor: {lang} (extensions: {processor.file_extensions})")
    
    @classmethod
    def get_processor(cls, language: str) -> Optional[LanguageProcessor]:
        """
        获取语言处理器
        
        Args:
            language: 语言名称
            
        Returns:
            语言处理器实例，如果未找到则返回 None
        """
        return cls._processors.get(language)
    
    @classmethod
    def get_processor_by_file(cls, file_path: str) -> Optional[LanguageProcessor]:
        """
        根据文件路径获取语言处理器
        
        Args:
            file_path: 文件路径
            
        Returns:
            语言处理器实例，如果未找到则返回 None
        """
        ext = pathlib.Path(file_path).suffix.lower()
        lang = cls._extension_map.get(ext)
        if lang:
            return cls._processors.get(lang)
        return None
    
    @classmethod
    def get_processor_by_extension(cls, extension: str) -> Optional[LanguageProcessor]:
        """
        根据扩展名获取语言处理器
        
        Args:
            extension: 文件扩展名（如 '.java'）
            
        Returns:
            语言处理器实例
        """
        lang = cls._extension_map.get(extension.lower())
        if lang:
            return cls._processors.get(lang)
        return None
    
    @classmethod
    def get_supported_languages(cls) -> List[str]:
        """获取所有已注册的支持语言列表"""
        return list(cls._processors.keys())
    
    @classmethod
    def is_language_supported(cls, language: str) -> bool:
        """检查语言是否已注册"""
        return language in cls._processors
    
    @classmethod
    def get_language_by_extension(cls, extension: str) -> Optional[str]:
        """
        根据扩展名获取语言名称
        
        Args:
            extension: 文件扩展名
            
        Returns:
            语言名称，如果未找到则返回 None
        """
        return cls._extension_map.get(extension.lower())
    
    @classmethod
    def clear(cls):
        """清空所有注册（仅用于测试）"""
        cls._processors.clear()
        cls._extension_map.clear()
        logger.info("Language registry cleared")
