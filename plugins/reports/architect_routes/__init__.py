"""Architect API routes — merged into reports FastAPI app.

All routes mount at /api/architect/* prefix.
Uses common.multi_db and common.zmq_server directly (no proxy hop).
"""

from fastapi import APIRouter

from . import project, knowledge, requirements, execution, arch_change, mcp_collab, websocket

router = APIRouter(prefix="/api/architect")
router.include_router(project.router)
router.include_router(knowledge.router)
router.include_router(requirements.router)
router.include_router(execution.router)
router.include_router(arch_change.router)
router.include_router(mcp_collab.router)
router.include_router(websocket.router)
