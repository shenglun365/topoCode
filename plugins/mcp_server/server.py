"""MCP Server — independent process (port 3460).

Exposes Model Context Protocol for external tools/agents.
Provides controlled access to architecture knowledge base: tool calls are
forwarded to the standalone architect service (default 3470) and recorded in
architect's External Call log (`POST /api/architect/mcp/calls`).
"""

import json
import logging
import os
import urllib.request

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

PORT = int(os.environ.get("MCP_SERVER_PORT", "3460"))
ARCHITECT_API = os.environ.get("ARCHITECT_API_URL", "http://127.0.0.1:3470/api/architect").rstrip("/")
app = FastAPI(title="TopoCode MCP Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


_TOOLS = [
    {"name": "arch.read", "description": "Read a file / architecture symbol from the bound project"},
    {"name": "arch.write", "description": "Propose a file/content write to the bound project"},
    {"name": "arch.invoke", "description": "Invoke a coding-agent task (analysis/execution)"},
    {"name": "arch.status", "description": "Query current bound project & KB status"},
]


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-server", "port": PORT}


@app.get("/v1/tools")
async def list_tools():
    """List available MCP tools."""
    return {"tools": _TOOLS}


def _forward_call(tool_name: str, params: dict) -> dict:
    """转发到 architect：记录外部调用并取回结果。architect 不可达时返回 ok:False。"""
    url = f"{ARCHITECT_API}/mcp/calls"
    record = {
        "tool": tool_name, "input": params, "status": "ok", "output": None,
    }
    try:
        req = urllib.request.Request(
            url, data=json.dumps(record).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode())
        if body.get("code") == 0:
            return {"ok": True, "tool": tool_name, "params": params, "call": body.get("data")}
        return {"ok": False, "tool": tool_name, "error": body.get("message", "architect rejected")}
    except Exception as e:
        logger.warning("[MCP] architect unreachable: %s", e)
        return {"ok": False, "tool": tool_name, "error": f"architect unreachable ({e})"}


@app.post("/v1/tools/{tool_name}/call")
async def call_tool(tool_name: str, request: Request):
    """Execute an MCP tool — forwarded to the architect service."""
    body = await request.json()
    logger.info(f"MCP tool call: {tool_name}")
    return _forward_call(tool_name, body or {})


def main():
    logging.basicConfig(level=logging.INFO)
    logger.info(f"Starting MCP Server on port {PORT} (architect: {ARCHITECT_API})")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
