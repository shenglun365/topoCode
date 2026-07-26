"""Web Server entry point — import modules, create app, start uvicorn"""

import asyncio
import logging
import os

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import common
from web_root import router as web_root_router
from viewer import router as viewer_router
from chat import router as chat_router
from vue_routes import vue_router
from web_tools import WebToolExecutor

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

# Create FastAPI app
app = FastAPI(title="TopoOne Web Viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5174"],
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

# Mount Vue web static files at /web
_web_static = os.path.join(STATIC_DIR, "web")
if os.path.isdir(_web_static):
    app.mount("/web", StaticFiles(directory=_web_static), name="web_vue")


def create_app(multi_db_instance, zmq_server_instance=None) -> FastAPI:
    """Create and configure app with injected dependencies"""
    common.set_globals(multi_db_instance, zmq_server_instance)
    common.web_tool_executor = WebToolExecutor(multi_db_instance)
    common._ensure_chat_tables()
    return app


async def start_http_server(multi_db_instance, port: int = 3456, host: str = '0.0.0.0',
                            cache_path: str = None, zmq_server_instance: object = None):
    """Start uvicorn server (used by BackendApp._start_optional_services)"""
    common.http_port = port
    create_app(multi_db_instance, zmq_server_instance)
    if cache_path:
        common._init_cache_db(cache_path)
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Web server starting on http://{host}:{port}")
    await server.serve()
