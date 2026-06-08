"""LanguageExtractor — 声明式语言提取器接口 + 注册表"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional
from tree_sitter import Node as SyntaxNode

from ..core.node_types import NodeKind


@dataclass
class LanguageExtractor:
    """语言提取器 — 声明式 AST 节点类型映射 + 可选钩子函数

    核心 Walker 根据此配置将 tree-sitter AST 节点分发到对应的提取方法，
    自动处理 scope 栈、contains 边、qualified_name 构建。
    """

    # ── AST 节点类型 → 图节点类型映射 ──
    function_types: tuple[str, ...] = ()
    class_types: tuple[str, ...] = ()
    method_types: tuple[str, ...] = ()
    interface_types: tuple[str, ...] = ()
    struct_types: tuple[str, ...] = ()
    enum_types: tuple[str, ...] = ()
    enum_member_types: tuple[str, ...] = ()
    type_alias_types: tuple[str, ...] = ()
    import_types: tuple[str, ...] = ()
    call_types: tuple[str, ...] = ()
    instantiation_types: tuple[str, ...] = ()
    variable_types: tuple[str, ...] = ()
    field_types: tuple[str, ...] = ()
    property_types: tuple[str, ...] = ()
    package_types: tuple[str, ...] = ()

    # ── 字段名映射 ──
    name_field: str = "name"
    body_field: str = "body"
    params_field: str = "parameters"
    return_field: Optional[str] = None

    # ── 标志 ──
    methods_are_top_level: bool = False
    interface_kind: NodeKind = NodeKind.INTERFACE

    # ── 钩子函数 (可选) ──
    extract_name: Optional[Callable[[SyntaxNode, str], Optional[str]]] = None
    extract_signature: Optional[Callable[[SyntaxNode, str], Optional[str]]] = None
    extract_visibility: Optional[Callable[[SyntaxNode], Optional[str]]] = None
    extract_import: Optional[Callable[[SyntaxNode, str], Optional[dict]]] = None
    extract_package: Optional[Callable[[SyntaxNode, str], Optional[str]]] = None
    extract_receiver: Optional[Callable[[SyntaxNode, str], Optional[str]]] = None
    classify_class: Optional[Callable[[SyntaxNode], str]] = None
    is_exported: Optional[Callable[[SyntaxNode, str], bool]] = None
    is_async: Optional[Callable[[SyntaxNode], bool]] = None
    is_static: Optional[Callable[[SyntaxNode], bool]] = None
    is_const: Optional[Callable[[SyntaxNode], bool]] = None
    resolve_type_alias_kind: Optional[Callable[[SyntaxNode, str], Optional[NodeKind]]] = None
    resolve_body: Optional[Callable[[SyntaxNode, str], Optional[SyntaxNode]]] = None
    is_misparsed_function: Optional[Callable[[str, SyntaxNode], bool]] = None
    extract_bare_call: Optional[Callable[[SyntaxNode, str], Optional[str]]] = None
    resolve_callee: Optional[Callable[[SyntaxNode, str], Optional[str]]] = None


# ── 注册表 ──────────────────────────────────────────────

from .python import PYTHON
from .javascript import JAVASCRIPT
from .typescript import TYPESCRIPT
from .java import JAVA
from .c import C
from .cpp import CPP
from .go import GO
from .rust import RUST
from .csharp import CSHARP
from .swift import SWIFT
from .ruby import RUBY
from .kotlin import KOTLIN
from .php import PHP
from .dart import DART
from .scala import SCALA
from .lua import LUA
from .objc import OBJC

EXTRACTORS: dict[str, LanguageExtractor] = {
    "python":     PYTHON,
    "javascript": JAVASCRIPT,
    "jsx":        JAVASCRIPT,
    "typescript": TYPESCRIPT,
    "tsx":        TYPESCRIPT,
    "java":       JAVA,
    "c":          C,
    "c_header":   C,
    "cpp":        CPP,
    "cpp_header": CPP,
    "go":         GO,
    "rust":       RUST,
    "c_sharp":    CSHARP,
    "swift":      SWIFT,
    "ruby":       RUBY,
    "kotlin":     KOTLIN,
    "php":        PHP,
    "dart":       DART,
    "scala":      SCALA,
    "lua":        LUA,
    "luau":       LUA,
    "objc":       OBJC,
}
