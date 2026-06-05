# parsers/languages/c_family/ast_parser.py
"""
C/C++ 共享 AST 解析器

使用 tree-sitter 解析 C/C++ 源代码，生成 AST 节点并写入 MongoDB。

架构:
- 使用共享的 tree-sitter 语言配置
- 支持 C (.c, .h) 和 C++ (.cpp, .cc, .hpp, .cxx) 文件
- 与 parsers/parser.py 中的 source_code_to_ast 兼容
"""
import logging
from typing import Optional, Any
from pathlib import Path

from ..base import ASTParser
from .utils import get_tree_sitter_language

logger = logging.getLogger(__name__)


class CFamilyASTParser(ASTParser):
    """C/C++ 共享 AST 解析器"""
    
    def __init__(self):
        self._parser_cache = {}  # 缓存 parser 实例
    
    def _get_parser(self, language: str):
        """获取或创建 tree-sitter 解析器实例"""
        if language not in self._parser_cache:
            lang_module = get_tree_sitter_language(language)
            if lang_module:
                self._parser_cache[language] = lang_module.Parser()
        return self._parser_cache.get(language)
    
    def parse_file(self, source_file_path: str, proj_id: int, proj_path: str) -> int:
        """
        解析 C/C++ 文件的 AST 并写入 MongoDB
        
        Args:
            source_file_path: 源文件路径
            proj_id: 项目 ID
            proj_path: 项目根路径
            
        Returns:
            解析的节点数量
            
        Raises:
            Exception: 解析失败时抛出异常
        """
        # 延迟导入，避免循环依赖
        from parsers.parser import source_code_to_ast
        
        try:
            # 使用现有的 source_code_to_ast 函数
            # 该函数已经处理了 tree-sitter 解析和 MongoDB 写入
            node_count = source_code_to_ast(
                source_file_path=source_file_path,
                proj_id=proj_id,
                proj_path=proj_path
            )
            return node_count
            
        except Exception as e:
            logger.error(f"Failed to parse {source_file_path}: {e}", exc_info=True)
            raise
