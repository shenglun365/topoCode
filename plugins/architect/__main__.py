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


def _load_env():
    """加载项目根 .env(参照 plugins/reports/__main__.py)。"""
    env_path = os.path.join(_project_dir, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())


_load_env()


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
    # 让 architect 应用模块的 INFO 级日志可见(默认根 logger 只输出 WARNING+，
    # 会吞掉语义资产提取等关键诊断的 collect_context/extract_scope 明细)。
    _log_level = os.environ.get("ARCH_LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, _log_level, logging.INFO),
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    for _name in ("arch_routes", "arch_routes.semantic_assets", "arch_routes.req_agent",
                  "arch_routes.kb_gateway", "arch_routes.project", "arch_routes.common"):
        logging.getLogger(_name).setLevel(getattr(logging, _log_level, logging.INFO))
    logger.info("Architect 日志级别: %s (可用 ARCH_LOG_LEVEL 覆盖)", _log_level)
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