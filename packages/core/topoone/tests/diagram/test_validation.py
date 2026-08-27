"""Validation service tests: L1-L4 unit (pure) + /topo/validate endpoint (L5 wiring)."""

import json
import pytest
from fastapi.testclient import TestClient

from ._harness import create_app
from topoone.diagram.diagrams import DiagramSettings
from topoone.diagram.validation import validate_schema_document

from .conftest import PLANTUML_JAR as VENDOR_JAR


def codes(report: dict) -> list[tuple[str, str, str]]:
    """(level, code, path) triples of errors, for stable assertions."""
    return [(e["level"], e["code"], e["path"]) for e in report["errors"]]


def base_flowchart() -> dict:
    return {
        "version": 1,
        "type": "flowchart",
        "nodes": [
            {"id": "a", "label": "A"},
            {"id": "b", "label": "B"},
            {"id": "c", "label": "C"},
        ],
        "edges": [
            {"id": "e1", "from": "a", "to": "b"},
            {"id": "e2", "from": "b", "to": "c"},
        ],
    }


# ── L1: JSON syntax (string payloads) ───────────────────────────────────────


def test_l1_invalid_json_string():
    report = validate_schema_document('{"version": 1, "type": "flowchart", oops')
    assert report["ok"] is False
    assert codes(report) == [("syntax", "JSON_PARSE", "/")]
    assert "invalid JSON" in report["errors"][0]["message"]


def test_l1_top_level_not_object():
    report = validate_schema_document("[1, 2, 3]")
    assert codes(report) == [("syntax", "JSON_PARSE", "/")]


# ── L2: structural ──────────────────────────────────────────────────────────


def test_l2_valid_flowchart_ok():
    assert validate_schema_document(base_flowchart())["ok"] is True


def test_l2_invalid_enum_has_allowed():
    doc = base_flowchart()
    doc["nodes"][0]["kind"] = "box"
    report = validate_schema_document(doc)
    assert report["ok"] is False
    assert ("schema", "INVALID_ENUM", "/nodes/0/kind") in codes(report)
    err = report["errors"][0]
    assert err["value"] == "box"
    assert "rect" in err["allowed"] and "diamond" in err["allowed"]


def test_l2_type_required():
    # sequence without participants -> allOf/if/then requirement
    report = validate_schema_document({"version": 1, "type": "sequence", "messages": []})
    assert ("schema", "TYPE_REQUIRED", "/participants") in codes(report)


def test_l2_extra_property_lists_allowed_properties():
    doc = base_flowchart()
    doc["bogus"] = 1
    report = validate_schema_document(doc)
    assert ("schema", "EXTRA_PROPERTY", "/bogus") in codes(report)
    assert "nodes" in report["errors"][0]["allowed"]


def test_l2_missing_required():
    doc = base_flowchart()
    del doc["nodes"][0]["label"]
    report = validate_schema_document(doc)
    assert ("schema", "REQUIRED_MISSING", "/nodes/0/label") in codes(report)


# ── L3: semantic (per-type rules) ───────────────────────────────────────────


def test_l3_duplicate_node_id():
    doc = base_flowchart()
    doc["nodes"][1]["id"] = "a"
    report = validate_schema_document(doc)
    assert ("semantic", "DUPLICATE_ID", "/nodes/1/id") in codes(report)


def test_l3_dangling_edge_ref_has_available():
    doc = base_flowchart()
    doc["edges"][0]["to"] = "zzz"
    report = validate_schema_document(doc)
    assert ("semantic", "REF_MISSING", "/edges/0/to") in codes(report)
    err = next(e for e in report["errors"] if e["code"] == "REF_MISSING")
    assert err["value"] == "zzz"
    assert err["available"] == ["a", "b", "c"]


def test_l3_gantt_cycle_detected():
    doc = {
        "version": 1,
        "type": "gantt",
        "sections": [{"id": "s1", "label": "S"}],
        "tasks": [
            {"id": "t1", "title": "T1", "section": "s1", "start": "2026-01-01", "duration": 1, "dependsOn": ["t3"]},
            {"id": "t2", "title": "T2", "section": "s1", "start": "2026-01-02", "duration": 1, "dependsOn": ["t1"]},
            {"id": "t3", "title": "T3", "section": "s1", "start": "2026-01-03", "duration": 1, "dependsOn": ["t2"]},
        ],
    }
    report = validate_schema_document(doc)
    assert ("semantic", "CYCLE_DETECTED", "/tasks") in codes(report)
    assert "t1 -> t3 -> t2 -> t1" == report["errors"][0]["message"].split(": ")[1]


