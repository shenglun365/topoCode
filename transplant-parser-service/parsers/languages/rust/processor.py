# parsers/languages/rust/processor.py
"""
Rust 语言处理器

组合 Rust AST 解析、符号提取、调用图提取、依赖图提取功能。

注意：各方法只处理 Rust 语言的文件（.rs），不影响其他语言。
"""
from typing import List, Dict, Any
from ..base import (
    LanguageProcessor,
    ASTParser,
    SymbolExtractor,
    CallGraphExtractor,
    DependencyExtractor
)


class RustASTParser(ASTParser):
    """Rust AST 解析器"""

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
            raise Exception(f"Failed to parse Rust file {source_file_path}: {e}")


class RustSymbolExtractor(SymbolExtractor):
    """Rust 符号提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 Rust 符号（函数、结构体等）

        注意：只处理 .rs 文件，使用 file_lang 字段过滤
        """
        from databases.db_pools import get_mongo_client
        from parsers.extract_call_graph import _save_symbols

        mongo_client = get_mongo_client()
        db = mongo_client.topocode

        # 只获取 Rust 文件（使用 file_lang 字段过滤）
        file_records = list(db.proj_info.find({
            "proj_id": proj_id,
            "file_id": {"$lt": 1000000},
            "file_lang": "rust"  # 直接过滤 Rust 文件
        }, {"file_id": 1, "file_name": 1, "_id": 0}))

        global_defs = []

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
                                "language": "rust",  # ← 新增
                                "def_file_id": file_id,
                                "def_node_id": node["node_id"],
                                "start_line": node["start"],
                                "end_line": node["end"]
                            })

        # 写入数据库
        if global_defs:
            _save_symbols(db.graph_node, proj_id, global_defs, "rust")

        return global_defs


class RustCallGraphExtractor(CallGraphExtractor):
    """Rust 调用图提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 Rust 调用图
        
        使用 extract_call_graph 的通用逻辑，但只处理 Rust 文件
        """
        from parsers.extract_call_graph import extract_call_graph
        return extract_call_graph(proj_id, language='rust')


class RustDependencyExtractor(DependencyExtractor):
    """Rust 依赖图提取器"""

    def extract(self, proj_id: int) -> List[Dict[str, Any]]:
        """
        提取 Rust 依赖图（use）
        
        使用 extract_dependency_graph 的通用逻辑，但只处理 Rust 文件
        """
        from parsers.extract_dependency_graph import extract_dependency_graph
        return extract_dependency_graph(proj_id, language='rust')


class RustLanguageProcessor(LanguageProcessor):
    """Rust 语言处理器"""

    def __init__(self):
        self._ast_parser = RustASTParser()
        self._symbol_extractor = RustSymbolExtractor()
        self._call_graph_extractor = RustCallGraphExtractor()
        self._dependency_extractor = RustDependencyExtractor()

    @property
    def language_name(self) -> str:
        return 'rust'

    @property
    def file_extensions(self) -> List[str]:
        return ['.rs']

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


# 自动注册到 LanguageRegistry（延迟注册，检查版本兼容性）
from ..language_registry import LanguageRegistry

def register_rust_processor():
    """延迟注册 Rust 处理器（仅在 tree-sitter-rust 兼容时）"""
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        import tree_sitter_rust
        import tree_sitter
        
        # 新版本 tree-sitter (>= 0.25.0) 使用 language() 函数返回 Language
        if hasattr(tree_sitter_rust, 'language'):
            lang = tree_sitter_rust.language()
            lang_obj = tree_sitter.Language(lang)
            
            version = getattr(lang_obj, 'version', 0)
            min_ver = tree_sitter.MIN_COMPATIBLE_LANGUAGE_VERSION
            max_ver = tree_sitter.LANGUAGE_VERSION
            
            if min_ver <= version <= max_ver:
                LanguageRegistry.register(RustLanguageProcessor())
                logger.info(f"Rust 处理器已注册 (language version={version})")
            else:
                logger.warning(f"Rust 处理器未注册：language version {version} 不在兼容范围 {min_ver}-{max_ver} 内")
        elif hasattr(tree_sitter_rust, 'Parser'):
            # 旧版本 API
            test_parser = tree_sitter_rust.Parser()
            LanguageRegistry.register(RustLanguageProcessor())
            logger.info("Rust 处理器已注册 (旧版本 API)")
        else:
            raise AttributeError("tree_sitter_rust 没有 language 或 Parser 属性")
            
    except (ImportError, AttributeError, ValueError) as e:
        logger.warning(f"Rust 处理器未注册：tree-sitter-rust 版本不兼容 - {e}")
