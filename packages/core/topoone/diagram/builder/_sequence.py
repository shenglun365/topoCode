from typing import Any

from ._segments import (
    header_segment,
    title_segment,
    comment_segment,
    safe_id,
)

_ARROW_MAP = {
    "->": "->",
    "-->": "-->",
    "->>": "->>",
    "-->>": "-->>",
    "-x": "-x",
    "--x": "--x",
}


def build_sequence(ir: dict) -> str:
    segments: list[str] = []

    segments += header_segment("sequence")
    segments += title_segment(ir.get("title", ""))
    segments += comment_segment(ir.get("comments"))

    participants = ir.get("participants") or []
    seen: set[str] = set()
    for p in participants:
        name = p.get("name", "")
        alias = p.get("alias", name)
        ptype = p.get("type", "participant")
        if alias in seen:
            continue
        seen.add(alias)
        if alias == name:
            segments.append(f"    {ptype} {name}")
        else:
            segments.append(f"    {ptype} {name} as {alias}")

    if participants:
        segments.append("")

    for m in ir.get("messages", []):
        frm = m.get("from", "")
        to = m.get("to", "")
        arrow = _ARROW_MAP.get(m.get("arrow", "->>"), "->>")
        label = m.get("label", "")
        if label:
            segments.append(f"    {frm} {arrow} {to} : {label}")
        else:
            segments.append(f"    {frm} {arrow} {to}")

    return "\n".join(segments)
