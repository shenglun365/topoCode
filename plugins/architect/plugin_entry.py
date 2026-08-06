"""Architect plugin — standalone service.

Architect now runs as its own process (plugins/architect/__main__.py, port 3470),
serving its own SPA + /api/architect, and owns architect.db + KbGateway to KB.
This file stays a no-op placeholder so PluginManager.discover() doesn't warn;
the real entry is `__main__.py` (spawned by backend main.py / Supervisor).
"""

import logging

logger = logging.getLogger(__name__)


def register_methods(server, multi_db):
    """No-op — architect is served by its own process (plugins/architect/__main__.py)."""
    pass
