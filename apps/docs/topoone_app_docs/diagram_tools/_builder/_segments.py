import re
from typing import Any


def safe_id(raw: str) -> str:
    safe = raw.replace(" ", "_").replace("-", "_").replace(".", "_")
    safe = re.sub(r'[^a-zA-Z0-9_\u4e00-\u9fff]', '_', safe)
    if safe and safe[0].isdigit():
        safe = "n" + safe
    return safe if safe else "node"


def serialize_styles(styles: dict) -> str:
    return ",".join(f"{k}:{v}" for k, v in styles.items())


_SHAPE_SYMS = {
    "rect": ("[", "]"),
    "round": ("(", ")"),
    "stadium": ("([", "])"),
    "diamond": ("{", "}"),
    "circle": ("((", "))"),
    "asymmetric": (">", "]"),
    "hexagon": ("{{", "}}"),
    "parallelogram": ("[/", "/]"),
    "trapezoid": ("[\\", "\\]"),
}

_EDGE_SYMS = {
    "arrow": "-->",
    "thick": "==>",
    "dotted": "-.->",
    "line": "---",
    "cross": "--x",
    "circle": "--o",
    "double": "<-->",
    "thick_double": "<==>",
}

_EDGE_START_MARKERS = {
    "circle": "o",
    "cross": "x",
    "arrow": ">",
    "none": "",
}

_EDGE_END_MARKERS = {
    "circle": "o",
    "cross": "x",
    "arrow": ">",
    "none": "",
}


# ── Mermaid segments ──

def config_segment(init_config: dict | None) -> list[str]:
    if not init_config:
        return []
    theme = init_config.get("theme", "")
    tv = init_config.get("themeVariables") or {}
    parts = []
    if theme:
        parts.append(f"theme: {theme}")
    if tv:
        tv_strs = [f"{k}: {v}" for k, v in tv.items()]
        parts.append(f"themeVariables: {{{{{','.join(tv_strs)}}}}}")
    if parts:
        return [f"%%{{init: {{'config': {{{', '.join(parts)}}}}}}}%%"]
    return []


_HEADERS = {
    "flowchart": "flowchart {direction}",
    "graph": "flowchart {direction}",
    "sequence": "sequenceDiagram",
    "class": "classDiagram",
    "state": "stateDiagram-v2",
    "er": "erDiagram",
}

def header_segment(diagram_type: str, direction: str = "TB") -> list[str]:
    fmt = _HEADERS.get(diagram_type)
    if fmt:
        return [fmt.format(direction=direction)]
    return [f"graph {direction}"]


def title_segment(title: str) -> list[str]:
    if title:
        return [f"    title {title}"]
    return []


def comment_segment(comments: list[str] | None) -> list[str]:
    if not comments:
        return []
    return [f"    %% {c}" for c in comments]


_SUBGRAPH_ID_COUNTER: int = 0

def subgraph_open_segment(title: str, direction: str | None = None, indent: int = 1) -> list[str]:
    global _SUBGRAPH_ID_COUNTER
    _SUBGRAPH_ID_COUNTER += 1
    safe = f"sg_{_SUBGRAPH_ID_COUNTER}"
    pad = "    " * indent
    lines = [f'{pad}subgraph {safe}["{title}"]']
    if direction:
        lines.append(f"{pad}    direction {direction}")
    return lines


def subgraph_close_segment(indent: int = 1) -> list[str]:
    return ["    " * indent + "end"]


def node_segment(nid: str, text: str, shape: str = "rect", styles: dict | None = None,
                 classes: list[str] | None = None, click: dict | None = None,
                 indent: int = 1) -> list[str]:
    pad = "    " * indent
    sid = safe_id(nid)
    l, r = _SHAPE_SYMS.get(shape, _SHAPE_SYMS["rect"])
    lines = [f"{pad}{sid}{l}{text}{r}"]
    if styles:
        lines.append(f"{pad}style {sid} {serialize_styles(styles)}")
    if classes:
        lines.append(f"{pad}class {sid} {' '.join(classes)}")
    if click:
        url = click.get("url", "")
        tooltip = click.get("tooltip", "")
        if url:
            lines.append(f"{pad}click {sid} \"{url}\" \"{tooltip}\"" if tooltip else f"{pad}click {sid} \"{url}\"")
    return lines


def edge_segment(from_id: str, to_id: str, label: str = "",
                 style: str = "arrow",
                 markers: dict | None = None,
                 indent: int = 1) -> list[str]:
    pad = "    " * indent
    frm = safe_id(from_id)
    to = safe_id(to_id)
    sym = _EDGE_SYMS.get(style, "-->")
    if label:
        return [f"{pad}{frm} {sym}|{label}| {to}"]
    return [f"{pad}{frm} {sym} {to}"]


def class_def_segment(class_defs: list[dict] | None) -> list[str]:
    if not class_defs:
        return []
    lines = []
    for cd in class_defs:
        name = cd.get("name", "")
        styles = cd.get("styles", {})
        if name and styles:
            lines.append(f"    classDef {name} {serialize_styles(styles)}")
    return lines


# ── PlantUML segments ──

def pu_header_segment() -> list[str]:
    return ["@startuml"]


def pu_footer_segment() -> list[str]:
    return ["@enduml"]


def pu_comment_segment(comments: list[str] | None) -> list[str]:
    if not comments:
        return []
    return [f"' {c}" for c in comments]


def pu_component_segment(nid: str, text: str, styles: dict | None = None) -> list[str]:
    sid = safe_id(nid)
    fill = (styles or {}).get("fill", "").lstrip("#")
    if fill:
        return [f'component "{text}" as {sid} #{fill}']
    return [f'component "{text}" as {sid}']


def pu_actor_segment(name: str, alias: str = "") -> list[str]:
    if alias and alias != name:
        return [f"actor {name} as {alias}"]
    return [f"actor {name}"]


def pu_participant_segment(name: str, alias: str = "") -> list[str]:
    if alias and alias != name:
        return [f"participant {name} as {alias}"]
    return [f"participant {name}"]


def pu_edge_segment(from_id: str, to_id: str, label: str = "") -> list[str]:
    frm = safe_id(from_id)
    to = safe_id(to_id)
    if label:
        return [f"{frm} --> {to} : {label}"]
    return [f"{frm} --> {to}"]


def pu_note_segment(position: str, text: str, target: str = "") -> list[str]:
    if target:
        return [f"note {position} of {target}\n  {text}\nend note"]
    return [f"note {position}\n  {text}\nend note"]


def pu_component_header(title: str) -> list[str]:
    return [f"package \"{title}\" {{"]


def pu_component_footer() -> list[str]:
    return ["}"]
