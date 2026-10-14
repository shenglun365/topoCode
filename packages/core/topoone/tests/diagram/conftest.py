"""Diagram-kernel test fixtures.

Provides cross-repo artifact paths (plantuml jar / web bundle) with skip guards
so the migrated tests run in the main project even before those artifacts exist.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# packages/core/topoone/tests/diagram/conftest.py -> repo root = parents[5]
REPO_ROOT = Path(__file__).resolve().parents[5]

WEB_BUNDLE = REPO_ROOT / "packages" / "web-core" / "dist-topoone" / "topo-one.js"

PLANTUML_JAR = Path(os.environ.get("TOPOONE_PLANTUML_JAR", "~/.topocode/plantuml.jar")).expanduser()

REQUIRE_JAR = pytest.mark.skipif(
    not PLANTUML_JAR.exists(),
    reason=f"plantuml jar not present ({PLANTUML_JAR}); set TOPOONE_PLANTUML_JAR",
)

REQUIRE_BUNDLE = pytest.mark.skipif(
    not WEB_BUNDLE.exists(),
    reason=f"web bundle not built ({WEB_BUNDLE}); run web-core build:topoone-browser",
)
