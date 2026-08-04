"""MCP logs, collaboration mode, interactions."""
from fastapi import APIRouter, Request
from .common import _ts, _id, ok, err

router = APIRouter()


@router.get("/mcp/calls")
async def list_mcp_calls():
    return ok([])


@router.post("/mcp/calls")
async def record_mcp_call(request: Request):
    body = await request.json()
    return ok(body)


@router.get("/collab/mode")
async def get_collab_mode():
    return ok({"mode": "main-agent"})


@router.put("/collab/mode")
async def set_collab_mode(request: Request):
    body = await request.json()
    return ok(body)


@router.get("/collab/interactions")
async def list_interactions():
    return ok([])


@router.post("/collab/interactions")
async def create_interaction(request: Request):
    body = await request.json()
    return ok(body)


@router.post("/collab/interactions/{interaction_id}/resolve")
async def resolve_interaction(interaction_id: str, request: Request):
    body = await request.json()
    return ok({"id": interaction_id, "status": "resolved", "answer": body.get("answer")})


@router.get("/health")
async def health():
    return {"status": "ok", "service": "architect-api"}
