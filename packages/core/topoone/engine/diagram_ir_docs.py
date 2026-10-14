"""Deprecated shim -> topoone.diagram.prompts (unified DiagramSchema IR docs).

Moved in the diagram-kernel integration (Phase 1). The LLM prompt now describes
the single IR (DiagramSchema); legacy per-type IR doc functions are gone. Keep
importing this module only for backward compatibility; new code should import
``topoone.diagram.prompts`` directly.
"""

from topoone.diagram.prompts import (
    animation_docs,
    activity_docs,
    class_docs,
    constraints_docs,
    diagram_editor_prompt,
    er_docs,
    flowchart_example_docs,
    gantt_docs,
    overview_docs,
    pie_docs,
    sequence_docs,
    state_docs,
)

__all__ = [
    "diagram_editor_prompt",
    "overview_docs",
    "sequence_docs",
    "state_docs",
    "class_docs",
    "er_docs",
    "gantt_docs",
    "pie_docs",
    "activity_docs",
    "flowchart_example_docs",
    "animation_docs",
    "constraints_docs",
]
