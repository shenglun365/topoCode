# parsers/languages/c/processor.py
"""
C 语言处理器

组合 C 语言 AST 解析、符号提取、调用图提取、依赖图提取功能。

注意：各方法只处理 C 语言的文件（.c, .h），不影响其他语言。
"""
from typing import List, Dict, Any
from ..base import (
    LanguageProcessor,
    ASTParser,
    SymbolExtractor,
    CallGraphExtractor,
    DependencyExtractor
)


class CASTParser(ASTParser):
    """C 语言 AST 解析器"""
    
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
            raise Exception(f"Failed to parse C file {source_file_path}: {e}")


class CSymbolExtractor(SymbolExtractor):
    """C 语言符号提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 C 语言符号（函数、宏等）

        注意：只处理 .c/.h 文件，使用 file_lang 字段过滤
        """
        from databases.db_pools import get_mongo_client
        from parsers.extract_call_graph import _save_symbols

        mongo_client = get_mongo_client()
        db = mongo_client.topocode

        # 只获取 C 语言文件（使用 file_lang 字段过滤）
        file_records = list(db.proj_info.find({
            "proj_id": proj_id,
            "file_id": {"$lt": 1000000},
            "file_lang": "c"  # 直接过滤 C 语言文件
        }, {"file_id": 1, "file_name": 1, "_id": 0}))

        global_defs = []
        macro_records = []

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

                    # 提取宏定义
                    if node_type == 'preproc_def':
                        macro_name = node.get("refs", [None])[0] if node.get("refs") else None
                        if macro_name:
                            macro_records.append({
                                "proj_id": proj_id,
                                "file_id": file_id,
                                "symbol_node_type": "macro_name",
                                "macro_name": macro_name,
                                "language": "c",  # ← 新增
                                "def_file_id": file_id,
                                "def_node_id": node["node_id"],
                                "start_line": node["start"],
                                "end_line": node["end"],
                            })

                    # 提取函数定义
                    elif node_type == 'function_definition':
                        func_name = node.get("refs", [None])[0] if node.get("refs") else None
                        if func_name:
                            global_defs.append({
                                "proj_id": proj_id,
                                "file_id": file_id,
                                "symbol_node_type": "func_name",
                                "func_name": func_name,
                                "language": "c",  # ← 新增
                                "def_file_id": file_id,
                                "def_node_id": node["node_id"],
                                "start_line": node["start"],
                                "end_line": node["end"]
                            })

        # 写入数据库
        all_records = macro_records + global_defs
        if all_records:
            _save_symbols(db.graph_node, proj_id, all_records, "c")

        return all_records


class CCallGraphExtractor(CallGraphExtractor):
    """C 语言调用图提取器"""
    
    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 C 语言调用图
        
        使用 extract_call_graph 的通用逻辑，但只处理 C 语言文件
        """
        from parsers.extract_call_graph import extract_call_graph
        return extract_call_graph(proj_id, language='c')


class CDependencyExtractor(DependencyExtractor):
    """C 语言依赖图提取器"""
    
    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 C 语言依赖图（#include）
        
        使用 extract_dependency_graph 的通用逻辑，但只处理 C 语言文件
        """
        from parsers.extract_dependency_graph import extract_dependency_graph
        return extract_dependency_graph(proj_id, language='c')


class CLanguageProcessor(LanguageProcessor):
    """C 语言处理器"""
    
    def __init__(self):
        self._ast_parser = CASTParser()
        self._symbol_extractor = CSymbolExtractor()
        self._call_graph_extractor = CCallGraphExtractor()
        self._dependency_extractor = CDependencyExtractor()
    
    @property
    def language_name(self) -> str:
        return 'c'
    
    @property
    def file_extensions(self) -> List[str]:
        return ['.c', '.h']
    
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
LanguageRegistry.register(CLanguageProcessor())
