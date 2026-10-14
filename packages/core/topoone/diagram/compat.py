"""Legacy IR <-> DiagramSchema bidirectional adapter.

The single IR is ``DiagramSchema`` (see schema.py / schema_data/diagram.schema.json).
The legacy per-type IR (``{lang, diagram_type, nodes, ...}``) predates it and is
still produced/consumed by in-production callers (chat diagram_editor skill, the
docs ``/api/diagram/*`` endpoints, the diagram editor, and the Python builder in
``topoone.diagram.builder`` which consumes the legacy shape).

To converge on ONE IR without breaking those callers:

- ``legacy_ir_to_schema()`` normalizes legacy IR into a DiagramSchema-shaped dict so
  the unified L1-L4 validator and render/export paths treat it uniformly. The
  complete original legacy IR is preserved verbatim under ``extra["legacy"]``, so
  ``schema_to_legacy_ir`` can restore it losslessly (agent-produced schema has no
  ``extra.legacy`` and maps field-by-field instead).
- ``schema_to_legacy_ir()`` feeds the battle-tested Python builder (which reads the
  legacy shape) from a DiagramSchema. Used by /api/diagram/build when new-format IR
  arrives.

Both directions are pure functions; the mapped fields stay schema-conformant (no
extra nested keys) so L1/L2 validation always passes.
"""

from __future__ import annotations

from typing import Any


def is_legacy_ir(payload: dict) -> bool:
    return "lang" in payload and "diagram_type" in payload


# ── legacy IR -> DiagramSchema ──────────────────────────────────────────────


def legacy_ir_to_schema(legacy: dict) -> dict:
    lang = legacy.get("lang", "mermaid")
    dtype = _normalize_legacy_type((legacy.get("diagram_type") or "").strip().lower())

    doc: dict[str, Any] = {
        "version": 1,
        "type": dtype,
        "extra": {"legacy": legacy, "comments": legacy.get("comments")},
    }
    if legacy.get("title"):
        doc["title"] = legacy["title"]
    if legacy.get("direction") and dtype == "flowchart":
        doc["direction"] = legacy["direction"]

    if dtype in ("flowchart", "component", "usecase", "architecture"):
        _map_flow_like(legacy, doc)
    elif dtype == "sequence":
        _map_sequence(legacy, doc)
    elif dtype == "class":
        _map_class(legacy, doc)
    elif dtype == "state":
        _map_state(legacy, doc)
    elif dtype == "er":
        _map_er(legacy, doc)
    elif dtype == "gantt":
        _map_gantt(legacy, doc)
    elif dtype == "pie":
        _map_pie(legacy, doc)
    elif dtype == "activity":
        _map_activity(legacy, doc)
    return doc


def _normalize_legacy_type(raw: str) -> str:
    aliases = {
        "graph": "flowchart", "graph_tb": "flowchart", "graph_lr": "flowchart",
        "graph_rl": "flowchart", "graph_bt": "flowchart", "flow": "flowchart",
        "seq": "sequence", "sequence_diagram": "sequence", "class_diagram": "class",
        "classDiagram": "class", "state_diagram": "state", "stateDiagram": "state",
        "er_diagram": "er", "component_diagram": "component",
        "activity_diagram": "activity", "diagram_activity": "activity",
    }
    return aliases.get(raw, raw)


