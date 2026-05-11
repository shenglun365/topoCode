# parsers/languages/javascript/processor.py
"""
JavaScript 语言处理器

组合 JavaScript AST 解析、符号提取、调用图提取、依赖图提取功能。

注意：各方法只处理 JavaScript 语言的文件（.js, .jsx, .mjs），不影响其他语言。
"""
from typing import List, Dict, Any
from ..base import (
    LanguageProcessor,
    ASTParser,
    SymbolExtractor,
    CallGraphExtractor,
    DependencyExtractor
)


class JavaScriptASTParser(ASTParser):
    """JavaScript AST 解析器"""

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
            raise Exception(f"Failed to parse JavaScript file {source_file_path}: {e}")


class JavaScriptSymbolExtractor(SymbolExtractor):
    """JavaScript 符号提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 JavaScript 符号（函数、类等）

        注意：只处理 .js/.jsx/.mjs 文件，使用 file_lang 字段过滤
        """
        from parsers.extract_call_graph import _save_symbols


        # 只获取 JavaScript 文件（使用 file_lang 字段过滤）
        file_records = list(db.proj_info.find({
            "proj_id": proj_id,
            "file_id": {"$lt": 1000000},
            "file_lang": "javascript"  # 直接过滤 JavaScript 文件
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
                    if node_type == 'function_declaration':
                        func_name = node.get("refs", [None])[0] if node.get("refs") else None
                        if func_name:
                            global_defs.append({
                                "proj_id": proj_id,
                                "file_id": file_id,
                                "symbol_node_type": "func_name",
                                "func_name": func_name,
                                "language": "javascript",  # ← 新增
                                "def_file_id": file_id,
                                "def_node_id": node["node_id"],
                                "start_line": node["start"],
                                "end_line": node["end"]
                            })

                    # 提取类定义
                    elif node_type == 'class_declaration':
                        class_name = node.get("refs", [None])[0] if node.get("refs") else None
                        if class_name:
                            class_defs.append({
                                "proj_id": proj_id,
                                "file_id": file_id,
                                "symbol_node_type": "class_name",
                                "class_name": class_name,
                                "language": "javascript",  # ← 新增
                                "def_file_id": file_id,
                                "def_node_id": node["node_id"],
                                "start_line": node["start"],
                                "end_line": node["end"]
                            })

        # 写入数据库
        all_records = global_defs + class_defs
        if all_records:
            _save_symbols(db.graph_node, proj_id, all_records, "javascript")

        return all_records


class JavaScriptCallGraphExtractor(CallGraphExtractor):
    """JavaScript 调用图提取器"""

    def extract(self, proj_id: int, nodes_by_file: Dict[int, Dict[int, Dict]] = None) -> List[Dict[str, Any]]:
        """
        提取 JavaScript 调用图

        使用 JavaScriptCallExtractor 的专门逻辑，只处理 JS 文件
        
        Args:
            proj_id: 项目 ID
            nodes_by_file: AST 节点字典（可选，如果提供则直接使用，否则从数据库加载）
        """
        from parsers.languages.call_parser.javascript_call_parser import JavaScriptCallExtractor


        # 如果提供了 nodes_by_file，直接使用
        if nodes_by_file is not None:
            # 过滤出 JavaScript 文件
            js_file_ids = set()
            for file_id in nodes_by_file.keys():
                file_rec = db.proj_info.find_one(
                    {"proj_id": proj_id, "file_id": file_id},
                    {"file_lang": 1, "_id": 0}
                )
                if file_rec and file_rec.get("file_lang") == "javascript":
                    js_file_ids.add(file_id)
            
            nodes_by_file = {
                fid: nodes for fid, nodes in nodes_by_file.items() 
                if fid in js_file_ids
            }
        else:
            # 从数据库加载（旧逻辑）
            # 只获取 JavaScript 文件（使用 file_lang 字段过滤）
            file_records = list(db.proj_info.find({
                "proj_id": proj_id,
                "file_id": {"$lt": 1000000},
                "file_lang": "javascript"
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


class JavaScriptDependencyExtractor(DependencyExtractor):
    """JavaScript 依赖图提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 JavaScript 依赖图（import/require）
        
        使用 extract_dependency_graph 的通用逻辑，但只处理 JS 文件
        """
        from parsers.extract_dependency_graph import extract_dependency_graph
        return extract_dependency_graph(proj_id, language='javascript')


class JavaScriptLanguageProcessor(LanguageProcessor):
    """JavaScript 语言处理器"""

    def __init__(self):
        self._ast_parser = JavaScriptASTParser()
        self._symbol_extractor = JavaScriptSymbolExtractor()
        self._call_graph_extractor = JavaScriptCallGraphExtractor()
        self._dependency_extractor = JavaScriptDependencyExtractor()

    @property
    def language_name(self) -> str:
        return 'javascript'

    @property
    def file_extensions(self) -> List[str]:
        return ['.js', '.jsx', '.mjs']

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
LanguageRegistry.register(JavaScriptLanguageProcessor())
