from typing import Any

from ._flowchart import build_flowchart
from ._sequence import build_sequence
from ._class import build_class_diagram
from ._state import build_state
from ._er import build_er
from ._gantt import build_gantt
from ._pie import build_pie
from ._plantuml import build_pu_component, build_pu_sequence

_MERMAID_BUILDERS = {
    "flowchart": build_flowchart,
    "sequence": build_sequence,
    "class": build_class_diagram,
    "state": build_state,
    "er": build_er,
    "gantt": build_gantt,
    "pie": build_pie,
}

_PLANTUML_BUILDERS = {
    "component": build_pu_component,
    "sequence": build_pu_sequence,
    "class": build_pu_component,
}

_TYPE_ALIASES = {
    "graph": "flowchart",
    "graph_tb": "flowchart",
    "graph_lr": "flowchart",
    "graph_rl": "flowchart",
    "graph_bt": "flowchart",
    "flow": "flowchart",
    "seq": "sequence",
    "sequence_diagram": "sequence",
    "class_diagram": "class",
    "classDiagram": "class",
    "class": "class",
    "state_diagram": "state",
    "statediagram": "state",
    "stateDiagram": "state",
    "er_diagram": "er",
    "erDiagram": "er",
    "gantt": "gantt",
    "pie": "pie",
}

_PU_TYPE_ALIASES = {
    "flowchart": "component",
    "graph": "component",
    "component_diagram": "component",
    "seq": "sequence",
    "sequence_diagram": "sequence",
}


def build_from_ir(ir: dict) -> dict[str, Any]:
    lang = ir.get("lang", "mermaid")

    if lang == "plantuml":
        return _build_plantuml(ir)

    diagram_type = _resolve_mermaid_type(ir)
    builder = _MERMAID_BUILDERS.get(diagram_type)
    if builder:
        try:
            code = builder(ir)
            return {"code": code, "type": f"mermaid_{diagram_type}"}
        except Exception as e:
            return {"error": f"Build failed: {e}"}

    return _fallback_rebuild(ir)


def _build_plantuml(ir: dict) -> dict[str, Any]:
    raw = ir.get("diagram_type", "") or ""
    diagram_type = _PU_TYPE_ALIASES.get(raw.strip().lower(), raw)

    if diagram_type not in _PLANTUML_BUILDERS:
        diagram_type = _infer_pu_type(ir)

    builder = _PLANTUML_BUILDERS.get(diagram_type)
    if builder:
        try:
            code = builder(ir)
            return {"code": code, "type": f"plantuml_{diagram_type}"}
        except Exception as e:
            return {"error": f"PlantUML build failed: {e}"}

    return _fallback_rebuild(ir)


def _resolve_mermaid_type(ir: dict) -> str:
    raw = ir.get("diagram_type", "") or ""
    normalized = _TYPE_ALIASES.get(raw.strip().lower(), raw)

    if not normalized or normalized not in _MERMAID_BUILDERS:
        if ir.get("participants") or ir.get("messages"):
            return "sequence"
        if ir.get("classes") or ir.get("relations"):
            return "class"
        if ir.get("nodes") or ir.get("edges"):
            return "flowchart"

    return normalized


def _infer_pu_type(ir: dict) -> str:
    if ir.get("participants") or ir.get("messages"):
        return "sequence"
    if ir.get("nodes") or ir.get("edges"):
        return "component"
    return "component"


def _fallback_rebuild(ir: dict) -> dict[str, Any]:
    lang = ir.get("lang", "mermaid")
    original_code = ir.get("_original", "")

    if original_code:
        try:
            if lang == "mermaid":
                from diagram import rebuild_mermaid
                result = rebuild_mermaid(original_code)
            elif lang == "plantuml":
                from diagram import rebuild_plantuml
                result = rebuild_plantuml(original_code)
            else:
                return {"error": f"Unknown language: {lang}", "_fallback": True}
            return {"code": result.get("code", ""), "type": result.get("type", ""), "_fallback": True}
        except Exception as e:
            return {"error": f"Fallback rebuild failed: {e}", "_fallback": True}

    return {"error": f"No builder for diagram type: {ir.get('diagram_type')}", "_fallback": True}
