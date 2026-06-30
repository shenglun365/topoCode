"""Initcall 注册模式 — 识别 Linux 内核 module_init/subsys_initcall 等宏

这些宏在 AST 中表现为 call_expression（因为宏展开前的 C 语法与函数调用相同），
被解析为对 'module_init' 等名字的 CALLS 引用。标准解析器无法解析宏名，
本模式从 source 中正则提取宏参数（被注册的函数），生成 CALLBACK 边。
"""

import logging
import os
import re
from typing import Optional

from parsers.patterns import CallPattern
from parsers.core.symbol_model import FileSymbolTable, Node, NodeKind, Edge, EdgeKind, Provenance

logger = logging.getLogger(__name__)

# Linux 内核已知的 initcall 宏（按常用度排序）
_INITCALL_MACROS = [
    r"module_init\s*\(\s*(\w+)\s*\)",
    r"module_exit\s*\(\s*(\w+)\s*\)",
    r"subsys_initcall\s*\(\s*(\w+)\s*\)",
    r"arch_initcall\s*\(\s*(\w+)\s*\)",
    r"device_initcall\s*\(\s*(\w+)\s*\)",
    r"fs_initcall\s*\(\s*(\w+)\s*\)",
    r"rootfs_initcall\s*\(\s*(\w+)\s*\)",
    r"late_initcall\s*\(\s*(\w+)\s*\)",
    r"core_initcall\s*\(\s*(\w+)\s*\)",
    r"postcore_initcall\s*\(\s*(\w+)\s*\)",
    r"pure_initcall\s*\(\s*(\w+)\s*\)",
]

# 可选的 RPC/组件框架注册模式
_REGISTER_PATTERNS = [
    r"register_\w+\s*\(\s*(\w+)\s*\)",
]


class InitcallPattern(CallPattern):
    """initcall 宏 → CALLBACK 边"""

    language = "c"
    priority = 10

    def process(
        self,
        tables: list[FileSymbolTable],
        node_index: dict[str, Node],
    ) -> list[Edge]:
        edges: list[Edge] = []

        # 构建 name → Node 索引（用于查找被注册的函数）
        name_index: dict[str, Node] = {}
        for n in node_index.values():
            if n.kind == NodeKind.FUNCTION:
                name_index[n.name] = n

        # 收集所有文件名（用于读取源文件）
        proj_path = _resolve_project_path(tables)

        for table in tables:
            file_edges = self._scan_file(table, proj_path, name_index)
            edges.extend(file_edges)

        return edges

    def _scan_file(
        self,
        table: FileSymbolTable,
        proj_path: str,
        name_index: dict[str, Node],
    ) -> list[Edge]:
        edges: list[Edge] = []
        file_path = table.file_path

        # 确定实际文件路径
        abs_path = file_path
        if proj_path and not os.path.isabs(file_path):
            abs_path = os.path.join(proj_path, file_path)
        if not os.path.isfile(abs_path):
            return edges

        try:
            with open(abs_path, "rb") as f:
                source = f.read()
        except OSError as e:
            logger.debug(f"[Initcall] cannot read {abs_path}: {e}")
            return edges

        # 从本文件找出所有 FUNCTION 节点（用于定位行号）
        local_functions = {
            n.name: n for n in table.nodes if n.kind == NodeKind.FUNCTION
        }

        for macro_re in _INITCALL_MACROS + _REGISTER_PATTERNS:
            for match in re.finditer(macro_re.encode(), source, re.MULTILINE):
                func_name = match.group(1).decode()
                callee = name_index.get(func_name)
                if not callee:
                    # 被注册的函数不在已解析的符号表中
                    continue

                # 找到包含该宏调用的函数（在宏上方的最近函数）
                call_line = source[: match.start()].count(b"\n") + 1
                caller = self._find_enclosing_function(table.nodes, table.unresolved_refs, call_line)

                # 生成 CALLBACK 边
                edges.append(Edge(
                    source=caller.id if caller else "",
                    target=callee.id,
                    kind=EdgeKind.CALLBACK,
                    line=call_line,
                    col=source[: match.start()].rfind(b"\n") if b"\n" in source[: match.start()] else 0,
                    file_path=file_path,
                    provenance=Provenance.PATTERN,
                    metadata={"pattern": "initcall", "macro": match.group(0).decode()[:60]},
                ))

        return edges

    @staticmethod
    def _find_enclosing_function(
        nodes: list[Node],
        refs,
        line: int,
    ) -> Optional[Node]:
        """在节点列表中找包含给定行号的函数"""
        candidates = [n for n in nodes if n.kind == NodeKind.FUNCTION
                      and n.start_line <= line <= n.end_line]
        if candidates:
            return max(candidates, key=lambda n: n.end_line - n.start_line)
        return None


def _resolve_project_path(tables: list[FileSymbolTable]) -> Optional[str]:
    """从符号表推断项目根路径"""
    for t in tables:
        fp = t.file_path
        if fp and os.path.isabs(fp):
            # 取第一个绝对路径的公共前缀
            return "/"
    return None
