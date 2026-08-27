"""topo_one.diagrams — diagram render/validate/report service library.

Drop-in subpackage for the host core framework (main project:
``packages/core/topoone/diagrams/``). Public API:

- DiagramSettings / DiagramServices (settings, lifecycle)
- create_topo_router (FastAPI router factory under /topo)
- PlantUmlSidecar / find_plantuml_jar, RenderPool / RenderError / RenderUnavailable
- build_report / ReportEntry (HTML report, pure functions)
"""

from .lifecycle import DiagramServices
from .plantuml_sidecar import PlantUmlError, PlantUmlSidecar, find_plantuml_jar
from .render_pool import RenderError, RenderPool, RenderUnavailable
from .router import create_topo_router, resolve_engine
from .settings import DiagramSettings

__all__ = [
    "DiagramSettings",
    "DiagramServices",
    "PlantUmlError",
    "PlantUmlSidecar",
    "find_plantuml_jar",
    "RenderError",
    "RenderPool",
    "RenderUnavailable",
    "create_topo_router",
    "resolve_engine",
]
