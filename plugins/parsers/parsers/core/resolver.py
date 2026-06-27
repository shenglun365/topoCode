"""ResolutionEngine — 两阶段跨文件名称解析引擎

Phase 2: 解析阶段
  1. 建立全局索引 (name → nodes, qualifiedName → node, export map)
  2. 对每个 unresolved reference 尝试解析:
     a. 文件内 local scope 链查找
     b. import 跨文件解析 (从 export 表匹配)
     c. qualified name 全限定名匹配
  3. 输出 resolved Edge 列表 (calls, imports, extends, implements, ...)

优化说明 (Phase D):
  - _suffix_index: 路径后缀倒排索引，将 _find_file_for_import() 从 O(N_files) 降至 O(1)
  - _file_node_index: file_path → name → [Node]，消除 O(N_nodes) 全表扫描
"""

from __future__ import annotations

import logging
import os
import time
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

        # 优化索引 (Phase D): 加速跨文件查找
        self._suffix_index: dict[str, str] = {}      # 路径去扩展名后缀 → file_path (O(1) 查找)
        self._file_node_index: dict[str, dict[str, list[Node]]] = defaultdict(lambda: defaultdict(list))
                                                      # file_path → name → [Node]

    def build_index(self, tables: list[FileSymbolTable], progress_callback=None,
                    stop_check=None):
        """从所有文件的提取结果构建全局索引"""
        total_files = len(tables)
        logger.info("[resolve] build_index: building index from %d files", total_files)
        _t0 = time.perf_counter()
        _last_report = 0
        for i, table in enumerate(tables):
            if stop_check and stop_check():
                logger.info("[resolve] build_index: stopped at file %d/%d", i + 1, total_files)
                return False

            fp = table.file_path
            for node in table.nodes:
                self._name_index[node.name].append(node)
                self._qualified_index[node.qualified_name] = node
                self._node_by_id[node.id] = node
                self._file_node_index[fp][node.name].append(node)

                if node.is_exported:
                    self._export_index[fp].add(node.name)

            # 顶层节点也视为可导出
            for node in table.top_level_nodes():
                self._export_index[fp].add(node.name)

            # 构建路径后缀索引: 去扩展名后的路径及其所有后缀
            fp_noext, _ = os.path.splitext(fp)
            self._suffix_index.setdefault(fp_noext, fp)
            parts = fp_noext.split("/")
            for i in range(len(parts)):
                key = "/".join(parts[i:])
                self._suffix_index.setdefault(key, fp)

            if (i + 1) % 500 == 0:
                _elapsed = time.perf_counter() - _t0
                logger.info("[resolve] build_index: %d/%d files (%.1fs)", i + 1, total_files, _elapsed)
                if progress_callback:
                    progress_callback(i + 1, total_files)

        _elapsed = time.perf_counter() - _t0
        if progress_callback:
            progress_callback(total_files, total_files)
        logger.info("[resolve] build_index: done %d files in %.1fs (nodes=%d, exports=%d)",
                    total_files, _elapsed,
                    sum(len(t.nodes) for t in tables),
                    sum(len(e) for e in self._export_index.values()))
        return True

    def resolve(self, tables: list[FileSymbolTable],
                progress_callback=None, stop_check=None) -> list[Edge]:
        """解析所有未解析引用，生成 edges

        Args:
            tables: 所有文件的 FileSymbolTable 列表
            progress_callback: 可选进度回调 fn(current, total)，
                               在 build_index 和 resolve 阶段均会调用
            stop_check: 可选停止检查回调 fn() → bool，
                        返回 True 时立即中断

        Returns:
            resolved Edge 列表
        """
        _t0 = time.perf_counter()
        if not self.build_index(tables, progress_callback=progress_callback,
                                stop_check=stop_check):
            logger.info("[resolve] resolve: stopped during build_index, returning partial results")
            return []
        _total_refs = sum(len(t.unresolved_refs) for t in tables)
        _total_files = len(tables)
        logger.info("[resolve] resolve: starting %d refs across %d files", _total_refs, _total_files)

        if progress_callback:
            progress_callback(0, _total_refs)

        edges: list[Edge] = []
        _ref_count = 0
        _last_report = 0

        for table in tables:
            if stop_check and stop_check():
                logger.info("[resolve] resolve: stopped at table %s, %d/%d refs processed",
                            table.file_path, _ref_count, _total_refs)
                break

            for ref in table.unresolved_refs:
                if stop_check and stop_check():
                    logger.info("[resolve] resolve: stopped at ref %d/%d",
                                _ref_count, _total_refs)
                    break

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

                _ref_count += 1
                if _ref_count - _last_report >= 5000:
                    _last_report = _ref_count
                    _elapsed = time.perf_counter() - _t0
                    logger.info("[resolve] resolve: %d/%d refs processed (%.1fs, edges=%d)",
                                _ref_count, _total_refs, _elapsed, len(edges))
                    if progress_callback:
                        progress_callback(_ref_count, _total_refs)
                    if stop_check and stop_check():
                        logger.info("[resolve] resolve: stopped at ref %d/%d",
                                    _ref_count, _total_refs)
                        break

            else:
                continue
            break

        if progress_callback:
            progress_callback(_ref_count, _total_refs)

        _elapsed = time.perf_counter() - _t0
        logger.info("[resolve] resolve: done %d refs in %.1fs → %d edges (resolved=%d, unresolved=%d)",
                    _total_refs, _elapsed, len(edges),
                    sum(1 for e in edges if e.target),
                    sum(1 for e in edges if not e.target))
        return edges

    # ── 策略实现 ─────────────────────────────────────────

    def _resolve_local(self, ref: UnresolvedReference, table: FileSymbolTable) -> Optional[Node]:
        """文件内按 scope 链向上查找（使用 _file_node_index O(1) 查找）"""
        name = ref.reference_name
        caller = self._node_by_id.get(ref.from_node_id)
        if not caller:
            return None

        # 使用 _file_node_index 直接获取当前文件下同名节点列表
        candidates = self._file_node_index.get(table.file_path, {}).get(name, [])

        # 获取 caller 的 scope 链
        scopes = self._scope_chain(caller.qualified_name)
        for scope in scopes:
            for node in candidates:
                if node.qualified_name.startswith(scope):
                    return node

        # 文件内任意匹配（返回第一个同名节点）
        if candidates:
            return candidates[0]

        return None

    def _resolve_via_import(self, ref: UnresolvedReference, table: FileSymbolTable) -> Optional[Node]:
        """通过 import 关系跨文件查找（使用 _suffix_index + _file_node_index O(1) 查找）"""
        name = ref.reference_name
        src_lang = ref.language or ""

        # 先检查 name 是否完整匹配某个 import 中的导出符号
        for imp in table.imports:
            target_file = self._find_file_for_import(imp, table.file_path)
            if target_file:
                exports = self._export_index.get(target_file, set())
                if name in exports:
                    nodes = self._file_node_index.get(target_file, {}).get(name, [])
                    if nodes:
                        return nodes[0]

        # 包限定调用 "pkg.Func" → 分割后通过 import 匹配
        if "." in name and src_lang in ("go", "python", "typescript", "javascript", "java"):
            pkg_part, func_part = name.rsplit(".", 1)
            for imp in table.imports:
                imp_pkg = imp.split("/")[-1].split(".")[-1]
                if imp_pkg == pkg_part or imp.endswith(pkg_part):
                    target_file = self._find_file_for_import(imp, table.file_path)
                    if target_file:
                        exports = self._export_index.get(target_file, set())
                        if func_part in exports:
                            nodes = self._file_node_index.get(target_file, {}).get(func_part, [])
                            if nodes:
                                return nodes[0]

        return None

    def _find_file_for_import(self, module_name: str, current_file: str) -> Optional[str]:
        """根据 import 模块名找到目标文件路径（使用 _suffix_index O(1) 查找）"""
        # 1. 精确后缀匹配（去扩展名）
        target = self._suffix_index.get(module_name)
        if target:
            return target

        # 2. 无扩展名形式匹配
        mod_noext, _ = os.path.splitext(module_name)
        if mod_noext != module_name:
            target = self._suffix_index.get(mod_noext)
            if target:
                return target

        # 3. 逐段缩短后缀匹配
        mod_parts = mod_noext.split("/")
        for i in range(1, len(mod_parts)):
            suffix = "/".join(mod_parts[i:])
            if suffix:
                target = self._suffix_index.get(suffix)
                if target:
                    return target

        # 4. 回退: 当前文件所在目录作为前缀匹配
        cur_dir = "/".join(current_file.split("/")[:-1]) if "/" in current_file else ""
        if cur_dir:
            candidate = f"{cur_dir}/{module_name}"
            target = self._suffix_index.get(candidate)
            if not target:
                candidate_noext, _ = os.path.splitext(candidate)
                target = self._suffix_index.get(candidate_noext)
            if target:
                return target

        # 5. 最终回退: 子串扫描（原 O(N) 逻辑，极少命中）
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
