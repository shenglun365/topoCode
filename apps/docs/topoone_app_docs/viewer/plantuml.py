"""PlantUML 代理/缓存 + rebuild 路由（MS5-V2 自 viewer.py 切分）。"""
import hashlib
import logging

from fastapi import APIRouter, HTTPException, Query, Request, Response

from topoone import service_common as common
import logging
logger = logging.getLogger(__name__)

router = APIRouter()

# ── PlantUML ──

@router.get("/api/plantuml")
async def render_plantuml(code: str = Query(...)):
    if not common.multi_db:
        raise HTTPException(503, "Backend not ready")
    try:
        code_hash = hashlib.md5(code.encode("utf-8")).hexdigest()
        cached = common._get_cached_plantuml(code_hash)
        if cached:
            return Response(content=cached, media_type="image/svg+xml")
        from topoone.engine.plantuml_service import render_plantuml as render_pu
        svg_bytes = render_pu(code, format="svg", use_remote=True)
        svg_text = svg_bytes.decode("utf-8", errors="replace")
        common._set_cached_plantuml(code_hash, code, svg_text)
        return Response(content=svg_text, media_type="image/svg+xml")
    except Exception as e:
        raise HTTPException(500, f"PlantUML render failed: {e}")

@router.post("/api/plantuml")
async def render_plantuml_post(request: Request):
    import logging
    logger = logging.getLogger(__name__)
    try:
        body = await request.body()
        code = body.decode("utf-8", errors="replace")
        if not code or not code.strip():
            raise HTTPException(400, "Empty PlantUML code")
        if not common.multi_db:
            raise HTTPException(503, "Backend not ready")
        code_hash = hashlib.md5(code.encode("utf-8")).hexdigest()
        cached = common._get_cached_plantuml(code_hash)
        if cached:
            return Response(content=cached, media_type="image/svg+xml")
        from topoone.engine.plantuml_service import render_plantuml as render_pu
        from topoone.engine.plantuml_service import PLANTUML_SERVER as _pu_srv
        logger.info(f"POST /api/plantuml: PLANTUML_SERVER={_pu_srv} code_len={len(code)}")
        svg_bytes = render_pu(code, format="svg", use_remote=True)
        svg_text = svg_bytes.decode("utf-8", errors="replace")
        common._set_cached_plantuml(code_hash, code, svg_text)
        return Response(content=svg_text, media_type="image/svg+xml")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/plantuml failed")
        raise HTTPException(500, f"PlantUML render failed: {e}")


@router.get("/api/plantuml/clear-cache")
async def clear_plantuml_cache():
    common._clear_plantuml_cache()
    return {"status": "ok"}


# ── Diagram Rebuild API (Parser + Template) ──

@router.post("/api/plantuml/rebuild")
async def rebuild_plantuml(request: Request):
    try:
        body = await request.json()
        code: str = body.get("code", "")
        diag_type: str = body.get("type", "auto")
        if not code or not code.strip():
            raise HTTPException(400, "Empty code")
        from ..diagram import rebuild_plantuml as _rebuild
        try:
            result = _rebuild(code, diag_type if diag_type != "auto" else None)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/plantuml/rebuild failed")
        raise HTTPException(500, f"Rebuild failed: {e}")


@router.post("/api/mermaid/rebuild")
async def rebuild_mermaid(request: Request):
    try:
        body = await request.json()
        code: str = body.get("code", "")
        diag_type: str = body.get("type", "auto")
        if not code or not code.strip():
            raise HTTPException(400, "Empty code")
        from ..diagram import rebuild_mermaid as _rebuild
        try:
            result = _rebuild(code, diag_type if diag_type != "auto" else None)
        except ValueError as e:
            raise HTTPException(422, str(e))
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("POST /api/mermaid/rebuild failed")
        raise HTTPException(500, f"Rebuild failed: {e}")
