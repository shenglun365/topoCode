"""TopoOne Backend - 入口 + 进程管理

模式:
  monolith (default)  — 单进程，所有模块在同一进程内
  distributed         — 多进程，各服务独立进程通过 ZMQ Internal Bus 通信

Phase 1: monolith = 原 BackendApp 行为；distributed = skeleton（占位 fallback）
Phase 2: distributed 启动 DB Service 子进程
Phase 3+: 逐步加入 AST/LLM/Agent Worker 子进程
"""

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime

# Windows: zmq.asyncio needs SelectorEventLoop (ProactorEventLoop is incompatible)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from config import TOPO_MODE
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
    register_module_methods,
)
from llm_service import register_llm_methods
from plugin_manager import PluginManager

setup_logging()
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# 单进程模式
# ═══════════════════════════════════════════════════════════════

class BackendApp:
    """单进程后端应用"""

    def __init__(self, data_dir: str = None, http_port: int = None, http_host: str = None):
        if data_dir is None:
            if sys.platform == "win32":
                data_dir = os.path.join(os.environ.get("APPDATA", ""), "TopoOne")
            elif sys.platform == "darwin":
                data_dir = os.path.join(os.path.expanduser("~"), "Library", "Application Support", "TopoOne")
            else:
                data_dir = os.path.join(os.path.expanduser("~"), ".topocode")

        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        self.http_port = http_port
        self.http_host = http_host or '0.0.0.0'
        self.multi_db = MultiDBManager(data_dir)

        dealer_port = int(os.environ.get('ZMQ_DEALER_PORT', '5671'))
        pub_port = int(os.environ.get('ZMQ_PUB_PORT', '5680'))
        self.server = ZMQServer(self.multi_db, dealer_port=dealer_port, pub_port=pub_port)
        self.plugin_manager = PluginManager()

    def _setup_signals(self):
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

    def register_all(self):
        """注册核心方法 + 插件方法"""
        register_project_methods(self.server, self.multi_db)
        register_analysis_methods(self.server, self.multi_db)
        register_knowledge_methods(self.server, self.multi_db)
        register_settings_methods(self.server, self.multi_db)
        register_backend_methods(self.server, self.multi_db, self.plugin_manager)
        register_render_methods(self.server, self.multi_db)
        register_llm_methods(self.server, self.multi_db)
        register_report_methods(self.server, self.multi_db)
        register_module_methods(self.server)
        logger.info(f"Registered {len(self.server.methods)} core methods")

        plugins_found = self.plugin_manager.discover()
        if plugins_found:
            logger.info(f"Discovered {len(plugins_found)} plugins: {[p.name for p in plugins_found]}")
            for p in plugins_found:
                self.plugin_manager.load_plugin(p.name)
            self.plugin_manager.register_all_methods(self.server, self.multi_db)

        # 同步 @register_skill 装饰器注册的技能到 skill_configs 表
        # 先导入所有含 @register_skill 的模块，确保装饰器在 sync 前触发
        try:
            from agent_workflow.workflows import overview as _  # noqa: F811
            from agent_workflow.workflows import component_analyst as _  # noqa: F811
            from agent_workflow.workflows import agentic_component_analyst as _  # noqa: F811
            from agent_workflow.toolkits import file_tools as _  # noqa: F811
            from agent_workflow.toolkits import symbol_tools as _  # noqa: F811
            from agent_workflow.toolkits import graph_tools as _  # noqa: F811
            from agent_workflow.toolkits import edge_tools as _  # noqa: F811
        except Exception as e:
            logger.warning(f"Failed to import skill modules: {e}")

        try:
            from agent_workflow.skill_registry import sync_skills_to_db
            sync_skills_to_db(self.multi_db)
        except Exception as e:
            logger.warning(f"Failed to sync skills to DB: {e}")

        # 注册 ingest 消费端 handler
        from ingest import setup_handlers
        setup_handlers(self.multi_db)

    def _start_optional_services(self):
        web_task = None
        ingest_task = None

        # 启动 ingest 消费循环
        try:
            from ingest import ingest_consumer_loop
            ingest_task = asyncio.create_task(
                ingest_consumer_loop(self.multi_db, interval=2.0)
            )
            logger.info("[Ingest] consumer loop started")
        except Exception as e:
            logger.warning(f"[Ingest] failed to start consumer: {e}")

        if self.http_port:
            self.multi_db.http_port = self.http_port
            self.multi_db.http_host = self.http_host
            try:
                from web_server import start_http_server
                cache_path = os.path.join(self.data_dir, "plantuml_cache.db")
                web_task = asyncio.create_task(
                    start_http_server(self.multi_db, port=self.http_port, host=self.http_host,
                                      cache_path=cache_path, zmq_server_instance=self.server)
                )
                logger.info(f"Web server task created for http://{self.http_host}:{self.http_port}")
            except Exception as e:
                logger.warning(f"Failed to start web server: {e}")
        return web_task, ingest_task

    async def run(self):
        logger.info(f"Starting TopoOne Backend (data_dir: {self.data_dir})")
        self.register_all()
        self._setup_signals()
        web_task, ingest_task = self._start_optional_services()
        try:
            await self.server.run_forever()
        finally:
            for task in (web_task, ingest_task):
                if task:
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            self.multi_db.close_all()
            logger.info("Backend shutdown complete")

    def shutdown(self):
        logger.info("Shutting down...")
        self.server.stop()
        self.multi_db.close_all()