def test_l3_gantt_bad_section():
    doc = {
        "version": 1,
        "type": "gantt",
        "sections": [{"id": "s1", "label": "S"}],
        "tasks": [{"id": "t1", "title": "T1", "section": "nope", "start": "2026-01-01", "duration": 1}],
    }
    report = validate_schema_document(doc)
    assert ("semantic", "REF_MISSING", "/tasks/0/section") in codes(report)


def test_l3_sequence_message_ref_and_unreferenced_warning():
    doc = {
        "version": 1,
        "type": "sequence",
        "participants": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "messages": [{"from": "a", "to": "x", "label": "hi", "kind": "sync"}],
    }
    report = validate_schema_document(doc)
    assert ("semantic", "REF_MISSING", "/messages/0/to") in codes(report)
    assert any(w["code"] == "UNREFERENCED_PARTICIPANT" for w in report["warnings"])


def test_l3_class_relation_ref_and_duplicate_member():
    doc = {
        "version": 1,
        "type": "class",
        "classes": [
            {"id": "c1", "name": "C1", "members": [{"name": "m"}, {"name": "m"}]},
            {"id": "c2", "name": "C2"},
        ],
        "classRelations": [{"from": "c1", "to": "ghost", "kind": "assoc"}],
    }
    report = validate_schema_document(doc)
    assert ("semantic", "REF_MISSING", "/classRelations/0/to") in codes(report)
    assert ("semantic", "DUPLICATE_MEMBER", "/classes/0/members/1") in codes(report)


def test_l3_er_relation_ref():
    doc = {
        "version": 1,
        "type": "er",
        "entities": [{"id": "e1", "name": "E1"}],
        "erRelations": [{"from": "e1", "to": "ghost", "kind": "1:N"}],
    }
    report = validate_schema_document(doc)
    assert ("semantic", "REF_MISSING", "/erRelations/0/to") in codes(report)


def test_l3_state_transition_ref():
    doc = {
        "version": 1,
        "type": "state",
        "states": [{"id": "s1", "label": "S1"}],
        "transitions": [{"from": "s1", "to": "ghost"}],
    }
    report = validate_schema_document(doc)
    assert ("semantic", "REF_MISSING", "/transitions/0/to") in codes(report)


def test_l3_orphan_node_is_warning_not_error():
    doc = base_flowchart()
    doc["nodes"].append({"id": "d", "label": "D"})
    report = validate_schema_document(doc)
    assert report["ok"] is True
    assert any(w["code"] == "ORPHAN_NODE" for w in report["warnings"])


def test_l3_self_loop_is_warning():
    doc = base_flowchart()
    doc["edges"].append({"id": "e3", "from": "a", "to": "a"})
    report = validate_schema_document(doc)
    assert report["ok"] is True
    assert any(w["code"] == "SELF_LOOP" for w in report["warnings"])


def test_l3_type_required_field_empty():
    doc = {"version": 1, "type": "gantt", "sections": [{"id": "s1", "label": "S"}], "tasks": []}
    report = validate_schema_document(doc)
    assert ("semantic", "TYPE_EMPTY", "/tasks") in codes(report)


def test_l2_failure_short_circuits_l3():
    doc = base_flowchart()
    doc["version"] = 99  # structural failure first; no semantic noise
    report = validate_schema_document(doc)
    assert all(e["level"] == "schema" for e in report["errors"])


# ── L4: animation consistency ───────────────────────────────────────────────


def test_l4_valid_animation_ok():
    doc = base_flowchart()
    doc["animation"] = {
        "mode": "reveal",
        "stepMs": 500,
        "steps": [
            {"label": "start", "nodes": ["a"]},
            {"label": "rest", "nodes": ["b", "c"], "edges": ["e1", "e2"]},
        ],
    }
    report = validate_schema_document(doc)
    assert report["ok"] is True
    assert report["errors"] == []


def test_l4_unknown_node_has_available():
    doc = base_flowchart()
    doc["animation"] = {"steps": [{"nodes": ["ghost"]}]}
    report = validate_schema_document(doc)
    assert ("animation", "ANIM_NODE_MISSING", "/animation/steps/0/nodes/0") in codes(report)
    err = report["errors"][0]
    assert err["value"] == "ghost"
    assert err["available"] == ["a", "b", "c"]


def test_l4_unknown_edge_id():
    doc = base_flowchart()
    doc["animation"] = {"steps": [{"edges": ["e9"]}]}
    report = validate_schema_document(doc)
    assert ("animation", "ANIM_EDGE_MISSING", "/animation/steps/0/edges/0") in codes(report)
    assert report["errors"][0]["available"] == ["e1", "e2"]


