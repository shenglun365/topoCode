"""Topo-one diagram router factory.

``create_topo_router(services, fallback_renderer=...)`` builds a self-contained
APIRouter under the ``/topo`` prefix:

- POST /topo/render/mermaid     raw mermaid code -> {svg, warnings} (headless pool)
- POST /topo/render/schema      DiagramSchema -> {engine, svg, warnings} (auto negotiation)
- POST /topo/render/plantuml    raw plantuml code -> {svg} (sidecar-first, injected fallback)
- POST /topo/plantuml/svg       kroki-style alias: raw body -> image/svg+xml
                                (PlantUmlEngine 'post-raw' protocol / main-project convention)
- POST /topo/validate           agent-friendly validation (L1-L4 + optional L5):
                                {schema | code, engine?, check_render?} -> {ok, errors, warnings},
                                always HTTP 200 (report contract, see topo_one.validation)
- POST /topo/validate/plantuml  raw code -> {valid, error}
- POST /topo/export/report      mixed code/schema diagrams -> self-contained HTML
- GET  /topo/health             {plantuml, render}
- GET  /internal/*              worker page + bundle assets (debug; pool itself needs no HTTP)

The factory takes no host-app knowledge: the sidecar + render pool live in
``DiagramServices``; the plantuml fallback renderer is injected (main project
passes ``topoone.engine.plantuml_service.render_plantuml``) so this package has
zero imports from the host project.
"""

from __future__ import annotations

import json
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field

from ..capabilities import DIAGRAM_TYPES, pick_engine, supports_type
from ..encoder import decode as decode_plantuml
from ..report import ReportEntry, build_report
from ..validation import validate_schema_document
from .lifecycle import DiagramServices
from .plantuml_cli import PlantUmlError
from .render_pool import RenderError, build_worker_html

FALLBACK_RENDERER = Callable[[str], bytes]


# ── engine negotiation (shared by /render/schema and /export/report) ────────


def resolve_engine(engine: str, diagram_type: str) -> str:
    if diagram_type not in DIAGRAM_TYPES:
        raise HTTPException(400, f"unknown diagram type: {diagram_type!r}")
    if engine == "auto":
        picked = pick_engine(diagram_type)
        if picked is None:
            raise HTTPException(400, f"no engine supports type {diagram_type!r}")
        return picked
    if supports_type(engine, diagram_type) not in ("native", "emulated"):
        alt = pick_engine(diagram_type)
        raise HTTPException(400, f"engine {engine!r} cannot render type {diagram_type!r}" + (f"; try {alt!r}" if alt else ""))
    return engine


# ── plantuml: cli-first, injected fallback ────────────────────────────────


def _render_plantuml(services: DiagramServices, code: str, fmt: str,
                     fallback: FALLBACK_RENDERER | None) -> bytes:
    sc = services.sidecar
    if sc is not None and sc.is_up():
        try:
            return sc.render(code, fmt)
        except PlantUmlError as e:
            raise HTTPException(e.status or 502, str(e))
    if fallback is not None:
        try:
            return fallback(code)
        except Exception as e:
            raise HTTPException(502, f"plantuml fallback render failed: {e}")
    raise HTTPException(503, "plantuml unavailable: cli down and no fallback configured")


def _validate_plantuml(services: DiagramServices, code: str,
                       fallback: FALLBACK_RENDERER | None) -> dict:
    sc = services.sidecar
    if sc is not None and sc.is_up():
        valid, error = sc.validate(code)
        return {"valid": valid, "error": error}
    if fallback is not None:
        try:
            fallback(code)
            return {"valid": True, "error": None}
        except Exception as e:
            return {"valid": False, "error": str(e)}
    raise HTTPException(503, "plantuml unavailable: cli down and no fallback configured")


# ── L5 render-level checks (async facilities: plantuml cli / pool) ─────────


def _unavailable(path: str, message: str) -> dict:
    return {"ok": True, "errors": [], "warnings": [{"level": "render", "code": "RENDER_UNAVAILABLE", "path": path, "message": message}]}


async def _validate_code(services: DiagramServices, code: str, engine: str,
                         fallback: FALLBACK_RENDERER | None) -> dict:
    if engine == "plantuml":
        sc = services.sidecar
        if sc is not None and sc.is_up():
            valid, error = sc.validate(code)
            if valid:
                return {"ok": True, "errors": [], "warnings": []}
            return {"ok": False,
                    "errors": [{"level": "render", "code": "RENDER_FAILED", "path": "/code",
                                "message": f"plantuml syntax error: {error}"}],
                    "warnings": []}
        if fallback is not None:
            try:
                fallback(code)
                return {"ok": True, "errors": [], "warnings": []}
            except Exception as e:
                return {"ok": False,
                        "errors": [{"level": "render", "code": "RENDER_FAILED", "path": "/code",
                                    "message": f"plantuml render failed: {e}"}],
                        "warnings": []}
        return _unavailable("/code", "plantuml sidecar down and no fallback configured; syntax not checked")
    if engine != "mermaid":
        return {"ok": False,
                "errors": [{"level": "request", "code": "INVALID_REQUEST", "path": "/engine",
                            "message": f"engine '{engine}' cannot be syntax-checked; use 'mermaid' or 'plantuml'"}],
                "warnings": []}
    pool = services.pool
    if pool is None or not pool.available:
        return _unavailable("/code", "render pool unavailable; mermaid syntax not checked")
    try:
        await pool.render({"engine": "mermaid", "code": code})
        return {"ok": True, "errors": [], "warnings": []}
    except RenderError as e:
        return {"ok": False,
                "errors": [{"level": "render", "code": "RENDER_FAILED", "path": "/code",
                            "message": f"mermaid syntax error: {e}"}],
                "warnings": []}


