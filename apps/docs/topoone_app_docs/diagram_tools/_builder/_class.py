from typing import Any

from ._segments import (
    header_segment,
    title_segment,
    comment_segment,
    safe_id,
)

_REL_SYMS = {
    "extension": "<|--",
    "composition": "*--",
    "aggregation": "o--",
    "association": "-->",
    "dependency": "..>",
    "realization": "<|..",
}


def build_class_diagram(ir: dict) -> str:
    segments: list[str] = []

    segments += header_segment("class")
    segments += title_segment(ir.get("title", ""))
    segments += comment_segment(ir.get("comments"))

    namespace_map: dict[str, list[dict]] = {}
    standalone: list[dict] = []
    for cls in ir.get("classes", []):
        ns = cls.get("namespace", "")
        if ns:
            namespace_map.setdefault(ns, []).append(cls)
        else:
            standalone.append(cls)

    for cls in standalone:
        segments += _class_body_segment(cls, indent=1)

    for ns_name, ns_classes in namespace_map.items():
        segments.append(f"    namespace {ns_name} {{")
        for cls in ns_classes:
            segments += _class_body_segment(cls, indent=2)
        segments.append("    }")

    for r in ir.get("relations", []):
        frm = safe_id(r.get("from", ""))
        to = safe_id(r.get("to", ""))
        sym = _REL_SYMS.get(r.get("type", "association"), "-->")
        label = r.get("label", "")
        if label:
            segments.append(f"    {frm} {sym} {to} : {label}")
        else:
            segments.append(f"    {frm} {sym} {to}")

    return "\n".join(segments)


def _class_body_segment(cls: dict, indent: int = 1) -> list[str]:
    pad = "    " * indent
    name = safe_id(cls["name"])
    stereotype = cls.get("stereotype", "")
    members = cls.get("members") or []
    has_body = bool(members or stereotype)
    lines: list[str] = []
    if has_body:
        lines.append(f"{pad}class {name} {{")
        if stereotype:
            lines.append(f"{pad}    {stereotype}")
        for m in members:
            parts = []
            if m.get("is_static"):
                parts.append("{static}")
            if m.get("is_abstract"):
                parts.append("{abstract}")
            parts.append(m.get("visibility", "+"))
            parts.append(m.get("name", ""))
            if m.get("is_method"):
                parts.append(f"({m.get('params', '')})")
            if m.get("type"):
                parts.append(f" : {m['type']}")
            line = "".join(parts).strip()
            if line:
                lines.append(f"{pad}    {line}")
        lines.append(f"{pad}}}")
    else:
        lines.append(f"{pad}class {name}")
    return lines
