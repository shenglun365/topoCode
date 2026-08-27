from typing import Any

from ._segments import comment_segment


def build_pie(ir: dict) -> str:
    segments: list[str] = []
    segments.append("pie")
    segments += comment_segment(ir.get("comments"))

    title = ir.get("title", "")
    if title:
        segments.append(f"    title {title}")

    for item in ir.get("items", []):
        label = item.get("label", "")
        value = item.get("value", 0)
        segments.append(f'    "{label}" : {value}')

    return "\n".join(segments)
