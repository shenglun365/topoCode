"""统一 Symbol 模型 — 在 parse_file() 和后续 Step 之间共享的内存结构

新流程:
  parse_file() → Query 引擎 → Symbol/Reference 列表 (内存)
       ↓
  resolve_scopes() → 文件内引用绑定 (内存)
       ↓
  persist() → 批量写入 base_node + graph_node (SQL)
       ↓
  Step 2/3/4 → 直接读取 graph_node
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SymbolKind(Enum):
    """符号种类"""
    FUNCTION = "function"
    METHOD = "method"
    CLASS = "class"
    VARIABLE = "variable"
    PARAMETER = "parameter"
    INTERFACE = "interface"
    TYPE_ALIAS = "type_alias"
    ENUM = "enum"
    MODULE = "module"
    CONSTRUCTOR = "constructor"
    PROPERTY = "property"


class RefKind(Enum):
    """引用种类"""
    CALL = "call"           # foo()
    MEMBER = "member"       # obj.prop
    IMPORT = "import"       # import / require
    TYPE_REF = "type_ref"   # Type annotation reference
    IDENT = "ident"         # Generic identifier
    NEW = "new"             # new Foo()
    ASSIGN = "assign"       # x = value
    RETURN = "return"       # return value


@dataclass
class SourceLocation:
    """源码位置"""
    file_path: str
    start_byte: int
    end_byte: int
    start_line: int
    start_col: int
    end_line: int
    end_col: int


@dataclass
class Symbol:
    """统一符号定义模型"""
    name: str
    kind: SymbolKind
    location: SourceLocation
    scope: str                          # "module", "class.Foo", "class.Foo.method.bar"
    is_definition: bool = True
    doc_comment: Optional[str] = None   # 关联的 JSDoc/docstring
    signature: Optional[str] = None     # JSON: params + return type
    parent_name: Optional[str] = None   # 父符号名 (如类的完整限定名)


@dataclass
class Reference:
    """统一引用模型"""
    name: str
    kind: RefKind
    location: SourceLocation           # 引用发生位置
    scope: str                         # 引用所在作用域
    target: Optional[str] = None       # 解析后的目标符号全限定名 (if resolved)


@dataclass
class ImportRecord:
    """导入记录"""
    module: str                        # 模块路径, e.g. "./utils/helper"
    imported_names: list[str]          # 导入的符号名, e.g. ["Helper", "formatTime"]
    is_default: bool = False           # 是否为默认导入
    is_namespace: bool = False         # 是否为命名空间导入 (import * as)
    alias: Optional[str] = None        # 别名
    resolved_file: Optional[str] = None  # 解析后的文件路径
    location: Optional[SourceLocation] = None


@dataclass
class FileSymbolTable:
    """单文件符号表 — 所有分析结果的统一容器"""
    file_path: str
    language: str
    symbols: list[Symbol] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    imports: list[ImportRecord] = field(default_factory=list)
    exports: list[str] = field(default_factory=list)    # 对外暴露的符号名

    def add_symbol(self, symbol: Symbol):
        self.symbols.append(symbol)

    def add_reference(self, ref: Reference):
        self.references.append(ref)

    def add_import(self, imp: ImportRecord):
        self.imports.append(imp)

    def get_symbol(self, name: str, scope: str = "") -> Optional[Symbol]:
        """在当前文件的指定作用域中查找符号"""
        for s in self.symbols:
            if s.name == name:
                if not scope or s.scope == scope:
                    return s
        return None

    def symbols_by_kind(self, kind: SymbolKind) -> list[Symbol]:
        return [s for s in self.symbols if s.kind == kind]

    def top_level_symbols(self) -> list[Symbol]:
        """返回顶层符号 (scope == "module")"""
        return [s for s in self.symbols if s.scope == "module"]
