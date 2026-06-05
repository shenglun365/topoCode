# parsers/languages/code_parser/parser_factory.py
"""
语言解析器工厂模块

提供统一的解析器创建接口，支持多语言 AST 解析。
使用工厂模式，根据语言名称返回对应的解析器实例。
"""
import logging
from typing import Optional, Dict, Type
from tree_sitter import Parser
from .lang_parser_conf import LANGUAGES

logger = logging.getLogger(__name__)


# 解析器缓存（每进程单例）
_parser_cache: Dict[str, Parser] = {}


class UnsupportedLanguageError(Exception):
    """不支持的语言异常"""
    pass


class LanguageParserFactory:
    """
    语言解析器工厂类
    
    负责根据语言名称创建和缓存 tree-sitter 解析器实例。
    支持的语言取决于已安装的 tree-sitter 语言包。
    
    使用示例:
        parser = LanguageParserFactory.get_parser("python")
        tree = parser.parse(source_code_bytes)
    """
    
    # 语言名称映射（标准化）
    LANGUAGE_ALIASES = {
        # C 系列
        'c': 'c',
        'c++': 'cpp',
        'cpp': 'cpp',
        'objective-c': 'objective-c',
        'objc': 'objective-c',
        'objective-c++': 'objective-c++',
        'objc++': 'objective-c++',
        
        # Java 系列
        'java': 'java',
        
        # Python
        'python': 'python',
        'py': 'python',
        
        # JavaScript 系列
        'javascript': 'javascript',
        'js': 'javascript',
        'mjs': 'javascript',
        'typescript': 'typescript',
        'ts': 'typescript',
        'tsx': 'tsx',
        
        # Go
        'go': 'go',
        'golang': 'go',
        
        # Rust
        'rust': 'rust',
        'rs': 'rust',
        
        # PHP
        'php': 'php',
        
        # Ruby
        'ruby': 'ruby',
        'rb': 'ruby',
        
        # C#
        'c#': 'csharp',
        'csharp': 'csharp',
        
        # Swift
        'swift': 'swift',
        
        # Kotlin
        'kotlin': 'kotlin',
        'kt': 'kotlin',
        
        # Scala
        'scala': 'scala',
        
        # Bash/Shell
        'bash': 'bash',
        'sh': 'bash',
        'shell': 'bash',
        'zsh': 'bash',
    }
    
    @classmethod
    def get_parser(cls, lang: str) -> Optional[Parser]:
        """
        获取指定语言的解析器
        
        Args:
            lang: 语言名称（支持别名）
            
        Returns:
            tree_sitter.Parser 实例，如果语言不支持则返回 None
            
        Raises:
            UnsupportedLanguageError: 当语言未安装对应的 tree-sitter 包时
        """
        # 标准化语言名称
        normalized_lang = cls._normalize_language(lang)
        
        if not normalized_lang:
            raise UnsupportedLanguageError(f"Unknown language alias: {lang}")
        
        # 检查缓存
        if normalized_lang in _parser_cache:
            logger.debug(f"Using cached parser for language: {normalized_lang}")
            return _parser_cache[normalized_lang]
        
        # 检查语言是否可用
        if normalized_lang not in LANGUAGES:
            available_languages = list(LANGUAGES.keys())
            raise UnsupportedLanguageError(
                f"Language '{normalized_lang}' is not supported. "
                f"Available languages: {available_languages}. "
                f"Please install the corresponding tree-sitter package (e.g., pip install tree-sitter-{normalized_lang})"
            )
        
        # 创建解析器
        logger.info(f"Creating new parser for language: {normalized_lang}")
        language = LANGUAGES[normalized_lang]
        parser = Parser(language)
        
        # 缓存解析器
        _parser_cache[normalized_lang] = parser
        logger.info(f"Parser for '{normalized_lang}' created and cached")
        
        return parser
    
    @classmethod
    def _normalize_language(cls, lang: str) -> Optional[str]:
        """
        标准化语言名称
        
        Args:
            lang: 原始语言名称
            
        Returns:
            标准化后的语言名称，如果无法识别则返回 None
        """
        if not lang:
            return None
        
        lang_lower = lang.lower().strip()
        
        # 直接匹配
        if lang_lower in cls.LANGUAGE_ALIASES:
            return cls.LANGUAGE_ALIASES[lang_lower]
        
        # 尝试去掉版本号（如 python3 -> python）
        import re
        base_lang = re.sub(r'\d+$', '', lang_lower)
        if base_lang in cls.LANGUAGE_ALIASES:
            return cls.LANGUAGE_ALIASES[base_lang]
        
        return None
    
    @classmethod
    def get_supported_languages(cls) -> list:
        """
        获取所有支持的语言列表
        
        Returns:
            支持的语言名称列表
        """
        return list(LANGUAGES.keys())
    
    @classmethod
    def is_language_supported(cls, lang: str) -> bool:
        """
        检查语言是否支持
        
        Args:
            lang: 语言名称
            
        Returns:
            True 如果语言支持，否则 False
        """
        normalized = cls._normalize_language(lang)
        return normalized is not None and normalized in LANGUAGES
    
    @classmethod
    def clear_cache(cls):
        """
        清除解析器缓存
        
        主要用于测试或内存管理场景
        """
        global _parser_cache
        _parser_cache.clear()
        logger.info("Parser cache cleared")


# 便捷函数
def get_parser(lang: str) -> Optional[Parser]:
    """
    便捷函数：获取语言解析器
    
    Args:
        lang: 语言名称
        
    Returns:
        tree_sitter.Parser 实例
    """
    return LanguageParserFactory.get_parser(lang)


def get_supported_languages() -> list:
    """
    便捷函数：获取支持的语言列表
    
    Returns:
        支持的语言列表
    """
    return LanguageParserFactory.get_supported_languages()
