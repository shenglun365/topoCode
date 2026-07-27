"""Web端独立启动入口 — 供 main.py 以 subprocess 方式调用

用法: python -m plugins.reports.web_server --port 3456 --data-dir /path/to/data
"""

import argparse
import logging
import os
import signal
import sys

# Add backend-core to path (required for sqlite_ctx, community_data, etc.)
_self_dir = os.path.dirname(os.path.abspath(__file__))
_project_dir = os.path.dirname(os.path.dirname(_self_dir))  # go up from plugins/reports/ to project root
_backend_dir = os.path.join(_project_dir, "backend-core")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

# Add self to path
_self_dir = os.path.dirname(os.path.abspath(__file__))
if _self_dir not in sys.path:
    sys.path.insert(0, _self_dir)

from logging_config import setup_logging
setup_logging()
logger = logging.getLogger(__name__)


def main():
    # Load .env from project root if present
    env_path = os.path.join(_project_dir, '.env')
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                os.environ.setdefault(key.strip(), val.strip())

    parser = argparse.ArgumentParser(description="TopoCode Web Server")
    parser.add_argument("--port", type=int, default=3456, help="HTTP port")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="HTTP host")
    parser.add_argument("--data-dir", type=str, default=None, help="Data directory")
    parser.add_argument("--data-api-port", type=int, default=3459, help="Data API port")
    args = parser.parse_args()

    # Initialize DB from the data directory
    from sqlite_ctx import MultiDBManager
    data_dir = args.data_dir or os.path.join(os.path.expanduser("~"), ".topocode")
    multi_db = MultiDBManager(data_dir)

    # Configure write proxy to go through Data API (Phase 3: multi-process mode)
    import db_client
    db_client.configure(mode='proxy', data_api_url=f'http://127.0.0.1:{args.data_api_port}')

    # Start the web server
    import uvicorn
    from web_server import app, create_app
    create_app(multi_db)

    logger.info(f"Web server starting on http://{args.host}:{args.port}")

    # Handle SIGTERM gracefully
    should_exit = False

    def handle_sigterm(signum, frame):
        nonlocal should_exit
        logger.info("Received SIGTERM, shutting down web server...")
        should_exit = True

    signal.signal(signal.SIGTERM, handle_sigterm)
    signal.signal(signal.SIGINT, handle_sigterm)

    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="info")
    server = uvicorn.Server(config)
    server.run()


if __name__ == "__main__":
    main()
