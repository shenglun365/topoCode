"""Vue-built page routes — serve Vite build output while preserving old pages

Vite build output is at:
  plugins/reports/static/
    ├── web-root.html     (Vue home page)
    ├── viewer.html       (Vue viewer page)
    ├── chat.html         (Vue chat page)
    └── web/              (assets & chunks)
        ├── web-root/assets/...
        ├── viewer/assets/...
        └── chat/assets/...
"""

import os
import logging

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

vue_router = APIRouter()


def _build_path(filename: str) -> str:
    return os.path.join(STATIC_DIR, filename)


def _exists(filename: str) -> bool:
    return os.path.isfile(_build_path(filename))


@vue_router.get("/v2", response_class=HTMLResponse)
async def v2_root():
    """Vue home page"""
    if _exists("web-root.html"):
        return FileResponse(_build_path("web-root.html"))
    return HTMLResponse("Vue not built. Run: npm run build:web")


@vue_router.get("/v2/doc", response_class=HTMLResponse)
async def v2_doc():
    """Vue viewer page"""
    if _exists("viewer.html"):
        return FileResponse(_build_path("viewer.html"))
    return HTMLResponse("Vue not built. Run: npm run build:web")


@vue_router.get("/v2/chat", response_class=HTMLResponse)
async def v2_chat():
    """Vue chat page"""
    if _exists("chat.html"):
        return FileResponse(_build_path("chat.html"))
    return HTMLResponse("Vue not built. Run: npm run build:web")
