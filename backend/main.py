"""TopoOne Backend - 入口 + 进程管理 (多数据库架构)"""

import asyncio
import json
import logging
import os
import signal
import sys
import uuid
from datetime import datetime

from sqlite_ctx import MultiDBManager
from zmq_server import ZMQServer
from core_service import (
    register_project_methods,
    register_analysis_methods,
    register_knowledge_methods,
    register_settings_methods,
    register_backend_methods,
    register_render_methods,
)

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


class BackendApp:
    """后端应用"""

    def __init__(self, data_dir: str = None):
        # 数据目录
        if data_dir is None:
            if os.name == "nt":  # Windows
                data_dir = os.path.join(os.environ.get("APPDATA", ""), "TopoOne")
            elif os.name == "darwin":  # macOS
                data_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "TopoOne")
            else:  # Linux
                data_dir = os.path.join(os.path.expanduser("~"), ".topoone")

        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir

        # 多数据库管理器
        self.multi_db = MultiDBManager(data_dir)

        # 从环境变量读取端口配置
        dealer_port = int(os.environ.get('ZMQ_DEALER_PORT', '5671'))
        pub_port = int(os.environ.get('ZMQ_PUB_PORT', '5680'))

        self.server = ZMQServer(self.multi_db, dealer_port=dealer_port, pub_port=pub_port)
        self._setup_signals()

    def _setup_signals(self):
        """设置信号处理"""
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def _signal_handler(self, signum, frame):
        """信号处理"""
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
        logger.info(f"Registered {len(self.server.methods)} methods")

    async def run(self):
        """运行后端"""
        logger.info(f"Starting TopoOne Backend (data_dir: {self.data_dir})")
        self.register_all()
        await self.server.run_forever()

    def shutdown(self):
        """关闭后端"""
        logger.info("Shutting down...")
        self.server.stop()
        self.multi_db.close_all()


def main():
    """主入口"""
    # 支持命令行参数
    data_dir = None
    if len(sys.argv) > 1:
        data_dir = sys.argv[1]

    app = BackendApp(data_dir)

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
