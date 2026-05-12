"""
RPC Server — ZMQ RPC 服务器

- DEALER socket (5671): 接收 3 帧 RPC 请求，返回 3 帧响应
- PUB socket (5680): 发布 3 帧事件推送
- @server.register("method.name"): 注册方法装饰器
"""
import asyncio
import json
import logging
import signal
import sys
import traceback
from datetime import datetime

import zmq
import zmq.asyncio

from .config import ZMQ_BIND_HOST, ZMQ_DEALER_PORT, ZMQ_PUB_PORT, RPC_TIMEOUT

logger = logging.getLogger(__name__)


class RPCHandler:
    """ZMQ RPC 服务器"""

    def __init__(self):
        self.context = zmq.asyncio.Context()
        self.dealer = self.context.socket(zmq.DEALER)
        self.pub = self.context.socket(zmq.PUB)
        self.methods = {}  # method_name -> callable
        self._running = False

    def bind(self):
        """绑定端口"""
        self.dealer.bind(f"tcp://{ZMQ_BIND_HOST}:{ZMQ_DEALER_PORT}")
        self.pub.bind(f"tcp://{ZMQ_BIND_HOST}:{ZMQ_PUB_PORT}")
        logger.info(f"RPC Server bound on DEALER:{ZMQ_DEALER_PORT} PUB:{ZMQ_PUB_PORT}")

    def register(self, name: str):
        """
        装饰器: @server.register('analysis.createTask')

        注册 RPC 方法。
        """
        def decorator(func):
            self.methods[name] = func
            logger.debug(f"Registered method: {name}")
            return func
        return decorator

    def publish(self, topic: str, event_type: str, data: dict):
        """
        发布 3 帧事件推送

        Frame 1: topic
        Frame 2: event_type
        Frame 3: data_json
        """
        try:
            self.pub.send_multipart([
                topic.encode("utf-8"),
                event_type.encode("utf-8"),
                json.dumps(data, ensure_ascii=False).encode("utf-8"),
            ])
        except Exception as e:
            logger.error(f"Publish failed: {e}")

    async def handle_request(self, frames):
        """
        处理 3 帧 RPC 请求

        Frame 1: requestId
        Frame 2: method
        Frame 3: params_json

        Returns:
            3 帧响应: [requestId, result_json, error_json]
        """
        request_id = frames[0].decode("utf-8")
        method_name = frames[1].decode("utf-8")

        # 解析参数
        params = {}
        if len(frames) > 2 and frames[2]:
            try:
                params = json.loads(frames[2].decode("utf-8"))
            except json.JSONDecodeError as e:
                return self._error_response(request_id, -32700, f"Parse error: {e}")

        # 查找方法
        if method_name not in self.methods:
            return self._error_response(request_id, -32601, f"Method not found: {method_name}")

        # 调用方法
        try:
            func = self.methods[method_name]
            result = func(**params)

            # 如果是协程，await 它
            if asyncio.iscoroutine(result):
                result = await result

            return self._success_response(request_id, result)

        except Exception as e:
            logger.error(f"Method {method_name} failed: {e}", exc_info=True)
            return self._error_response(request_id, -32000, str(e))

    def _success_response(self, request_id: str, result) -> list:
        return [
            request_id.encode("utf-8"),
            json.dumps(result, ensure_ascii=False, default=str).encode("utf-8"),
            b"null",
        ]

    def _error_response(self, request_id: str, code: int, message: str) -> list:
        return [
            request_id.encode("utf-8"),
            b"null",
            json.dumps({"code": code, "message": message}).encode("utf-8"),
        ]

    async def start(self):
        """主循环"""
        self._running = True
        self.bind()

        logger.info("RPC Server started, waiting for requests...")

        # 注册信号处理
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: self._stop())

        while self._running:
            try:
                frames = await self.dealer.recv_multipart()
                if len(frames) < 2:
                    logger.warning(f"Invalid request: {len(frames)} frames")
                    continue

                response = await self.handle_request(frames)
                await self.dealer.send_multipart(response)

            except zmq.ZMQError as e:
                if self._running:
                    logger.error(f"ZMQ error: {e}")
            except Exception as e:
                logger.error(f"Request handling error: {e}", exc_info=True)

        self.stop()

    def _stop(self):
        self._running = False

    def stop(self):
        """清理资源"""
        logger.info("RPC Server stopping...")
        self.dealer.close()
        self.pub.close()
        self.context.term()


# ==================== 全局服务器实例 ====================
server = RPCHandler()


async def main():
    """主入口"""
    import os
    import sys

    # 添加项目根目录到路径
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # 初始化日志
    from .config import LOG_DIR, LOG_LEVEL
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, LOG_LEVEL, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(os.path.join(LOG_DIR, "rpc_server.log")),
        ],
    )

    # 初始化数据库
    from sqlite_store.connection import MultiDBManager
    from .config import DB_DIR
    multi_db = MultiDBManager(DB_DIR)

    # 注册分析方法
    from task_manager import register_analysis_methods
    register_analysis_methods(server, multi_db)

    # 导入语言处理器（自动注册到 LanguageRegistry）
    try:
        from parsers_new import languages  # noqa: F401
        logger.info("Language processors loaded")
    except ImportError as e:
        logger.warning(f"Language processors not loaded: {e}")

    # 启动服务器
    await server.start()


if __name__ == "__main__":
    asyncio.run(main())