# ═══════════════════════════════════════════════════════════════
# 多进程模式 — Phase 2+ 逐步启用
# ═══════════════════════════════════════════════════════════════

async def _run_distributed(data_dir: str, http_port: int | None, http_host: str | None):
    """多进程入口 — Supervisor 管理所有子进程生命周期"""
    logger.info("=" * 60)
    logger.info("TopoOne Distributed Mode")
    logger.info("=" * 60)
    logger.info(f"data_dir={data_dir}")

    from supervisor import Supervisor
    sv = Supervisor()

    # 注册受管进程
    sv.register("db_service",
                 [sys.executable, "-m", "db_service", "--data-dir", data_dir],
                 restart_limit=3)
    sv.register("agent_worker",
                 [sys.executable, "-m", "agent_worker", "--data-dir", data_dir],
                 restart_limit=3)

    await sv.start_all()

    # 主进程
    logger.info("[Distributed] Starting Main Process...")
    app = BackendApp(data_dir, http_port=http_port)
    app.multi_db._supervisor = sv
    if http_host:
        app.http_host = http_host

    shutdown_task = None

    async def _do_shutdown():
        logger.info("[Distributed] shutting down...")
        sv.stop()
        app.server.stop()
        await sv.shutdown_all(timeout=5.0)
        app.multi_db.close_all()
        logger.info("[Distributed] shutdown complete")

    def _signal_handler():
        nonlocal shutdown_task
        if shutdown_task is None:
            shutdown_task = asyncio.create_task(_do_shutdown())

    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop = asyncio.get_running_loop()
                loop.add_signal_handler(sig, _signal_handler)
            except (NotImplementedError, ValueError):
                try:
                    signal.signal(sig, lambda s, f: _signal_handler())
                except Exception:
                    pass
        await app.run()
    finally:
        if shutdown_task is None:
            await _do_shutdown()
        else:
            await shutdown_task


# ═══════════════════════════════════════════════════════════════
# CLI + 模式分发
# ═══════════════════════════════════════════════════════════════

def _parse_args() -> tuple:
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
    return data_dir, http_port, http_host, memory_limit


def _apply_memory_limit(memory_limit: int):
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


def _apply_app_config(app):
    try:
        row = app.multi_db.main_db.fetchone(
            "SELECT value FROM app_config WHERE key='http_host'"
        )
        if row and row["value"]:
            app.http_host = row["value"]
            logger.info(f"Loaded http_host from app_config: {app.http_host}")
    except Exception:
        pass
    try:
        row = app.multi_db.main_db.fetchone(
            "SELECT value FROM app_config WHERE key='http_port'"
        )
        if row and row["value"]:
            app.http_port = int(row["value"])
            logger.info(f"Loaded http_port from app_config: {app.http_port}")
    except Exception:
        pass


def main():
    print("[TopoOne Backend] Starting...", flush=True)
    data_dir, http_port, http_host, memory_limit = _parse_args()
    _apply_memory_limit(memory_limit)

    logger.info(f"Mode: {TOPO_MODE}")

    if TOPO_MODE == "distributed":
        if "--stdio" in sys.argv:
            logger.warning("stdio mode unsupported in distributed; falling back to monolith")
        else:
            asyncio.run(_run_distributed(data_dir, http_port, http_host))
            return

    # ── monolith ────────────────────────────────────────────────
    app = BackendApp(data_dir, http_port=http_port)
    if http_host:
        app.http_host = http_host
    _apply_app_config(app)

    if "--stdio" in sys.argv:
        _run_stdio(app)
    else:
        asyncio.run(app.run())


def _run_stdio(app):
    """通过 stdin/stdout 处理 RPC 请求"""
    app.register_all()

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        params = msg.get("params", {})
        rid = msg.get("id", 0)

        try:
            if method not in app.server.methods:
                resp = {"jsonrpc": "2.0", "id": rid, "result": None,
                        "error": {"code": -32601, "message": f"Method not found: {method}"}}
            else:
                result = app.server.methods[method](**params)
                if asyncio.iscoroutine(result):
                    result = asyncio.run(result)
                resp = {"jsonrpc": "2.0", "id": rid, "result": result, "error": None}
        except Exception as e:
            resp = {"jsonrpc": "2.0", "id": rid, "result": None,
                    "error": {"code": -32000, "message": str(e)}}
        print(json.dumps(resp, default=str), flush=True)


if __name__ == "__main__":
    main()
