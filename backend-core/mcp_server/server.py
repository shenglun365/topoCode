"""MCPServer — JSON-RPC 2.0 over stdio server for MCP protocol.

Implements the Model Context Protocol specification:
- tools/list → list available tools
- tools/call → invoke a tool
- prompts/list → list available skills/prompts
- prompts/get → get a specific prompt template
"""

import json
import logging
import sys
import traceback
from typing import Any, Optional

from .tools import CORE_TOOLS
from .dispatcher import ToolDispatcher
from .skill_executor import SkillExecutor
from .skills import register_core_skills

logger = logging.getLogger(__name__)


class MCPServer:
    """MCP protocol JSON-RPC 2.0 server over stdio."""

    def __init__(self, dispatcher: ToolDispatcher):
        self.dispatcher = dispatcher
        self.tools = CORE_TOOLS
        self.skill_executor = SkillExecutor(dispatcher)
        register_core_skills(self.skill_executor, dispatcher)

    async def run(self):
        """Read JSON-RPC requests from stdin, process, write responses to stdout."""
        logger.info("MCP Server started, waiting for requests on stdin...")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
            except json.JSONDecodeError as e:
                self._send_error(None, -32700, f"Parse error: {e}")
                continue

            response = await self._handle_request(request)
            self._send(response)

    async def _handle_request(self, req: dict) -> dict:
        method = req.get("method")
        req_id = req.get("id")
        params = req.get("params", {})

        if method == "tools/list":
            return self._response(req_id, {
                "tools": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "inputSchema": t.inputSchema,
                    }
                    for t in self.tools
                ],
            })

        elif method == "tools/call":
            tool_name = params.get("name", "")
            arguments = params.get("arguments", {})
            try:
                result = await self.dispatcher.dispatch(tool_name, arguments)
                return self._response(req_id, result)
            except Exception as e:
                logger.exception(f"Tool call failed: {tool_name}")
                return self._error(req_id, -32000, str(e))

        elif method == "prompts/list":
            skills = self.skill_executor.list_skills()
            return self._response(req_id, {
                "prompts": [
                    {
                        "name": s["name"],
                        "description": s["description"],
                        "arguments": [
                            {"name": k, "description": v.get("description", ""), "required": True}
                            for k, v in s["input_schema"].get("properties", {}).items()
                        ],
                    }
                    for s in skills
                ],
            })

        elif method == "prompts/get":
            name = params.get("name", "")
            skill = self.skill_executor.get_definition(name)
            if not skill:
                return self._error(req_id, -32602, f"Unknown prompt: {name}")
            return self._response(req_id, {
                "name": skill.name,
                "description": skill.description,
                "prompt": f"Execute skill: {skill.name}\n\n{skill.description}",
            })

        elif method == "initialize":
            return self._response(req_id, {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                },
                "serverInfo": {
                    "name": "topocode-mcp",
                    "version": "0.1.0",
                },
            })

        elif method == "ping":
            return self._response(req_id, {})

        else:
            return self._error(req_id, -32601, f"Method not found: {method}")

    # ---- JSON-RPC wire helpers ----

    def _send(self, response: dict):
        line = json.dumps(response, default=str)
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def _send_error(self, req_id: Any, code: int, message: str):
        self._send(self._error(req_id, code, message))

    def _response(self, req_id: Any, result: Any) -> dict:
        return {"jsonrpc": "2.0", "id": req_id, "result": result}

    def _error(self, req_id: Any, code: int, message: str) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }
