"""Diagram service settings (env prefix TOPOONE_).

Standalone defaults point into this repo; the main project overrides
``render_bundle`` / ``plantuml_jar`` via env or constructor kwargs.
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[5]


class DiagramSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="TOPOONE_")

    # Headless render pool (N chromium pages running the web IIFE bundle).
    render_pool_size: int = 2
    render_timeout_ms: int = 20000
    render_bundle: Path = REPO_ROOT / "packages" / "web-core" / "dist-topoone" / "topo-one.js"

    # PlantUML sidecar (resident JVM). jar=None -> discovery (see find_plantuml_jar).
    plantuml_enabled: bool = True
    plantuml_port: int = 3491
    plantuml_host: str = "127.0.0.1"
    plantuml_jar: Path | None = None
    plantuml_java: str = "java"
