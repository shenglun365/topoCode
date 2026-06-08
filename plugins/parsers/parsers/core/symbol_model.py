"""统一符号模型 — Node, Edge, FileSymbolTable, UnresolvedReference

新流程:
  TreeSitterWalker.extract() → [Node] + [UnresolvedReference] (内存)
        ↓
  GraphEmitter.write_nodes() → graph_node (SQL)
        ↓
  ResolutionEngine.resolve() → [Edge] (内存)
        ↓
  GraphEmitter.write_edges() → graph_edge (SQL)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .node_types import NodeKind, EdgeKind, Provenance


@dataclass
class Node:
    """统一符号节点"""
    id: str
    kind: NodeKind
    name: str
    qualified_name: str
    file_path: str
    file_id: str = ""
    language: str = ""
    start_line: int = 0
    start_col: int = 0
    end_line: int = 0
    end_col: int = 0
    signature: Optional[str] = None
    visibility: Optional[str] = None          # public / private / protected / internal
    is_exported: bool = False
    is_async: bool = False
    is_static: bool = False
    docstring: Optional[str] = None
    decorators: Optional[list[str]] = None
    type_parameters: Optional[list[str]] = None


@dataclass
class Edge:
    """统一关系边"""
    source: str                               # source Node.id
    target: str                               # target Node.id
    kind: EdgeKind
    line: int = 0
    col: int = 0
    file_path: str = ""
    provenance: Provenance = Provenance.PARSER
    metadata: Optional[dict] = None


@dataclass
class UnresolvedReference:
    """未解析引用 — 在第一阶段收集，第二阶段解析"""
    from_node_id: str
    reference_name: str
    reference_kind: EdgeKind
    line: int = 0
    col: int = 0
    file_path: str = ""
    language: str = ""


@dataclass
class FileSymbolTable:
    """单文件提取结果容器"""
    file_path: str
    language: str
    nodes: list[Node] = field(default_factory=list)
    unresolved_refs: list[UnresolvedReference] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)       # 模块名列表
    exports: list[str] = field(default_factory=list)       # 导出符号名列表

    def add_node(self, node: Node):
        self.nodes.append(node)

    def add_ref(self, ref: UnresolvedReference):
        self.unresolved_refs.append(ref)

    def add_import(self, module_name: str):
        self.imports.append(module_name)

    def add_export(self, name: str):
        self.exports.append(name)

    def get_node(self, name: str, kind: Optional[NodeKind] = None) -> Optional[Node]:
        for n in self.nodes:
            if n.name == name:
                if kind is None or n.kind == kind:
                    return n
        return None

    def nodes_by_kind(self, kind: NodeKind) -> list[Node]:
        return [n for n in self.nodes if n.kind == kind]

    def top_level_nodes(self) -> list[Node]:
        """返回顶层节点 (文件级，非嵌套)"""
        return [n for n in self.nodes if not n.qualified_name or "::" not in n.qualified_name]
