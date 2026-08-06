"""Architect standalone FastAPI app.

`build_app(data_dir, kb_url, mcp_url)` 构造能独立运行的服务：
- include `arch_routes.router` (prefix `/api/architect`)；
- 挂载 architect SPA 静态(/architect.html + /web)；
- CORS 放行 dev(5173/5174) 与 reports(3456) 以便联调/反代。

端口/编排由 `plugins/architect/__main__.py`(subprocess) 或 back `main.py` 负责。
"""
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from arch_routes import router as architect_router
from arch_routes import ctx

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def _default_cors() -> list:
    arch_port = os.environ.get("ARCH_PORT", "3470")
    return [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        f"http://localhost:{arch_port}", f"http://127.0.0.1:{arch_port}",
        "http://localhost:3456", "http://127.0.0.1:3456",
    ]


def build_app(data_dir: str = None, kb_url: str = None, mcp_url: str = None,
              cors_origins: list = None) -> FastAPI:
    """装配 architect FastAPI 应用。data_dir 传经 ctx.setup 注入 architect.db。"""
    ctx.setup(data_dir=data_dir, kb_url=kb_url, mcp_url=mcp_url)

    app = FastAPI(title="TopoOne Architect")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else _default_cors(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(architect_router)

    # SPA 静态产物(由 vite.architect.config.ts 构建到 static/)
    _web = os.path.join(STATIC_DIR, "web")
    if os.path.isdir(_web):
        app.mount("/web", StaticFiles(directory=_web), name="arch_web")

    _html = os.path.join(STATIC_DIR, "architect.html")
    if os.path.isfile(_html):
        from fastapi.responses import FileResponse

        @app.get("/architect", include_in_schema=False)
        @app.get("/architect/", include_in_schema=False)
        async def serve_architect():
            return FileResponse(_html)

    return app