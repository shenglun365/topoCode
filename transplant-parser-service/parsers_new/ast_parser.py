"""
ASTParser — 基于 tree-sitter 的 AST 解析器

提供通用的 tree-sitter 解析逻辑，各语言子类只需指定语法包和节点映射。
"""
import os
import logging
from typing import Optional, List, Dict

from transplant.config import MAX_FILE_SIZE, MAX_AST_NODES, BATCH_INSERT_SIZE

from .base import ASTParser

logger = logging.getLogger(__name__)

try:
    import tree_sitter_languages
    HAS_TS = True
except ImportError:
    HAS_TS = False


class TreeSitterASTParser(ASTParser):
    """
    基于 tree-sitter 的通用 AST 解析器

    子类需要设置:
    - LANG_NAME: tree-sitter 语言包名称
    - NODE_TYPE_MAP: 可选，自定义节点类型映射
    """

    LANG_NAME: str = "c"  # 子类覆盖

    def __init__(self):
        if not HAS_TS:
            raise ImportError("tree-sitter_languages is required")
        self._parser = None
        self._language = None

    def _init_parser(self):
        """懒加载 tree-sitter parser"""
        if self._parser is None:
            self._language = tree_sitter_languages.get_language(self.LANG_NAME)
            self._parser = tree_sitter_languages.get_parser(self.LANG_NAME)

    def parse_file(self, source_file_path: str, file_id: int,
                   analysis_store) -> int:
        """
        解析单个文件，将 AST 节点写入 SQLite

        Returns:
            AST 节点数，-1 表示文件过大被跳过
        """
        # 检查文件大小
        try:
            file_size = os.path.getsize(source_file_path)
        except OSError:
            logger.warning(f"无法读取文件大小: {source_file_path}")
            return 0

        if file_size > MAX_FILE_SIZE:
            logger.debug(f"跳过过大文件: {source_file_path} ({file_size} bytes)")
            return -1

        # 读取文件内容
        try:
            with open(source_file_path, "r", encoding="utf-8", errors="replace") as f:
                source_code = f.read()
        except Exception as e:
            logger.error(f"读取文件失败 {source_file_path}: {e}")
            return 0

        # 解析 AST
        self._init_parser()
        tree = self._parser.parse(bytes(source_code, "utf-8"))
        root = tree.root_node

        # 遍历节点
        nodes = []
        node_id_counter = [0]

        def _traverse(node, scope_node_id=None):
            if len(nodes) >= MAX_AST_NODES:
                return

            # 生成节点 ID
            node_id = f"n{node_id_counter[0]:06d}"
            node_id_counter[0] += 1

            # 格式化位置
            start = f"{node.start_point[0]},{node.start_point[1]}"
            end = f"{node.end_point[0]},{node.end_point[1]}"

            nodes.append({
                "file_id": file_id,
                "node_id": node_id,
                "scope_node_id": scope_node_id,
                "def_node_id": None,
                "type": node.type,
                "name": self._extract_name(node),
                "op": None,
                "refs": [],
                "start": start,
                "end": end,
                "content_size": node.end_byte - node.start_byte,
            })

            # 递归子节点
            child_scope = node_id if self._is_scope(node.type) else scope_node_id
            for child in node.children:
                _traverse(child, child_scope)

        _traverse(root)

        # 批量写入 SQLite
        if nodes:
            analysis_store.bulk_insert_nodes(nodes)

        return len(nodes)

    def _extract_name(self, node) -> Optional[str]:
        """从节点提取名称"""
        # 尝试找 identifier 子节点
        for child in node.children:
            if child.type in ("identifier", "field_identifier"):
                return child.text.decode("utf-8", errors="replace")
        # 节点本身有 text
        if node.type in ("identifier", "field_identifier"):
            return node.text.decode("utf-8", errors="replace")
        return None

    def _is_scope(self, node_type: str) -> bool:
        """判断节点是否为作用域节点"""
        scope_types = {
            "function_definition", "method_definition", "class_definition",
            "struct_definition", "namespace", "block", "function_item",
            "class_declaration", "method_declaration", "function_declaration",
            "procedure_declaration", "class_body", "compound_statement",
        }
        return node_type in scope_types