async def _render_check_schema(services: DiagramServices, doc: dict, engine: str) -> dict:
    """L5 for a structurally-valid schema: negotiate engine and dry-render headless."""
    try:
        engine = resolve_engine(engine, doc.get("type"))
    except HTTPException as e:
        return {"ok": False,
                "errors": [{"level": "request", "code": "INVALID_REQUEST", "path": "/engine",
                            "message": str(e.detail)}],
                "warnings": []}
    pool = services.pool
    if pool is None or not pool.available:
        return _unavailable("/schema", "render pool unavailable; schema not dry-rendered")
    try:
        await pool.render({"engine": engine, "schema": doc})
        return {"ok": True, "errors": [], "warnings": []}
    except RenderError as e:
        return {"ok": False,
                "errors": [{"level": "render", "code": "RENDER_FAILED", "path": "/schema",
                            "message": f"{engine} render failed: {e}"}],
                "warnings": []}


# ── request models ──────────────────────────────────────────────────────────


class RenderMermaidRequest(BaseModel):
    code: str
    theme: str = "dark"


class RenderPlantUmlRequest(BaseModel):
    code: str
    format: str = "svg"


class ValidatePlantUmlRequest(BaseModel):
    code: str


class ValidateSourceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: dict | str | None = Field(default=None, alias="schema")
    code: str | None = None
    engine: str = "auto"
    check_render: bool = False


class RenderSchemaRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: dict = Field(alias="schema")
    engine: str = "auto"
    theme: str = "dark"
    policy: str = "drop"


