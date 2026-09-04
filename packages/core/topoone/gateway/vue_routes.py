"""SPA html 路由 — 静态源 manifest 驱动（M06），URL 布局不变。

静态源：docs app static_dir（manifest，过渡期 = plugins/reports/static，M11 后 apps/docs/dist）；
门户 /home 优先 packages/web-core/dist-portal（M09），未构建回退 legacy static。
"""

import os
import logging

from fastapi import APIRouter
from fastapi.responses import FileResponse, HTMLResponse

from topoone.gateway import static_sources

logger = logging.getLogger(__name__)

vue_router = APIRouter()


def _exists(filename: str) -> bool:
    return os.path.isfile(os.path.join(static_sources.spa_static_dir(), filename))


def _file(filename: str) -> str:
    return os.path.join(static_sources.spa_static_dir(), filename)


def _chat_static_dir() -> str:
    """chat SPA 静态目录（apps/chat/dist；manifest 驱动，无 legacy 回退）。"""
    from topoone.manifest import discover_apps
    try:
        apps = discover_apps(static_sources._REPO_ROOT)
        m = apps.get("chat")
        if m and m.static_dir:
            return m.static_dir if os.path.isabs(m.static_dir) else os.path.join(static_sources._REPO_ROOT, m.static_dir)
    except Exception:
        pass
    return os.path.join(static_sources._REPO_ROOT, "apps", "chat", "dist")


def _chat_file(filename: str) -> str:
    return os.path.join(_chat_static_dir(), filename)


@vue_router.get("/v2", response_class=HTMLResponse)
async def v2_root():
    """Vue home page"""
    if _exists("web-root.html"):
        return FileResponse(_file("web-root.html"))
    return HTMLResponse("Vue not built. Run: npm run build:web")


@vue_router.get("/v2/doc", response_class=HTMLResponse)
async def v2_doc():
    """Vue viewer page"""
    if _exists("viewer.html"):
        return FileResponse(_file("viewer.html"))
    return HTMLResponse("Vue not built. Run: npm run build:web")


@vue_router.get("/v2/chat", response_class=HTMLResponse)
async def v2_chat():
    """Vue chat page"""
    if _exists("chat.html"):
        return FileResponse(_file("chat.html"))
    return HTMLResponse("Vue not built. Run: npm run build:web")


# ── P2：独立 SPA 按路径挂载（统一端口 3456） ──

@vue_router.get("/chat", response_class=HTMLResponse)
async def spa_chat():
    """chat SPA（/chat）— M12 起由 gateway serve（apps/chat/dist/chat.html）。"""
    if os.path.isfile(_chat_file("chat.html")):
        return FileResponse(_chat_file("chat.html"))
    return HTMLResponse("chat SPA not built. Run: npm run build:chat")


@vue_router.get("/viewer", response_class=HTMLResponse)
async def spa_viewer():
    """doc viewer SPA（/viewer）"""
    if _exists("viewer.html"):
        return FileResponse(_file("viewer.html"))
    return HTMLResponse("viewer SPA not built. Run: npm run build:web")


@vue_router.get("/web-root", response_class=HTMLResponse)
async def spa_web_root():
    """门户 SPA（/web-root）"""
    if _exists("web-root.html"):
        return FileResponse(_file("web-root.html"))
    return HTMLResponse("web-root SPA not built. Run: npm run build:web")


@vue_router.get("/projects", response_class=HTMLResponse)
async def spa_projects():
    """知识库构建和管理门户 SPA（/projects）"""
    if _exists("web-root.html"):
        return FileResponse(_file("web-root.html"))
    return HTMLResponse("web-root SPA not built. Run: npm run build:web")


@vue_router.get("/home", response_class=HTMLResponse)
async def spa_home():
    """统一首页 SPA（/home）— 门户：优先 web-core dist-portal（M09），未构建回退 legacy static"""
    portal = static_sources.portal_dir()
    if portal:
        p = os.path.join(portal, "home.html")
        if os.path.isfile(p):
            return FileResponse(p)
    if _exists("home.html"):
        return FileResponse(_file("home.html"))
    return HTMLResponse("home SPA not built. Run: npm run build:web")


@vue_router.get("/", response_class=HTMLResponse)
async def spa_index():
    """统一首页（/）— M11 起由 gateway 直接 serve（原 web_root index 路由）。与 /home 同源。"""
    portal = static_sources.portal_dir()
    if portal:
        p = os.path.join(portal, "home.html")
        if os.path.isfile(p):
            return FileResponse(p)
    if _exists("home.html"):
        return FileResponse(_file("home.html"))
    return HTMLResponse("home SPA not built. Run: npm run build:web")