def _map_flow_like(legacy: dict, doc: dict) -> None:
    nodes = []
    for n in legacy.get("nodes") or []:
        node = {"id": n.get("id", ""), "label": n.get("text", "") or n.get("id", "")}
        if n.get("shape"):
            node["kind"] = n["shape"]
        style = _style_to_schema(n.get("styles"))
        if style:
            node["style"] = style
        nodes.append(node)
    if nodes:
        doc["nodes"] = nodes

    edges = []
    for e in legacy.get("edges") or []:
        edge: dict = {"from": e.get("from", ""), "to": e.get("to", "")}
        if e.get("label"):
            edge["label"] = e["label"]
        kind = {"arrow": "solid", "thick": "thick", "dotted": "dotted", "line": "solid",
                "cross": "solid", "circle": "solid", "double": "solid", "thick_double": "thick"}.get(
            e.get("style", "arrow"))
        if kind:
            edge["kind"] = kind
        end = (e.get("markers") or {}).get("end")
        if end == "arrow":
            edge["arrow"] = "filled"
        elif end in ("circle", "cross"):
            edge["arrow"] = "open"
        edges.append(edge)
    if edges:
        doc["edges"] = edges

    groups = []
    for sg in legacy.get("subgraphs") or []:
        groups.append({"id": sg.get("id", ""), "label": sg.get("title") or sg.get("id", ""),
                       "contains": list(sg.get("nodes") or [])})
    if groups:
        doc["groups"] = groups


def _map_sequence(legacy: dict, doc: dict) -> None:
    participants = []
    for p in legacy.get("participants") or []:
        name = p.get("name", "")
        participant: dict = {"id": name, "label": p.get("alias") or name}
        if p.get("type"):
            participant["type"] = p["type"]
        participants.append(participant)
    if participants:
        doc["participants"] = participants
    messages = []
    for m in legacy.get("messages") or []:
        kind = {"->": "sync", "-x": "sync", "--x": "sync"}.get(m.get("arrow", "->>"), "async")
        messages.append({"from": m.get("from", ""), "to": m.get("to", ""),
                         "label": m.get("label", ""), "kind": kind})
    if messages:
        doc["messages"] = messages


def _map_class(legacy: dict, doc: dict) -> None:
    classes = []
    for c in legacy.get("classes") or []:
        klass: dict = {"id": c.get("name", ""), "name": c.get("name", "")}
        members = []
        for mem in c.get("members") or []:
            member: dict = {"name": mem.get("name", "")}
            member["kind"] = "method" if mem.get("is_method") else "attr"
            vis = mem.get("visibility")
            if vis in ("public", "+"):
                member["visibility"] = "public"
            elif vis in ("private", "-"):
                member["visibility"] = "private"
            elif vis in ("protected", "#"):
                member["visibility"] = "protected"
            elif vis in ("package", "~"):
                member["visibility"] = "package"
            if mem.get("type"):
                member["type"] = mem["type"]
            members.append(member)
        if members:
            klass["members"] = members
        classes.append(klass)
    if classes:
        doc["classes"] = classes
    relations = []
    for r in legacy.get("relations") or []:
        rel = {"from": r.get("from", ""), "to": r.get("to", ""),
               "kind": {"extension": "inherit", "composition": "comp",
                        "aggregation": "agg", "association": "assoc",
                        "dependency": "dep", "realization": "impl"}.get(
                   r.get("type", "association"), "assoc")}
        if r.get("label"):
            rel["label"] = r["label"]
        relations.append(rel)
    if relations:
        doc["classRelations"] = relations


def _map_state(legacy: dict, doc: dict) -> None:
    states = []
    for s in legacy.get("states") or []:
        states.append({"id": s.get("id", ""), "label": s.get("text") or s.get("id", "")})
    if states:
        doc["states"] = states
    transitions = []
    for t in legacy.get("transitions") or []:
        tr = {"from": t.get("from", ""), "to": t.get("to", "")}
        if t.get("label"):
            tr["label"] = t["label"]
        transitions.append(tr)
    if transitions:
        doc["transitions"] = transitions


