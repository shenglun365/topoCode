"""ZMQClient — ZMQ DEALER client for MCP Server to communicate with main backend.

When `--zmq-dealer-port > 0`, the MCP Server connects to the main backend's
ZMQ DEALER socket instead of using direct library calls. This decouples the
MCP Server lifecycle from the backend and enables independent restart/update.
"""

import asyncio
import json
import logging
import uuid
from typing import Any, Optional

import zmq
import zmq.asyncio

logger = logging.getLogger(__name__)


class ZMQClient:
    """Async ZMQ DEALER client that sends requests to the main backend."""

    def __init__(self, endpoint: str = "tcp://127.0.0.1:5671"):
        self.endpoint = endpoint
        self.context: Optional[zmq.asyncio.Context] = None
        self.socket: Optional[zmq.asyncio.Socket] = None
        self._pending: dict[str, asyncio.Future] = {}
        self._recv_task: Optional[asyncio.Task] = None

    async def connect(self):
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.DEALER)
        self.socket.connect(self.endpoint)
        self._recv_task = asyncio.create_task(self._recv_loop())
        logger.info(f"ZMQClient connected to {self.endpoint}")

    async def call(self, method: str, params: dict = None) -> Any:
        if not self.socket:
            raise RuntimeError("ZMQClient not connected, call connect() first")
        request_id = uuid.uuid4().hex[:12]
        future: asyncio.Future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        try:
            self.socket.send_multipart([
                request_id.encode("utf-8"),
                method.encode("utf-8"),
                json.dumps(params or {}, default=str).encode("utf-8"),
            ])
            result = await asyncio.wait_for(future, timeout=30.0)
            return result
        except asyncio.TimeoutError:
            self._pending.pop(request_id, None)
            raise TimeoutError(f"ZMQ call to {method} timed out after 30s")
        except Exception:
            self._pending.pop(request_id, None)
            raise

    async def _recv_loop(self):
        try:
            while self.socket:
                try:
                    frames = await self.socket.recv_multipart()
                    if len(frames) < 3:
                        logger.warning(f"Invalid response frames: {len(frames)}")
                        continue
                    request_id = frames[0].decode("utf-8")
                    result_data = json.loads(frames[1])
                    error_data = json.loads(frames[2]) if frames[2] else None
                    future = self._pending.pop(request_id, None)
                    if future:
                        if error_data:
                            future.set_exception(RuntimeError(error_data.get("message", str(error_data))))
                        else:
                            future.set_result(result_data)
                    else:
                        logger.debug(f"Received response for unknown request: {request_id}")
                except zmq.ZMQError:
                    break
                except Exception as e:
                    logger.exception(f"Error in recv loop: {e}")
        except asyncio.CancelledError:
            pass
        finally:
            for f in self._pending.values():
                if not f.done():
                    f.cancel()
            self._pending.clear()

    async def close(self):
        if self._recv_task:
            self._recv_task.cancel()
            try:
                await self._recv_task
            except asyncio.CancelledError:
                pass
            self._recv_task = None
        if self.socket:
            self.socket.close(linger=0)
            self.socket = None
        if self.context:
            self.context.term()
            self.context = None
