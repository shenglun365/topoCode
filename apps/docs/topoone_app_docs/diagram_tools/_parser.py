from typing import Any


def parse_to_ir(code: str, lang: str = "mermaid") -> dict[str, Any]:
    if lang == "mermaid":
        return _parse_mermaid(code)
    elif lang == "plantuml":
        return _parse_plantuml(code)
    return {"error": f"Unsupported language: {lang}"}


def _parse_mermaid(code: str) -> dict[str, Any]:
    from diagram import mermaid_flowchart, mermaid_sequence, mermaid_class
    from diagram.mermaid_preproc import extract_shared

    ctx, cleaned = extract_shared(code)

    init_blocks = ctx.init_blocks
    init_config = {}
    if init_blocks:
        for block in init_blocks:
            import re
            m = re.search(r"%%\{init:\s*(.+?)\s*\}%%", block, re.DOTALL)
            if m:
                try:
                    import json
                    cfg = json.loads(m.group(1))
                    if isinstance(cfg, dict):
                        cfg = cfg.get("config", cfg)
                        if "theme" in cfg:
                            init_config["theme"] = cfg["theme"]
                        if "themeVariables" in cfg:
                            init_config["themeVariables"] = cfg["themeVariables"]
                except Exception:
                    pass

    diag_type = _classify_mermaid(cleaned)
    if not diag_type:
        return {"error": "Unable to identify diagram type"}

    if diag_type == "mermaid_flowchart":
        data = mermaid_flowchart.parse(cleaned)
        ir = _flowchart_data_to_ir(data)
        ir["init_config"] = init_config
        ir["_preproc_comment_lines"] = ctx.comment_lines
        ir["_preproc_separators"] = ctx.separators
        return ir

    elif diag_type == "mermaid_sequence":
        data = mermaid_sequence.parse(cleaned)
        ir = _sequence_data_to_ir(data)
        ir["init_config"] = init_config
        ir["_preproc_comment_lines"] = ctx.comment_lines
        ir["_preproc_separators"] = ctx.separators
        return ir

    elif diag_type == "mermaid_class":
        data = mermaid_class.parse(cleaned)
        ir = _class_data_to_ir(data)
        ir["init_config"] = init_config
        ir["_preproc_comment_lines"] = ctx.comment_lines
        ir["_preproc_separators"] = ctx.separators
        return ir

    else:
        return {"error": f"No IR parser for type: {diag_type}"}


def _classify_mermaid(code: str) -> str | None:
    from diagram import classify_mermaid
    try:
        return classify_mermaid(code)
    except Exception:
        return None


def _flowchart_data_to_ir(data: Any) -> dict:
    nodes = []
    for n in data.nodes:
        node_obj = {"id": n.id, "text": n.text, "shape": n.shape}
        nodes.append(node_obj)

    edges = []
    for e in data.edges:
        edge_obj = {"from": e.from_id, "to": e.to_id, "style": e.style}
        if e.label:
            edge_obj["label"] = e.label
        edges.append(edge_obj)

    ir: dict[str, Any] = {
        "lang": "mermaid",
        "diagram_type": "flowchart",
        "direction": getattr(data, "direction", "TB"),
        "nodes": nodes,
        "edges": edges,
        "subgraphs": [],
    }

    title = getattr(data, "title", "")
    if title:
        ir["title"] = title

    return ir


def _sequence_data_to_ir(data: Any) -> dict:
    participants = []
    for p in data.participants:
        participants.append({
            "name": p.name,
            "alias": p.alias,
            "type": p.type,
        })

    messages = []
    for m in data.messages:
        msg = {
            "from": m.from_alias,
            "to": m.to_alias,
            "label": m.label,
            "arrow": m.arrow,
        }
        messages.append(msg)

    ir: dict[str, Any] = {
        "lang": "mermaid",
        "diagram_type": "sequence",
        "participants": participants,
        "messages": messages,
    }

    title = getattr(data, "title", "")
    if title:
        ir["title"] = title

    return ir


def _class_data_to_ir(data: Any) -> dict:
    classes = []
    for cls in data.classes:
        cls_obj = {"name": cls.name}
        if getattr(cls, "stereotype", ""):
            cls_obj["stereotype"] = cls.stereotype
        if hasattr(cls, "members") and cls.members:
            members = []
            for m in cls.members:
                member_obj = {
                    "visibility": getattr(m, "visibility", "+"),
                    "name": getattr(m, "name", ""),
                    "is_method": getattr(m, "is_method", False),
                }
                if getattr(m, "type", ""):
                    member_obj["type"] = m.type
                if getattr(m, "is_static", False):
                    member_obj["is_static"] = True
                if getattr(m, "is_abstract", False):
                    member_obj["is_abstract"] = True
                if getattr(m, "params", ""):
                    member_obj["params"] = m.params
                members.append(member_obj)
            cls_obj["members"] = members
        if hasattr(cls, "namespace") and cls.namespace:
            cls_obj["namespace"] = cls.namespace
        classes.append(cls_obj)

    relations = []
    for r in data.relations:
        rel = {
            "from": r.from_cls,
            "to": r.to_cls,
            "type": r.rel_type,
        }
        if getattr(r, "label", ""):
            rel["label"] = r.label
        relations.append(rel)

    ir: dict[str, Any] = {
        "lang": "mermaid",
        "diagram_type": "class",
        "classes": classes,
        "relations": relations,
    }

    title = getattr(data, "title", "")
    if title:
        ir["title"] = title

    return ir


def _parse_plantuml(code: str) -> dict[str, Any]:
    from diagram import rebuild_plantuml, classify_plantuml

    diag_type = classify_plantuml(code)
    if not diag_type:
        return {"error": "Unable to identify PlantUML diagram type"}

    return {
        "lang": "plantuml",
        "diagram_type": diag_type,
        "_original_type": diag_type,
        "_note": "PlantUML IR is read-only; use rebuild pipeline for modifications",
    }
