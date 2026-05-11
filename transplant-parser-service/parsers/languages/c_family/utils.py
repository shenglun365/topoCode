# parsers/languages/c_family/utils.py
"""
C/C++ 共享工具函数

提供 C/C++ 语言处理的共享工具函数。
"""
import logging
from typing import Optional, Any

logger = logging.getLogger(__name__)


def get_tree_sitter_language(language: str) -> Optional[Any]:
    """
    获取 tree-sitter 语言模块
    
    Args:
        language: 语言名称 ('c' 或 'cpp')
        
    Returns:
        tree-sitter 语言模块，如果不可用则返回 None
    """
    try:
        if language == 'c':
            import tree_sitter_c
            return tree_sitter_c
        elif language == 'cpp':
            import tree_sitter_cpp
            return tree_sitter_cpp
        else:
            logger.warning(f"Unsupported C family language: {language}")
            return None
    except ImportError as e:
        logger.warning(f"tree-sitter-{language} not installed: {e}")
        return None
    except AttributeError as e:
        logger.warning(f"tree-sitter-{language} has no 'language' attribute: {e}")
        return None


def is_header_file(file_path: str) -> bool:
    """
    检查是否为头文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        True 如果是头文件
    """
    from pathlib import Path
    ext = Path(file_path).suffix.lower()
    return ext in ['.h', '.hpp', '.hxx', '.hh']


def is_source_file(file_path: str) -> bool:
    """
    检查是否为源文件
    
    Args:
        file_path: 文件路径
        
    Returns:
        True 如果是源文件
    """
    from pathlib import Path
    ext = Path(file_path).suffix.lower()
    return ext in ['.c', '.cpp', '.cc', '.cxx', '.mm']
