"""TopoOne kb（core 引擎）进程应用 — 原 backend-core/main.py（M03 T3.3）。

入口: python -m topoone.engine  （engine/__main__.py → app.main()）

模式:
  monolith (default)  — 单进程，所有模块在同一进程内
  distributed         — 多进程，各服务独立进程通过 ZMQ Internal Bus 通信
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

import uvicorn

# Windows: zmq.asyncio needs SelectorEventLoop (ProactorEventLoop is incompatible)
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from pathlib import Path as _Path

_REPO_ROOT = _Path(__file__).resolve().parents[4]

from topoone.config import TOPO_MODE
from topoone.logging_config import setup_logging
from topoone.db.manager import MultiDBManager
from topoone.rpc.zmq_server import ZMQServer
from topoone.engine.service import (
    register_project_methods,
    register_dir_methods,
    register_settings_methods,
    register_backend_methods,
    register_module_methods,
    register_version_methods,
)
from topoone.engine.task_manager import register_analysis_methods
from topoone.llm.service import register_llm_methods
from topoone.plugins.manager import PluginManager

setup_logging()
logger = logging.getLogger(__name__)

# 压制非 AI Chat 模块的 INFO 日志（诊断模式下可启用）
if os.environ.get("TOPOCODE_CHAT_DEBUG", "") == "1":
    for _name in ['topoone.rpc.zmq_server', 'topoone.messaging', 'topoone.db.connection',
                   'topoone.engine.task_manager', 'topoone.engine.db_service',
                   'topoone.engine.ingest', 'topoone.db.data_layer', 'topoone.engine.store',
                   'plugin_manager', 'topoone.engine.export_service', 'topoone.engine.verify_service',
                   'topoone.engine.community_data', 'topoone.db.state_store',
                   'topoone.engine.analysis_context']:
        logging.getLogger(_name).setLevel(logging.WARNING)
    logging.getLogger('tools_executor').setLevel(logging.INFO)
    logging.getLogger('llm_service').setLevel(logging.INFO)
    logger.info("[CHAT_DEBUG] Non-essential loggers suppressed, chat tracing enabled")


# ═══════════════════════════════════════════════════════════════
# 单进程模式
# ═══════════════════════════════════════════════════════════════

class BackendApp:
    """单进程后端应用"""

    def __init__(self, data_dir: str = None, http_port: int = None, http_host: str = None,
                 no_spawn: bool = False):
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
        self.no_spawn = no_spawn
        self.multi_db = MultiDBManager(data_dir)

        dealer_port = int(os.environ.get('ZMQ_DEALER_PORT', '5671'))
        pub_port = int(os.environ.get('ZMQ_PUB_PORT', '5680'))
        self.server = ZMQServer(self.multi_db, dealer_port=dealer_port, pub_port=pub_port)
        self.plugin_manager = PluginManager()
        self._web_proc = None
        self._arch_proc = None
        self._mcp_proc = None

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
        from topoone.engine.service import register_all_engine_methods
        register_all_engine_methods(self.server, self.multi_db,
                                    module_manager=None, plugin_manager=self.plugin_manager)
        register_analysis_methods(self.server, self.multi_db)
        register_llm_methods(self.server, self.multi_db)
        logger.info(f"Registered {len(self.server.methods)} core methods")

        topoone_plugins_dir = _Path(__file__).resolve().parents[1] / "plugins"
        plugins_found = self.plugin_manager.discover(plugins_dir=str(topoone_plugins_dir))
        if plugins_found:
            logger.info(f"Discovered {len(plugins_found)} plugins: {[p.name for p in plugins_found]}")
            for p in plugins_found:
                self.plugin_manager.load_plugin(p.name)
            self.plugin_manager.register_all_methods(self.server, self.multi_db)

        # 同步 @register_skill 装饰器注册的技能到 skill_configs 表
        # 先导入所有含 @register_skill 的模块，确保装饰器在 sync 前触发
        try:
            from topoone.agent.agent_workflow.workflows import overview as _  # noqa: F811
            from topoone.agent.agent_workflow.workflows import component_analyst as _  # noqa: F811
            from topoone.agent.agent_workflow.workflows import agentic_component_analyst as _  # noqa: F811
            from topoone.agent.agent_workflow.toolkits import file_tools as _  # noqa: F811
            from topoone.agent.agent_workflow.toolkits import symbol_tools as _  # noqa: F811
            from topoone.agent.agent_workflow.toolkits import graph_tools as _  # noqa: F811
            from topoone.agent.agent_workflow.toolkits import edge_tools as _  # noqa: F811
        except Exception as e:
            logger.warning(f"Failed to import skill modules: {e}")

        try:
            from topoone.agent.agent_workflow.skill_registry import sync_skills_to_db
            sync_skills_to_db(self.multi_db)
        except Exception as e:
            logger.warning(f"Failed to sync skills to DB: {e}")

        # 注册 ingest 消费端 handler
        from topoone.engine.ingest import setup_handlers
        setup_handlers(self.multi_db)

        # M10: manifest 驱动加载 kind=core app（进程内注册方法，try/except 隔离）
        self._register_core_app_methods()

    def _register_core_app_methods(self):
        """M10: 按 manifest 加载 kind=core app 并在进程内注册其方法。

        python_entry 形如 'module:func'（func 缺省 register_methods）。失败仅降级该
        app（ERROR 日志），不影响核心进程与其他 app（隔离性）。
        """
        import importlib
        try:
            from topoone.manifest import discover_apps
            apps = discover_apps(str(_REPO_ROOT))
        except Exception as e:
            logger.error(f"[manifest] app discovery failed: {e}")
            return
        for app in apps.values():
            if app.kind != "core" or not app.python_entry:
                continue
            try:
                mod_name, _, func_name = app.python_entry.partition(":")
                mod = importlib.import_module(mod_name)
                reg = getattr(mod, func_name or "register_methods")
                reg(self.server, self.multi_db)
                logger.info(f"[manifest] registered kind=core app '{app.name}' methods via {app.python_entry}")
            except Exception as e:
                logger.error(f"[manifest] FAILED to register kind=core app '{app.name}' ({app.python_entry}): {e}")

    def _start_optional_services(self):
        self._ingest_consumer = None
        self._web_proc = None

        # 启动 ingest 消费后台线程
        try:
            from topoone.engine.ingest import IngestConsumer
            self._ingest_consumer = IngestConsumer(self.multi_db, interval=2.0)
            self._ingest_consumer.start()
        except Exception as e:
            logger.warning(f"[Ingest] failed to start consumer: {e}")

        # 启动 Data API（HTTP 写代理），供子进程 Web 端使用
        try:
            from topoone.rpc.data_api import app as data_app, set_globals as set_data_globals
            from topoone.http_logging import install_heartbeat_filter
            install_heartbeat_filter()
            data_port = int(os.environ.get('DATA_API_PORT', '3459'))
            set_data_globals(self.multi_db, self.server)
            self._data_api_thread = threading.Thread(
                target=lambda: uvicorn.run(data_app, host='127.0.0.1', port=data_port, log_level='info'),
                daemon=True
            )
            self._data_api_thread.start()
            logger.info(f"Data API started on http://127.0.0.1:{data_port}")
        except Exception as e:
            self._data_api_thread = None
            logger.warning(f"Failed to start data API: {e}")

        # no_spawn：reports/architect/mcp 由 supervisor 作为独立子进程纳管，此处不再自行 spawn
        # （`topo serve` 唯一 owner 场景；独立运行时 supervisor 负责拉起）
        if self.no_spawn:
            logger.info("no_spawn mode: reports/architect/mcp handled by supervisor")
            return

        # 启动 Web 端（子进程）
        if self.http_port:
            self.multi_db.http_port = self.http_port
            self.multi_db.http_host = self.http_host
            try:
                # Use subprocess to run web端 as a child process（M06: 入口迁至核心包）
                data_port = int(os.environ.get('DATA_API_PORT', '3459'))
                self._web_proc = subprocess.Popen(
                    [sys.executable, "-m", "topoone.gateway",
                     "--port", str(self.http_port),
                     "--host", str(self.http_host),
                     "--data-dir", self.data_dir,
                     "--data-api-port", str(data_port)],
                    stdout=None, stderr=None,
                )
                logger.info(f"Web server subprocess started (PID {self._web_proc.pid}) on http://{self.http_host}:{self.http_port}")
            except Exception as e:
                logger.warning(f"Failed to start web server subprocess: {e}")

        # 启动 Architect 独立服务（子进程，3470）— M13 迁至 apps/architect（python -m topoone_app_architect）
        arch_port = int(os.environ.get('ARCH_PORT', '3470'))
        try:
            self._arch_proc = subprocess.Popen(
                [sys.executable, "-m", "topoone_app_architect",
                 "--port", str(arch_port),
                 "--host", "127.0.0.1",
                 "--data-dir", self.data_dir],
                stdout=None, stderr=None,
            )
            logger.info(f"Architect server subprocess started (PID {self._arch_proc.pid}) on http://127.0.0.1:{arch_port}")
        except Exception as e:
            self._arch_proc = None
            logger.warning(f"Failed to start architect subprocess: {e}")

        # 启动 MCP Server（子进程，3460）— 提供外部 agent/工具访问 KB 的通道
        try:
            mcp_port = int(os.environ.get('MCP_SERVER_PORT', '3460'))
            # M08: MCP Server 入口迁至核心包（python -m topoone.plugins.mcp）
            self._mcp_proc = subprocess.Popen(
                [sys.executable, "-m", "topoone.plugins.mcp"],
                stdout=None, stderr=None,
            )
            logger.info(f"MCP server subprocess started (PID {self._mcp_proc.pid}) on http://127.0.0.1:{mcp_port}")
        except Exception as e:
            self._mcp_proc = None
            logger.warning(f"Failed to start MCP server subprocess: {e}")

    async def run(self):
        logger.info(f"Starting TopoOne Backend (data_dir: {self.data_dir})")
        self.register_all()
        self._setup_signals()
        self._start_optional_services()
        try:
            await self.server.run_forever()
        finally:
            self._shutdown_web_process()
            self._shutdown_arch_process()
            self._shutdown_mcp_process()
            self.multi_db.close_all()
            logger.info("Backend shutdown complete")

    def _shutdown_arch_process(self):
        if self._arch_proc and self._arch_proc.poll() is None:
            logger.info(f"Terminating architect subprocess (PID {self._arch_proc.pid})...")
            self._arch_proc.terminate()
            try:
                self._arch_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Architect subprocess did not exit in 5s, killing...")
                self._arch_proc.kill()
                self._arch_proc.wait(timeout=2)

    def _shutdown_mcp_process(self):
        if self._mcp_proc and self._mcp_proc.poll() is None:
            logger.info(f"Terminating MCP server subprocess (PID {self._mcp_proc.pid})...")
            self._mcp_proc.terminate()
            try:
                self._mcp_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("MCP server subprocess did not exit in 5s, killing...")
                self._mcp_proc.kill()
                self._mcp_proc.wait(timeout=2)

    def _shutdown_web_process(self):
        if self._web_proc and self._web_proc.poll() is None:
            logger.info(f"Terminating web server subprocess (PID {self._web_proc.pid})...")
            self._web_proc.terminate()
            try:
                self._web_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("Web server subprocess did not exit in 5s, killing...")
                self._web_proc.kill()
                self._web_proc.wait(timeout=2)
            logger.info("Web server subprocess terminated")

    def shutdown(self):
        logger.info("Shutting down...")
        self._shutdown_web_process()
        self._shutdown_arch_process()
        self._shutdown_mcp_process()
        self.server.stop()
        if self._ingest_consumer:
            self._ingest_consumer.stop()
            self._ingest_consumer.join(timeout=2.0)
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

    from topoone.supervisor.supervisor import Supervisor
    sv = Supervisor()

    # 注册受管进程（M03: db_service 迁至 topoone.engine.db_service；M05: agent_worker 并入 topoone.agent）
    sv.register("db_service",
                 [sys.executable, "-m", "topoone.engine.db_service", "--data-dir", data_dir],
                 restart_limit=3)
    sv.register("agent_worker",
                 [sys.executable, "-m", "topoone.agent", "--data-dir", data_dir],
                 restart_limit=3)
    # M13: architect 迁至 apps/architect（python -m topoone_app_architect）
    sv.register("architect",
                 [sys.executable, "-m", "topoone_app_architect",
                  "--port", str(int(os.environ.get('ARCH_PORT', '3470'))),
                  "--host", "127.0.0.1", "--data-dir", data_dir],
                 restart_limit=3)
    # M08: MCP Server 入口迁至核心包（python -m topoone.plugins.mcp）
    sv.register("mcp_server",
                 [sys.executable, "-m", "topoone.plugins.mcp"],
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
        if app._ingest_consumer:
            app._ingest_consumer.stop()
            app._ingest_consumer.join(timeout=2.0)
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
    no_spawn = False
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
        elif args[i] == "--no-spawn":
            no_spawn = True
            i += 1
        elif not args[i].startswith("--"):
            data_dir = args[i]
            i += 1
        else:
            i += 1
    return data_dir, http_port, http_host, memory_limit, no_spawn


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
    data_dir, http_port, http_host, memory_limit, no_spawn = _parse_args()
    _apply_memory_limit(memory_limit)

    logger.info(f"Mode: {TOPO_MODE}")

    if TOPO_MODE == "distributed":
        if "--stdio" in sys.argv:
            logger.warning("stdio mode unsupported in distributed; falling back to monolith")
        else:
            asyncio.run(_run_distributed(data_dir, http_port, http_host))
            return

    # ── monolith ────────────────────────────────────────────────
    app = BackendApp(data_dir, http_port=http_port, no_spawn=no_spawn)
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
