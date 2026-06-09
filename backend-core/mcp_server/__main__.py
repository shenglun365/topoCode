"""MCP Server entry point — python -m backend-core.mcp_server

Usage:
    python -m backend-core.mcp_server --project-root /path/to/project
    python -m backend-core.mcp_server --project-root . --zmq-dealer-port 5671
"""

import argparse
import asyncio
import logging
import sys
import os

# Ensure backend-core is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "plugins"))


def main():
    parser = argparse.ArgumentParser(description="TopoCode MCP Server")
    parser.add_argument("--project-root", required=True, help="Project root directory")
    parser.add_argument("--zmq-dealer-port", type=int, default=0,
                        help="ZMQ DEALER port for backend communication (0 = direct library calls)")
    parser.add_argument("--log-level", default="WARN", help="Logging level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARN),
        format="%(levelname)s %(name)s: %(message)s",
    )

    project_root = os.path.abspath(args.project_root)
    logger = logging.getLogger("mcp_server")
    logger.info(f"Starting MCP Server for project: {project_root}")

    # Build dispatcher — ZMQ mode when dealer port is specified
    from mcp_server.dispatcher import ToolDispatcher
    from change_tracker.snapshot_store import SnapshotStore
    from change_tracker.git_adapter import GitAdapter
    zmq_client = None

    if args.zmq_dealer_port > 0:
        from mcp_server.zmq_client import ZMQClient
        zmq_client = ZMQClient(endpoint=f"tcp://127.0.0.1:{args.zmq_dealer_port}")
        logger.info(f"MCP Server using ZMQ mode: {zmq_client.endpoint}")
    else:
        logger.info("MCP Server using direct library calls (--zmq-dealer-port=0)")

    data_dir = os.path.join(project_root, ".topocode", "data")
    snapshot_dir = os.path.join(data_dir, "snapshots")
    snapshot_store = SnapshotStore(os.path.join(snapshot_dir, "snapshots.db"))
    git_adapter = GitAdapter(project_root)

    dispatcher = ToolDispatcher(
        project_root=project_root,
        zmq_client=zmq_client,
        snapshot_store=snapshot_store,
        git_adapter=git_adapter,
    )

    from mcp_server.server import MCPServer
    server = MCPServer(dispatcher)

    async def _run():
        if zmq_client:
            await zmq_client.connect()
        try:
            await server.run()
        finally:
            if zmq_client:
                await zmq_client.close()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("MCP Server stopped by user")


if __name__ == "__main__":
    main()
