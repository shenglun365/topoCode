"""TopoOne Backend - 入口 + 进程管理 (多数据库架构)"""

import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from datetime import datetime

from logging_config import setup_logging
from sqlite_ctx import MultiDBManager
from zmq_server import ZMQServer
from core_service import (
    register_project_methods,
    register_analysis_methods,
    register_knowledge_methods,
    register_settings_methods,
    register_backend_methods,
    register_render_methods,
    register_report_methods,
)
from llm_service import register_llm_methods

# 初始化统一日志系统
setup_logging()
logger = logging.getLogger(__name__)


class BackendApp:
    """后端应用"""

    def __init__(self, data_dir: str = None, http_port: int = None, http_host: str = None):
        # 数据目录
        if data_dir is None:
            if sys.platform == "win32":  # Windows
                data_dir = os.path.join(os.environ.get("APPDATA", ""), "TopoOne")
            elif sys.platform == "darwin":  # macOS
                data_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "TopoOne")
            else:  # Linux
                data_dir = os.path.join(os.path.expanduser("~"), ".topoone")

        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        self.http_port = http_port
        self.http_host = http_host or '127.0.0.1'

        # 多数据库管理器
        self.multi_db = MultiDBManager(data_dir)

        # 从环境变量读取端口配置
        dealer_port = int(os.environ.get('ZMQ_DEALER_PORT', '5671'))
        pub_port = int(os.environ.get('ZMQ_PUB_PORT', '5680'))

        self.server = ZMQServer(self.multi_db, dealer_port=dealer_port, pub_port=pub_port)

    def _setup_signals(self):
        """设置信号处理 - 在 asyncio 事件循环中注册"""
        try:
            loop = asyncio.get_running_loop()

            def _handle_signal():
                logger.info("Received shutdown signal, stopping server...")
                self.server.stop()

            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, _handle_signal)
                except (NotImplementedError, ValueError):
                    try:
                        signal.signal(sig, _handle_signal)
                    except (ValueError, OSError):
                        logger.warning(f"Signal {sig} not supported on this platform")
        except Exception as e:
            logger.warning(f"Failed to setup signal handlers: {e}")

    def _signal_handler(self, signum, frame):
        """信号处理 (兼容旧版)"""
        logger.info(f"Received signal {signum}, shutting down...")
        self.shutdown()

    def register_all(self):
        """注册所有方法"""
        register_project_methods(self.server, self.multi_db)
        register_analysis_methods(self.server, self.multi_db)
        register_knowledge_methods(self.server, self.multi_db)
        register_settings_methods(self.server, self.multi_db)
        register_backend_methods(self.server, self.multi_db)
        register_render_methods(self.server, self.multi_db)
        register_llm_methods(self.server, self.multi_db)
        register_report_methods(self.server, self.multi_db)
        logger.info(f"Registered {len(self.server.methods)} methods")

    async def run(self):
        """运行后端"""
        logger.info(f"Starting TopoOne Backend (data_dir: {self.data_dir})")
        self.register_all()
        self._setup_signals()  # 必须在 asyncio 事件循环中注册
        web_task = None
        if self.http_port:
            self.multi_db.http_port = self.http_port
            self.multi_db.http_host = self.http_host
            try:
                from web_server import start_http_server
                cache_path = os.path.join(self.data_dir, "plantuml_cache.db")
                web_task = asyncio.create_task(
                    start_http_server(self.multi_db, port=self.http_port, host=self.http_host, cache_path=cache_path)
                )
                logger.info(f"Web server started on http://{self.http_host}:{self.http_port}")
            except Exception as e:
                logger.warning(f"Failed to start web server: {e}")
        try:
            await self.server.run_forever()
        finally:
            if web_task:
                web_task.cancel()
                try:
                    await web_task
                except asyncio.CancelledError:
                    pass
            self.multi_db.close_all()
            logger.info("Backend shutdown complete")

    def shutdown(self):
        """关闭后端"""
        logger.info("Shutting down...")
        self.server.stop()
        self.multi_db.close_all()


def main():
    """主入口"""
    print("[TopoOne Backend] Starting...", flush=True)

    # 支持命令行参数
    data_dir = None
    http_port = None
    http_host = None
    memory_limit = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "--http-port" and i + 1 < len(args):
            http_port = int(args[i + 1])
            i += 2
        elif args[i] == "--http-host" and i + 1 < len(args):
            http_host = args[i + 1]
            i += 2
        elif args[i] == "--memory-limit" and i + 1 < len(args):
            memory_limit = int(args[i + 1])
            i += 2
        elif not args[i].startswith("--"):
            data_dir = args[i]
            i += 1
        else:
            i += 1

    # 设置进程内存上限 (MB)
    if memory_limit and memory_limit > 0:
        try:
            import resource
            limit_bytes = memory_limit * 1024 * 1024
            resource.setrlimit(resource.RLIMIT_AS, (limit_bytes, limit_bytes))
            logger.info(f"Memory limit set to {memory_limit} MB")
        except ImportError:
            logger.warning("resource module not available, memory limit not set")
        except Exception as e:
            logger.warning(f"Failed to set memory limit: {e}")

    app = BackendApp(data_dir, http_port=http_port)
    if http_host:
        app.http_host = http_host

    # 如果是 stdio 模式 (调试用)
    if "--stdio" in sys.argv:
        run_stdio_mode(app)
    else:
        # ZeroMQ 模式
        asyncio.run(app.run())


def run_stdio_mode(app):
    """stdio 模式 (调试用)"""
    app.register_all()

    def handle_line(line: str):
        try:
            msg = json.loads(line)
            method = msg.get("method")
            params = msg.get("params", {})
            request_id = msg.get("id", 0)

            if method and method in app.server.methods:
                result = app.server.methods[method](**params)
                if asyncio.iscoroutine(result):
                    result = asyncio.run(result)

                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": result,
                    "error": None,
                }
            else:
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": None,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }

            print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": 0,
                "result": None,
                "error": {"code": -32000, "message": str(e)},
            }
            print(json.dumps(error_response), flush=True)

    # 读取 stdin
    for line in sys.stdin:
        handle_line(line.strip())


if __name__ == "__main__":
    main()
