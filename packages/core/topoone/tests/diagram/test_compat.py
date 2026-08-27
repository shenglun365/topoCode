"""compat.py bidirectional adapter + IR convergence tests."""

from __future__ import annotations

import pytest

from topoone.diagram import (
    build_from_ir,
    is_legacy_ir,
    legacy_ir_to_schema,
    schema_to_legacy_ir,
)
from topoone.diagram.encoder import decode, encode
from topoone.diagram.validation import validate_schema_document


FLOWCHART_LEGACY = {
    "lang": "mermaid", "diagram_type": "flowchart", "title": "demo", "direction": "LR",
    "nodes": [
        {"id": "a", "text": "A", "shape": "round", "styles": {"fill": "#ff0000", "stroke": "#000"}},
        {"id": "b", "text": "B"},
    ],
    "edges": [{"from": "a", "to": "b", "label": "x", "style": "dotted"}],
    "subgraphs": [{"id": "g1", "title": "grp", "nodes": ["a"]}],
}


def test_is_legacy_ir():
    assert is_legacy_ir({"lang": "mermaid", "diagram_type": "flowchart"})
    assert not is_legacy_ir({"version": 1, "type": "flowchart"})


def test_legacy_flowchart_roundtrip_lossless():
    sch = legacy_ir_to_schema(FLOWCHART_LEGACY)
    assert sch["type"] == "flowchart"
    assert sch["direction"] == "LR"
    assert validate_schema_document(sch)["ok"]
    # lossless restore through the extra.legacy carrier
    assert schema_to_legacy_ir(sch) == FLOWCHART_LEGACY


def test_legacy_flowchart_validates_and_builds():
    sch = legacy_ir_to_schema(FLOWCHART_LEGACY)
    report = validate_schema_document(sch)
    assert report["ok"], report["errors"]
    out = build_from_ir(FLOWCHART_LEGACY)
    assert "error" not in out
    assert "flowchart LR" in out["code"]
    assert 'a -.->|x| b' in out["code"]


def test_schema_to_legacy_new_flowchart():
    schema = {
        "version": 1, "type": "flowchart",
        "nodes": [{"id": "a", "label": "A", "kind": "diamond"},
                  {"id": "b", "label": "B"}],
        "edges": [{"from": "a", "to": "b", "label": "go", "kind": "thick"}],
        "groups": [{"id": "g", "label": "G", "contains": ["a"]}],
    }
    legacy = schema_to_legacy_ir(schema)
    assert legacy["lang"] == "mermaid"
    assert legacy["diagram_type"] == "flowchart"
    assert legacy["nodes"][0] == {"id": "a", "text": "A", "shape": "diamond"}
    assert legacy["edges"][0]["style"] == "thick"
    assert legacy["subgraphs"] == [{"id": "g", "title": "G", "nodes": ["a"]}]
    out = build_from_ir(legacy)
    assert "error" not in out
    assert "a ==>|go| b" in out["code"]


def test_legacy_sequence_maps_and_builds():
    legacy = {
        "lang": "mermaid", "diagram_type": "sequence", "title": "t",
        "participants": [{"name": "alice", "alias": "A", "type": "actor"},
                         {"name": "bob", "alias": "B", "type": "participant"}],
        "messages": [{"from": "alice", "to": "bob", "label": "hi", "arrow": "->"}],
    }
    sch = legacy_ir_to_schema(legacy)
    assert validate_schema_document(sch)["ok"]
    assert sch["participants"][0]["type"] == "actor"
    assert schema_to_legacy_ir(sch) == legacy
    out = build_from_ir(legacy)
    assert "sequenceDiagram" in out["code"]
    assert "actor alice as A" in out["code"]


def test_legacy_class_maps_and_builds():
    legacy = {
        "lang": "mermaid", "diagram_type": "class",
        "classes": [{"name": "User", "members": [
            {"name": "id", "visibility": "+", "type": "Long", "is_method": False},
            {"name": "save", "visibility": "-", "is_method": True, "params": "u"},
        ]}],
        "relations": [{"from": "User", "to": "Order", "type": "composition", "label": "owns"}],
    }
    legacy["classes"].append({"name": "Order"})
    sch = legacy_ir_to_schema(legacy)
    assert validate_schema_document(sch)["ok"]
    assert schema_to_legacy_ir(sch) == legacy
    out = build_from_ir(legacy)
    assert "classDiagram" in out["code"]
    assert "class User {" in out["code"]


