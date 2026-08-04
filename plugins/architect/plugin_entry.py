"""Architect plugin — legacy entry point.

Architect API is now merged directly into plugins/reports/architect_routes/.
This file exists as a no-op placeholder so PluginManager.discover() doesn't warn.
The actual routes are served by the reports FastAPI app at /api/architect/*.
"""

import logging

logger = logging.getLogger(__name__)


def register_methods(server, multi_db):
    """No-op — architect routes are in plugins/reports/architect_routes/"""
    pass