class ReportDiagram(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    title: str | None = None
    engine: str = "auto"
    code: str | None = None
    schema_: dict | None = Field(default=None, alias="schema")


class ReportRequest(BaseModel):
    title: str = "topo-one report"
    theme: str = "dark"
    animation: bool = True
    diagrams: list[ReportDiagram]


# ── factory ─────────────────────────────────────────────────────────────────


def create_topo_router(
    services: DiagramServices,
    *,
    fallback_renderer: FALLBACK_RENDERER | None = None,
    prefix: str = "/topo",
) -> APIRouter:
    router = APIRouter(prefix=prefix)

    def _pool():
        pool = services.pool
        if pool is None or not pool.available:
            reason = pool.error if pool else "render pool disabled (size=0 or not started)"
            raise HTTPException(503, reason)
        return pool

    # ── headless rendering (web bundle in chromium) ────────────

    @router.post("/render/mermaid")
    async def render_mermaid(req: RenderMermaidRequest) -> dict:
        try:
            result = await _pool().render({"engine": "mermaid", "code": req.code}, theme=req.theme)
        except RenderError as e:
            raise HTTPException(400, str(e))
        return {"svg": result["svg"], "warnings": result["warnings"]}

    @router.post("/render/schema")
    async def render_schema(req: RenderSchemaRequest) -> dict:
        engine = resolve_engine(req.engine, req.schema_.get("type"))
        try:
            result = await _pool().render(
                {"engine": engine, "schema": req.schema_},
                theme=req.theme,
                policy=req.policy,
            )
        except RenderError as e:
            raise HTTPException(400, str(e))
        return {"engine": engine, "svg": result["svg"], "warnings": result["warnings"]}

    # ── plantuml (sidecar-first, injected fallback) ────────────

    @router.post("/render/plantuml")
    async def render_plantuml(req: RenderPlantUmlRequest) -> Response:
        if req.format not in ("svg", "png"):
            raise HTTPException(400, f"unsupported format: {req.format}")
        data = _render_plantuml(services, req.code, req.format, fallback_renderer)
        media = "image/svg+xml" if req.format == "svg" else "image/png"
        return Response(content=data, media_type=media)

    @router.post("/plantuml/svg")
    async def plantuml_svg(request: Request) -> Response:
        """Unified CLI endpoint: accepts JSON {source} (engine 'post-json' protocol,
        topo-animation contract docs/plantuml-cli-migration.md) or raw body
        (kroki-style 'post-raw' alias). -> image/svg+xml; 400 + error svg on syntax error."""
        ctype = (request.headers.get("content-type") or "").lower()
        if "application/json" in ctype:
            payload = await request.json()
            body = payload.get("source") if isinstance(payload, dict) else None
            body = body if isinstance(body, str) else ""
        else:
            body = (await request.body()).decode("utf-8", errors="replace")
        if not body.strip():
            raise HTTPException(400, "empty plantuml code")
        data = _render_plantuml(services, body, "svg", fallback_renderer)
        return Response(content=data, media_type="image/svg+xml")

    @router.get("/svg/{encoded}")
    async def plantuml_svg_encoded(encoded: str) -> Response:
        """GET-encoded alias for the web PlantUmlEngine 'get-encoded' protocol:
        ``GET {base}/svg/{plantuml-encoded}`` -> image/svg+xml (Kroki-compatible)."""
        try:
            code = decode_plantuml(encoded)
        except ValueError as e:
            raise HTTPException(400, str(e))
        if not code.strip():
            raise HTTPException(400, "empty plantuml code after decode")
        data = _render_plantuml(services, code, "svg", fallback_renderer)
        return Response(content=data, media_type="image/svg+xml")

    @router.post("/validate/plantuml")
    async def validate_plantuml(req: ValidatePlantUmlRequest) -> dict:
        return _validate_plantuml(services, req.code, fallback_renderer)

    @router.post("/validate")
    async def validate_source(req: ValidateSourceRequest) -> dict:
        """Agent-friendly validation, always 200 with the report contract.

        schema source -> L1 (JSON parse) + L2 (structure) + L3 (semantics)
                        + L4 (animation consistency) [+ L5 if check_render]
        code source   -> L5 (engine syntax: mermaid pool / plantuml sidecar)
        """
        if (req.schema_ is None) == (req.code is None):
            return {"ok": False,
                    "errors": [{"level": "request", "code": "INVALID_REQUEST", "path": "/",
                                "message": "provide exactly one of 'schema' or 'code'"}],
                    "warnings": []}
        if req.code is not None:
            return await _validate_code(services, req.code, req.engine, fallback_renderer)

        report = validate_schema_document(req.schema_)
        if report["ok"] and req.check_render:
            doc = req.schema_ if isinstance(req.schema_, dict) else json.loads(req.schema_)
            l5 = await _render_check_schema(services, doc, req.engine)
            if not l5["ok"]:
                report["ok"] = False
                report["errors"].extend(l5["errors"])
            report["warnings"].extend(l5["warnings"])
        return report

    # ── report export ──────────────────────────────────────────

    @router.post("/export/report")
    async def export_report(req: ReportRequest, request: Request, download: bool = False) -> Response:
        pool = _pool()
        if not req.diagrams:
            raise HTTPException(400, "diagrams must not be empty")

        entries: list[ReportEntry] = []
        for i, d in enumerate(req.diagrams, start=1):
            title = d.title or f"Diagram {i}"
            if bool(d.code) == bool(d.schema_):
                entries.append(ReportEntry(engine=d.engine, title=title, error="provide exactly one of 'code' or 'schema'"))
                continue
            try:
                if d.schema_ is not None:
                    engine = resolve_engine(d.engine, d.schema_.get("type"))
                    source = {"engine": engine, "schema": d.schema_}
                else:
                    if d.engine == "auto":
                        entries.append(ReportEntry(engine="?", title=title, error="raw 'code' requires an explicit engine"))
                        continue
                    engine = d.engine
                    source = {"engine": engine, "code": d.code}
                result = await pool.render(source, theme=req.theme, want_animation=req.animation)
                entries.append(
                    ReportEntry(
                        engine=engine,
                        title=title,
                        svg=result["svg"],
                        warnings=result["warnings"],
                        animation=result.get("animation"),
                    )
                )
            except HTTPException:
                raise
            except RenderError as e:
                entries.append(ReportEntry(engine=engine, title=title, error=str(e)))
            except Exception as e:
                entries.append(ReportEntry(engine=d.engine, title=title, error=str(e).splitlines()[0]))

        html_doc = build_report(req.title, entries, theme=req.theme)
        headers = {}
        if download:
            headers["Content-Disposition"] = 'attachment; filename="topo-one-report.html"'
        return Response(content=html_doc, media_type="text/html; charset=utf-8", headers=headers)

    # ── health & debug assets ──────────────────────────────────

    @router.get("/health")
    async def health() -> dict:
        return services.status()

    @router.get("/internal/worker.html", include_in_schema=False)
    def worker_html() -> Response:
        path = services.settings.render_bundle
        if not path.exists():
            raise HTTPException(503, f"web bundle not built at {path}")
        return Response(content=build_worker_html(path.read_text(encoding="utf-8")), media_type="text/html; charset=utf-8")

    @router.get("/internal/bundle.js", include_in_schema=False)
    def worker_bundle() -> Response:
        path = services.settings.render_bundle
        if not path.exists():
            raise HTTPException(503, f"web bundle not built at {path}")
        return Response(content=path.read_bytes(), media_type="text/javascript; charset=utf-8")

    @router.get("/internal/{filename}", include_in_schema=False)
    def worker_asset(filename: str) -> Response:
        if not filename.endswith(".js") or "/" in filename or ".." in filename:
            raise HTTPException(404)
        path = services.settings.render_bundle.parent / filename
        if not path.is_file():
            raise HTTPException(404)
        return Response(content=path.read_bytes(), media_type="text/javascript; charset=utf-8")

    return router
