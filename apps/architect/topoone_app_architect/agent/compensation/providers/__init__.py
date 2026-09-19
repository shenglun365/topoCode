"""providers — 内置补偿 Provider 登记口(R1.1 收编 / R1.2 消费门禁依据)。

模块导入即向 GLOBAL_REGISTRY 登记五个内置 Provider(M1 收编批次);
登记序 (priority, name) 稳定, 消费清单经 registry.consumption_map() 自省。
"""
from __future__ import annotations

from ..registry import GLOBAL_REGISTRY
from .budget import BudgetTrimProvider, trim_optional_blocks
from .builtin import (ArchitectNoteProvider, CapNoteProvider,
                      ElementHintProvider, architect_note_text,
                      cap_note_section, element_hint_text)
from .milestone import MilestoneProvider, agent_note_section, milestone_section
from .output import (LogicDiagramGateProvider, StructuredOutputProvider,
                     parse_json_block, validate_logic_diagram)
from .scaffold import ScaffoldProvider
from .toolsurface import ToolSurfaceProvider

BUILTIN_PROVIDERS = (
    ArchitectNoteProvider(),
    ElementHintProvider(),
    CapNoteProvider(),
    BudgetTrimProvider(),
    MilestoneProvider(),
    ToolSurfaceProvider(),
    ScaffoldProvider(),
    StructuredOutputProvider(),
    LogicDiagramGateProvider(),
)


def register_builtin(registry=GLOBAL_REGISTRY) -> None:
    """登记内置 Provider(幂等由 registry 查重保障; 测试可传入独立实例)。"""
    for p in BUILTIN_PROVIDERS:
        registry.register(p)


register_builtin()

__all__ = [
    "ArchitectNoteProvider", "ElementHintProvider", "CapNoteProvider",
    "BudgetTrimProvider", "MilestoneProvider", "ToolSurfaceProvider",
    "ScaffoldProvider", "StructuredOutputProvider", "LogicDiagramGateProvider",
    "BUILTIN_PROVIDERS", "register_builtin", "architect_note_text",
    "element_hint_text", "cap_note_section", "milestone_section",
    "agent_note_section", "trim_optional_blocks", "parse_json_block",
    "validate_logic_diagram",
]
