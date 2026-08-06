"""Architect 独立服务入口 — 供 main.py 以 subprocess 方式调用。

用法: python -m plugins.architect --port 3470 --data-dir /path/to/data
      [--kb-url http://127.0.0.1:3459] [--mcp-url http://127.0.0.1:3460]
"""

import argparse
import logging
import os
import signal
import sys

# Add backend-core to path (required for sqlite_ctx)
_self_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(os.path.dirname(_self_dir))  # plugins/architect -> project root
_backend_dir = os.path.join(_project_dir, "backend-core")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Add self to path (arch_routes, server)
if _self_dir not in sys.path:
    sys.path.insert(0, _self_dir)

# Add project root to path (required for plugins.installer.targets, etc.)
if _project_dir not in sys.path:
    sys.path.insert(0, _project_dir)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="TopoOne Architect Service")
    parser.add_argument("--port", type=int, default=3470, help="HTTP port")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="HTTP host")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory")
    parser.add_argument("--kb-url", type=str, default=None, help="KB data_api base URL")
    parser.add_argument("--mcp-url", type=str, default=None, help="MCP server base URL")
    args = parser.parse_args()

    if args.kb_url:
        os.environ.setdefault("KB_BASE_URL", args.kb_url)
    if args.mcp_url:
        os.environ.setdefault("MCP_BASE_URL", args.mcp_url)

    import uvicorn
    from server import build_app, _default_cors
    # cross-origin: dev/web via vite, and reports 3456 (if any reverse proxy kept)
    app = build_app(data_dir=args.data_dir, cors_origins=_default_cors())

    logger.info(f"Architect server starting on http://{args.host}:{args.port}")

    should_exit = False

    def handle_sigterm(signum, frame):
        nonlocal should_exit
        logger.info("Received SIGTERM, shutting down architect...")
        should_exit = True

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()