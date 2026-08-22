"""Gateway 进程 FastAPI 骨架 — 中间件 + 静态挂载（manifest 驱动，M06）。

纯基础设施：反向代理 / RPC 路由 / 事件桥 / 鉴权（gateway.py）+ SPA 静态（vue_routes.py）。
M11: web_root 业务 API 已移入 docs 服务（:3481），gateway 零业务 router / 零业务 DB 句柄。
门户 HTML（/ · /projects · /viewer · /home）由 vue_routes 从 docs static_dir serve。
"""

import logging
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from topoone.gateway import gateway  # noqa: E402
from topoone.gateway import vue_routes  # noqa: E402
from topoone.gateway import static_sources  # noqa: E402
from topoone.gateway import system_routes  # noqa: E402

logger = logging.getLogger(__name__)

app = FastAPI(title="TopoOne Web Viewer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://localhost:5174", "http://localhost:5175",
        "http://127.0.0.1:5173", "http://127.0.0.1:5174", "http://127.0.0.1:5175",
        "http://localhost:3456", "http://127.0.0.1:3456",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 网关：反向代理 / RPC 路由 / 事件桥 / 鉴权（P1）
# 必须先于其它 router，保证 /api/architect* 与 /api/rpc 不被业务路由抢先。
app.include_router(gateway.router)

# P1: supervisor 控制面代理（/api/system/apps · /api/system/apps/{name}/restart）
app.include_router(system_routes.router)

# 全局鉴权（D7）：/api/* 与 /ws/events 校验 token（静态/健康除外）
app.middleware("http")(gateway.auth_middleware)

# Include routers from modules
# M11: web_root 业务 API 已移入 docs 服务（:3481），gateway 只留 SPA 静态路由。
app.include_router(vue_routes.vue_router)

# M11: docs SPA 资产挂载（viewer/web-root 的 JS/CSS/图片，vite base=/docs/）。
# 页面 URL（/viewer · /web-root · /projects）仍由 vue_routes serve；此处只 serve dist 内资产。
_docs_dist = static_sources.spa_static_dir()
if os.path.isdir(_docs_dist):
    app.mount("/docs", StaticFiles(directory=_docs_dist), name="docs_assets")

# M14: 门户（home.html）资产挂载。home.html 由 vue_routes serve 于 / · /home（根上下文），
# vite base=./（相对），故 ./assets/ 解析为 /assets/（区别于 workbench /app/ 的 trailing-slash 模式）。
_portal_dir = static_sources.portal_dir()
if _portal_dir and os.path.isdir(os.path.join(_portal_dir, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_portal_dir, "assets")), name="portal_assets")

# 主工作台静态挂载 — manifest 驱动（workbench: static_dir × static_mount）+ legacy 回退
for _mount, _dir in static_sources.main_app_mounts():
    if os.path.isdir(_dir):
        app.mount(_mount, StaticFiles(directory=_dir, html=True), name=f"app_{_mount.strip('/')}")
    else:
        logger.warning(f"[gateway] static mount {_mount} missing: {_dir} (fallback skipped)")


@app.get("/health", include_in_schema=False)
async def health():
    return {"status": "ok", "service": "gateway"}


def create_app(multi_db_instance=None, zmq_server_instance=None) -> FastAPI:
    """Create and configure app with injected dependencies.

    M11: gateway 为零业务基础设施 —— 不再持有业务 DB 句柄 / 初始化业务表
    （web_root 业务 API 已移入 docs 服务，chat 业务由 chat 服务持有）。
    参数保留以兼容既有调用方（BackendApp / __main__），但不再写入 common 全局。
    """
    # NOTE: architect workbench db is owned by the standalone architect service
    # (plugins/architect); docs/chat 业务 DB 由各自服务进程持有。
    return app


# ==================== Subprocess Management ====================
# NOTE: coding_agent_runner / mcp 的 spawn 已移除 —— 进程拓扑唯一化（D8）：
# 所有子进程由 `topo serve` 的 supervisor 统一纳管，本入口不再自行 spawn。


async def start_http_server(multi_db_instance, port: int = 3456, host: str = '0.0.0.0',
                            cache_path: str = None, zmq_server_instance: object = None):
    """Start uvicorn server (used by BackendApp._start_optional_services)"""
    create_app(multi_db_instance, zmq_server_instance)
    # M11: plantuml 缓存由 docs 服务独占初始化，gateway 不再持有业务句柄。
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    logger.info(f"Web server starting on http://{host}:{port}")
    await server.serve()
