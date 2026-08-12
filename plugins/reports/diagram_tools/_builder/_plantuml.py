from typing import Any

from ._segments import (
    pu_header_segment,
    pu_footer_segment,
    pu_comment_segment,
    pu_component_segment,
    pu_actor_segment,
    pu_participant_segment,
    pu_edge_segment,
    pu_component_header,
    pu_component_footer,
    safe_id,
)


def build_pu_component(ir: dict) -> str:
    segments: list[str] = []
    segments += pu_header_segment()
    segments += pu_comment_segment(ir.get("comments"))

    title = ir.get("title", "")
    if title:
        segments.append(f"title {title}")

    subgraphs = ir.get("subgraphs") or []
    subgraph_node_ids: set[str] = set()
    for sg in subgraphs:
        for nid in sg.get("nodes", []):
            subgraph_node_ids.add(nid)

    nodes_by_sg: dict[str, list[dict]] = {}
    for sg in subgraphs:
        sg_id = sg.get("id", "")
        nodes_by_sg[sg_id] = []
        for n in ir.get("nodes", []):
            if n["id"] in sg.get("nodes", []):
                nodes_by_sg[sg_id].append(n)

    standalone = [n for n in ir.get("nodes", []) if n["id"] not in subgraph_node_ids]

    for n in standalone:
        segments += pu_component_segment(
            nid=n.get("id", ""),
            text=n.get("text", ""),
            styles=n.get("styles"),
        )

    for sg in subgraphs:
        segments += pu_component_header(sg.get("title", sg.get("id", "")))
        for n in nodes_by_sg.get(sg["id"], []):
            segments += pu_component_segment(
                nid=n.get("id", ""),
                text=n.get("text", ""),
                styles=n.get("styles"),
            )
        segments += pu_component_footer()

    for e in ir.get("edges", []):
        segments += pu_edge_segment(
            from_id=e.get("from", ""),
            to_id=e.get("to", ""),
            label=e.get("label", ""),
        )

    segments += pu_footer_segment()
    return "\n".join(segments)


def build_pu_sequence(ir: dict) -> str:
    segments: list[str] = []
    segments += pu_header_segment()
    segments += pu_comment_segment(ir.get("comments"))

    title = ir.get("title", "")
    if title:
        segments.append(f"title {title}")

    participants = ir.get("participants") or []
    seen: set[str] = set()
    for p in participants:
        name = p.get("name", "")
        alias = p.get("alias", "")
        ptype = p.get("type", "participant")
        if alias in seen:
            continue
        seen.add(alias)
        if ptype == "actor":
            segments += pu_actor_segment(name, alias)
        else:
            segments += pu_participant_segment(name, alias)

    if participants:
        segments.append("")

    for m in ir.get("messages", []):
        frm = m.get("from", "")
        to = m.get("to", "")
        label = m.get("label", "")
        if label:
            segments.append(f"{frm} -> {to} : {label}")
        else:
            segments.append(f"{frm} -> {to}")

    segments += pu_footer_segment()
    return "\n".join(segments)


def build_pu_activity(ir: dict) -> str:
    """活动图(Activity Diagram)：由结构化 `flow[]` 生成 PlantUML 活动图代码。

    flow 内每个元素为线性顺序的一步：
      - {"type": "action", "text": "动作"}      → :动作;
      - {"type": "branch", "condition", "then": [steps], "else": [steps],
         "then_label"?, "else_label"?}           → if/else/endif
      - {"type": "fork", "branches": [[steps], [steps]]} → fork / fork again / end fork
      - {"type": "note", "text": "备注"}         → note right ... end note
    兼容简化写法 steps: ["动作1", "动作2"]。
    """
    segments: list[str] = []
    segments += pu_header_segment()
    segments += pu_comment_segment(ir.get("comments"))

    title = ir.get("title", "")
    if title:
        segments.append(f"title {title}")

    flow = ir.get("flow") or _activity_steps_from_ir(ir)
    segments.append("start")
    for step in flow or []:
        segments += _pu_activity_step(step, indent=0)
    segments.append("stop")

    segments += pu_footer_segment()
    return "\n".join(segments)


def _activity_steps_from_ir(ir: dict) -> list:
    """兼容 `steps: ["动作1", "动作2"]` / `[{"text": "动作"}]` 的简化 IR。"""
    steps = ir.get("steps")
    if not steps:
        return []
    out = []
    for s in steps:
        if isinstance(s, str):
            out.append({"type": "action", "text": s})
        elif isinstance(s, dict) and (s.get("text") or s.get("name")):
            out.append({"type": "action", "text": s.get("text") or s.get("name")})
    return out


def _pu_activity_step(step: dict, indent: int) -> list[str]:
    pad = "    " * indent
    if not isinstance(step, dict):
        return []
    stype = step.get("type", "action")

    if stype in ("action", "activity"):
        text = str(step.get("text", "")).strip()
        return [f"{pad}:{text};"] if text else []

    if stype == "note":
        text = str(step.get("text", "")).strip()
        return [f"{pad}note right", f"{pad}  {text}", f"{pad}end note"] if text else []

    if stype in ("branch", "if"):
        condition = str(step.get("condition", "")).strip() or "判断"
        then_label = str(step.get("then_label") or "then").strip()
        else_label = str(step.get("else_label") or "else").strip()
        lines = [f"{pad}if ({condition}) then ({then_label})"]
        for s in step.get("then") or []:
            lines += _pu_activity_step(s, indent + 1)
        lines.append(f"{pad}else ({else_label})")
        for s in step.get("else") or []:
            lines += _pu_activity_step(s, indent + 1)
        lines.append(f"{pad}endif")
        return lines

    if stype == "fork":
        branches = step.get("branches") or []
        lines = []
        for i, branch in enumerate(branches):
            if i == 0:
                lines.append(f"{pad}fork")
            else:
                lines.append(f"{pad}fork again")
            for s in branch:
                lines += _pu_activity_step(s, indent + 1)
        if branches:
            lines.append(f"{pad}end fork")
        return lines

    # 未知类型 → 当作文本动作输出
    text = str(step.get("text", "")).strip()
    return [f"{pad}:{text};"] if text else []
