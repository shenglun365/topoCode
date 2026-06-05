"""QueryLoader — 加载 .scm 文件并编译为 Tree-sitter Query 对象"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from tree_sitter import Language, Query, QueryCursor, Node


@dataclass
class QuerySet:
    """一种语言的 Tree-sitter 查询集"""
    language: str
    definitions: Query
    references: Query
    imports: Query


@dataclass
class CapturedNode:
    """单个查询捕获结果"""
    name: str
    capture_name: str        # e.g., "func.name", "call.callee"
    match_id: int
    node: Node


@dataclass
class QueryMatch:
    """一次查询匹配的全部捕获"""
    match_id: int
    captures: list[CapturedNode] = field(default_factory=list)

    def get(self, name: str) -> Optional[Node]:
        """按捕获名获取第一个匹配节点"""
        for c in self.captures:
            if c.capture_name == name:
                return c.node
        return None

    def get_all(self, name: str) -> list[Node]:
        """按捕获名获取所有匹配节点"""
        return [c.node for c in self.captures if c.capture_name == name]


class QueryLoader:
    """加载 .scm 文件并编译为 Tree-sitter Query 对象, 带缓存"""

    _cache: dict[str, QuerySet] = {}

    @classmethod
    def load(cls, lang_name: str, language: Language) -> QuerySet:
        """加载指定语言的 QuerySet

        Args:
            lang_name: 语言名称 (e.g. "typescript")
            language: 已初始化的 tree-sitter Language 对象

        Returns:
            编译好的 QuerySet 对象
        """
        if lang_name in cls._cache:
            return cls._cache[lang_name]

        base = Path(__file__).parent / "queries" / lang_name

        defs_path = base / "definitions.scm"
        refs_path = base / "references.scm"
        imps_path = base / "imports.scm"

        qs = QuerySet(
            language=lang_name,
            definitions=Query(language, defs_path.read_text(encoding="utf-8")) if defs_path.exists() else None,
            references=Query(language, refs_path.read_text(encoding="utf-8")) if refs_path.exists() else None,
            imports=Query(language, imps_path.read_text(encoding="utf-8")) if imps_path.exists() else None,
        )
        cls._cache[lang_name] = qs
        return qs

    @classmethod
    def clear_cache(cls):
        """清除查询缓存 (用于测试)"""
        cls._cache.clear()

    @classmethod
    def run_query(cls, query: Query, root_node: Node) -> list[QueryMatch]:
        """执行一个 Query 并返回结构化匹配结果

        Args:
            query: 编译后的 Tree-sitter Query
            root_node: AST 根节点

        Returns:
            按 match_id 分组的 QueryMatch 列表
        """
        cursor = QueryCursor(query)
        matches = {}
        for match_id, capture_dict in cursor.matches(root_node):
            if match_id not in matches:
                matches[match_id] = QueryMatch(match_id=match_id)
            for capture_name, node_list in capture_dict.items():
                for node in node_list:
                    matches[match_id].captures.append(
                        CapturedNode(
                            name=cls._extract_text(node),
                            capture_name=capture_name,
                            match_id=match_id,
                            node=node,
                        )
                    )
        return list(matches.values())

    @classmethod
    def _extract_text(cls, node: Node) -> str:
        """从节点安全提取文本"""
        try:
            return node.text.decode("utf-8", errors="replace")
        except Exception:
            return ""
