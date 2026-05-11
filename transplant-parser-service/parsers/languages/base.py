# parsers/languages/base.py
"""
多语言处理器抽象基类

定义语言处理器的标准接口，所有语言处理器必须实现这些接口。

架构:
- ASTParser: AST 解析器接口
- SymbolExtractor: 符号提取器接口
- CallGraphExtractor: 调用图提取器接口
- DependencyExtractor: 依赖图提取器接口
- LanguageProcessor: 语言处理器（组合所有功能模块）
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional, Set
import pathlib


class ASTParser(ABC):
    """AST 解析器接口"""
    
    @abstractmethod
    def parse_file(self, source_file_path: str, proj_id: int, proj_path: str) -> int:
        """
        解析单个文件的 AST 并写入 MongoDB
        
        Args:
            source_file_path: 源文件路径
            proj_id: 项目 ID
            proj_path: 项目根路径
            
        Returns:
            解析的节点数量
            
        Raises:
            Exception: 解析失败时抛出异常，停止处理
        """
        pass


class SymbolExtractor(ABC):
    """符号提取器接口"""
    
    @abstractmethod
    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取符号定义（函数、类、宏等）
        
        Args:
            proj_id: 项目 ID
            
        Returns:
            符号列表
            
        Raises:
            Exception: 提取失败时抛出异常
        """
        pass


class CallGraphExtractor(ABC):
    """调用图提取器接口"""
    
    @abstractmethod
    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取调用图
        
        Args:
            proj_id: 项目 ID
            
        Returns:
            调用边列表
            
        Raises:
            Exception: 提取失败时抛出异常
        """
        pass


class DependencyExtractor(ABC):
    """依赖图提取器接口"""
    
    @abstractmethod
    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取依赖图
        
        Args:
            proj_id: 项目 ID
            
        Returns:
            依赖边列表
            
        Raises:
            Exception: 提取失败时抛出异常
        """
        pass


class LanguageProcessor(ABC):
    """
    语言处理器 - 组合所有功能模块
    
    每个语言实现一个 LanguageProcessor 子类，组合 AST 解析、符号提取、
    调用图提取、依赖图提取功能。
    """
    
    @property
    @abstractmethod
    def language_name(self) -> str:
        """返回语言名称，如 'java', 'python'"""
        pass
    
    @property
    @abstractmethod
    def file_extensions(self) -> List[str]:
        """返回该语言支持的文件扩展名，如 ['.java', '.kt']"""
        pass
    
    @property
    def priority(self) -> int:
        """
        处理器优先级（用于解决扩展名冲突）
        数字越大优先级越高，默认 0
        """
        return 0
    
    @abstractmethod
    def get_ast_parser(self) -> ASTParser:
        """获取 AST 解析器"""
        pass
    
    @abstractmethod
    def get_symbol_extractor(self) -> SymbolExtractor:
        """获取符号提取器"""
        pass
    
    @abstractmethod
    def get_call_graph_extractor(self) -> CallGraphExtractor:
        """获取调用图提取器"""
        pass
    
    @abstractmethod
    def get_dependency_extractor(self) -> DependencyExtractor:
        """获取依赖图提取器"""
        pass
    
    # === 便捷方法（默认实现，子类可重写）===
    
    def parse_ast(self, source_file_path: str, proj_id: int, proj_path: str) -> int:
        """便捷方法：调用 AST 解析器"""
        return self.get_ast_parser().parse_file(source_file_path, proj_id, proj_path)
    
    def extract_symbols(self, proj_id: int) -> List[Dict[str, Any]]:
        """便捷方法：调用符号提取器"""
        return self.get_symbol_extractor().extract(proj_id)
    
    def extract_call_graph(self, proj_id: int) -> List[Dict[str, Any]]:
        """便捷方法：调用调用图提取器"""
        return self.get_call_graph_extractor().extract(proj_id)
    
    def extract_dependency_graph(self, proj_id: int) -> List[Dict[str, Any]]:
        """便捷方法：调用依赖图提取器"""
        return self.get_dependency_extractor().extract(proj_id)
