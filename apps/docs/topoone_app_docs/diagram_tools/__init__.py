"""Diagram tools facade.

IR 建图内核已迁入 core（topoone.diagram：builder/compat/_ir_schema/validation），
本包仅保留 docs 服务专属部分（代码语法校验 _validator、代码→IR _parser、
图编辑子代理 _subagent），并在此重导出 core 符号以兼容既有相对导入。
"""

from topoone.diagram._ir_schema import (
    validate_ir,
    IR_SCHEMA_FLOWCHART,
    IR_SCHEMA_SEQUENCE,
    IR_SCHEMA_CLASS,
    ir_schema_for_type,
)
from topoone.diagram.builder import build_from_ir
from ._validator import validate_diagram_syntax
from ._parser import parse_to_ir
from ._subagent import (
    create_subagent_session,
    get_subagent_session,
    apply_change,
    commit_to_main,
    discard_subagent_session,
)

__all__ = [
    "validate_ir",
    "IR_SCHEMA_FLOWCHART",
    "IR_SCHEMA_SEQUENCE",
    "IR_SCHEMA_CLASS",
    "ir_schema_for_type",
    "validate_diagram_syntax",
    "parse_to_ir",
    "build_from_ir",
    "create_subagent_session",
    "get_subagent_session",
    "apply_change",
    "commit_to_main",
    "discard_subagent_session",
]
