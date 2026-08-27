"""Test harness: assemble create_topo_router into a runnable FastAPI app.

Mirrors the animation repo's standalone app.main harness so migrated tests run
without the animation repo.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from topoone.diagram.diagrams import DiagramServices, DiagramSettings, create_topo_router


def create_app(diag: DiagramSettings | None = None,
               services: DiagramServices | None = None,
               fallback_renderer=None) -> FastAPI:
    if diag is None:
        diag = DiagramSettings(render_pool_size=0, plantuml_enabled=False)
    svc = services or DiagramServices(diag)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await svc.start()
        yield
        await svc.stop()

    app = FastAPI(title="topo-one (test)", lifespan=lifespan)
    app.state.diagram_services = svc
    app.include_router(create_topo_router(svc, fallback_renderer=fallback_renderer))
    return app
