"""BackendBridge — registers MCP dispatch method on the main backend's ZMQServer.

When the main backend starts, it calls `register_mcp_methods(server)` to register
the `mcp.dispatch` method. This allows the MCP Server (in ZMQ mode) to forward
`tools/call` requests to the backend, which creates a ToolDispatcher internally
and processes the request with full access to database-backed state.
"""

import logging

from zmq_server import ZMQServer

logger = logging.getLogger(__name__)


def register_mcp_methods(server: ZMQServer):
    """Register the mcp.dispatch handler on the backend ZMQServer.

    This method receives {tool_name, arguments} from the MCP Server,
    creates a ToolDispatcher, and returns the dispatch result.
    """
    @server.register("mcp.dispatch")
    def mcp_dispatch(tool_name: str = "", arguments: dict = None):
        from mcp_server.dispatcher import ToolDispatcher

        dispatcher = ToolDispatcher(
            project_root=arguments.get("_project_root", "") if arguments else "",
        )
        import asyncio
        result = asyncio.run(dispatcher.dispatch(tool_name, arguments or {}))
        return result

    logger.info("Registered mcp.dispatch method on backend ZMQServer")