def _map_er(legacy: dict, doc: dict) -> None:
    entities = []
    for e in legacy.get("entities") or []:
        entity: dict = {"id": e.get("name", ""), "name": e.get("name", "")}
        attrs = []
        for a in e.get("attributes") or []:
            attr: dict = {"name": a.get("name", "")}
            if a.get("type"):
                attr["type"] = a["type"]
            if a.get("pk"):
                attr["key"] = True
            attrs.append(attr)
        if attrs:
            entity["attrs"] = attrs
        entities.append(entity)
    if entities:
        doc["entities"] = entities
    relations = []
    for r in legacy.get("relations") or []:
        rel = {"from": r.get("from", ""), "to": r.get("to", ""),
               "kind": {"one_to_one": "1:1", "one_to_many": "1:N",
                        "many_to_one": "1:N", "many_to_many": "M:N",
                        "zero_to_one": "1:1", "zero_to_many": "1:N"}.get(
                   r.get("type", "one_to_many"), "1:N")}
        if r.get("label"):
            rel["label"] = r["label"]
        relations.append(rel)
    if relations:
        doc["erRelations"] = relations


def _map_gantt(legacy: dict, doc: dict) -> None:
    sections = []
    tasks = []
    for sect in legacy.get("sections") or []:
        sname = sect.get("name", "")
        if sname:
            sections.append({"id": sname, "label": sname})
        for task in sect.get("tasks") or []:
            t: dict = {"id": task.get("name", ""), "title": task.get("name", ""),
                       "section": sname, "start": task.get("start", "1970-01-01"),
                       "duration": int(task.get("duration", 1) or 1)}
            if task.get("status"):
                t["tags"] = [task["status"]]
            tasks.append(t)
    if sections:
        doc["sections"] = sections
    if tasks:
        doc["tasks"] = tasks


def _map_pie(legacy: dict, doc: dict) -> None:
    slices = []
    for item in legacy.get("items") or []:
        label = item.get("label", "")
        slices.append({"id": label or item.get("id", ""), "label": label,
                       "value": float(item.get("value", 0) or 0)})
    if slices:
        doc["slices"] = slices


def _map_activity(legacy: dict, doc: dict) -> None:
    nodes: list[dict] = []
    edges: list[dict] = []
    counter = [0]

    def nid() -> str:
        counter[0] += 1
        return f"a{counter[0]}"

    def walk(steps: list, prev: str | None = None) -> str | None:
        last = prev
        for s in steps or []:
            if not isinstance(s, dict):
                s = {"type": "action", "text": str(s)}
            stype = s.get("type", "action")
            if stype in ("action", "activity", "note"):
                text = str(s.get("text", "")).strip()
                n = nid()
                nodes.append({"id": n, "label": text or n, "kind": "action"})
                if last:
                    edges.append({"from": last, "to": n, "kind": "solid"})
                last = n
            elif stype in ("branch", "if"):
                n = nid()
                nodes.append({"id": n, "label": str(s.get("condition", "")).strip() or "branch",
                              "kind": "decision"})
                if last:
                    edges.append({"from": last, "to": n, "kind": "solid"})
                then_last = walk(s.get("then") or [], None)
                if then_last:
                    edges.append({"from": n, "to": then_last, "kind": "solid"})
                last = then_last or last
            elif stype == "fork":
                for br in (s.get("branches") or []):
                    br_last = walk(br if isinstance(br, list) else [br], last)
                    if br_last:
                        last = br_last
            else:
                text = str(s.get("text", "")).strip()
                if text:
                    n = nid()
                    nodes.append({"id": n, "label": text, "kind": "action"})
                    if last:
                        edges.append({"from": last, "to": n, "kind": "solid"})
                    last = n
        return last

    steps = legacy.get("flow") or legacy.get("steps") or []
    walk(steps, None)
    if nodes:
        doc["nodes"] = nodes
    if edges:
        doc["edges"] = edges


def _style_to_schema(styles: dict | None) -> dict | None:
    if not styles:
        return None
    out: dict = {}
    if styles.get("fill"):
        out["fill"] = styles["fill"]
    if styles.get("stroke"):
        out["stroke"] = styles["stroke"]
    if styles.get("color"):
        out["color"] = styles["color"]
    return out or None


# ── DiagramSchema -> legacy IR (feeds topoone.diagram.builder) ─────────────


