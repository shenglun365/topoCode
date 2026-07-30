from typing import Any

from ._segments import (
    config_segment,
    header_segment,
    comment_segment,
    subgraph_open_segment,
    subgraph_close_segment,
    node_segment,
    edge_segment,
    class_def_segment,
    safe_id,
)


def _collect_defined_styles(nodes: list[dict]) -> dict[str, list[str]]:
    style_out: dict[str, list[str]] = {}
    class_out: dict[str, list[str]] = {}
    for n in nodes:
        sid = safe_id(n.get("id", ""))
        styles = n.get("styles") or {}
        if styles:
            style_out[sid] = [f"    style {sid} {','.join(f'{k}:{v}' for k,v in styles.items())}"]
        classes = n.get("classes") or []
        if classes:
            class_out[sid] = [f"    class {sid} {' '.join(classes)}"]
    return style_out, class_out


def build_flowchart(ir: dict) -> str:
    segments: list[str] = []

    segments += config_segment(ir.get("init_config"))
    segments += header_segment("flowchart", ir.get("direction", "TB"))
    segments += comment_segment(ir.get("comments"))

    subgraphs = ir.get("subgraphs") or []
    subgraph_node_ids: set[str] = set()
    for sg in subgraphs:
        for nid in sg.get("nodes", []):
            subgraph_node_ids.add(nid)

    nodes_by_subgraph: dict[str, list[dict]] = {}
    for sg in subgraphs:
        sg_id = sg.get("id", "")
        nodes_by_subgraph[sg_id] = []
        for n in ir.get("nodes", []):
            if n["id"] in sg.get("nodes", []):
                nodes_by_subgraph[sg_id].append(n)

    standalone_nodes = [n for n in ir.get("nodes", []) if n["id"] not in subgraph_node_ids]

    for sg in subgraphs:
        title = sg.get("title", sg.get("id", ""))
        sg_dir = sg.get("direction")
        segments += subgraph_open_segment(title, sg_dir)
        for n in nodes_by_subgraph.get(sg["id"], []):
            segments += node_segment(
                nid=n.get("id", ""),
                text=n.get("text", ""),
                shape=n.get("shape", "rect"),
                styles=n.get("styles"),
                classes=n.get("classes"),
                click=n.get("click"),
                indent=2,
            )
        segments += subgraph_close_segment()

    for n in standalone_nodes:
        segments += node_segment(
            nid=n.get("id", ""),
            text=n.get("text", ""),
            shape=n.get("shape", "rect"),
            styles=n.get("styles"),
            classes=n.get("classes"),
            click=n.get("click"),
        )

    for e in ir.get("edges", []):
        segments += edge_segment(
            from_id=e.get("from", ""),
            to_id=e.get("to", ""),
            label=e.get("label", ""),
            style=e.get("style", "arrow"),
            markers=e.get("markers"),
        )

    segments += class_def_segment(ir.get("class_defs"))

    return "\n".join(segments)
