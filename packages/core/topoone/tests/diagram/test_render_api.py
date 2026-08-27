from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ._harness import create_app
from topoone.diagram.diagrams import DiagramServices, DiagramSettings
from topoone.diagram.diagrams.plantuml_sidecar import PlantUmlError
from topoone.diagram.diagrams.render_pool import RenderError

FLOWCHART_SCHEMA = {
    "version": 1,
    "type": "flowchart",
    "nodes": [{"id": "a", "label": "Start"}, {"id": "b", "label": "Done"}],
    "edges": [{"from": "a", "to": "b"}],
}

GANTT_SCHEMA = {
    "version": 1,
    "type": "gantt",
    "title": "T",
    "sections": [{"id": "s1", "label": "Core"}],
    "tasks": [{"id": "t1", "title": "Alpha", "section": "s1", "start": "2024-01-01", "duration": 5}],
}


class StubPool:
    size = 1
    error = None
    available = True

    def __init__(self, fail: Exception | None = None):
        self.calls: list[tuple[dict, dict]] = []
        self._fail = fail

    async def render(self, source: dict, **kwargs) -> dict:
        if self._fail is not None:
            raise self._fail
        self.calls.append((source, kwargs))
        return {"svg": "<svg>stub</svg>", "warnings": [], "animation": None}


def make_app(tmp_path: Path, pool=None, **diag_kwargs):
    diag = DiagramSettings(render_pool_size=0, render_bundle=tmp_path / "topo-one.js", **diag_kwargs)
    services = DiagramServices(diag)
    if pool is not None:
        services.pool = pool
    app = create_app(services=services)
    return app, services


