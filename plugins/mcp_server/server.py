"""MCP Server — independent process (port 3460).

Exposes Model Context Protocol for external tools/agents.
Provides controlled access to architecture knowledge base.
"""

import logging
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)

PORT = int(os.environ.get("MCP_SERVER_PORT", "3460"))
app = FastAPI(title="TopoCode MCP Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mcp-server", "port": PORT}


@app.get("/v1/tools")
async def list_tools():
    """List available MCP tools."""
    return {
        "tools": [
            {"name": "kb.query", "description": "Query architecture knowledge base"},
            {"name": "arch.search", "description": "Search architecture components"},
            {"name": "spec.get", "description": "Get architecture specification"},
        ]
    }


@app.post("/v1/tools/{tool_name}/call")
async def call_tool(tool_name: str, request: Request):
    """Execute an MCP tool."""
    body = await request.json()
    logger.info(f"MCP tool call: {tool_name}")
    return {"ok": True, "tool": tool_name, "params": body}


def main():
    logging.basicConfig(level=logging.INFO)
    logger.info(f"Starting MCP Server on port {PORT}")
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")


if __name__ == "__main__":
    main()
