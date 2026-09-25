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

from topoone_app_architect.arch_routes import router as architect_router
from topoone_app_architect import ctx

logger = logging.getLogger(__name__)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


def default_cors() -> list:
    """A9 修正：默认仍面向 dev 联调（5173/5174 直连 + 3456 反代），
    可经 `ARCH_CORS_ORIGINS`（逗号分隔）整体覆盖，供独立/生产部署配置。"""
    override = os.environ.get("ARCH_CORS_ORIGINS", "").strip()
    if override:
        return [o.strip() for o in override.split(",") if o.strip()]
    arch_port = os.environ.get("ARCH_PORT", "3470")
    return [
        "http://localhost:5173", "http://127.0.0.1:5173",
        "http://localhost:5174", "http://127.0.0.1:5174",
        f"http://localhost:{arch_port}", f"http://127.0.0.1:{arch_port}",
        "http://localhost:3456", "http://127.0.0.1:3456",
    ]


class ProjectContextMiddleware:
    """ASGI 中间件: 解析 ?project=/?root= → 设置请求级项目上下文(contextvar)。

    项目库路由(architect/<pid>/arch.db)依据该上下文；解析失败/无参数 →
    无上下文(store 层回退主库默认桶)。WebSocket 不经 HTTP 查询串，
    由 WS 处理器按首条消息显式 set_project。
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        token = None
        try:
            from urllib.parse import parse_qs
            qs = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
            project = (qs.get("project") or [""])[0].strip() or None
            root = (qs.get("root") or [""])[0].strip() or None
            if project or root:
                from topoone_app_architect.arch_routes.project import resolve_project
                try:
                    proj = resolve_project(root, project)
                    if proj and proj.get("id"):
                        token = ctx.set_project(proj["id"])
                except Exception:
                    pass
        except Exception:
            token = None
        try:
            await self.app(scope, receive, send)
        finally:
            if token:
                ctx.reset_project(token)


def build_app(data_dir: str = None, kb_url: str = None, mcp_url: str = None,
              cors_origins: list = None) -> FastAPI:
    """装配 architect FastAPI 应用。data_dir 传经 ctx.setup 注入 architect.db。"""
    ctx.setup(data_dir=data_dir, kb_url=kb_url, mcp_url=mcp_url)

    app = FastAPI(title="TopoOne Architect")
    app.add_middleware(ProjectContextMiddleware)
    # GZip 压缩(≥1KB 才压): 静态主包 ~2.2MB → ~700KB 传输, API JSON 同收益
    from fastapi.middleware.gzip import GZipMiddleware
    app.add_middleware(GZipMiddleware, minimum_size=1024)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins if cors_origins is not None else default_cors(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(architect_router)

    # 模型未配置 → 400 明确报错(用户裁决: 禁止静默兜底 KB 默认)
    from .agent.cognition.llm import ModelNotConfigured
    from .common import err as _api_err

    @app.exception_handler(ModelNotConfigured)
    async def _model_not_configured_handler(request, exc: ModelNotConfigured):
        return _api_err(400, str(exc))
    # 内置 Git HTTP 托管：无前缀 /git/{project}.git（remote worker clone/push 面）
    from topoone_app_architect.arch_routes import git_host
    app.include_router(git_host.router)
    # MCP 服务（streamable HTTP）：资产地图对外暴露，/mcp
    # （子应用 lifespan 不随挂载执行 → 会话任务组并入宿主 lifespan）
    _mcp_lifespan = None
    try:
        from topoone_app_architect.mcp import mcp_http_app
        _mcp_asgi, _mcp_lifespan = mcp_http_app()
        app.mount("/mcp", _mcp_asgi)
    except Exception as e:  # noqa: BLE001
        logger.warning("MCP HTTP 挂载失败（mcp 依赖缺失? pip install 'mcp<2'）: %s", e)

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def _lifespan(_app):
        # 任务泵主循环捕获: REST to_thread 工作线程无事件循环, 泵须调度回主循环
        try:
            import asyncio as _aio
            from .agent.execution.exec_bridge import set_main_loop, start_recover_sweep
            set_main_loop(_aio.get_running_loop())
            start_recover_sweep()   # C 定时对账: 假 running 任务自动收敛
        except Exception:
            pass
        # 会话 agent 工具面注册(ctx.*/评估/提炼, 幂等)——P4 起实现延迟到
        # agent.orchestrator, 此处恢复"服务启动即注册"语义(MCP 面首调可用)
        try:
            from .agent.orchestrator import register_session_tools
            register_session_tools()
        except Exception:
            pass
        # P5: 定时批量提炼后台循环(异常自吞, 不影响主服务)
        try:
            from .agent.reflection.mining import start_periodic_mine
            start_periodic_mine()
        except Exception:
            pass
        if _mcp_lifespan is not None:
            async with _mcp_lifespan():
                yield
        else:
            yield

    app.router.lifespan_context = _lifespan

    @app.get("/health", include_in_schema=False)
    async def health():
        # pid 自报(服务身份): supervisor 就绪判定校验「响应者==自己 spawn 的
        # 进程」——端口可达≠就绪, 外部监听者(孤儿实例)不再能骗过探针
        return {"status": "ok", "service": "architect", "pid": os.getpid()}

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