def test_l4_edges_unsupported_for_sequence():
    doc = {
        "version": 1,
        "type": "sequence",
        "participants": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "messages": [{"from": "a", "to": "b", "label": "hi", "kind": "sync"}],
        "animation": {"steps": [{"nodes": ["a", "b"], "edges": ["m1"]}]},
    }
    report = validate_schema_document(doc)
    assert ("animation", "ANIM_EDGES_UNSUPPORTED", "/animation/steps/0/edges/0") in codes(report)


def test_l4_sequence_nodes_resolve_against_participants():
    doc = {
        "version": 1,
        "type": "sequence",
        "participants": [{"id": "a", "label": "A"}, {"id": "b", "label": "B"}],
        "messages": [{"from": "a", "to": "b", "label": "hi", "kind": "sync"}],
        "animation": {"steps": [{"nodes": ["a"]}, {"nodes": ["b"]}]},
    }
    assert validate_schema_document(doc)["ok"] is True


def test_l4_step_without_targets_rejected_by_schema():
    doc = base_flowchart()
    doc["animation"] = {"steps": [{"label": "empty"}]}
    report = validate_schema_document(doc)
    assert any(e["code"] == "SCHEMA_VIOLATION" for e in report["errors"])


# ── determinism ─────────────────────────────────────────────────────────────


def test_deterministic_output():
    doc = base_flowchart()
    doc["edges"][0]["to"] = "zzz"
    doc["animation"] = {"steps": [{"nodes": ["ghost"]}]}
    a = validate_schema_document(json.dumps(doc))
    b = validate_schema_document(doc)
    assert a == b


# ── endpoint: /topo/validate (L5 wiring + report contract) ──────────────────

CODE_OK = "@startuml\nAlice -> Bob: hello\n@enduml"
CODE_BAD = "@startuml\nfoo bar baz qux\n@enduml"


@pytest.fixture(scope="module")
def client():
    # No jar/sidecar in CI: inject a fallback renderer so plantuml code checks
    # behave deterministically (OK renders, BAD raises).
    def _fallback(code: str) -> bytes:
        if code.strip() == CODE_BAD.strip():
            raise ValueError("syntax error")
        return b"<svg/>"

    diag = DiagramSettings(plantuml_jar=VENDOR_JAR, render_pool_size=0)
    with TestClient(create_app(diag=diag, fallback_renderer=_fallback)) as c:
        yield c


def test_endpoint_schema_ok(client: TestClient):
    r = client.post("/topo/validate", json={"schema": base_flowchart()})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["errors"] == []


def test_endpoint_schema_errors_report(client: TestClient):
    doc = base_flowchart()
    doc["edges"][0]["to"] = "zzz"
    r = client.post("/topo/validate", json={"schema": doc})
    assert r.status_code == 200  # report contract: always 200
    body = r.json()
    assert body["ok"] is False
    assert body["errors"][0]["code"] == "REF_MISSING"
    assert body["errors"][0]["available"] == ["a", "b", "c"]


def test_endpoint_schema_as_json_string(client: TestClient):
    r = client.post("/topo/validate", json={"schema": json.dumps(base_flowchart())})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_endpoint_check_render_unavailable_warning(client: TestClient):
    # render_pool_size=0 -> L5 degrades to a warning, ok stays true
    r = client.post("/topo/validate", json={"schema": base_flowchart(), "check_render": True})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert any(w["code"] == "RENDER_UNAVAILABLE" for w in body["warnings"])


def test_endpoint_code_plantuml_valid(client: TestClient):
    r = client.post("/topo/validate", json={"code": CODE_OK, "engine": "plantuml"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_endpoint_code_plantuml_syntax_error(client: TestClient):
    r = client.post("/topo/validate", json={"code": CODE_BAD, "engine": "plantuml"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is False
    assert body["errors"][0]["level"] == "render"
    assert body["errors"][0]["code"] == "RENDER_FAILED"


def test_endpoint_code_mermaid_pool_unavailable(client: TestClient):
    r = client.post("/topo/validate", json={"code": "flowchart TD\n  A-->B", "engine": "mermaid"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True  # nothing failed; just not checked
    assert any(w["code"] == "RENDER_UNAVAILABLE" for w in body["warnings"])


def test_endpoint_invalid_request_envelope(client: TestClient):
    for payload in ({}, {"schema": base_flowchart(), "code": "x"}):
        r = client.post("/topo/validate", json=payload)
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is False
        assert body["errors"][0]["code"] == "INVALID_REQUEST"
