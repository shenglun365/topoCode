# parsers/languages/typescript/processor.py
"""
TypeScript 语言处理器

组合 TypeScript AST 解析、符号提取、调用图提取、依赖图提取功能。

注意：各方法只处理 TypeScript/JavaScript 语言的文件，不影响其他语言。
"""
from typing import List, Dict, Any
from ..base import (
    LanguageProcessor,
    ASTParser,
    SymbolExtractor,
    CallGraphExtractor,
    DependencyExtractor
)


class TypeScriptASTParser(ASTParser):
    """TypeScript AST 解析器"""

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
            raise Exception(f"Failed to parse TypeScript file {source_file_path}: {e}")


class TypeScriptSymbolExtractor(SymbolExtractor):
    """TypeScript/JavaScript 符号提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 TypeScript/JavaScript 符号

        注意：只处理 .ts/.tsx/.js/.jsx 文件，使用 file_lang 字段过滤
        """
        from databases.db_pools import get_mongo_client
        from parsers.extract_call_graph import _save_symbols
        from parsers.extract_global_symbols import extract_typescript_symbols

        mongo_client = get_mongo_client()
        db = mongo_client.topocode

        # 只获取 TypeScript/JavaScript 文件（使用 file_lang 字段过滤）
        file_records = list(db.proj_info.find({
            "proj_id": proj_id,
            "file_id": {"$lt": 1000000},
            "file_lang": {"$in": ["typescript", "javascript"]}  # 过滤 TS/JS 文件
        }, {"file_id": 1, "file_name": 1, "_id": 0}))

        global_defs = []
        class_defs = []

        for rec in file_records:
            file_id = rec["file_id"]
            file_lang = rec.get("file_lang", "typescript")  # 获取文件实际语言

            # 获取该文件的 AST 节点
            nodes_cursor = db.base_node.find({
                "proj_id": proj_id,
                "file_id": file_id
            })
            nodes = {node["node_id"]: node for node in nodes_cursor}

            if nodes:
                extract_typescript_symbols(proj_id, file_id, nodes, global_defs, class_defs, file_lang)

        # 写入数据库
        all_records = global_defs + class_defs
        if all_records:
            # 按语言分组保存
            ts_records = [r for r in all_records if r.get("language") == "typescript"]
            js_records = [r for r in all_records if r.get("language") == "javascript"]
            
            if ts_records:
                _save_symbols(db.graph_node, proj_id, ts_records, "typescript")
            if js_records:
                _save_symbols(db.graph_node, proj_id, js_records, "javascript")

        return all_records


class TypeScriptCallGraphExtractor(CallGraphExtractor):
    """TypeScript 调用图提取器"""

    def extract(self, proj_id: int, nodes_by_file: Dict[int, Dict[int, Dict]] = None) -> List[Dict[str, Any]]:
        """
        提取 TypeScript/JavaScript 调用图

        使用 JavaScriptCallExtractor 的专门逻辑，只处理 TS/JS 文件
        
        Args:
            proj_id: 项目 ID
            nodes_by_file: AST 节点字典（可选，如果提供则直接使用，否则从数据库加载）
        """
        from databases.db_pools import get_mongo_client
        from parsers.languages.call_parser.javascript_call_parser import JavaScriptCallExtractor

        mongo_client = get_mongo_client()
        db = mongo_client.topocode

        # 如果提供了 nodes_by_file，直接使用
        if nodes_by_file is not None:
            # 过滤出 TypeScript/JavaScript 文件
            ts_js_file_ids = set()
            for file_id in nodes_by_file.keys():
                file_rec = db.proj_info.find_one(
                    {"proj_id": proj_id, "file_id": file_id},
                    {"file_lang": 1, "_id": 0}
                )
                if file_rec and file_rec.get("file_lang") in ["typescript", "javascript"]:
                    ts_js_file_ids.add(file_id)
            
            nodes_by_file = {
                fid: nodes for fid, nodes in nodes_by_file.items() 
                if fid in ts_js_file_ids
            }
        else:
            # 从数据库加载（旧逻辑）
            # 只获取 TypeScript/JavaScript 文件（使用 file_lang 字段过滤）
            file_records = list(db.proj_info.find({
                "proj_id": proj_id,
                "file_id": {"$lt": 1000000},
                "file_lang": {"$in": ["typescript", "javascript"]}
            }, {"file_id": 1, "_id": 0}))

            file_ids = {rec["file_id"] for rec in file_records}

            # 按 file_id 加载 AST 节点
            nodes_by_file = {}
            nodes_cursor = db.base_node.find({
                "proj_id": proj_id,
                "file_id": {"$in": list(file_ids)}
            })

            for node in nodes_cursor:
                file_id = node["file_id"]
                if file_id not in nodes_by_file:
                    nodes_by_file[file_id] = {}
                nodes_by_file[file_id][node["node_id"]] = node

        # 使用 JavaScript 调用图提取器
        extractor = JavaScriptCallExtractor()
        return extractor.extract(proj_id, nodes_by_file)


class TypeScriptDependencyExtractor(DependencyExtractor):
    """TypeScript 依赖图提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 TypeScript 依赖图（import/require）
        
        使用 extract_dependency_graph 的通用逻辑，但只处理 TS/JS 文件
        """
        from parsers.extract_dependency_graph import extract_dependency_graph
        return extract_dependency_graph(proj_id, language='typescript')


class TypeScriptLanguageProcessor(LanguageProcessor):
    """TypeScript 语言处理器"""

    def __init__(self):
        self._ast_parser = TypeScriptASTParser()
        self._symbol_extractor = TypeScriptSymbolExtractor()
        self._call_graph_extractor = TypeScriptCallGraphExtractor()
        self._dependency_extractor = TypeScriptDependencyExtractor()

    @property
    def language_name(self) -> str:
        return 'typescript'

    @property
    def file_extensions(self) -> List[str]:
        return ['.ts', '.tsx', '.mts']

    @property
    def priority(self) -> int:
        return 1  # TypeScript 优先级高于 JavaScript

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
LanguageRegistry.register(TypeScriptLanguageProcessor())
