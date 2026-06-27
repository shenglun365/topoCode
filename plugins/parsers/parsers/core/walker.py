"""TreeSitterWalker — 统一 AST 遍历器

核心入口: TreeSitterWalker.extract() → FileSymbolTable

直接替代旧管线:
  - parser.py (手写 DFS → base_node)
  - parse_with_queries.py (.scm Query → graph_node)
  - extract_global_symbols.py (base_node → graph_node)
  - extract_call_graph.py / extract_dependency_graph.py

架构:
  1. tree-sitter parse → AST
  2. DFS 遍历 (按 LanguageExtractor 分发)
  3. nodeStack 管理 scope / contains 边 / qualifiedName
  4. 输出: FileSymbolTable (nodes + unresolved_refs + imports/exports)
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path
from typing import Optional

from tree_sitter import Node as SyntaxNode, Parser

from .node_types import NodeKind, EdgeKind, Provenance
from .symbol_model import Node, Edge, UnresolvedReference, FileSymbolTable
from ..languages import LanguageExtractor
from ..language_loader import get_language, get_parser

logger = logging.getLogger(__name__)

# ── 常量 ──────────────────────────────────────────────────
_MAX_FILE_SIZE = 500 * 1024  # 500KB
_TYPE_IDENTIFIER_NODES = frozenset({
    "type_identifier", "identifier", "simple_identifier",
    "scoped_identifier", "generic_type", "predefined_type",
})
_INSTANTIATION_NODES = frozenset({
    "new_expression", "object_creation_expression",
})

# ── 扩展名→语言映射 ──────────────────────────────────────
_EXT_MAP = {
    ".ts": "typescript", ".tsx": "tsx", ".mts": "typescript", ".cts": "typescript",
    ".js": "javascript", ".jsx": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".py": "python", ".pyw": "python",
    ".java": "java",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".hpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hh": "cpp", ".hxx": "cpp",
    ".go": "go",
    ".rs": "rust",
    ".cs": "c_sharp",
    ".swift": "swift",
    ".rb": "ruby", ".rake": "ruby",
    ".kt": "kotlin", ".kts": "kotlin",
    ".php": "php", ".inc": "php",
    ".dart": "dart",
    ".scala": "scala", ".sc": "scala",
    ".lua": "lua", ".luau": "luau",
    ".m": "objc", ".mm": "objc",
}


def _detect_language(file_path: str) -> Optional[str]:
    ext = Path(file_path).suffix.lower()
    return _EXT_MAP.get(ext)


def _make_node_id(file_path: str, kind: NodeKind, name: str, line: int) -> str:
    raw = f"{file_path}:{kind.value}:{name}:{line}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _make_edge_id(source: str, target: str, kind: EdgeKind) -> str:
    raw = f"{source}->{target}:{kind.value}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _node_text(node: SyntaxNode, source: bytes) -> str:
    try:
        return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")
    except Exception:
        return ""


def _child_by_field(node: SyntaxNode, field: str) -> Optional[SyntaxNode]:
    try:
        return node.child_by_field_name(field)
    except Exception:
        return None


def _prev_docstring(node: SyntaxNode, source: bytes) -> Optional[str]:
    """获取前面的 docstring 注释"""
    prev = node.prev_sibling
    if prev and prev.type in ("comment", "block_comment", "line_comment"):
        return _node_text(prev, source)
    return None


# ══════════════════════════════════════════════════════════
# TreeSitterWalker
# ══════════════════════════════════════════════════════════

class TreeSitterWalker:
    """统一 AST 遍历器 — 每个文件创建一个实例"""

    def __init__(
        self,
        file_path: str,
        source: bytes,
        language: str,
        extractor: LanguageExtractor,
    ):
        self.file_path = file_path
        self.source = source
        self.source_str = ""
        self.language = language
        self.ex: LanguageExtractor = extractor

        # 输出
        self.nodes: list[Node] = []
        self.edges: list[Edge] = []              # 仅 contains 边（解析阶段生成）
        self.unresolved_refs: list[UnresolvedReference] = []

        # 状态
        self.node_stack: list[str] = []           # 当前 scope 节点 ID 栈
        self._node_index: dict[str, Node] = {}    # id → Node 快速查找

    # ── 主入口 ───────────────────────────────────────────

    def extract(self) -> FileSymbolTable:
        """解析文件，返回 FileSymbolTable"""
        sys.setrecursionlimit(max(sys.getrecursionlimit(), 50000))

        # 解码源文本（供钩子函数使用）
        self.source_str = self.source.decode("utf-8", errors="replace")

        # 创建 file 节点
        file_node = Node(
            id=f"file:{self.file_path}",
            kind=NodeKind.FILE,
            name=Path(self.file_path).name,
            qualified_name=self.file_path,
            file_path=self.file_path,
            language=self.language,
            start_line=1,
            end_line=self.source_str.count("\n") + 1,
        )
        self._add_node(file_node)
        self.node_stack.append(file_node.id)

        # 解析 AST
        parser = get_parser(self.language)
        if parser is None:
            logger.warning(f"No parser for {self.language}: {self.file_path}")
            return self._build_result()

        tree = parser.parse(self.source)
        if not tree or not tree.root_node:
            logger.warning(f"Empty AST: {self.file_path}")
            return self._build_result()

        # 包声明（Java/Kotlin package）
        pkg_node_id = self._extract_package(tree.root_node)
        if pkg_node_id:
            self.node_stack.append(pkg_node_id)

        # 遍历
        self.visit(tree.root_node)

        if pkg_node_id:
            self.node_stack.pop()
        self.node_stack.pop()

        # 清理
        tree.delete() if hasattr(tree, 'delete') else None

        return self._build_result()

    def _build_result(self) -> FileSymbolTable:
        table = FileSymbolTable(
            file_path=self.file_path,
            language=self.language,
            nodes=self.nodes,
            unresolved_refs=self.unresolved_refs,
        )
        for n in self.nodes:
            if n.is_exported:
                table.add_export(n.name)
            if n.kind == NodeKind.IMPORT:
                table.add_import(n.name)
        return table

    # ── 核心分发循环 ─────────────────────────────────────

    def visit(self, node: SyntaxNode):
        skip_children = self._dispatch(node)

        # 递归子节点 — 使用显式迭代栈避免 Python 递归深度限制
        # 未命中分发表的节点类型 (preproc_if, expression_statement 等) 会大量累积深度
        if not skip_children:
            _work = [(node, 0)]
            while _work:
                parent, idx = _work[-1]
                if idx < parent.named_child_count:
                    child = parent.named_child(idx)
                    _work[-1] = (parent, idx + 1)
                    if child:
                        _work.append((child, 0))
                        if self._dispatch(child):
                            _work.pop()
                else:
                    _work.pop()

    def _dispatch(self, node: SyntaxNode) -> bool:
        """分发单节点到对应提取逻辑，返回 True 表示 skip_children"""
        node_type = node.type
        ex = self.ex

        # 0. 自定义钩子
        if node_type in ex.import_types:
            self._extract_import(node)
            return False

        # 1. 函数
        if node_type in ex.function_types:
            if self._inside_class_like() and node_type in ex.method_types:
                self._extract_method(node)
            else:
                self._extract_function(node)
            return True

        # 2. 方法
        if node_type in ex.method_types:
            self._extract_method(node)
            return True

        # 3. 类
        if node_type in ex.class_types:
            classification = "class"
            if ex.classify_class:
                classification = ex.classify_class(node)
            self._extract_class_like(node, classification)
            return True

        # 4. 接口/trait/protocol
        if node_type in ex.interface_types:
            self._extract_class_like(node, ex.interface_kind.value)
            return True

        # 5. 结构体
        if node_type in ex.struct_types:
            self._extract_class_like(node, "struct")
            return True

        # 6. 枚举
        if node_type in ex.enum_types:
            self._extract_class_like(node, "enum")
            return True

        # 7. 类型别名
        if node_type in ex.type_alias_types:
            return self._extract_type_alias(node)

        # 8. 变量
        if node_type in ex.variable_types and not self._inside_class_like():
            self._extract_variable(node)
            return False

        # 9. 字段
        if node_type in ex.field_types and self._inside_class_like():
            self._extract_field(node)
            return False

        # 10. 属性
        if node_type in ex.property_types and self._inside_class_like():
            self._extract_property(node)
            return False

        # 11. 枚举成员
        if node_type in ex.enum_member_types and self._inside_enum():
            self._extract_enum_member(node)
            return False

        # 12. 调用
        if node_type in ex.call_types:
            self._collect_call(node)
            return False

        # 13. 实例化
        if node_type in ex.instantiation_types or node_type in _INSTANTIATION_NODES:
            self._collect_instantiation(node)
            return False

        # 14. Rust impl
        if node_type == "impl_item":
            self._extract_rust_impl(node)
            return False

        return False

    # ── 节点创建 ─────────────────────────────────────────

    def _add_node(self, node: Node):
        self.nodes.append(node)
        self._node_index[node.id] = node

    def _create_node(
        self,
        kind: NodeKind,
        name: str,
        ast_node: SyntaxNode,
        **extra,
    ) -> Optional[Node]:
        if not name or name == "<anonymous>":
            return None

        node_id = _make_node_id(self.file_path, kind, name, ast_node.start_point[0] + 1)
        qualified_name = self._build_qualified_name(name)

        new_node = Node(
            id=node_id,
            kind=kind,
            name=name,
            qualified_name=qualified_name,
            file_path=self.file_path,
            language=self.language,
            start_line=ast_node.start_point[0] + 1,
            start_col=ast_node.start_point[1],
            end_line=ast_node.end_point[0] + 1,
            end_col=ast_node.end_point[1],
            **{k: v for k, v in extra.items() if hasattr(Node, k)},
        )
        self._add_node(new_node)

        # contains 边
        if self.node_stack:
            parent_id = self.node_stack[-1]
            self.edges.append(Edge(
                source=parent_id,
                target=node_id,
                kind=EdgeKind.CONTAINS,
                provenance=Provenance.PARSER,
            ))

        return new_node

    def _build_qualified_name(self, name: str) -> str:
        parts = []
        for nid in self.node_stack:
            n = self._node_index.get(nid)
            if n and n.kind not in (NodeKind.FILE, NodeKind.MODULE):
                parts.append(n.name)
        parts.append(name)
        return "::".join(parts)

    # ── scope 辅助 ───────────────────────────────────────

    def _inside_class_like(self) -> bool:
        if not self.node_stack:
            return False
        n = self._node_index.get(self.node_stack[-1])
        return n is not None and n.kind in (
            NodeKind.CLASS, NodeKind.STRUCT, NodeKind.INTERFACE,
            NodeKind.TRAIT, NodeKind.PROTOCOL, NodeKind.ENUM,
        )

    def _inside_enum(self) -> bool:
        if not self.node_stack:
            return False
        n = self._node_index.get(self.node_stack[-1])
        return n is not None and n.kind == NodeKind.ENUM

    def _push_scope(self, node_id: str):
        self.node_stack.append(node_id)

    def _pop_scope(self):
        if self.node_stack:
            self.node_stack.pop()

    # ── 包声明 ───────────────────────────────────────────

    def _extract_package(self, root: SyntaxNode) -> Optional[str]:
        types = self.ex.package_types
        if not types or not self.ex.extract_package:
            return None
        for i in range(root.named_child_count):
            c = root.named_child(i)
            if c and c.type in types:
                pkg_name = self.ex.extract_package(c, self.source_str)
                if pkg_name:
                    ns = self._create_node(NodeKind.NAMESPACE, pkg_name, c)
                    return ns.id if ns else None
        return None

    # ── 函数 ─────────────────────────────────────────────

    def _extract_function(self, node: SyntaxNode, name_override: Optional[str] = None):
        ex = self.ex

        # 如果语言有 receiver 且此函数有 receiver，作为 method 处理
        if ex.extract_receiver and ex.extract_receiver(node, self.source_str):
            self._extract_method(node)
            return

        name = name_override or self._extract_name(node, ex.name_field)
        if not name or name == "<anonymous>":
            # 箭头函数/函数表达式 — 从父变量声明器取名称
            if node.type in ("arrow_function", "function_expression"):
                parent = node.parent
                if parent and parent.type == "variable_declarator":
                    n = _child_by_field(parent, "name")
                    if n:
                        name = _node_text(n, self.source)
        if not name or name == "<anonymous>":
            return

        # 检查误解析
        if ex.is_misparsed_function and ex.is_misparsed_function(name, node):
            body = self._resolve_body(node)
            if body:
                self._visit_function_body(body)
            return

        func_node = self._create_node(
            NodeKind.FUNCTION,
            name,
            node,
            signature=ex.extract_signature(node, self.source_str) if ex.extract_signature else None,
            visibility=ex.extract_visibility(node) if ex.extract_visibility else None,
            is_async=bool(ex.is_async and ex.is_async(node)),
            is_static=bool(ex.is_static and ex.is_static(node)),
            is_exported=bool(ex.is_exported and ex.is_exported(node, self.source_str)),
            docstring=_prev_docstring(node, self.source),
        )
        if not func_node:
            return

        # 装饰器
        self._extract_decorators(node, func_node.id)
        # 类型注解
        self._extract_type_annotations(node, func_node.id)

        self._push_scope(func_node.id)
        body = self._resolve_body(node)
        if body:
            self._visit_function_body(body)
        self._pop_scope()

    # ── 方法 ─────────────────────────────────────────────

    def _extract_method(self, node: SyntaxNode):
        ex = self.ex
        receiver = ex.extract_receiver(node, self.source_str) if ex.extract_receiver else None

        if not self._inside_class_like() and not ex.methods_are_top_level and not receiver:
            # 对象字面量中的方法跳过
            if node.parent and node.parent.type in ("object", "object_expression", "object_type"):
                body = self._resolve_body(node)
                if body:
                    self._visit_function_body(body)
                return
            self._extract_function(node)
            return

        name = self._extract_name(node, ex.name_field)
        if not name or name == "<anonymous>":
            return

        method_node = self._create_node(
            NodeKind.METHOD,
            name,
            node,
            signature=ex.extract_signature(node, self.source_str) if ex.extract_signature else None,
            visibility=ex.extract_visibility(node) if ex.extract_visibility else None,
            is_async=bool(ex.is_async and ex.is_async(node)),
            is_static=bool(ex.is_static and ex.is_static(node)),
            is_exported=bool(ex.is_exported and ex.is_exported(node, self.source_str)),
            docstring=_prev_docstring(node, self.source),
        )
        if not method_node:
            return

        # receiver 类型 → contains 边
        if receiver and not self._inside_class_like():
            owner = None
            for n in self.nodes:
                if (n.name == receiver and n.file_path == self.file_path
                        and n.kind in (NodeKind.STRUCT, NodeKind.CLASS, NodeKind.ENUM, NodeKind.TRAIT)):
                    owner = n
                    break
            if owner:
                self.edges.append(Edge(
                    source=owner.id, target=method_node.id,
                    kind=EdgeKind.CONTAINS, provenance=Provenance.PARSER,
                ))

        self._extract_decorators(node, method_node.id)
        self._extract_type_annotations(node, method_node.id)

        self._push_scope(method_node.id)
        body = self._resolve_body(node)
        if body:
            self._visit_function_body(body)
        self._pop_scope()

    # ── 类/结构体/枚举/接口/trait ────────────────────────

    def _extract_class_like(self, node: SyntaxNode, classification: str):
        kind_map = {
            "class": NodeKind.CLASS, "struct": NodeKind.STRUCT,
            "enum": NodeKind.ENUM, "interface": NodeKind.INTERFACE,
            "trait": NodeKind.TRAIT, "protocol": NodeKind.PROTOCOL,
        }
        kind = kind_map.get(classification, NodeKind.CLASS)
        ex = self.ex

        # 无 body 的枚举/结构体跳过（前向声明）
        if kind in (NodeKind.STRUCT, NodeKind.ENUM):
            body = self._resolve_body(node)
            if not body:
                return

        name = self._extract_name(node, ex.name_field)
        if not name or name == "<anonymous>":
            return

        class_node = self._create_node(
            kind,
            name,
            node,
            visibility=ex.extract_visibility(node) if ex.extract_visibility else None,
            is_exported=bool(ex.is_exported and ex.is_exported(node, self.source_str)),
            docstring=_prev_docstring(node, self.source),
        )
        if not class_node:
            return

        # 继承
        self._extract_inheritance(node, class_node.id)
        # 装饰器
        self._extract_decorators(node, class_node.id)

        self._push_scope(class_node.id)
        body = self._resolve_body(node)
        if not body:
            body = node
        for i in range(body.named_child_count):
            child = body.named_child(i)
            if child:
                self.visit(child)
        self._pop_scope()

    # ── 类型别名 ─────────────────────────────────────────

    def _extract_type_alias(self, node: SyntaxNode) -> bool:
        """返回 True 表示子节点已处理（跳过 Walker 递归）"""
        ex = self.ex
        name = self._extract_name(node, ex.name_field)
        if not name or name == "<anonymous>":
            return False

        # Go type_spec 检测 → 生成 struct/enum/interface
        if ex.resolve_type_alias_kind:
            resolved = ex.resolve_type_alias_kind(node, self.source_str)
            if resolved == NodeKind.STRUCT:
                return self._extract_type_alias_as(node, name, NodeKind.STRUCT)
            if resolved == NodeKind.ENUM:
                return self._extract_type_alias_as(node, name, NodeKind.ENUM)
            if resolved == NodeKind.INTERFACE:
                return self._extract_type_alias_as(node, name, ex.interface_kind)

        self._create_node(
            NodeKind.TYPE_ALIAS, name, node,
            is_exported=bool(ex.is_exported and ex.is_exported(node, self.source_str)),
        )
        return False

    def _extract_type_alias_as(self, node: SyntaxNode, name: str, kind: NodeKind) -> bool:
        class_node = self._create_node(
            kind, name, node,
            is_exported=bool(self.ex.is_exported and self.ex.is_exported(node, self.source_str)),
        )
        if not class_node:
            return True

        type_child = _child_by_field(node, "type")
        self._push_scope(class_node.id)
        if type_child:
            self._extract_inheritance(type_child, class_node.id)
            body = self._resolve_body(type_child) or type_child
            for i in range(body.named_child_count):
                child = body.named_child(i)
                if child:
                    self.visit(child)
        self._pop_scope()
        return True

    # ── 变量 ─────────────────────────────────────────────

    def _extract_variable(self, node: SyntaxNode):
        ex = self.ex
        is_const = bool(ex.is_const and ex.is_const(node))
        kind = NodeKind.CONSTANT if is_const else NodeKind.VARIABLE
        is_exported = bool(ex.is_exported and ex.is_exported(node, self.source_str))

        # TypeScript/JavaScript
        if self.language in ("typescript", "javascript", "tsx", "jsx"):
            for i in range(node.named_child_count):
                child = node.named_child(i)
                if child and child.type == "variable_declarator":
                    name_node = _child_by_field(child, "name")
                    if not name_node:
                        continue
                    if name_node.type in ("object_pattern", "array_pattern"):
                        continue
                    name = _node_text(name_node, self.source)
                    value_node = _child_by_field(child, "value")
                    if value_node and value_node.type in ("arrow_function", "function_expression"):
                        self._extract_function(value_node)
                        continue
                    var_node = self._create_node(kind, name, child, is_exported=is_exported)
                    if var_node and value_node:
                        self._extract_type_annotations(child, var_node.id)

        # Python / Ruby
        elif self.language in ("python", "ruby"):
            left = _child_by_field(node, "left") or node.named_child(0)
            if left and left.type == "identifier":
                self._create_node(kind, _node_text(left, self.source), node)

        # Go
        elif self.language == "go":
            if node.type == "short_var_declaration":
                left = _child_by_field(node, "left")
                if left:
                    ids = left.named_children if left.type == "expression_list" else [left]
                    for id_node in ids:
                        if id_node.type == "identifier":
                            self._create_node(NodeKind.VARIABLE, _node_text(id_node, self.source), node)
            else:
                for c in node.named_children:
                    if c and c.type in ("var_spec", "const_spec"):
                        n = c.named_child(0)
                        if n and n.type == "identifier":
                            k = NodeKind.CONSTANT if node.type == "const_declaration" else NodeKind.VARIABLE
                            self._create_node(k, _node_text(n, self.source), c,
                                              is_exported=is_exported)

        # C/C++ / generic
        else:
            for i in range(node.named_child_count):
                child = node.named_child(i)
                if child and child.type in ("identifier", "init_declarator"):
                    n = _node_text(child, self.source) if child.type == "identifier" else self._extract_name(child, ex.name_field)
                    if n and n != "<anonymous>":
                        self._create_node(kind, n, child, is_exported=is_exported)

    # ── 字段 ─────────────────────────────────────────────

    def _extract_field(self, node: SyntaxNode):
        ex = self.ex
        vis = ex.extract_visibility(node) if ex.extract_visibility else None
        is_static = bool(ex.is_static and ex.is_static(node))
        doc = _prev_docstring(node, self.source)

        declarators = [c for c in node.named_children if c.type == "variable_declarator"]
        if not declarators:
            # C# wrapper
            var_dec = next((c for c in node.named_children if c.type == "variable_declaration"), None)
            if var_dec:
                declarators = [c for c in var_dec.named_children if c.type == "variable_declarator"]

        for decl in declarators:
            name_node = _child_by_field(decl, "name") or next((c for c in decl.named_children if c.type == "identifier"), None)
            if name_node:
                name = _node_text(name_node, self.source)
                f = self._create_node(NodeKind.FIELD, name, decl, visibility=vis, is_static=is_static, docstring=doc)
                if f:
                    self._extract_decorators(node, f.id)
                    self._extract_type_annotations(node, f.id)

        if not declarators:
            name_node = _child_by_field(node, "name") or next((c for c in node.named_children if c.type == "identifier"), None)
            if name_node:
                self._create_node(NodeKind.FIELD, _node_text(name_node, self.source), node,
                                  visibility=vis, is_static=is_static, docstring=doc)

    # ── 属性 ─────────────────────────────────────────────

    def _extract_property(self, node: SyntaxNode):
        ex = self.ex
        name_node = _child_by_field(node, "name")
        if not name_node:
            name_node = next((c for c in node.named_children if c.type in ("identifier", "property_identifier")), None)
        if not name_node:
            return
        name = _node_text(name_node, self.source)

        prop = self._create_node(
            NodeKind.PROPERTY, name, node,
            visibility=ex.extract_visibility(node) if ex.extract_visibility else None,
            is_static=bool(ex.is_static and ex.is_static(node)),
        )
        if prop:
            self._extract_decorators(node, prop.id)
            self._extract_type_annotations(node, prop.id)

    # ── 枚举成员 ────────────────────────────────────────

    def _extract_enum_member(self, node: SyntaxNode):
        name_node = _child_by_field(node, "name")
        if not name_node:
            name_node = next((c for c in node.named_children if c.type in ("identifier", "simple_identifier", "property_identifier")), None)
        if name_node:
            self._create_node(NodeKind.ENUM_MEMBER, _node_text(name_node, self.source), name_node)

    # ── 导入 ─────────────────────────────────────────────

    def _extract_import(self, node: SyntaxNode):
        ex = self.ex
        import_text = _node_text(node, self.source).strip()

        # ── 通用 source 字段提取 (从 bytes，避免非 ASCII 偏移失真) ──
        source_node = _child_by_field(node, "source")
        if source_node:
            raw = self.source[source_node.start_byte:source_node.end_byte]
            module_name = raw.decode("utf-8", errors="replace").strip("'\"")
            if module_name:
                self._create_node(
                    NodeKind.IMPORT, module_name, node,
                    signature=import_text,
                )
                # 仍调用 extract_import 钩子以允许额外处理（非标准导入样式等）
                if ex.extract_import:
                    ex.extract_import(node, self.source_str)
                return

        # ── 回退：语言特定提取器 ──
        if ex.extract_import:
            info = ex.extract_import(node, self.source_str)
            if info:
                module_name = info.get("module_name", "")
                if module_name:
                    self._create_node(
                        NodeKind.IMPORT, module_name, node,
                        signature=import_text,
                    )
                    return

        # Python: import os, sys → 每项一个 node
        if self.language == "python" and node.type == "import_statement":
            for c in node.named_children:
                if c.type == "dotted_name":
                    self._create_node(NodeKind.IMPORT, _node_text(c, self.source), node, signature=import_text)
                elif c.type == "aliased_import":
                    dn = next((cc for cc in c.named_children if cc.type == "dotted_name"), None)
                    if dn:
                        self._create_node(NodeKind.IMPORT, _node_text(dn, self.source), node, signature=import_text)
            return

        # Go: import_spec_list
        if self.language == "go":
            spec_list = next((c for c in node.named_children if c.type == "import_spec_list"), None)
            specs = spec_list.named_children if spec_list else [c for c in node.named_children if c.type == "import_spec"]
            for s in specs:
                if s.type != "import_spec":
                    continue
                sl = next((c for c in s.named_children if c.type == "interpreted_string_literal"), None)
                if sl:
                    path = _node_text(sl, self.source).strip("\"'")
                    self._create_node(NodeKind.IMPORT, path, s, signature=_node_text(s, self.source).strip())
            return

        # fallback
        self._create_node(NodeKind.IMPORT, import_text, node, signature=import_text)

    # ── 调用 ─────────────────────────────────────────────

    def _collect_call(self, node: SyntaxNode):
        if not self.node_stack:
            return
        caller_id = self.node_stack[-1]
        ex = self.ex

        # 语言特定 callee 提取
        if ex.resolve_callee:
            callee = ex.resolve_callee(node, self.source_str)
            if callee:
                self.unresolved_refs.append(UnresolvedReference(
                    from_node_id=caller_id, reference_name=callee,
                    reference_kind=EdgeKind.CALLS,
                    line=node.start_point[0] + 1, col=node.start_point[1],
                    file_path=self.file_path, language=self.language,
                ))
                return

        callee_name = ""
        name_field = _child_by_field(node, "name")
        obj_field = _child_by_field(node, "object") or _child_by_field(node, "scope")

        # Java method_invocation: object + name
        if name_field and obj_field and node.type == "method_invocation":
            method = _node_text(name_field, self.source)
            receiver = _node_text(obj_field, self.source).lstrip("$")
            skip = {"self", "this", "cls", "super", "parent", "static"}
            callee_name = method if receiver in skip else f"{receiver}.{method}"

        # PHP member_call_expression
        elif name_field and obj_field and node.type in ("member_call_expression", "scoped_call_expression"):
            method = _node_text(name_field, self.source)
            receiver = _node_text(obj_field, self.source).lstrip("$")
            skip = {"self", "this", "parent", "static"}
            callee_name = method if receiver in skip else f"{receiver}.{method}"

        else:
            func = _child_by_field(node, "function") or node.named_child(0)
            if func:
                if func.type in ("member_expression", "attribute", "selector_expression",
                                 "navigation_expression", "field_expression"):
                    prop = _child_by_field(func, "property") or _child_by_field(func, "field")
                    if not prop:
                        prop = func.named_child(1) if func.named_child_count > 1 else None
                    if prop:
                        method_name = _node_text(prop, self.source)
                        obj = (_child_by_field(func, "object") or
                               _child_by_field(func, "operand") or
                               _child_by_field(func, "argument") or
                               func.named_child(0))
                        receiver = _node_text(obj, self.source) if obj else ""
                        skip = {"self", "this", "cls", "super"}
                        callee_name = method_name if receiver in skip else f"{receiver}.{method_name}"
                elif func.type in ("scoped_identifier",):
                    callee_name = _node_text(func, self.source)
                else:
                    callee_name = _node_text(func, self.source)

        if callee_name:
            self.unresolved_refs.append(UnresolvedReference(
                from_node_id=caller_id, reference_name=callee_name,
                reference_kind=EdgeKind.CALLS,
                line=node.start_point[0] + 1, col=node.start_point[1],
                file_path=self.file_path, language=self.language,
            ))

    # ── 实例化 ───────────────────────────────────────────

    def _collect_instantiation(self, node: SyntaxNode):
        if not self.node_stack:
            return
        caller_id = self.node_stack[-1]

        ctor = (_child_by_field(node, "constructor") or
                _child_by_field(node, "type") or
                _child_by_field(node, "name") or
                node.named_child(0))
        if not ctor:
            return
        class_name = _node_text(ctor, self.source)
        lt = class_name.find("<")
        if lt > 0:
            class_name = class_name[:lt]
        # 去掉命名空间前缀，只保留类名
        last_dot = max(class_name.rfind("."), class_name.rfind("::"))
        if last_dot >= 0:
            class_name = class_name[last_dot + 1:]
        class_name = class_name.strip()
        if class_name:
            self.unresolved_refs.append(UnresolvedReference(
                from_node_id=caller_id, reference_name=class_name,
                reference_kind=EdgeKind.INSTANTIATES,
                line=node.start_point[0] + 1, col=node.start_point[1],
                file_path=self.file_path, language=self.language,
            ))

    # ── 继承 ─────────────────────────────────────────────

    def _extract_inheritance(self, node: SyntaxNode, class_id: str):
        for child in node.named_children:
            if not child:
                continue

            # extends_clause / class_heritage / base_class_clause / superclass
            if child.type in ("extends_clause", "class_heritage", "superclass", "base_clause", "extends_interfaces"):
                type_list = next((c for c in child.named_children if c.type == "type_list"), None)
                targets = type_list.named_children if type_list else [child.named_child(0)]
                kind = EdgeKind.EXTENDS if child.type != "extends_interfaces" else EdgeKind.EXTENDS
                for t in targets:
                    if t:
                        self._add_inheritance_ref(class_id, t, EdgeKind.EXTENDS)

            # C++ base_class_clause
            if child.type == "base_class_clause":
                for t in child.named_children:
                    if t and t.type in ("type_identifier", "qualified_identifier", "template_type"):
                        self._add_inheritance_ref(class_id, t, EdgeKind.EXTENDS)

            # implements_clause / super_interfaces / interfaces
            if child.type in ("implements_clause", "class_interface_clause", "super_interfaces", "interfaces"):
                type_list = next((c for c in child.named_children if c.type == "type_list"), None)
                targets = type_list.named_children if type_list else child.named_children
                for t in targets:
                    if t:
                        self._add_inheritance_ref(class_id, t, EdgeKind.IMPLEMENTS)

            # Python: class Foo(Base1, Base2)
            if child.type == "argument_list" and node.type == "class_definition":
                for arg in child.named_children:
                    if arg.type in ("identifier", "attribute"):
                        self._add_inheritance_ref(class_id, arg, EdgeKind.EXTENDS)

            # Rust trait bounds
            if child.type == "trait_bounds":
                for bound in child.named_children:
                    name_node = None
                    if bound.type == "type_identifier":
                        name_node = bound
                    elif bound.type == "generic_type":
                        name_node = next((c for c in bound.named_children if c.type == "type_identifier"), None)
                    if name_node:
                        self._add_inheritance_ref(class_id, name_node, EdgeKind.EXTENDS)

            # C# base_list
            if child.type == "base_list":
                for base in child.named_children:
                    if base:
                        self._add_inheritance_ref(class_id, base, EdgeKind.EXTENDS)

            # Kotlin delegation_specifier
            if child.type == "delegation_specifier":
                ut = next((c for c in child.named_children if c.type == "user_type"), None)
                tid = None
                if ut:
                    tid = next((c for c in ut.named_children if c.type == "type_identifier"), ut)
                if tid:
                    self._add_inheritance_ref(class_id, tid, EdgeKind.EXTENDS)

            # Swift inheritance_specifier
            if child.type == "inheritance_specifier":
                ut = next((c for c in child.named_children if c.type == "user_type"), None)
                if ut:
                    tid = next((c for c in ut.named_children if c.type == "type_identifier"), None)
                    if tid:
                        self._add_inheritance_ref(class_id, tid, EdgeKind.EXTENDS)

            # Go struct embedding: field_declaration without field_identifier
            if child.type == "field_declaration":
                has_fid = any(c.type == "field_identifier" for c in child.named_children)
                if not has_fid:
                    tid = next((c for c in child.named_children if c.type == "type_identifier"), None)
                    if tid:
                        self._add_inheritance_ref(class_id, tid, EdgeKind.EXTENDS)

            # Go interface embedding
            if child.type == "constraint_elem":
                tid = next((c for c in child.named_children if c.type == "type_identifier"), None)
                if tid:
                    self._add_inheritance_ref(class_id, tid, EdgeKind.EXTENDS)

            # JavaScript class_heritage → identifier
            if (child.type in ("identifier", "type_identifier") and node.type == "class_heritage"):
                self._add_inheritance_ref(class_id, child, EdgeKind.EXTENDS)

            # 递归进入容器节点
            if child.type in ("field_declaration_list", "class_heritage"):
                self._extract_inheritance(child, class_id)

    def _add_inheritance_ref(self, class_id: str, node: SyntaxNode, kind: EdgeKind):
        name = _node_text(node, self.source)
        # 去泛型
        lt = name.find("<")
        if lt > 0:
            name = name[:lt]
        if name:
            self.unresolved_refs.append(UnresolvedReference(
                from_node_id=class_id, reference_name=name,
                reference_kind=kind,
                line=node.start_point[0] + 1, col=node.start_point[1],
                file_path=self.file_path, language=self.language,
            ))

    # ── Rust impl ────────────────────────────────────────

    def _extract_rust_impl(self, node: SyntaxNode):
        has_for = any(not c.is_named and c.type == "for" for c in node.children) if hasattr(node, 'children') else False
        if not has_for:
            return
        type_ids = [c for c in node.named_children if c.type in ("type_identifier", "generic_type", "scoped_type_identifier")]
        if len(type_ids) < 2:
            return
        trait_node = type_ids[0]
        type_node = type_ids[-1]
        self._add_inheritance_ref(type_node.id if hasattr(type_node, 'id') else "", type_node, EdgeKind.IMPLEMENTS)

    # ── 装饰器 ───────────────────────────────────────────

    def _extract_decorators(self, decl_node: SyntaxNode, decorated_id: str):
        deco_types = {"decorator", "annotation", "marker_annotation"}

        # 直接子节点
        for c in decl_node.named_children:
            if c and c.type in deco_types:
                name = self._resolve_decorator_name(c)
                if name:
                    self.unresolved_refs.append(UnresolvedReference(
                        from_node_id=decorated_id, reference_name=name,
                        reference_kind=EdgeKind.DECORATES,
                        line=c.start_point[0] + 1, col=c.start_point[1],
                        file_path=self.file_path, language=self.language,
                    ))

        # 前置兄弟节点 (TS @Foo class Bar)
        parent = decl_node.parent
        if parent:
            decl_start = decl_node.start_byte
            decl_idx = -1
            for i in range(parent.named_child_count):
                sib = parent.named_child(i)
                if sib and sib.start_byte == decl_start:
                    decl_idx = i
                    break
            if decl_idx > 0:
                for j in range(decl_idx - 1, -1, -1):
                    sib = parent.named_child(j)
                    if not sib or sib.type not in deco_types:
                        break
                    name = self._resolve_decorator_name(sib)
                    if name:
                        self.unresolved_refs.append(UnresolvedReference(
                            from_node_id=decorated_id, reference_name=name,
                            reference_kind=EdgeKind.DECORATES,
                            line=sib.start_point[0] + 1, col=sib.start_point[1],
                            file_path=self.file_path, language=self.language,
                        ))

    def _resolve_decorator_name(self, node: SyntaxNode) -> Optional[str]:
        for c in node.named_children:
            if not c:
                continue
            if c.type == "call_expression":
                fn = _child_by_field(c, "function") or c.named_child(0)
                if fn:
                    return _node_text(fn, self.source)
            if c.type in ("identifier", "member_expression", "scoped_identifier", "navigation_expression"):
                name = _node_text(c, self.source)
                ld = max(name.rfind("."), name.rfind("::"))
                return name[ld + 1:] if ld >= 0 else name
        return None

    # ── 类型注解 ─────────────────────────────────────────

    def _extract_type_annotations(self, node: SyntaxNode, owner_id: str):
        """对参数类型和返回类型中引用的标识符创建 type_of/returns 引用"""
        # 参数
        params = _child_by_field(node, self.ex.params_field)
        if params:
            for t_node in self._walk_type_nodes(params):
                if t_node.type in _TYPE_IDENTIFIER_NODES:
                    self.unresolved_refs.append(UnresolvedReference(
                        from_node_id=owner_id, reference_name=_node_text(t_node, self.source),
                        reference_kind=EdgeKind.TYPE_OF,
                        line=t_node.start_point[0] + 1, col=t_node.start_point[1],
                        file_path=self.file_path, language=self.language,
                    ))

        # 返回类型
        if self.ex.return_field:
            ret = _child_by_field(node, self.ex.return_field)
            if ret:
                for t_node in self._walk_type_nodes(ret):
                    if t_node.type in _TYPE_IDENTIFIER_NODES:
                        self.unresolved_refs.append(UnresolvedReference(
                            from_node_id=owner_id, reference_name=_node_text(t_node, self.source),
                            reference_kind=EdgeKind.RETURNS,
                            line=t_node.start_point[0] + 1, col=t_node.start_point[1],
                            file_path=self.file_path, language=self.language,
                        ))

    def _walk_type_nodes(self, node: SyntaxNode):
        """遍历类型子树中的所有标识符节点"""
        result = []
        stack = [node]
        while stack:
            n = stack.pop()
            if n.type in _TYPE_IDENTIFIER_NODES:
                result.append(n)
            for i in range(n.named_child_count):
                c = n.named_child(i)
                if c:
                    stack.append(c)
        return result

    # ── 辅助方法 ─────────────────────────────────────────

    def _extract_name(self, node: SyntaxNode, field: str) -> Optional[str]:
        """通用名称提取"""
        if self.ex.extract_name:
            hn = self.ex.extract_name(node, self.source_str)
            if hn:
                return hn

        name_node = _child_by_field(node, field)
        if name_node:
            # C/C++ 指针声明器解包
            resolved = name_node
            while resolved and resolved.type == "pointer_declarator":
                inner = _child_by_field(resolved, "declarator") or resolved.named_child(0)
                if not inner:
                    break
                resolved = inner
            if resolved and resolved.type in ("function_declarator", "field_declarator"):
                inner = _child_by_field(resolved, "declarator") or resolved.named_child(0)
                return _node_text(inner, self.source) if inner else _node_text(resolved, self.source)
            # Lua dot/method index
            if resolved and resolved.type in ("dot_index_expression", "method_index_expression"):
                f = _child_by_field(resolved, "field") or _child_by_field(resolved, "method")
                if f:
                    return _node_text(f, self.source)
            return _node_text(resolved, self.source)

        # fallback: 第一个 identifier 子节点
        for i in range(node.named_child_count):
            c = node.named_child(i)
            if c and c.type in ("identifier", "type_identifier", "simple_identifier", "constant"):
                return _node_text(c, self.source)

        return "<anonymous>"

    def _resolve_body(self, node: SyntaxNode) -> Optional[SyntaxNode]:
        if self.ex.resolve_body:
            return self.ex.resolve_body(node, self.ex.body_field)
        return _child_by_field(node, self.ex.body_field)

    def _visit_function_body(self, body: SyntaxNode):
        """访问函数体 —— 只提取调用和结构节点"""
        ex = self.ex

        def _walk(n: SyntaxNode):
            if n.type in ex.call_types:
                self._collect_call(n)
            elif n.type in ex.instantiation_types or n.type in _INSTANTIATION_NODES:
                self._collect_instantiation(n)
            elif ex.extract_bare_call:
                cn = ex.extract_bare_call(n, self.source_str)
                if cn and self.node_stack:
                    self.unresolved_refs.append(UnresolvedReference(
                        from_node_id=self.node_stack[-1], reference_name=cn,
                        reference_kind=EdgeKind.CALLS,
                        line=n.start_point[0] + 1, col=n.start_point[1],
                        file_path=self.file_path, language=self.language,
                    ))
            # 嵌套命名函数
            if n.type in ex.function_types:
                nn = self._extract_name(n, ex.name_field)
                if nn and nn != "<anonymous>":
                    self._extract_function(n)
                    return
            for i in range(n.named_child_count):
                c = n.named_child(i)
                if c:
                    _walk(c)

        _walk(body)