def test_legacy_er_state_gantt_pie_roundtrip():
    for legacy in [
        {"lang": "mermaid", "diagram_type": "er",
         "entities": [{"name": "A", "attributes": [{"name": "id", "type": "int", "pk": True}]},
                      {"name": "B"}],
         "relations": [{"from": "A", "to": "B", "type": "one_to_many"}]},
        {"lang": "mermaid", "diagram_type": "state",
         "states": [{"id": "s1", "text": "Start"}, {"id": "s2", "text": "Done"}],
         "transitions": [{"from": "s1", "to": "s2", "label": "go"}]},
        {"lang": "mermaid", "diagram_type": "gantt",
         "sections": [{"name": "S", "tasks": [{"name": "t", "start": "2024-01-01", "duration": 2, "status": "done"}]}]},
        {"lang": "mermaid", "diagram_type": "pie",
         "items": [{"label": "A", "value": 3}, {"label": "B", "value": 7}]},
    ]:
        sch = legacy_ir_to_schema(legacy)
        report = validate_schema_document(sch)
        assert report["ok"], (legacy["diagram_type"], report["errors"])
        assert schema_to_legacy_ir(sch) == legacy
        out = build_from_ir(legacy)
        assert "error" not in out, legacy["diagram_type"]


def test_pie_schema_direct_build():
    schema = {"version": 1, "type": "pie", "title": "dist",
              "slices": [{"id": "s1", "label": "A", "value": 3}]}
    assert validate_schema_document(schema)["ok"]
    legacy = schema_to_legacy_ir(schema)
    assert legacy["items"] == [{"label": "A", "value": 3}]
    out = build_from_ir(legacy)
    assert out["code"].startswith("pie")
    assert '"A" : 3' in out["code"]


def test_activity_legacy_to_schema():
    legacy = {"lang": "plantuml", "diagram_type": "activity",
              "flow": [
                  {"type": "action", "text": "start"},
                  {"type": "branch", "condition": "ok?", "then": [{"type": "action", "text": "yes"}],
                   "else": [{"type": "action", "text": "no"}]},
              ]}
    sch = legacy_ir_to_schema(legacy)
    assert validate_schema_document(sch)["ok"]
    assert any(n["kind"] == "decision" for n in sch["nodes"])
    assert len(sch["edges"]) >= 2


def test_new_schema_activity_builds_plantuml():
    schema = {"version": 1, "type": "activity",
              "nodes": [{"id": "n1", "label": "Start", "kind": "action"},
                        {"id": "n2", "label": "End", "kind": "action"}],
              "edges": [{"from": "n1", "to": "n2"}]}
    assert validate_schema_document(schema)["ok"]
    legacy = schema_to_legacy_ir(schema)
    assert legacy["lang"] == "plantuml"
    out = build_from_ir(legacy)
    assert out["code"].startswith("@startuml")


def test_plantuml_component_legacy():
    legacy = {"lang": "plantuml", "diagram_type": "component",
              "nodes": [{"id": "a", "text": "API", "styles": {"fill": "#red"}},
                        {"id": "b", "text": "DB"}],
              "edges": [{"from": "a", "to": "b", "label": "http"}]}
    sch = legacy_ir_to_schema(legacy)
    assert validate_schema_document(sch)["ok"]
    assert schema_to_legacy_ir(sch) == legacy
    out = build_from_ir(legacy)
    assert out["code"].startswith("@startuml")


def test_encoder_decode_roundtrip():
    for s in ["@startuml\nA -> B\n@enduml", "", "A", "中文测试"]:
        assert decode(encode(s)) == s


def test_encoder_decode_invalid():
    with pytest.raises(ValueError):
        decode("!!!not-valid!!!")


def test_unknown_legacy_type_fails_closed():
    # unknown type -> rejected by the unified schema (fail closed, no silent degrade)
    legacy = {"lang": "mermaid", "diagram_type": "weird",
              "nodes": [{"id": "a", "text": "A"}]}
    sch = legacy_ir_to_schema(legacy)
    assert not validate_schema_document(sch)["ok"]
    assert schema_to_legacy_ir(sch) == legacy  # lossless regardless
