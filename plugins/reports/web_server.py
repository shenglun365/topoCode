"""Web Server entry point — import modules, create app, start uvicorn.

Serves: Viewer, AI Chat, Architect API (merged), Architect SPA.
Manages subprocesses: Coding Agent Runner (3458), MCP Server (3460).
"""

import asyncio
import logging
import os
import signal
import sys

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import common
from web_root import router as web_root_router
from viewer import router as viewer_router
from chat import router as chat_router
from vue_routes import vue_router
from architect_routes import router as architect_router
from web_tools import WebToolExecutor

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

app = FastAPI(title="TopoOne Web Viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:5174",
        "http://127.0.0.1:5173", "http://127.0.0.1:5174",
        "http://localhost:3456", "http://127.0.0.1:3456",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Include routers from modules
app.include_router(web_root_router)
app.include_router(viewer_router)
app.include_router(chat_router)
app.include_router(vue_router)

# Architect API — merged into same process, no proxy hop
app.include_router(architect_router)

# Mount Vue web static files at /web
_web_static = os.path.join(STATIC_DIR, "web")
if os.path.isdir(_web_static):
    app.mount("/web", StaticFiles(directory=_web_static), name="web_vue")

# Mount Architect SPA (production only; dev uses Vite)
# HTML is at STATIC_DIR/architect.html; JS/CSS assets under /web/ (already mounted)
_architect_html = os.path.join(STATIC_DIR, "architect.html")
if os.path.isfile(_architect_html):
    from fastapi.responses import FileResponse

    @app.get("/architect", include_in_schema=False)
    @app.get("/architect/", include_in_schema=False)
    async def serve_architect():
        return FileResponse(_architect_html)


def create_app(multi_db_instance, zmq_server_instance=None) -> FastAPI:
    """Create and configure app with injected dependencies"""
    common.set_globals(multi_db_instance, zmq_server_instance)
    common.web_tool_executor = WebToolExecutor(multi_db_instance)
    common._ensure_chat_tables()
    return app


# ==================== Subprocess Management ====================

RUNNER_PORT = int(os.environ.get("CODING_AGENT_RUNNER_PORT", "3458"))
MCP_PORT = int(os.environ.get("MCP_SERVER_PORT", "3460"))


async def _start_subprocess(script_name: str, port: int, label: str):
    """Start a subprocess and return the process handle."""
    script = os.path.join(os.path.dirname(__file__), "..", script_name)
    script = os.path.abspath(script)
    if not os.path.isfile(script):
        logger.warning(f"{label} script not found at {script}, skipping")
        return None
    proc = await asyncio.create_subprocess_exec(
        sys.executable, script,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env={**os.environ, f"{label.upper().replace(' ', '_')}_PORT": str(port)},
    )
    logger.info(f"{label} started (pid={proc.pid}, port={port})")

    async def _pipe(stream, lbl):
        while True:
            line = await stream.readline()
            if not line:
                break
            logger.info(f"[{label}] {line.decode().rstrip()}")

    asyncio.create_task(_pipe(proc.stdout, "out"))
    asyncio.create_task(_pipe(proc.stderr, "err"))
    return proc


async def _stop_subprocess(proc, label: str):
    if proc is None or proc.returncode is not None:
        return
    logger.info(f"Stopping {label}...")
    proc.send_signal(signal.SIGTERM)
    try:
        await asyncio.wait_for(proc.wait(), timeout=5.0)
    except asyncio.TimeoutError:
        logger.warning(f"{label} did not exit in time, sending SIGKILL")
        proc.kill()
        await proc.wait()


async def start_http_server(multi_db_instance, port: int = 3456, host: str = '0.0.0.0',
                            cache_path: str = None, zmq_server_instance: object = None):
    """Start uvicorn server (used by BackendApp._start_optional_services)"""
    common.http_port = port
    create_app(multi_db_instance, zmq_server_instance)
    if cache_path:
        common._init_cache_db(cache_path)

    # Start subprocesses (non-blocking)
    runner_proc = await _start_subprocess(
        "plugins/coding_agent_runner/server.py", RUNNER_PORT, "Coding Agent Runner")
    mcp_proc = await _start_subprocess(
        "plugins/mcp_server/server.py", MCP_PORT, "MCP Server")

    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Web server starting on http://{host}:{port}")
    try:
        await server.serve()
    finally:
        await _stop_subprocess(runner_proc, "Coding Agent Runner")
        await _stop_subprocess(mcp_proc, "MCP Server")
