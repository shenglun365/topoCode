"""ResolutionEngine — 两阶段跨文件名称解析引擎

Phase 2: 解析阶段
  1. 建立全局索引 (name → nodes, qualifiedName → node, export map)
  2. 对每个 unresolved reference 尝试解析:
     a. 文件内 local scope 链查找
     b. import 跨文件解析 (从 export 表匹配)
     c. qualified name 全限定名匹配
  3. 输出 resolved Edge 列表 (calls, imports, extends, implements, ...)
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Optional

from .node_types import NodeKind, EdgeKind, Provenance
from .symbol_model import Node, Edge, UnresolvedReference, FileSymbolTable
from ..languages import same_language_family

logger = logging.getLogger(__name__)


class ResolutionEngine:
    """跨文件引用解析引擎"""

    def __init__(self):
        # 全局索引
        self._name_index: dict[str, list[Node]] = defaultdict(list)       # name → [Node]
        self._qualified_index: dict[str, Node] = {}                       # qualifiedName → Node
        self._export_index: dict[str, set[str]] = defaultdict(set)        # file → exported names
        self._node_by_id: dict[str, Node] = {}

    def build_index(self, tables: list[FileSymbolTable]):
        """从所有文件的提取结果构建全局索引"""
        for table in tables:
            for node in table.nodes:
                self._name_index[node.name].append(node)
                self._qualified_index[node.qualified_name] = node
                self._node_by_id[node.id] = node

                if node.is_exported:
                    self._export_index[table.file_path].add(node.name)

            # 顶层节点也视为可导出
            for node in table.top_level_nodes():
                self._export_index[table.file_path].add(node.name)

    def resolve(self, tables: list[FileSymbolTable]) -> list[Edge]:
        """解析所有未解析引用，生成 edges

        Args:
            tables: 所有文件的 FileSymbolTable 列表

        Returns:
            resolved Edge 列表
        """
        self.build_index(tables)
        edges: list[Edge] = []

        for table in tables:
            for ref in table.unresolved_refs:
                target = None
                method = "unresolved"

                # 策略 1: 文件内 local scope 链查找
                target = self._resolve_local(ref, table)

                # 策略 2: import 跨文件解析
                if not target:
                    result = self._resolve_via_import(ref, table)
                    if result:
                        target = result

                # 策略 3: qualified name 匹配
                if not target:
                    target = self._qualified_index.get(ref.reference_name)

                # 策略 4: name 匹配 (project-wide, 低置信度)
                if not target:
                    candidates = self._name_index.get(ref.reference_name, [])
                    if len(candidates) == 1:
                        target = candidates[0]
                        method = "name_match"

                if target:
                    # 语言族校验: 跨族调用无意义 (e.g. Java → Python)
                    src_lang = ref.language or ""
                    tgt_lang = target.language or ""
                    if src_lang and tgt_lang and not same_language_family(src_lang, tgt_lang):
                        method = "cross_language_rejected"

                    if method != "cross_language_rejected":
                        edges.append(Edge(
                            source=ref.from_node_id,
                            target=target.id,
                            kind=ref.reference_kind,
                            line=ref.line,
                            col=ref.col,
                            file_path=ref.file_path,
                            provenance=Provenance.RESOLUTION,
                            metadata={"method": method},
                        ))
                    else:
                        edges.append(Edge(
                            source=ref.from_node_id,
                            target="",
                            kind=ref.reference_kind,
                            line=ref.line,
                            col=ref.col,
                            file_path=ref.file_path,
                            provenance=Provenance.RESOLUTION,
                            metadata={"method": "cross_language_rejected"},
                        ))
                else:
                    edges.append(Edge(
                        source=ref.from_node_id,
                        target="",
                        kind=ref.reference_kind,
                        line=ref.line,
                        col=ref.col,
                        file_path=ref.file_path,
                        provenance=Provenance.RESOLUTION,
                        metadata={"method": "unresolved"},
                    ))

        return edges

    # ── 策略实现 ─────────────────────────────────────────

    def _resolve_local(self, ref: UnresolvedReference, table: FileSymbolTable) -> Optional[Node]:
        """文件内按 scope 链向上查找"""
        name = ref.reference_name
        caller = self._node_by_id.get(ref.from_node_id)
        if not caller:
            return None

        # 获取 caller 的 scope 链
        scopes = self._scope_chain(caller.qualified_name)
        for scope in scopes:
            for node in table.nodes:
                if node.name == name and node.qualified_name.startswith(scope):
                    return node

        # 文件内任意匹配
        for node in table.nodes:
            if node.name == name:
                return node

        return None

    def _resolve_via_import(self, ref: UnresolvedReference, table: FileSymbolTable) -> Optional[Node]:
        """通过 import 关系跨文件查找"""
        name = ref.reference_name

        # 查找匹配的导入
        matching_imports = [imp for imp in table.imports if name in imp or imp.endswith(name)]

        for imp in table.imports:
            # 在导入的模块文件中查找导出的符号
            target_file = self._find_file_for_import(imp, table.file_path)
            if target_file:
                exports = self._export_index.get(target_file, set())
                if name in exports:
                    for node in self._name_index.get(name, []):
                        if node.file_path == target_file:
                            return node

        return None

    def _find_file_for_import(self, module_name: str, current_file: str) -> Optional[str]:
        """根据 import 模块名找到目标文件路径"""
        for fp in self._export_index:
            if module_name in fp or fp.endswith(module_name):
                return fp
        return None

    def _scope_chain(self, qualified_name: str) -> list[str]:
        """从当前 qualified name 向上到 file 层的作用域链"""
        parts = qualified_name.split("::")
        chain = []
        for i in range(len(parts)):
            chain.append("::".join(parts[:i + 1]))
        return list(reversed(chain))
