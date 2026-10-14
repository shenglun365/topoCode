from typing import Any

from ._segments import comment_segment


def build_gantt(ir: dict) -> str:
    segments: list[str] = []
    segments.append("gantt")
    segments += comment_segment(ir.get("comments"))

    title = ir.get("title", "")
    if title:
        segments.append(f"    title {title}")

    date_format = ir.get("date_format", "")
    if date_format:
        segments.append(f"    dateFormat {date_format}")

    axis_format = ir.get("axis_format", "")
    if axis_format:
        segments.append(f"    axisFormat {axis_format}")

    for sect in ir.get("sections", []):
        sname = sect.get("name", "")
        segments.append(f"    section {sname}")
        for task in sect.get("tasks", []):
            tname = task.get("name", "")
            start = task.get("start", "")
            duration = task.get("duration", "")
            status = task.get("status", "")
            if status:
                segments.append(f"        {tname} : {status}, {start}, {duration}")
            else:
                segments.append(f"        {tname} : {start}, {duration}")

    return "\n".join(segments)
