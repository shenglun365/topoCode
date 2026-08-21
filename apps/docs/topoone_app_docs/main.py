"""Doc 服务独立进程（M11）— doc viewer + web_root 业务 API :3481。

承载 viewer 全部路由（/doc · /code · /api/community-doc · /api/file ·
/api/heatmap · /api/diagram* · /api/graph-layout 等）+ web_root 业务 API
（/api/projects · /api/tasks · /api/docs · /api/import* · /api/export* ·
/api/verify*）+ render.*/report.* RPC 方法。
数据：共享 project.db 只读（WAL 多进程）。

用法：python -m topoone_app_docs --data-dir <dir> [--port 3481]
"""

import argparse
import logging
import os

from topoone.logging_config import setup_logging
setup_logging()
logger = logging.getLogger(__name__)


def register_methods(server, multi_db):
    """注册 render.* 方法（plantuml 渲染）。

    report.* 保留在核心进程（report_service + task_manager subdoc 写方法），
    docs 服务只注册 render.*（gateway 按命名空间路由，report 路由到核心）。
    """
    from topoone_app_docs.doc_service import register_render_methods
    register_render_methods(server, multi_db)


def main():
    parser = argparse.ArgumentParser(description="TopoOne Docs Service (doc viewer + web_root)")
    parser.add_argument("--data-dir", type=str, default=None)
    parser.add_argument("--port", type=int, default=int(os.environ.get("DOC_SERVICE_PORT", "3481")))
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    os.makedirs(data_dir, exist_ok=True)

    import uvicorn
    from topoone import service_common as common
    from topoone.db.manager import MultiDBManager
    from topoone.rpc.service_app import MethodServer, create_service_app

    multi_db = MultiDBManager(data_dir)
    common.set_globals(multi_db, port=args.port)

    # plantuml 缓存初始化（docs 服务独占，M11 起从 gateway 移入）
    cache_path = os.path.join(data_dir, "cache", "plantuml_cache.db")
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    common._init_cache_db(cache_path)

    # viewer + web_root HTTP 路由（纯读共享 DB，无 /zmq 方法）
    from topoone_app_docs.viewer import router as viewer_router
    from topoone_app_docs.web_root import router as web_root_router
    # render.* + report.* RPC 方法
    server = MethodServer(pub_port=None)
    register_methods(server, multi_db)

    app = create_service_app(server, multi_db, title="docs-service")
    app.include_router(viewer_router)
    app.include_router(web_root_router)

    logger.info(f"[docs-service] starting on http://{args.host}:{args.port}")
    from topoone.http_logging import install_heartbeat_filter
    install_heartbeat_filter()
    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    finally:
        multi_db.close_all()


if __name__ == "__main__":
    main()