def schema_to_legacy_ir(doc: dict) -> dict:
    """Map a DiagramSchema-shaped dict onto the legacy builder input shape.

    Supported: flowchart/sequence/class/state/er/gantt/pie (mermaid),
    component/sequence/class/activity (plantuml). usecase/architecture degrade to
    flowchart. engine defaults by the legacy Python builder's coverage.
    """
    dtype = doc.get("type", "flowchart")
    _PY_BUILDER_LANG = {
        "flowchart": "mermaid", "sequence": "mermaid", "class": "mermaid",
        "state": "mermaid", "er": "mermaid", "gantt": "mermaid", "pie": "mermaid",
        "component": "plantuml", "activity": "plantuml",
        "usecase": "mermaid", "architecture": "mermaid",
    }
    engine = doc.get("_engine", _PY_BUILDER_LANG.get(dtype, "mermaid"))
    legacy: dict[str, Any] = {"lang": engine, "diagram_type": dtype}
    if doc.get("title"):
        legacy["title"] = doc["title"]
    comments = doc.get("extra", {}).get("comments")
    if comments:
        legacy["comments"] = comments

    # Lossless restore when the doc was produced from legacy IR (see module docstring).
    legacy_src = doc.get("extra", {}).get("legacy")
    if isinstance(legacy_src, dict):
        return dict(legacy_src)

    if dtype in ("flowchart", "component", "usecase", "architecture"):
        _unmap_flow_like(doc, legacy, engine)
    elif dtype == "sequence":
        _unmap_sequence(doc, legacy)
    elif dtype == "class":
        _unmap_class(doc, legacy)
    elif dtype == "state":
        _unmap_state(doc, legacy)
    elif dtype == "er":
        _unmap_er(doc, legacy)
    elif dtype == "gantt":
        _unmap_gantt(doc, legacy)
    elif dtype == "pie":
        _unmap_pie(doc, legacy)
    elif dtype == "activity":
        _unmap_activity(doc, legacy)
    return legacy


def _unmap_flow_like(doc: dict, legacy: dict, engine: str) -> None:
    nodes = []
    for n in doc.get("nodes") or []:
        node: dict = {"id": n.get("id", ""), "text": n.get("label", "") or n.get("id", "")}
        if n.get("kind"):
            node["shape"] = n["kind"]
        style = n.get("style")
        if style:
            node["styles"] = {k: v for k, v in style.items() if v}
        nodes.append(node)
    if nodes:
        legacy["nodes"] = nodes

    edges = []
    for e in doc.get("edges") or []:
        style = {"solid": "arrow", "dashed": "dotted", "dotted": "dotted", "thick": "thick"}.get(
            e.get("kind", "solid"), "arrow")
        edge: dict = {"from": e.get("from", ""), "to": e.get("to", ""),
                      "label": e.get("label") or "", "style": style}
        end = {"filled": "arrow", "open": "circle"}.get(e.get("arrow"))
        if end:
            edge["markers"] = {"end": end}
        edges.append(edge)
    if edges:
        legacy["edges"] = edges

    groups = []
    for g in doc.get("groups") or []:
        groups.append({"id": g.get("id", ""), "title": g.get("label") or g.get("id", ""),
                       "nodes": list(g.get("contains") or [])})
    if groups:
        legacy["subgraphs"] = groups


def _unmap_sequence(doc: dict, legacy: dict) -> None:
    participants = []
    for p in doc.get("participants") or []:
        participants.append({"name": p.get("id", ""), "alias": p.get("label") or p.get("id", ""),
                             "type": p.get("type", "participant")})
    if participants:
        legacy["participants"] = participants
    messages = []
    for m in doc.get("messages") or []:
        arrow = {"sync": "->", "async": "-->>", "return": "-->>"}.get(m.get("kind", "async"), "-->>")
        messages.append({"from": m.get("from", ""), "to": m.get("to", ""),
                         "label": m.get("label", ""), "arrow": arrow})
    if messages:
        legacy["messages"] = messages


