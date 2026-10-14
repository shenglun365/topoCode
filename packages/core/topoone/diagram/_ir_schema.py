import json
from typing import Any

IR_SCHEMA_FLOWCHART = {
    "type": "object",
    "properties": {
        "lang": {"type": "string", "enum": ["mermaid", "plantuml"]},
        "diagram_type": {"type": "string", "enum": ["flowchart"]},
        "direction": {"type": "string", "enum": ["TB", "LR", "RL", "BT"]},
        "title": {"type": "string"},
        "comments": {"type": "array", "items": {"type": "string"}},
        "nodes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "shape": {"type": "string", "enum": ["rect", "round", "stadium", "diamond", "circle", "asymmetric", "hexagon", "parallelogram", "trapezoid"]},
                    "styles": {
                        "type": "object",
                        "properties": {
                            "fill": {"type": "string"},
                            "stroke": {"type": "string"},
                            "stroke-width": {"type": "string"},
                            "color": {"type": "string"},
                        },
                    },
                    "classes": {"type": "array", "items": {"type": "string"}},
                    "click": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "tooltip": {"type": "string"},
                        },
                    },
                    "_is_modified": {"type": "boolean"},
                },
                "required": ["id", "text"],
            },
        },
        "edges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "label": {"type": "string"},
                    "style": {"type": "string", "enum": ["arrow", "thick", "dotted", "line", "cross", "circle", "double", "thick_double"]},
                    "markers": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "enum": ["circle", "cross", "arrow", "none"]},
                            "end": {"type": "string", "enum": ["circle", "cross", "arrow", "none"]},
                        },
                    },
                    "link_style": {
                        "type": "object",
                        "properties": {
                            "stroke": {"type": "string"},
                            "stroke-width": {"type": "string"},
                        },
                    },
                    "_is_modified": {"type": "boolean"},
                },
                "required": ["from", "to"],
            },
        },
        "subgraphs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "title": {"type": "string"},
                    "nodes": {"type": "array", "items": {"type": "string"}},
                    "direction": {"type": "string"},
                    "_is_modified": {"type": "boolean"},
                },
                "required": ["id", "title", "nodes"],
            },
        },
        "class_defs": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "styles": {"type": "object"},
                },
            },
        },
        "init_config": {
            "type": "object",
            "properties": {
                "theme": {"type": "string"},
                "themeVariables": {"type": "object"},
            },
        },
    },
    "required": ["lang", "diagram_type", "nodes", "edges"],
}

IR_SCHEMA_SEQUENCE = {
    "type": "object",
    "properties": {
        "lang": {"type": "string", "enum": ["mermaid"]},
        "diagram_type": {"type": "string", "enum": ["sequence"]},
        "title": {"type": "string"},
        "participants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "alias": {"type": "string"},
                    "type": {"type": "string", "enum": ["participant", "actor"]},
                    "_is_modified": {"type": "boolean"},
                },
                "required": ["name", "alias"],
            },
        },
        "messages": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "label": {"type": "string"},
                    "arrow": {"type": "string", "enum": ["->", "-->", "->>", "-->>", "-x", "--x"]},
                    "_is_modified": {"type": "boolean"},
                },
                "required": ["from", "to", "label"],
            },
        },
    },
    "required": ["lang", "diagram_type", "participants", "messages"],
}

IR_SCHEMA_CLASS = {
    "type": "object",
    "properties": {
        "lang": {"type": "string", "enum": ["mermaid"]},
        "diagram_type": {"type": "string", "enum": ["class"]},
        "title": {"type": "string"},
        "classes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "stereotype": {"type": "string"},
                    "members": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "visibility": {"type": "string"},
                                "name": {"type": "string"},
                                "type": {"type": "string"},
                                "is_method": {"type": "boolean"},
                                "is_static": {"type": "boolean"},
                                "is_abstract": {"type": "boolean"},
                                "params": {"type": "string"},
                            },
                        },
                    },
                    "namespace": {"type": "string"},
                    "_is_modified": {"type": "boolean"},
                },
                "required": ["name"],
            },
        },
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "from": {"type": "string"},
                    "to": {"type": "string"},
                    "type": {"type": "string", "enum": ["extension", "composition", "aggregation", "association", "dependency", "realization"]},
                    "label": {"type": "string"},
                    "_is_modified": {"type": "boolean"},
                },
                "required": ["from", "to", "type"],
            },
        },
    },
    "required": ["lang", "diagram_type", "classes", "relations"],
}


IR_SCHEMA_ACTIVITY = {
    "type": "object",
    "properties": {
        "lang": {"type": "string", "enum": ["plantuml"]},
        "diagram_type": {"type": "string", "enum": ["activity"]},
        "title": {"type": "string"},
        "comments": {"type": "array", "items": {"type": "string"}},
        "flow": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {"type": "string", "enum": ["action", "note", "branch", "fork"]},
                    "text": {"type": "string"},
                    "condition": {"type": "string"},
                    "then_label": {"type": "string"},
                    "else_label": {"type": "string"},
                    "then": {"type": "array"},
                    "else": {"type": "array"},
                    "branches": {"type": "array"},
                },
                "required": ["type"],
            },
        },
        "steps": {"type": "array"},
    },
}


def ir_schema_for_type(diagram_type: str) -> dict | None:
    return {
        "flowchart": IR_SCHEMA_FLOWCHART,
        "sequence": IR_SCHEMA_SEQUENCE,
        "class": IR_SCHEMA_CLASS,
        "activity": IR_SCHEMA_ACTIVITY,
    }.get(diagram_type)


def _strip_meta(ir: dict) -> dict:
    result = {}
    for k, v in ir.items():
        if k == "_is_modified":
            continue
        if isinstance(v, list):
            result[k] = [_strip_meta(item) if isinstance(item, dict) else item for item in v]
        elif isinstance(v, dict):
            result[k] = _strip_meta(v)
        else:
            result[k] = v
    return result


def validate_ir(ir: dict, diagram_type: str) -> tuple[bool, list[str]]:
    schema = ir_schema_for_type(diagram_type)
    if not schema:
        return True, [f"Unknown diagram type: {diagram_type} (will attempt builder with type normalization)"]
    clean = _strip_meta(ir)
    errors = []
    _validate_against_schema(clean, schema, errors, "$")
    if errors:
        return True, errors
    return True, []


def _validate_against_schema(data: Any, schema: dict, errors: list[str], path: str):
    if schema.get("type") == "object":
        if not isinstance(data, dict):
            errors.append(f"{path}: expected object")
            return
        required = schema.get("required", [])
        for field in required:
            if field not in data:
                errors.append(f"{path}: missing required field '{field}'")
        props = schema.get("properties", {})
        for key, val in data.items():
            if key in props:
                _validate_against_schema(val, props[key], errors, f"{path}.{key}")
            elif key not in required and not key.startswith("_"):
                pass

    elif schema.get("type") == "array":
        if not isinstance(data, list):
            errors.append(f"{path}: expected array")
            return
        item_schema = schema.get("items", {})
        for i, item in enumerate(data):
            _validate_against_schema(item, item_schema, errors, f"{path}[{i}]")

    elif schema.get("type") == "string":
        if not isinstance(data, str):
            errors.append(f"{path}: expected string, got {type(data).__name__}")
            return
        enum_vals = schema.get("enum")
        if enum_vals and data not in enum_vals:
            errors.append(f"{path}: '{data}' not in {enum_vals}")

    elif schema.get("type") == "boolean":
        if not isinstance(data, bool):
            errors.append(f"{path}: expected boolean")
