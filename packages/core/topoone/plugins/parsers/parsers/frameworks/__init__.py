"""FrameworkResolver — 框架感知解析基类 + 注册表"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..core.symbol_model import Node, Edge, EdgeKind, FileSymbolTable
from ..core.node_types import NodeKind, Provenance

# 全局注册表
_RESOLVERS: list[FrameworkResolver] = []


class FrameworkResolver(ABC):
    """框架解析器 — 识别框架特有模式，生成额外节点和边"""

    name: str = ""           # "django", "react", ...
    language: str = ""       # "python", "typescript", ...

    @abstractmethod
    def detect(self, tables: list[FileSymbolTable]) -> bool:
        """检测项目是否使用此框架"""

    @abstractmethod
    def extract(self, table: FileSymbolTable) -> list[Node]:
        """从单文件提取框架特有节点（route, component 等）"""

    @abstractmethod
    def resolve(self, nodes: list[Node], tables: list[FileSymbolTable]) -> list[Edge]:
        """生成框架特有边"""


def register_resolver(resolver: FrameworkResolver):
    _RESOLVERS.append(resolver)


def get_detected_resolvers(tables: list[FileSymbolTable]) -> list[FrameworkResolver]:
    return [r for r in _RESOLVERS if r.detect(tables)]


def run_all(tables: list[FileSymbolTable]) -> list[Edge]:
    """运行所有已检测到的框架解析器"""
    all_edges: list[Edge] = []
    resolvers = get_detected_resolvers(tables)
    for resolver in resolvers:
        try:
            edges = resolver.resolve(
                [n for t in tables for n in t.nodes],
                tables,
            )
            for e in edges:
                e.provenance = Provenance.FRAMEWORK
            all_edges.extend(edges)
        except Exception:
            pass
    return all_edges
