"""独立服务脚手架 — P3 服务拆分复用。

每个服务进程（llm/agent/doc/chat/kb）用本模块组装：
  - `MethodServer`：轻量方法注册表（兼容 ZMQServer 的 register/publish 接口，
    不 bind dealer/pub 端口；publish 走可选 ZMQ PUB socket）。
  - `create_service_app(server, multi_db)`：FastAPI app，提供
    `POST /zmq/{method}`（调用已注册方法）+ `GET /health`。
  - `start_service(methods_loader, data_dir, port, pub_port)`：一键启动。

方法注册函数（register_llm_methods 等）仍可原样复用，只需传入 MethodServer。
事件：若 pub_port 给定，MethodServer 建 ZMQ PUB；否则 publish 为 no-op。
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import threading
import time
from typing import Callable, Dict, Optional

logger = logging.getLogger(__name__)


class MethodServer:
    """轻量方法注册表 — 兼容 ZMQServer.register/publish 接口。"""

    def __init__(self, pub_port: Optional[int] = None, pub_topic_prefix: str = ""):
        self.methods: Dict[str, Callable] = {}
        self.pub_port = pub_port
        self.pub_topic_prefix = pub_topic_prefix
        self._pub = None
        self._loop = None
        self._running = False
        self._publish_queue: Optional[asyncio.Queue] = None
        self._pub_task: Optional[asyncio.Task] = None
        self.bus = _NoopBus()

    def register(self, name: str):
        """方法注册装饰器"""
        def decorator(func: Callable):
            self.methods[name] = func
            logger.info(f"Registered method: {name}")
            return func
        return decorator

    def register_many(self, methods: Dict[str, Callable]):
        for name, func in methods.items():
            self.methods[name] = func
            logger.info(f"Registered method: {name}")

    def publish(self, topic: str, event_type: str, data: dict):
        """发布事件 — 经队列中继到事件循环线程的 PUB socket（no-op 若无 pub）。"""
        if self._pub is None or self._publish_queue is None:
            return
        try:
            self._publish_queue.put_nowait((topic, event_type, data))
        except Exception:
            pass

    async def start_pub(self):
        """启动事件发布（绑定 pub_port 的 ZMQ PUB + 队列消费者）。"""
        if not self.pub_port:
            return
        import zmq
        import zmq.asyncio
        self._loop = asyncio.get_running_loop()
        ctx = zmq.asyncio.Context.instance()
        self._pub = ctx.socket(zmq.PUB)
        self._pub.bind(f"tcp://127.0.0.1:{self.pub_port}")
        logger.info(f"[service] PUB bound to tcp://127.0.0.1:{self.pub_port}")
        self._publish_queue = asyncio.Queue()
        self._running = True
        self._pub_task = self._loop.create_task(self._pub_worker())

    async def _pub_worker(self):
        import json as _json
        import zmq as _zmq
        while self._running:
            try:
                topic, event_type, data = await self._publish_queue.get()
                prefix = self.pub_topic_prefix.encode() if self.pub_topic_prefix else b""
                self._pub.send_multipart([
                    prefix + topic.encode("utf-8"),
                    event_type.encode("utf-8"),
                    _json.dumps(data, default=str).encode("utf-8"),
                ], flags=_zmq.NOBLOCK)
            except _zmq.Again:
                pass
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def stop_pub(self):
        self._running = False
        if self._pub_task:
            self._pub_task.cancel()
            try:
                await self._pub_task
            except asyncio.CancelledError:
                pass
        if self._pub is not None:
            try:
                self._pub.close(linger=0)
            except Exception:
                pass
            self._pub = None

    def get_status(self) -> dict:
        return {
            "methods": len(self.methods),
            "pub_port": self.pub_port,
            "pub_topic_prefix": self.pub_topic_prefix,
            "methods_sample": sorted(self.methods.keys())[:20],
        }


class _NoopBus:
    def publish(self, channel: str, data: dict):
        pass


def create_service_app(server: MethodServer, multi_db, title: str = "TopoOne Service",
                       lifespan=None):
    """FastAPI app：POST /zmq/{method} + GET /health。

    lifespan：可选的 asynccontextmanager（如 diagram 服务的 DiagramServices 启停）。
    """
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import JSONResponse

    app = FastAPI(title=title, lifespan=lifespan)

    @app.post("/zmq/{method}")
    async def call_zmq(method: str, body: dict = None):
        handler = server.methods.get(method)
        if not handler:
            raise HTTPException(404, f"Method {method} not found")
        params = body or {}
        try:
            result = handler(**params)
            if inspect.isawaitable(result):
                result = await result
            return {"result": result}
        except Exception as e:
            logger.exception(f"[{title}] method {method} failed")
            raise HTTPException(500, str(e))

    @app.get("/health")
    async def health():
        return {"status": "ok", "service": title, "methods": len(server.methods)}

    @app.get("/zmq/status")
    async def status():
        return server.get_status()

    return app


def run_service(methods_loader: Callable, data_dir: str, port: int,
                pub_port: Optional[int] = None, pub_topic_prefix: str = "",
                title: str = "TopoOne Service", host: str = "127.0.0.1"):
    """启动独立服务进程（同步阻塞，供 __main__ 入口调用）。

    methods_loader: (server, multi_db) -> None，负责注册方法（复用 register_* 函数）。
    """
    import uvicorn
    from topoone.http_logging import install_heartbeat_filter
    from topoone.db.manager import MultiDBManager

    install_heartbeat_filter()
    os.makedirs(data_dir, exist_ok=True)
    multi_db = MultiDBManager(data_dir)
    server = MethodServer(pub_port=pub_port, pub_topic_prefix=pub_topic_prefix)
    methods_loader(server, multi_db)
    app = create_service_app(server, multi_db, title=title)

    async def _main():
        await server.start_pub()
        config = uvicorn.Config(app, host=host, port=port, log_level="info")
        srv = uvicorn.Server(config)
        logger.info(f"[service] {title} starting on http://{host}:{port}")
        try:
            await srv.serve()
        finally:
            await server.stop_pub()
            multi_db.close_all()

    asyncio.run(_main())
