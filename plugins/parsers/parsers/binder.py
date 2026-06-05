"""SimpleBinder — 基于作用域栈 + 导入的快速名称绑定器

覆盖 80% 常见模式:
  - 文件内作用域链查找 (向上遍历)
  - 导入跨文件查找 (从 export 表匹配)
  - 限定名访问 (a.b.c)
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass, field
from typing import Optional

from parsers.symbol_model import Symbol, Reference, RefKind, FileSymbolTable

logger = logging.getLogger(__name__)


@dataclass
class ResolveResult:
    """名称解析结果"""
    target: Optional[Symbol]
    confidence: float          # 0.0 ~ 1.0
    candidates: list[Symbol] = field(default_factory=list)
    method: str = "local"      # "local", "import", "qualified", "unresolved"


class SimpleBinder:
    """基于作用域栈 + 导出的快速名称绑定器

    用法:
        binder = SimpleBinder(file_tables)
        result = binder.resolve(reference)
    """

    def __init__(self, file_tables: dict[str, FileSymbolTable]):
        self.file_tables = file_tables
        self._scope_index: dict[str, list[Symbol]] = {}   # scope → symbols
        self._export_index: dict[str, set[str]] = {}      # file → exported names
        self._build_index()

    def _build_index(self):
        """构建作用域索引和导出索引"""
        for file_path, table in self.file_tables.items():
            exports: set[str] = set()
            for sym in table.symbols:
                # 构建作用域索引
                scope_key = f"{file_path}::{sym.scope}"
                self._scope_index.setdefault(scope_key, []).append(sym)

                # 顶层符号加入导出索引
                if sym.scope == "module":
                    exports.add(sym.name)

            self._export_index[file_path] = exports

    def resolve(self, ref: Reference, file_path: str = "") -> ResolveResult:
        """解析引用: 本地作用域 → 导入 → 未解析

        Args:
            ref: 待解析的引用
            file_path: 引用所在文件 (从 location 自动获取)

        Returns:
            解析结果
        """
        ctx_file = file_path or ref.location.file_path

        # 1. 本地作用域链向上查找
        local = self._resolve_local(ref, ctx_file)
        if local and local.confidence >= 0.9:
            return local

        # 2. 如果引用处有同名 import, 查跨文件导出
        imported = self._resolve_via_import(ref, ctx_file)
        if imported and imported.confidence >= 0.7:
            return imported

        # 3. 限定名访问 (e.g., Foo.bar)
        qualified = self._resolve_qualified(ref, ctx_file)
        if qualified and qualified.confidence >= 0.7:
            return qualified

        # 4. 返回低置信度结果, 标记为需要 Stack Graphs
        return ResolveResult(target=None, confidence=0.0, method="unresolved")

    def _resolve_local(self, ref: Reference, file_path: str) -> Optional[ResolveResult]:
        """文件内作用域链查找"""
        ref_scope = ref.scope
        name = ref.name

        # 从当前作用域向上遍历到 module
        scopes_to_check = self._scope_chain(ref_scope)
        for scope in scopes_to_check:
            scope_key = f"{file_path}::{scope}"
            symbols = self._scope_index.get(scope_key, [])
            for sym in symbols:
                if sym.name == name:
                    return ResolveResult(
                        target=sym,
                        confidence=1.0,
                        method="local",
                    )

        return None

    def _resolve_via_import(self, ref: Reference, file_path: str) -> Optional[ResolveResult]:
        """通过导入关系跨文件解析"""
        name = ref.name

        # 找到引用文件中匹配的导入
        file_table = self.file_tables.get(file_path)
        if not file_table:
            return None

        matching_imports = []
        for imp in file_table.imports:
            if name in imp.imported_names or imp.alias == name:
                matching_imports.append(imp)

        if not matching_imports:
            return None

        # 尝试在导入的目标文件中查找导出符号
        candidates = []
        for imp in matching_imports:
            target_file = self._find_file_from_import(imp)
            if target_file:
                exports = self._export_index.get(target_file, set())
                if name in exports:
                    sym = self._find_symbol_in_file(target_file, name)
                    if sym:
                        candidates.append(sym)

        if candidates:
            return ResolveResult(
                target=candidates[0],
                confidence=0.9,
                candidates=candidates,
                method="import",
            )

        # 导入存在但目标文件无分析结果, 返回中等置信度
        return ResolveResult(
            target=None,
            confidence=0.5,
            candidates=[],
            method="import",
        )

    def _resolve_qualified(self, ref: Reference, file_path: str) -> Optional[ResolveResult]:
        """解析限定名访问 (e.g., obj.prop → obj 的 class 定义中找 prop)"""
        if "." not in ref.name:
            return None

        parts = ref.name.split(".")
        if len(parts) < 2:
            return None

        # 尝试解析第一部分 (obj) 的作用域, 然后在其中找后续部分
        # 这是一个简化实现, 完整实现在 Phase 3 通过 Stack Graphs
        return ResolveResult(
            target=None,
            confidence=0.3,
            method="qualified",
        )

    def _scope_chain(self, scope: str) -> list[str]:
        """从当前作用域向上到 Module 的作用域链

        e.g., "class.Foo.method.bar" → ["class.Foo.method.bar", "class.Foo", "module"]
        """
        if not scope or scope == "module":
            return ["module"]

        parts = scope.split(".")
        chain = []
        for i in range(len(parts), 0, -1):
            chain.append(".".join(parts[:i]))
        chain.append("module")
        return chain

    def _find_file_from_import(self, imp) -> Optional[str]:
        """根据导入记录找到目标文件路径 (精确匹配优先, 模糊匹配回退)"""
        module_path = imp.module
        if imp.resolved_file:
            return imp.resolved_file

        # 在 file_tables 中尝试精确匹配
        if module_path in self.file_tables:
            return module_path

        # 尝试通过文件路径尾部匹配
        for fp in self.file_tables:
            if fp.endswith(module_path) or module_path.endswith(fp):
                return fp

        return None

    def _find_symbol_in_file(self, file_path: str, name: str) -> Optional[Symbol]:
        """在指定文件中查找顶层符号"""
        table = self.file_tables.get(file_path)
        if not table:
            return None
        return table.get_symbol(name)

    @classmethod
    def from_tables(cls, tables: list[FileSymbolTable]) -> SimpleBinder:
        """从 FileSymbolTable 列表构建 (自动按 file_path 索引)"""
        indexed = {t.file_path: t for t in tables}
        return cls(indexed)
