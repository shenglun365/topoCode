"""topo-one unified diagram kernel.

Unified IR = DiagramSchema (schema.py / schema_data/diagram.schema.json), the
single source of truth shared with the TS kernel. Legacy per-type IR (produced by
in-production agent tools / the docs diagram editor) is normalized via compat.py,
and the battle-tested Python builder (builder/) consumes DiagramSchema through the
same adapter.

Public API:
- DiagramSchema / DIAGRAM_TYPES / capabilities access
- legacy_ir_to_schema / schema_to_legacy_ir / is_legacy_ir (IR convergence)
- build_from_ir (legacy shape -> mermaid/plantuml code, used by agent tools)
"""

from .capabilities import DIAGRAM_TYPES, load_capabilities, supports_type
from .schema import DiagramSchema
from .compat import is_legacy_ir, legacy_ir_to_schema, schema_to_legacy_ir
from .builder import build_from_ir

__all__ = [
    "DIAGRAM_TYPES",
    "DiagramSchema",
    "load_capabilities",
    "supports_type",
    "is_legacy_ir",
    "legacy_ir_to_schema",
    "schema_to_legacy_ir",
    "build_from_ir",
]
