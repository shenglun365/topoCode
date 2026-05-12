"""
LanguageProcessor — 语言处理器抽象基类

定义 AST 解析、符号提取、调用图提取、依赖图提取的接口。
"""
from abc import ABC, abstractmethod
from typing import List, Dict


class ASTParser(ABC):
    """AST 解析器接口"""

    @abstractmethod
    def parse_file(self, source_file_path: str, file_id: int,
                   analysis_store) -> int:
        """
        解析单个文件，将 AST 节点写入 SQLite

        Args:
            source_file_path: 源文件路径
            file_id: source_files 表中的文件 ID
            analysis_store: AnalysisStore 实例

        Returns:
            AST 节点数，-1 表示文件过大被跳过
        """


class SymbolExtractor(ABC):
    """符号提取器接口"""

    @abstractmethod
    def extract(self, task_id: str, analysis_store) -> List[Dict]:
        """
        提取符号（函数、类、宏、方法等）

        Args:
            task_id: 任务 ID
            analysis_store: AnalysisStore 实例

        Returns:
            符号列表
        """


class CallGraphExtractor(ABC):
    """调用图提取器接口"""

    @abstractmethod
    def extract(self, task_id: str, analysis_store) -> List[Dict]:
        """
        提取函数调用关系

        Args:
            task_id: 任务 ID
            analysis_store: AnalysisStore 实例

        Returns:
            调用边列表
        """


class DependencyExtractor(ABC):
    """依赖图提取器接口"""

    @abstractmethod
    def extract(self, task_id: str, analysis_store) -> List[Dict]:
        """
        提取文件级依赖关系（import/include）

        Args:
            task_id: 任务 ID
            analysis_store: AnalysisStore 实例

        Returns:
            依赖边列表
        """


class LanguageProcessor(ABC):
    """
    语言处理器 — 组合 AST 解析 + 符号提取 + 调用图 + 依赖图

    每个语言实现一个具体的 LanguageProcessor 子类。
    """

    @property
    @abstractmethod
    def language_name(self) -> str:
        """语言名称，如 'c', 'java', 'python'"""

    @property
    @abstractmethod
    def file_extensions(self) -> List[str]:
        """支持的文件扩展名，如 ['.c', '.h']"""

    @property
    def priority(self) -> int:
        """优先级（扩展名冲突时，高的胜出）"""
        return 0

    @abstractmethod
    def get_ast_parser(self) -> ASTParser:
        """获取 AST 解析器实例"""

    @abstractmethod
    def get_symbol_extractor(self) -> SymbolExtractor:
        """获取符号提取器实例"""

    @abstractmethod
    def get_call_graph_extractor(self) -> CallGraphExtractor:
        """获取调用图提取器实例"""

    @abstractmethod
    def get_dependency_extractor(self) -> DependencyExtractor:
        """获取依赖图提取器实例"""

    # ==================== 便捷方法 ====================

    def parse_ast(self, source_file_path: str, file_id: int,
                  analysis_store) -> int:
        """解析单个文件的 AST"""
        return self.get_ast_parser().parse_file(
            source_file_path, file_id, analysis_store
        )

    def extract_symbols(self, task_id: str, analysis_store) -> List[Dict]:
        """提取符号"""
        return self.get_symbol_extractor().extract(task_id, analysis_store)

    def extract_call_graph(self, task_id: str, analysis_store) -> List[Dict]:
        """提取调用图"""
        return self.get_call_graph_extractor().extract(task_id, analysis_store)

    def extract_dependency_graph(self, task_id: str, analysis_store) -> List[Dict]:
        """提取依赖图"""
        return self.get_dependency_extractor().extract(task_id, analysis_store)
