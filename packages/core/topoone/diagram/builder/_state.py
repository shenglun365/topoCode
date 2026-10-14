from typing import Any

from ._segments import header_segment, title_segment, comment_segment


def _render_states(states: list[dict], indent: int = 1) -> list[str]:
    pad = "    " * indent
    lines: list[str] = []
    for s in states:
        sid = s.get("id", "")
        text = s.get("text", sid)
        children = s.get("children") or []
        if children:
            lines.append(f"{pad}state {sid} {{")
            # Start marker inside composite
            lines += _render_states(children, indent + 1)
            lines.append(f"{pad}}}")
        else:
            if text != sid:
                lines.append(f'{pad}state "{text}" as {sid}')
            else:
                lines.append(f"{pad}state {sid}")
    return lines


def _render_transitions(transitions: list[dict], indent: int = 1) -> list[str]:
    pad = "    " * indent
    lines: list[str] = []
    for t in transitions:
        frm = t.get("from", "")
        to = t.get("to", "")
        label = t.get("label", "")
        if label:
            lines.append(f"{pad}{frm} --> {to} : {label}")
        else:
            lines.append(f"{pad}{frm} --> {to}")
    return lines


def build_state(ir: dict) -> str:
    segments: list[str] = []
    segments += header_segment("state")
    segments += title_segment(ir.get("title", ""))
    segments += comment_segment(ir.get("comments"))
    segments += _render_states(ir.get("states") or [])
    segments += _render_transitions(ir.get("transitions") or [])
    return "\n".join(segments)
