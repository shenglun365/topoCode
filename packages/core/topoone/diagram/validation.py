"""Agent-friendly validation pipeline for diagram documents (L1-L4, optional L5).

Pure, stateless "judge": a document in, a structured report out. This module
deliberately has no notion of agents, retries or callbacks - whether (and how
many times) the host project asks an LLM to fix the reported errors is the
host project's orchestration concern (see docs/INTEGRATION.md, "validation
service and agent collaboration").

Report contract (the HTTP endpoint always answers 200 for a produced report)::

    {
      "ok": bool,                # no errors (warnings do not affect ok)
      "errors":   [ReportItem],  # must fix before rendering
      "warnings": [ReportItem]   # advisory
    }

ReportItem fields:
    level      "request" | "syntax" | "schema" | "semantic" | "animation" | "render"
    code       stable machine-readable identifier (registry in INTEGRATION.md)
    path       JSON Pointer into the input document ("/nodes/0/id", "/")
    message    one line, self-explanatory, safe to paste into an LLM prompt
    value?     the offending value (truncated)
    allowed?   legal values (enum members / allowed property names)
    available? existing ids the value could refer to (truncated to 50)

Determinism: the same input always yields the same report (items sorted by
(level, path, code)), so an orchestrator can detect "no progress" retry loops
by fingerprinting consecutive reports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from .capabilities import load_diagram_schema

# ── error code registry (mirror of docs/INTEGRATION.md) ─────────────────────
# level: request  - the request envelope itself is wrong
# level: syntax   - the document is not parseable JSON
# level: schema   - structural violation of schema/diagram.schema.json
# level: semantic - structure is valid but references/relations are broken
# level: animation- the animation block references unknown ids
# level: render   - engine-level failure (mermaid.parse / plantuml dry run)

LEVEL_ORDER = {"request": 0, "syntax": 1, "schema": 2, "semantic": 3, "animation": 4, "render": 5}

VALUE_LIMIT = 200
AVAILABLE_LIMIT = 50


def _truncate(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if len(text) <= VALUE_LIMIT else text[:VALUE_LIMIT] + "…"


@dataclass(frozen=True)
class ReportItem:
    level: str
    code: str
    path: str
    message: str
    value: str | None = None
    allowed: list[Any] | None = None
    available: list[str] | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"level": self.level, "code": self.code, "path": self.path, "message": self.message}
        if self.value is not None:
            out["value"] = self.value
        if self.allowed is not None:
            out["allowed"] = self.allowed
        if self.available is not None:
            out["available"] = self.available
        return out


def _report(errors: list[ReportItem], warnings: list[ReportItem]) -> dict[str, Any]:
    key = lambda i: (LEVEL_ORDER.get(i.level, 9), i.path, i.code)
    return {
        "ok": not errors,
        "errors": [i.to_dict() for i in sorted(errors, key=key)],
        "warnings": [i.to_dict() for i in sorted(warnings, key=key)],
    }


def _ptr(parts: tuple[str, ...]) -> str:
    return "/" + "/".join(str(p) for p in parts) if parts else "/"


def _available(ids: list[str]) -> list[str]:
    uniq = sorted(set(ids))
    return uniq[:AVAILABLE_LIMIT]


# ── L2: structural validation against schema/diagram.schema.json ────────────

_VALIDATOR_CODE = {
    "required": "REQUIRED_MISSING",
    "type": "INVALID_TYPE",
    "enum": "INVALID_ENUM",
    "const": "INVALID_CONST",
    "pattern": "PATTERN_MISMATCH",
    "minLength": "CONSTRAINT_VIOLATION",
    "maxLength": "CONSTRAINT_VIOLATION",
    "minItems": "CONSTRAINT_VIOLATION",
    "maxItems": "CONSTRAINT_VIOLATION",
    "minimum": "CONSTRAINT_VIOLATION",
    "maximum": "CONSTRAINT_VIOLATION",
    "additionalProperties": "EXTRA_PROPERTY",
    "anyOf": "SCHEMA_VIOLATION",
    "oneOf": "SCHEMA_VIOLATION",
    "allOf": "SCHEMA_VIOLATION",
}


def _l2_structural(doc: dict) -> list[ReportItem]:
    validator = Draft202012Validator(load_diagram_schema())
    errors: list[ReportItem] = []
    seen: set[tuple[str, str, str]] = set()
    for e in validator.iter_errors(doc):
        missing = None
        parts = tuple(e.absolute_path)
        if e.validator == "required":
            # jsonschema puts the missing property in the message: "'label' is a required property"
            missing = e.message.split("'")[1] if "'" in e.message else None
            parts = parts + ((missing or "?"),)
        elif e.validator == "additionalProperties":
            # message: "Additional properties are not allowed ('bogus' was unexpected)"
            prop = e.message.split("'")[1] if "'" in e.message else str(e.validator_value)
            parts = parts + (prop,)
        path = _ptr(parts)
        code = _VALIDATOR_CODE.get(e.validator, "SCHEMA_VIOLATION")
        if "allOf" in e.absolute_schema_path and e.validator == "required":
            code = "TYPE_REQUIRED"
        if code in ("TYPE_REQUIRED", "REQUIRED_MISSING", "EXTRA_PROPERTY"):
            prop = missing if e.validator == "required" else e.validator_value
            dedup = (code, path, str(prop))
        else:
            dedup = (code, path, e.message)
        if dedup in seen:
            continue
        seen.add(dedup)

        message = e.message
        if code == "TYPE_REQUIRED":
            message = f"type '{doc.get('type')}' requires non-empty '{e.validator_value}'"
        allowed = None
        value = None
        if code == "INVALID_ENUM":
            allowed = list(e.validator_value)
            value = _truncate(e.instance)
        elif code == "PATTERN_MISMATCH":
            allowed = [e.validator_value]
            value = _truncate(e.instance)
        elif code in ("REQUIRED_MISSING", "TYPE_REQUIRED"):
            value = str(e.validator_value)
        elif code == "EXTRA_PROPERTY":
            value = _truncate(e.validator_value)
            allowed = list(e.schema.get("properties", {}).keys()) if isinstance(e.schema, dict) else None
        elif e.instance is not None and isinstance(e.instance, (str, int, float, bool)):
            value = _truncate(e.instance)
        errors.append(ReportItem("schema", code, path, message, value=value, allowed=allowed))
    return errors


# ── L3: semantic rules (per-type table) ─────────────────────────────────────

def _dup_ids(errors: list[ReportItem], items: list[dict], field_name: str, key: str = "id") -> list[str]:
    seen: set[str] = set()
    ids: list[str] = []
    for i, item in enumerate(items):
        ident = item.get(key)
        if not ident:
            continue
        ids.append(ident)
        if ident in seen:
            errors.append(
                ReportItem("semantic", "DUPLICATE_ID", _ptr((field_name, i, key)), f"duplicate id '{ident}'", value=ident)
            )
        seen.add(ident)
    return ids


def _check_ref(
    errors: list[ReportItem], path: str, ref: str, known: list[str], what: str
) -> None:
    if ref not in known:
        errors.append(
            ReportItem(
                "semantic",
                "REF_MISSING",
                path,
                f"{what} '{ref}' does not exist",
                value=ref,
                available=_available(known),
            )
        )


def _find_cycle(ids: list[str], deps: dict[str, list[str]]) -> list[str] | None:
    """Return one dependency cycle as a list of ids, or None (iterative DFS)."""
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {i: WHITE for i in ids}
    for root in ids:
        if color[root] != WHITE:
            continue
        stack: list[tuple[str, int]] = [(root, 0)]
        path: list[str] = []
        while stack:
            node, idx = stack.pop()
            if idx == 0:
                color[node] = GRAY
                path.append(node)
            advanced = False
            for j in range(idx, len(deps.get(node, []))):
                dep = deps.get(node, [])[j]
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    return path[path.index(dep):] + [dep]
                if color[dep] == WHITE:
                    stack.append((node, j + 1))
                    stack.append((dep, 0))
                    advanced = True
                    break
            if not advanced:
                color[node] = BLACK
                path.pop()
    return None


# JSON Schema `required` only checks presence; non-emptiness is enforced here
# (mirrors pydantic _TYPE_REQUIRED and the TS validateSemantics table).
_TYPE_REQUIRED: dict[str, tuple[str, ...]] = {
    "flowchart": ("nodes",),
    "activity": ("nodes",),
    "usecase": ("nodes",),
    "component": ("nodes",),
    "architecture": ("nodes",),
    "sequence": ("participants", "messages"),
    "state": ("states",),
    "class": ("classes",),
    "er": ("entities",),
    "gantt": ("tasks",),
}


def _l3_semantic(doc: dict) -> tuple[list[ReportItem], list[ReportItem]]:
    errors: list[ReportItem] = []
    warnings: list[ReportItem] = []

    for field_name in _TYPE_REQUIRED.get(doc.get("type", ""), ()):
        if not doc.get(field_name):
            errors.append(
                ReportItem("semantic", "TYPE_EMPTY", f"/{field_name}", f"type '{doc.get('type')}' requires non-empty '{field_name}'")
            )

    nodes = doc.get("nodes") or []
    edges = doc.get("edges") or []

    # graph types: nodes / edges / groups / lanes
    if nodes:
        node_ids = _dup_ids(errors, nodes, "nodes")
        edge_ids: list[str] = []
        for i, e in enumerate(edges):
            _check_ref(errors, _ptr(("edges", i, "from")), e["from"], node_ids, "edge source")
            _check_ref(errors, _ptr(("edges", i, "to")), e["to"], node_ids, "edge target")
            if e["from"] == e["to"]:
                warnings.append(
                    ReportItem("semantic", "SELF_LOOP", _ptr(("edges", i)), f"edge from node '{e['from']}' to itself")
                )
            if e.get("id"):
                edge_ids.append(e["id"])
        if edge_ids:
            _dup_ids(errors, [{"id": i} for i in edge_ids], "edges")
        for g in doc.get("groups") or []:
            for j, member in enumerate(g["contains"]):
                _check_ref(errors, _ptr(("groups", g["id"], "contains", j)), member, node_ids, "group member")
        lane_ids = [l["id"] for l in doc.get("lanes") or []]
        if lane_ids:
            for i, n in enumerate(nodes):
                if n.get("lane"):
                    _check_ref(errors, _ptr(("nodes", i, "lane")), n["lane"], lane_ids, "lane")
        if edges:
            connected = {e["from"] for e in edges} | {e["to"] for e in edges}
            for n in nodes:
                if n["id"] not in connected:
                    warnings.append(
                        ReportItem("semantic", "ORPHAN_NODE", _ptr(("nodes", n["id"])), f"node '{n['id']}' has no edges")
                    )

    # sequence: participants / messages
    participants = doc.get("participants") or []
    if participants:
        pids = _dup_ids(errors, participants, "participants")
        used: set[str] = set()
        for i, m in enumerate(doc.get("messages") or []):
            _check_ref(errors, _ptr(("messages", i, "from")), m["from"], pids, "message sender")
            _check_ref(errors, _ptr(("messages", i, "to")), m["to"], pids, "message receiver")
            used.update((m["from"], m["to"]))
        for p in participants:
            if p["id"] not in used:
                warnings.append(
                    ReportItem(
                        "semantic",
                        "UNREFERENCED_PARTICIPANT",
                        _ptr(("participants", p["id"])),
                        f"participant '{p['id']}' appears in no message",
                    )
                )

    # state: states / transitions
    states = doc.get("states") or []
    if states:
        sids = _dup_ids(errors, states, "states")
        for i, s in enumerate(states):
            for j, sub in enumerate(s.get("sub") or []):
                _check_ref(errors, _ptr(("states", i, "sub", j)), sub, sids, "sub-state")
        for i, t in enumerate(doc.get("transitions") or []):
            _check_ref(errors, _ptr(("transitions", i, "from")), t["from"], sids, "transition source")
            _check_ref(errors, _ptr(("transitions", i, "to")), t["to"], sids, "transition target")

    # class: classes / classRelations / member names
    classes = doc.get("classes") or []
    if classes:
        cids = _dup_ids(errors, classes, "classes")
        for i, r in enumerate(doc.get("classRelations") or []):
            _check_ref(errors, _ptr(("classRelations", i, "from")), r["from"], cids, "relation source")
            _check_ref(errors, _ptr(("classRelations", i, "to")), r["to"], cids, "relation target")
        for i, c in enumerate(classes):
            names: set[str] = set()
            for j, m in enumerate(c.get("members") or []):
                if m["name"] in names:
                    errors.append(
                        ReportItem(
                            "semantic",
                            "DUPLICATE_MEMBER",
                            _ptr(("classes", i, "members", j)),
                            f"class '{c['id']}' has duplicate member '{m['name']}'",
                            value=m["name"],
                        )
                    )
                names.add(m["name"])

    # er: entities / erRelations / attr names
    entities = doc.get("entities") or []
    if entities:
        eids = _dup_ids(errors, entities, "entities")
        for i, r in enumerate(doc.get("erRelations") or []):
            _check_ref(errors, _ptr(("erRelations", i, "from")), r["from"], eids, "relation source")
            _check_ref(errors, _ptr(("erRelations", i, "to")), r["to"], eids, "relation target")
        for i, ent in enumerate(entities):
            names: set[str] = set()
            for j, a in enumerate(ent.get("attrs") or []):
                if a["name"] in names:
                    errors.append(
                        ReportItem(
                            "semantic",
                            "DUPLICATE_MEMBER",
                            _ptr(("entities", i, "attrs", j)),
                            f"entity '{ent['id']}' has duplicate attribute '{a['name']}'",
                            value=a["name"],
                        )
                    )
                names.add(a["name"])

    # gantt: tasks / sections / dependsOn (+ cycle detection)
    tasks = doc.get("tasks") or []
    if tasks:
        tids = _dup_ids(errors, tasks, "tasks")
        section_ids = [s["id"] for s in doc.get("sections") or []]
        deps: dict[str, list[str]] = {}
        for i, t in enumerate(tasks):
            if t.get("section"):
                _check_ref(errors, _ptr(("tasks", i, "section")), t["section"], section_ids, "task section")
            for j, dep in enumerate(t.get("dependsOn") or []):
                _check_ref(errors, _ptr(("tasks", i, "dependsOn", j)), dep, tids, "dependency")
                deps.setdefault(t["id"], []).append(dep)
        cycle = _find_cycle(tids, deps)
        if cycle:
            errors.append(
                ReportItem(
                    "semantic",
                    "CYCLE_DETECTED",
                    "/tasks",
                    "dependency cycle: " + " -> ".join(cycle),
                    value=" -> ".join(cycle),
                )
            )

    return errors, warnings


# ── L4: animation block consistency ─────────────────────────────────────────
# Per-type id space a step may reference: (node-like collection, edge collection or None)

_ANIM_ID_SPACE: dict[str, tuple[str, str | None]] = {
    "flowchart": ("nodes", "edges"),
    "activity": ("nodes", "edges"),
    "usecase": ("nodes", "edges"),
    "component": ("nodes", "edges"),
    "architecture": ("nodes", "edges"),
    "sequence": ("participants", None),
    "state": ("states", None),
    "class": ("classes", None),
    "er": ("entities", None),
    "gantt": ("tasks", None),
}


def _l4_animation(doc: dict) -> list[ReportItem]:
    anim = doc.get("animation")
    if not anim:
        return []
    errors: list[ReportItem] = []
    node_field, edge_field = _ANIM_ID_SPACE.get(doc["type"], ("nodes", "edges"))
    node_ids = [n["id"] for n in doc.get(node_field) or []]
    edge_ids = [e["id"] for e in doc.get("edges") or [] if e.get("id")] if edge_field else []
    for i, step in enumerate(anim["steps"]):
        for j, nid in enumerate(step.get("nodes") or []):
            if nid not in node_ids:
                errors.append(
                    ReportItem(
                        "animation",
                        "ANIM_NODE_MISSING",
                        _ptr(("animation", "steps", i, "nodes", j)),
                        f"animation step {i} references unknown id '{nid}'",
                        value=nid,
                        available=_available(node_ids),
                    )
                )
        for j, eid in enumerate(step.get("edges") or []):
            if not edge_field:
                errors.append(
                    ReportItem(
                        "animation",
                        "ANIM_EDGES_UNSUPPORTED",
                        _ptr(("animation", "steps", i, "edges", j)),
                        f"type '{doc['type']}' has no addressable edges; use 'nodes' or 'selectors'",
                        value=eid,
                    )
                )
            elif eid not in edge_ids:
                errors.append(
                    ReportItem(
                        "animation",
                        "ANIM_EDGE_MISSING",
                        _ptr(("animation", "steps", i, "edges", j)),
                        f"animation step {i} references unknown edge id '{eid}'",
                        value=eid,
                        available=_available(edge_ids),
                    )
                )
    return errors


# ── public API ───────────────────────────────────────────────────────────────


def validate_schema_document(payload: Any) -> dict[str, Any]:
    """L1 (JSON parse, when payload is a str) + L2 + L3 + L4 for a schema document."""
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8", errors="replace")
    if isinstance(payload, str):
        try:
            doc = json.loads(payload)
        except json.JSONDecodeError as e:
            return _report(
                [
                    ReportItem(
                        "syntax",
                        "JSON_PARSE",
                        _ptr(("",)),
                        f"invalid JSON: {e.msg} at line {e.lineno} column {e.colno}",
                    )
                ],
                [],
            )
        if not isinstance(doc, dict):
            return _report([ReportItem("syntax", "JSON_PARSE", "/", "top-level JSON value must be an object")], [])
    elif isinstance(payload, dict):
        doc = payload
    else:
        return _report([ReportItem("request", "INVALID_REQUEST", "/", "'schema' must be a JSON object or JSON string")], [])

    errors = _l2_structural(doc)
    if errors:
        return _report(errors, [])
    sem_errors, sem_warnings = _l3_semantic(doc)
    errors = sem_errors + _l4_animation(doc)
    return _report(errors, sem_warnings)


def invalid_request(message: str, path: str = "/") -> dict[str, Any]:
    return _report([ReportItem("request", "INVALID_REQUEST", path, message)], [])
