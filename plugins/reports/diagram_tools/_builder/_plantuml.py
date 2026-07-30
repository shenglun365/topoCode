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
