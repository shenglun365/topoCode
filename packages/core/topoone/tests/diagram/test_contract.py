import json
import typing
from pathlib import Path

from topoone.diagram.schema import DiagramSchema

from topoone.diagram.capabilities import load_diagram_schema


def _schema() -> dict:
    return load_diagram_schema()


def test_top_level_fields_align_with_json_schema():
    schema_props = set(_schema()["properties"].keys())
    pydantic_fields = set(DiagramSchema.model_fields.keys())
    assert schema_props == pydantic_fields


def test_type_enum_aligns_with_json_schema():
    schema_types = set(_schema()["$defs"]["diagramType"]["enum"])
    py_types = set(typing.get_args(DiagramSchema.model_fields["type"].annotation))
    assert schema_types == py_types


def test_valid_sequence_parses():
    s = DiagramSchema(
        **{
            "version": 1,
            "type": "sequence",
            "participants": [{"id": "a", "label": "Alice"}, {"id": "b", "label": "Bob"}],
            "messages": [{"from": "a", "to": "b", "label": "hello", "kind": "sync"}],
        }
    )
    assert s.type == "sequence"


def test_sequence_requires_participants_and_messages():
    import pytest

    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DiagramSchema(**{"version": 1, "type": "sequence"})
