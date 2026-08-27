"""Shim -> topoone.diagram._validator (single lightweight code-syntax validator).

Moved to core in the diagram-kernel integration (Phase 1). Importing this module
keeps legacy relative imports working; new code should use topoone.diagram.
"""

from topoone.diagram._validator import validate_diagram_syntax

__all__ = ["validate_diagram_syntax"]
