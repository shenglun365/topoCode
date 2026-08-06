"""MCP logs, collaboration mode, interactions, KB connection config (sqlite-backed)."""
import json
import logging
import urllib.error
import urllib.request
from fastapi import APIRouter, Request
from .common import _ts, _id, ok, err
from . import store

logger = logging.getLogger(__name__)
router = APIRouter()

DEFAULT_DATA_API = "http://127.0.0.1:3459"
DEFAULT_MCP_URL = "http://127.0.0.1:3460"

_KB_KEYS = ("dataApiUrl", "mcpUrl", "lastStatus", "lastDetail", "lastCheckAt", "updatedAt")


def get_kb_config() -> dict:
    return {
        "dataApiUrl": store.CollabConfigStore.get("kb.dataApiUrl", DEFAULT_DATA_API),
        "mcpUrl": store.CollabConfigStore.get("kb.mcpUrl", DEFAULT_MCP_URL),
        "lastStatus": store.CollabConfigStore.get("kb.lastStatus", "unknown"),
        "lastDetail": store.CollabConfigStore.get("kb.lastDetail", ""),
        "lastCheckAt": int(store.CollabConfigStore.get("kb.lastCheckAt", "0") or 0),
        "updatedAt": int(store.CollabConfigStore.get("kb.updatedAt", "0") or 0),
    }


def _save_kb_config(data: dict) -> None:
    for k, v in data.items():
        store.CollabConfigStore.set(f"kb.{k}", "" if v is None else str(v))


def probe_kb(cfg: dict) -> dict:
    """KB 连通性测试：data_api /health + MCP /health。"""
    data_api = (cfg.get("dataApiUrl") or DEFAULT_DATA_API).rstrip("/")
    mcp = (cfg.get("mcpUrl") or DEFAULT_MCP_URL).rstrip("/")
    failures = []
    for label, url in (("data_api", f"{data_api}/health"), ("mcp", f"{mcp}/health")):
        try:
            with urllib.request.urlopen(urllib.request.Request(url), timeout=3) as resp:
                if resp.status != 200:
                    failures.append(f"{label}: HTTP {resp.status}")
        except urllib.error.URLError as e:
            failures.append(f"{label}: {getattr(e, 'reason', e)}")
        except Exception as e:
            failures.append(f"{label}: {e}")
    if failures:
        return {"status": "fail", "detail": "；".join(failures)}
    return {"status": "ok", "detail": "KB data_api 与 MCP 均可达"}


@router.get("/kb/config")
async def get_kb_config_route():
    """获取知识库连接配置(不含凭据)。"""
    return ok(get_kb_config())


@router.put("/kb/config")
async def set_kb_config_route(request: Request):
    """保存知识库连接配置。Body: { dataApiUrl?, mcpUrl? }"""
    body = await request.json() or {}
    now = _ts()
    data = {
        "dataApiUrl": (body.get("dataApiUrl") or DEFAULT_DATA_API).strip(),
        "mcpUrl": (body.get("mcpUrl") or DEFAULT_MCP_URL).strip(),
        "updatedAt": now,
    }
    _save_kb_config(data)
    return ok(get_kb_config())


@router.post("/kb/config/test")
async def test_kb_config_route():
    """知识库连通性测试(data_api + MCP)，写回 last_status。"""
    now = _ts()
    result = probe_kb(get_kb_config())
    _save_kb_config({"lastStatus": result["status"], "lastDetail": result["detail"], "lastCheckAt": now})
    return ok({**get_kb_config(), "test": result})


@router.get("/mcp/calls")
async def list_mcp_calls():
    return ok(store.McpCallsStore.all())


@router.post("/mcp/calls")
async def record_mcp_call(request: Request):
    body = await request.json()
    call = {
        "id": store.next_id("mcp"), "tool": body.get("tool", ""),
        "input": body.get("input"), "output": body.get("output"),
        "status": body.get("status", ""), "time": _ts(),
    }
    store.McpCallsStore.create(call)
    return ok(call)


@router.get("/collab/mode")
async def get_collab_mode():
    return ok({"mode": store.CollabConfigStore.get("mode", "main-agent")})


@router.put("/collab/mode")
async def set_collab_mode(request: Request):
    body = await request.json()
    mode = body.get("mode", "main-agent")
    store.CollabConfigStore.set("mode", mode)
    return ok({"mode": mode})


@router.get("/collab/interactions")
async def list_interactions():
    return ok(store.InteractionsStore.all())


@router.post("/collab/interactions")
async def create_interaction(request: Request):
    body = await request.json()
    interaction = {
        "id": store.next_id("it"), "prompt": body.get("prompt", ""),
        "status": body.get("status", ""), "answer": body.get("answer", ""),
        "time": _ts(),
    }
    store.InteractionsStore.create(interaction)
    return ok(interaction)


@router.post("/collab/interactions/{interaction_id}/resolve")
async def resolve_interaction(interaction_id: str, request: Request):
    body = await request.json()
    row = store.InteractionsStore.update(interaction_id, {
        "status": "resolved", "answer": body.get("answer"),
    })
    if not row:
        return err(404, "Interaction not found")
    return ok(row)


@router.get("/health")
async def health():
    return {"status": "ok", "service": "architect-api"}