def test_render_mermaid_503_when_pool_disabled(tmp_path: Path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    r = client.post("/topo/render/mermaid", json={"code": "flowchart TD\n  A-->B"})
    assert r.status_code == 503


def test_render_schema_503_when_pool_disabled(tmp_path: Path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    r = client.post("/topo/render/schema", json={"schema": FLOWCHART_SCHEMA})
    assert r.status_code == 503


def test_topo_health_reports_render_state(tmp_path: Path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    body = client.get("/topo/health").json()
    assert body["render"]["available"] is False
    assert body["render"]["slots"] == 0
    assert body["render"]["error"] in (None, "render pool disabled (size=0)")


def test_worker_html_served(tmp_path: Path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.get("/topo/internal/worker.html").status_code == 503

    (tmp_path / "topo-one.js").write_text("window.topoOne = { probe: 42 };")
    r = client.get("/topo/internal/worker.html")
    assert r.status_code == 200
    assert '<div id="host">' in r.text
    assert "window.topoOne = { probe: 42 };" in r.text
    assert "window.__topoReady = true;" in r.text


def test_bundle_route_missing_and_present(tmp_path: Path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.get("/topo/internal/bundle.js").status_code == 503

    (tmp_path / "topo-one.js").write_text("export const x = 1;")
    r = client.get("/topo/internal/bundle.js")
    assert r.status_code == 200
    assert r.text == "export const x = 1;"


def test_chunk_route(tmp_path: Path):
    app, _ = make_app(tmp_path)
    client = TestClient(app)
    assert client.get("/topo/internal/nope.js").status_code == 404
    assert client.get("/topo/internal/..%2Fevil.js").status_code in (400, 404)

    (tmp_path / "chunk-A.js").write_text("chunk")
    r = client.get("/topo/internal/chunk-A.js")
    assert r.status_code == 200
    assert r.text == "chunk"
    assert client.get("/topo/internal/chunk-A.css").status_code == 404


def test_schema_engine_negotiation_auto(tmp_path: Path):
    stub = StubPool()
    app, services = make_app(tmp_path, pool=stub)
    client = TestClient(app)
    r = client.post("/topo/render/schema", json={"schema": GANTT_SCHEMA, "engine": "auto"})
    assert r.status_code == 200
    body = r.json()
    assert body["engine"] == "mermaid"  # plantuml cannot do gantt
    assert body["svg"] == "<svg>stub</svg>"
    source, kwargs = stub.calls[0]
    assert source == {"engine": "mermaid", "schema": GANTT_SCHEMA}
    assert kwargs["policy"] == "drop"


def test_schema_engine_negotiation_explicit_rejected(tmp_path: Path):
    app, _ = make_app(tmp_path, pool=StubPool())
    client = TestClient(app)
    r = client.post("/topo/render/schema", json={"schema": GANTT_SCHEMA, "engine": "plantuml"})
    assert r.status_code == 400
    assert "plantuml" in r.json()["detail"]


def test_schema_unknown_type_rejected(tmp_path: Path):
    app, _ = make_app(tmp_path, pool=StubPool())
    client = TestClient(app)
    r = client.post("/topo/render/schema", json={"schema": {"type": "nope"}, "engine": "auto"})
    assert r.status_code == 400


def test_render_mermaid_via_stub(tmp_path: Path):
    stub = StubPool()
    app, _ = make_app(tmp_path, pool=stub)
    client = TestClient(app)
    r = client.post("/topo/render/mermaid", json={"code": "flowchart TD\n  A-->B", "theme": "light"})
    assert r.status_code == 200
    assert r.json()["svg"] == "<svg>stub</svg>"
    source, kwargs = stub.calls[0]
    assert source["engine"] == "mermaid"
    assert kwargs["theme"] == "light"


def test_render_errors_map_to_400(tmp_path: Path):
    app, _ = make_app(tmp_path, pool=StubPool(fail=RenderError("invalid schema at /type: bad")))
    client = TestClient(app)
    r = client.post("/topo/render/schema", json={"schema": FLOWCHART_SCHEMA})
    assert r.status_code == 400
    assert "invalid schema" in r.json()["detail"]


# ── plantuml: sidecar-first + injected fallback ────────────────────────────


def test_plantuml_fallback_used_when_sidecar_down(tmp_path: Path):
    from topoone.diagram.diagrams.router import create_topo_router
    from fastapi import FastAPI

    diag = DiagramSettings(render_pool_size=0, render_bundle=tmp_path / "topo-one.js", plantuml_enabled=False)
    services = DiagramServices(diag)

    def fallback(code: str) -> bytes:
        assert "Alice" in code
        return b"<svg>fallback</svg>"

    app = FastAPI()
    app.include_router(create_topo_router(services, fallback_renderer=fallback))
    client = TestClient(app)
    r = client.post("/topo/render/plantuml", json={"code": "@startuml\nAlice -> Bob: hi\n@enduml"})
    assert r.status_code == 200
    assert r.text == "<svg>fallback</svg>"
    # kroki alias too
    r = client.post("/topo/plantuml/svg", content=b"@startuml\nAlice -> Bob: hi\n@enduml")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/svg+xml")


def test_plantuml_503_when_sidecar_down_and_no_fallback(tmp_path: Path):
    from topoone.diagram.diagrams.router import create_topo_router
    from fastapi import FastAPI

    diag = DiagramSettings(render_pool_size=0, render_bundle=tmp_path / "topo-one.js", plantuml_enabled=False)
    services = DiagramServices(diag)
    app = FastAPI()
    app.include_router(create_topo_router(services))
    client = TestClient(app)
    r = client.post("/topo/render/plantuml", json={"code": "@startuml\nA -> B: x\n@enduml"})
    assert r.status_code == 503
    r = client.post("/topo/validate/plantuml", json={"code": "@startuml\nA -> B: x\n@enduml"})
    assert r.status_code == 503


def test_plantuml_fallback_error_maps_to_502(tmp_path: Path):
    from topoone.diagram.diagrams.router import create_topo_router
    from fastapi import FastAPI

    diag = DiagramSettings(render_pool_size=0, render_bundle=tmp_path / "topo-one.js", plantuml_enabled=False)
    services = DiagramServices(diag)

    def fallback(code: str) -> bytes:
        raise RuntimeError("Syntax Error in line 2")

    app = FastAPI()
    app.include_router(create_topo_router(services, fallback_renderer=fallback))
    client = TestClient(app)
    r = client.post("/topo/render/plantuml", json={"code": "@startuml\nbad\n@enduml"})
    assert r.status_code == 502
    assert "Syntax Error" in str(r.json()["detail"])


def test_plantuml_sidecar_syntax_error_maps_to_400(tmp_path: Path):
    from topoone.diagram.diagrams.plantuml_sidecar import PlantUmlSidecar
    from fastapi import FastAPI
    from topoone.diagram.diagrams.router import create_topo_router

    diag = DiagramSettings(render_pool_size=0, render_bundle=tmp_path / "topo-one.js", plantuml_enabled=False)
    services = DiagramServices(diag)

    class FakeSidecar:
        def is_up(self):
            return True

        def render(self, code, fmt="svg"):
            raise PlantUmlError("Syntax Error in line 3", status=400)

        def validate(self, code):
            return False, "Syntax Error in line 3"

    services.sidecar = FakeSidecar()
    app = FastAPI()
    app.include_router(create_topo_router(services))
    client = TestClient(app)
    r = client.post("/topo/render/plantuml", json={"code": "@startuml\nbad\n@enduml"})
    assert r.status_code == 400
    r = client.post("/topo/validate/plantuml", json={"code": "@startuml\nbad\n@enduml"})
    assert r.json() == {"valid": False, "error": "Syntax Error in line 3"}