def _unmap_class(doc: dict, legacy: dict) -> None:
    classes = []
    for c in doc.get("classes") or []:
        klass: dict = {"name": c.get("name") or c.get("id", "")}
        members = []
        for mem in c.get("members") or []:
            member: dict = {"name": mem.get("name", "")}
            vis = mem.get("visibility")
            member["visibility"] = {"public": "+", "private": "-", "protected": "#", "package": "~"}.get(
                vis, vis or "+")
            if mem.get("kind") == "method":
                member["is_method"] = True
                member["params"] = ""
            elif mem.get("type"):
                member["type"] = mem["type"]
            members.append(member)
        if members:
            klass["members"] = members
        classes.append(klass)
    if classes:
        legacy["classes"] = classes
    relations = []
    for r in doc.get("classRelations") or []:
        relations.append({"from": r.get("from", ""), "to": r.get("to", ""),
                          "type": {"inherit": "extension", "comp": "composition",
                                   "agg": "aggregation", "assoc": "association",
                                   "dep": "dependency", "impl": "realization"}.get(
                              r.get("kind", "assoc"), "association"),
                          "label": r.get("label") or ""})
    if relations:
        legacy["relations"] = relations


def _unmap_state(doc: dict, legacy: dict) -> None:
    states = []
    for s in doc.get("states") or []:
        states.append({"id": s.get("id", ""), "text": s.get("label") or s.get("id", "")})
    if states:
        legacy["states"] = states
    transitions = []
    for t in doc.get("transitions") or []:
        transitions.append({"from": t.get("from", ""), "to": t.get("to", ""),
                            "label": t.get("label") or ""})
    if transitions:
        legacy["transitions"] = transitions


def _unmap_er(doc: dict, legacy: dict) -> None:
    entities = []
    for e in doc.get("entities") or []:
        entity: dict = {"name": e.get("name") or e.get("id", "")}
        attrs = []
        for a in e.get("attrs") or []:
            attr: dict = {"name": a.get("name", "")}
            if a.get("type"):
                attr["type"] = a["type"]
            attr["pk"] = bool(a.get("key"))
            attrs.append(attr)
        if attrs:
            entity["attributes"] = attrs
        entities.append(entity)
    if entities:
        legacy["entities"] = entities
    relations = []
    for r in doc.get("erRelations") or []:
        relations.append({"from": r.get("from", ""), "to": r.get("to", ""),
                          "type": {"1:1": "one_to_one", "1:N": "one_to_many", "M:N": "many_to_many"}.get(
                              r.get("kind", "1:N"), "one_to_many"),
                          "label": r.get("label") or ""})
    if relations:
        legacy["relations"] = relations


def _unmap_gantt(doc: dict, legacy: dict) -> None:
    sections = []
    for sect in doc.get("sections") or []:
        sname = sect.get("label") or sect.get("id", "")
        tasks = []
        for t in doc.get("tasks") or []:
            if t.get("section") != sect.get("id"):
                continue
            task: dict = {"name": t.get("title", ""), "start": t.get("start", ""),
                          "duration": t.get("duration", 1)}
            tags = t.get("tags") or []
            if tags:
                task["status"] = tags[0]
            tasks.append(task)
        sections.append({"name": sname, "tasks": tasks})
    if sections:
        legacy["sections"] = sections


def _unmap_pie(doc: dict, legacy: dict) -> None:
    items = []
    for s in doc.get("slices") or []:
        items.append({"label": s.get("label", ""), "value": s.get("value", 0)})
    if items:
        legacy["items"] = items


def _unmap_activity(doc: dict, legacy: dict) -> None:
    flow: list[dict] = []
    nodes = {n.get("id"): n for n in doc.get("nodes") or []}
    for e in doc.get("edges") or []:
        src = nodes.get(e.get("from"))
        if src:
            flow.append({"type": "action", "text": src.get("label", "")})
    legacy["flow"] = flow or [{"type": "action", "text": "end"}]
