"""函数指针注册模式 — 识别 C 代码中 struct 字段 = function_name 的赋值

常见场景：
  static struct file_operations my_fops = {
      .read   = my_read_func,
      .write  = my_write_func,
  };

这些赋值在 AST 中不产生调用引用，因此标准解析器不会生成任何边。
本模式从 source 中正则匹配模式，将注册的函数链接到其所在的 interface/vtable。
"""

import logging
import os
import re
from typing import Optional

from parsers.patterns import CallPattern
from parsers.core.symbol_model import FileSymbolTable, Node, NodeKind, Edge, EdgeKind, Provenance

logger = logging.getLogger(__name__)

# 匹配 .field_name = function_name 初始化器
_VTABLE_ASSIGN_RE = re.compile(
    rb"""\.\w+\s*=\s*(\w+)"""     # .field = func_name
)

# 匹配直接变量赋值 ops.func = my_handler
_DIRECT_ASSIGN_RE = re.compile(
    rb"""(\w+)\.(\w+)\s*=\s*(\w+)"""  # var.field = handler
)

# 结构体初始化块界定
_STRUCT_INIT_BLOCK_RE = re.compile(
    rb"(?:static\s+)?(?:const\s+)?struct\s+\w+\s+\w+\s*=\s*\{",
)


class CallbackRegistryPattern(CallPattern):
    """struct 函数指针字段赋值 → CALLBACK 边"""

    language = "c"
    priority = 8

    def process(
        self,
        tables: list[FileSymbolTable],
        node_index: dict[str, Node],
    ) -> list[Edge]:
        edges: list[Edge] = []

        # 构建 name → Node 索引
        name_index: dict[str, Node] = {}
        for n in node_index.values():
            if n.kind in (NodeKind.FUNCTION, NodeKind.METHOD):
                name_index[n.name] = n

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

        abs_path = file_path
        if proj_path and not os.path.isabs(file_path):
            abs_path = os.path.join(proj_path, file_path)
        if not os.path.isfile(abs_path):
            return edges

        try:
            with open(abs_path, "rb") as f:
                source = f.read()
        except OSError as e:
            logger.debug(f"[CallbackRegistry] cannot read {abs_path}: {e}")
            return edges

        # 1. 扫描 struct 初始化块内的 .field = func_name
        for block_match in _STRUCT_INIT_BLOCK_RE.finditer(source):
            block_start = block_match.start()
            # 找到匹配的 }（简易平衡——不处理嵌套 struct）
            brace_count = 1
            pos = block_match.end()
            while pos < len(source) and brace_count > 0:
                if source[pos:pos+1] == b"{":
                    brace_count += 1
                elif source[pos:pos+1] == b"}":
                    brace_count -= 1
                pos += 1
            block_end = pos
            block = source[block_start:block_end]

            struct_name_match = re.search(rb"struct\s+(\w+)", block)
            struct_name = struct_name_match.group(1).decode() if struct_name_match else "?"

            for assign_match in _VTABLE_ASSIGN_RE.finditer(block):
                self._add_assignment_edge(
                    assign_match, table, name_index,
                    struct_name, edges,
                    source_offset=block_start,
                )

        # 2. 扫描直接赋值 ops.func = handler
        for assign_match in _DIRECT_ASSIGN_RE.finditer(source):
            # 跳过已经在 struct 块内的
            handler_name = assign_match.group(3).decode()
            callee = name_index.get(handler_name)
            if not callee:
                continue
            call_line = source[: assign_match.start()].count(b"\n") + 1
            edges.append(Edge(
                source="",
                target=callee.id,
                kind=EdgeKind.CALLBACK,
                line=call_line,
                file_path=file_path,
                provenance=Provenance.PATTERN,
                metadata={
                    "pattern": "direct_callback",
                    "var": assign_match.group(1).decode(),
                    "field": assign_match.group(2).decode(),
                },
            ))

        return edges

    def _add_assignment_edge(
        self,
        match,
        table: FileSymbolTable,
        name_index: dict[str, Node],
        struct_name: str,
        edges: list[Edge],
        source_offset: int = 0,
    ):
        handler_name = match.group(1).decode()
        callee = name_index.get(handler_name)
        if not callee:
            return

        line = source[: match.start() + source_offset].count(b"\n") + 1
        col = match.start() - source[: match.start() + source_offset].rfind(b"\n")
        edges.append(Edge(
            source="",
            target=callee.id,
            kind=EdgeKind.CALLBACK,
            line=line,
            col=col,
            file_path=table.file_path,
            provenance=Provenance.PATTERN,
            metadata={
                "pattern": "vtable_field",
                "struct": struct_name,
                "field": match.group(0).decode().split("=")[0].strip().lstrip("."),
                "handler": handler_name,
            },
        ))


def _resolve_project_path(tables: list[FileSymbolTable]) -> Optional[str]:
    """从符号表推断项目根路径"""
    for t in tables:
        fp = t.file_path
        if fp and os.path.isabs(fp):
            return "/"
    return None
