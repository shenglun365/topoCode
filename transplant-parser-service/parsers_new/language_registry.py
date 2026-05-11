"""
LanguageRegistry — 语言处理器注册表（单例）

管理语言处理器的注册和路由，支持按文件名/扩展名查找处理器。
"""
from typing import Dict, List, Optional

from .base import LanguageProcessor


class LanguageRegistry:
    """语言处理器注册表（单例）"""

    _instance: Optional["LanguageRegistry"] = None
    _processors: Dict[str, LanguageProcessor]
    _extension_map: Dict[str, str]

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._processors = {}
            cls._instance._extension_map = {}
        return cls._instance

    @classmethod
    def register(cls, processor: LanguageProcessor):
        """注册语言处理器"""
        instance = cls()
        instance._processors[processor.language_name] = processor
        for ext in processor.file_extensions:
            ext_key = ext if ext.startswith(".") else f".{ext}"
            # 优先级高的覆盖低的
            if ext_key in instance._extension_map:
                existing = instance._processors.get(instance._extension_map[ext_key])
                if existing and processor.priority > existing.priority:
                    instance._extension_map[ext_key] = processor.language_name
            else:
                instance._extension_map[ext_key] = processor.language_name

    @classmethod
    def get_processor(cls, language: str) -> Optional[LanguageProcessor]:
        """按语言名获取处理器"""
        return cls()._processors.get(language)

    @classmethod
    def get_processor_by_file(cls, file_path: str) -> Optional[LanguageProcessor]:
        """按文件路径获取处理器"""
        import os
        ext = os.path.splitext(file_path)[1].lower()
        lang = cls()._extension_map.get(ext)
        if lang:
            return cls()._processors.get(lang)
        return None

    @classmethod
    def get_supported_languages(cls) -> List[str]:
        return list(cls()._processors.keys())

    @classmethod
    def is_language_supported(cls, language: str) -> bool:
        return language in cls()._processors

    @classmethod
    def clear(cls):
        """重置所有状态（测试用）"""
        instance = cls.__new__(cls)
        instance._processors = {}
        instance._extension_map = {}
        cls._instance = instance
