"""Capability matrix access - single source of truth is schema/capabilities.json."""

from __future__ import annotations

import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent / "schema_data"

DIAGRAM_TYPES = [
    "flowchart", "activity", "sequence", "state", "class",
    "er", "usecase", "component", "architecture", "gantt", "pie",
]


def load_capabilities() -> dict:
    return json.loads((SCHEMA_DIR / "capabilities.json").read_text(encoding="utf-8"))


def load_diagram_schema() -> dict:
    return json.loads((SCHEMA_DIR / "diagram.schema.json").read_text(encoding="utf-8"))


def supports_type(engine: str, diagram_type: str) -> str:
    caps = load_capabilities()
    return caps["engines"].get(engine, {}).get("types", {}).get(diagram_type, "unsupported")


def pick_engine(diagram_type: str, engines: list[str] | None = None) -> str | None:
    """Mirror of web's pickEngine: prefer native support, then emulated, in engine order."""
    caps = load_capabilities()
    engine_order = engines or list(caps["engines"].keys())
    for support in ("native", "emulated"):
        for engine in engine_order:
            if supports_type(engine, diagram_type) == support:
                return engine
    return None
