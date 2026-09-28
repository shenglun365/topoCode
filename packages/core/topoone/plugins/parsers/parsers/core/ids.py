"""符号/边 ID 单源生成 — 稳定身份契约(跨基线跟踪的根基)。

身份语义:
- node_id = sha256("{file_path}:{kind}:{qualified_name}")[ :16 ]，与行号无关。
  编辑只移动行号不改变符号内容时 ID 稳定；父级改名/文件移动/符号改名会改变
  ID —— 这是身份传播的语义正确行为(嵌套符号的限定路径变了)。
- 重载消歧: 同文件同 kind 同限定名(如 TS/Java overload)按源码序追加 "#N"
  (首个无后缀)。插入重载可能使后续序号位移 —— 重载签名本身即身份的一部分，
  该局限为设计内行为。
- edge_id = sha256("{source}->{target}:{kind}")[:16] —— 节点稳定则边稳定。

本模块是全仓唯一的 ID 生成点(walker/emitter/db_adapter 统一引用)，
禁止在他处内联哈希实现。
"""
from __future__ import annotations

import hashlib

_HEX_LEN = 16


def _kind_value(kind) -> str:
    return kind.value if hasattr(kind, "value") else str(kind)


def make_node_id(file_path: str, kind, qualified_name: str, ordinal: int = 1) -> str:
    """稳定符号 ID。ordinal>1 表示同名重载的源码序消歧。"""
    qn = qualified_name or ""
    if ordinal > 1:
        qn = f"{qn}#{ordinal}"
    raw = f"{file_path}:{_kind_value(kind)}:{qn}"
    return hashlib.sha256(raw.encode()).hexdigest()[:_HEX_LEN]


def make_edge_id(source: str, target: str, kind) -> str:
    """稳定边 ID(节点稳定则边稳定)。"""
    raw = f"{source}->{target}:{_kind_value(kind)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:_HEX_LEN]
