# parsers/languages/python/processor.py
"""
Python 语言处理器

组合 Python AST 解析、符号提取、调用图提取、依赖图提取功能。

注意：各方法只处理 Python 语言的文件（.py），不影响其他语言。
"""
from typing import List, Dict, Any
from ..base import (
    LanguageProcessor,
    ASTParser,
    SymbolExtractor,
    CallGraphExtractor,
    DependencyExtractor
)


class PythonASTParser(ASTParser):
    """Python AST 解析器"""

    def parse_file(self, source_file_path: str, proj_id: int, proj_path: str) -> int:
        from parsers.parser import source_code_to_ast
        try:
            node_count = source_code_to_ast(
                source_file_path=source_file_path,
                proj_id=proj_id,
                proj_path=proj_path
            )
            return node_count
        except Exception as e:
            raise Exception(f"Failed to parse Python file {source_file_path}: {e}")


class PythonSymbolExtractor(SymbolExtractor):
    """Python 符号提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 Python 符号（函数、类等）

        注意：只处理 .py 文件，使用 file_lang 字段过滤
        """
        from databases.db_pools import get_mongo_client
        from parsers.extract_call_graph import _save_symbols

        mongo_client = get_mongo_client()
        db = mongo_client.topocode

        # 只获取 Python 文件（使用 file_lang 字段过滤）
        file_records = list(db.proj_info.find({
            "proj_id": proj_id,
            "file_id": {"$lt": 1000000},
            "file_lang": "python"  # 直接过滤 Python 文件
        }, {"file_id": 1, "file_name": 1, "_id": 0}))

        global_defs = []
        class_defs = []

        for rec in file_records:
            file_id = rec["file_id"]

            # 获取该文件的 AST 节点
            nodes_cursor = db.base_node.find({
                "proj_id": proj_id,
                "file_id": file_id
            })
            nodes = {node["node_id"]: node for node in nodes_cursor}

            if nodes:
                for node in nodes.values():
                    node_type = node.get("type")

                    # 提取函数定义
                    if node_type == 'function_definition':
                        func_name = node.get("refs", [None])[0] if node.get("refs") else None
                        if func_name:
                            global_defs.append({
                                "proj_id": proj_id,
                                "file_id": file_id,
                                "symbol_node_type": "func_name",
                                "func_name": func_name,
                                "language": "python",  # ← 新增
                                "def_file_id": file_id,
                                "def_node_id": node["node_id"],
                                "start_line": node["start"],
                                "end_line": node["end"]
                            })

                    # 提取类定义
                    elif node_type == 'class_definition':
                        class_name = node.get("refs", [None])[0] if node.get("refs") else None
                        if class_name:
                            class_defs.append({
                                "proj_id": proj_id,
                                "file_id": file_id,
                                "symbol_node_type": "class_name",
                                "class_name": class_name,
                                "language": "python",  # ← 新增
                                "def_file_id": file_id,
                                "def_node_id": node["node_id"],
                                "start_line": node["start"],
                                "end_line": node["end"]
                            })

        # 写入数据库
        all_records = global_defs + class_defs
        if all_records:
            _save_symbols(db.graph_node, proj_id, all_records, "python")

        return all_records


class PythonCallGraphExtractor(CallGraphExtractor):
    """Python 调用图提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 Python 调用图
        
        使用 extract_call_graph 的通用逻辑，但只处理 Python 文件
        """
        from parsers.extract_call_graph import extract_call_graph
        return extract_call_graph(proj_id, language='python')


class PythonDependencyExtractor(DependencyExtractor):
    """Python 依赖图提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 Python 依赖图（import）
        
        使用 extract_dependency_graph 的通用逻辑，但只处理 Python 文件
        """
        from parsers.extract_dependency_graph import extract_dependency_graph
        return extract_dependency_graph(proj_id, language='python')


class PythonLanguageProcessor(LanguageProcessor):
    """Python 语言处理器"""

    def __init__(self):
        self._ast_parser = PythonASTParser()
        self._symbol_extractor = PythonSymbolExtractor()
        self._call_graph_extractor = PythonCallGraphExtractor()
        self._dependency_extractor = PythonDependencyExtractor()

    @property
    def language_name(self) -> str:
        return 'python'

    @property
    def file_extensions(self) -> List[str]:
        return ['.py']

    @property
    def priority(self) -> int:
        return 0

    def get_ast_parser(self) -> ASTParser:
        return self._ast_parser

    def get_symbol_extractor(self) -> SymbolExtractor:
        return self._symbol_extractor

    def get_call_graph_extractor(self) -> CallGraphExtractor:
        return self._call_graph_extractor

    def get_dependency_extractor(self) -> DependencyExtractor:
        return self._dependency_extractor


# 自动注册到 LanguageRegistry
from ..language_registry import LanguageRegistry
LanguageRegistry.register(PythonLanguageProcessor())
