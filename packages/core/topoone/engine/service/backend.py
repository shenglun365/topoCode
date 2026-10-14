"""backend.* 后端信息命名空间 —— 原 core_service.py 解构（M03 T3.2）。"""
import logging

import time
import os
from datetime import datetime
from topoone.db.manager import SQLiteContext, MultiDBManager
from topoone.rpc.zmq_server import ZMQServer

logger = logging.getLogger(__name__)
def register_backend_methods(server: ZMQServer, multi_db: MultiDBManager, plugin_manager: 'PluginManager' = None):
    """注册后端管理方法"""

    @server.register("backend.start")
    def start_backend():
        return {"status": "running", "pid": os.getpid(), "port": 5671}

    @server.register("backend.stop")
    def stop_backend():
        server.stop()
        return {"status": "stopped"}

    @server.register("backend.restart")
    def restart_backend():
        return {"status": "restarting"}

    @server.register("backend.getStatus")
    def get_status():
        http_port = getattr(multi_db, 'http_port', None)
        http_host = getattr(multi_db, 'http_host', None)
        result = {"status": "running", "pid": os.getpid(), "port": 5671, "httpPort": http_port, "httpHost": http_host}
        sv = getattr(multi_db, '_supervisor', None)
        if sv:
            result["supervisor"] = sv.get_status()
        return result

    @server.register("backend.getMetrics")
    def get_metrics():
        """返回 Prometheus-style 运行时指标"""
        import os as _os
        import time as _time
        metrics = {
            "pid": os.getpid(),
            "uptime_sec": _time.time() - _time.monotonic(),
            "memory_mb": 0,
            "active_tasks": [],
            "supervisor": {},
        }
        # 内存
        try:
            import psutil
            proc = psutil.Process()
            metrics["memory_mb"] = proc.memory_info().rss / 1024 / 1024
        except Exception:
            pass
        # 任务
        from topoone.engine.store.task_store import TaskStore
        try:
            rows = TaskStore(multi_db.main_db)._db.execute(
                "SELECT id, name, status, progress FROM analysis_tasks WHERE status IN ('running','queued')"
            ).fetchall()
            metrics["active_tasks"] = [dict(r) for r in rows]
        except Exception:
            pass
        # supervisor
        sv = getattr(multi_db, '_supervisor', None)
        if sv:
            metrics["supervisor"] = sv.get_status()
        return metrics

    @server.register("backend.saveHttpConfig")
    def save_http_config(host: str = None, port: int = None):
        """持久化 HTTP 配置到 app_config 表"""
        from datetime import datetime
        now = datetime.now().isoformat()
        if host is not None:
            multi_db.main_db.execute(
                "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("http_host", host, now)
            )
        if port is not None:
            multi_db.main_db.execute(
                "INSERT OR REPLACE INTO app_config (key, value, updated_at) VALUES (?, ?, ?)",
                ("http_port", str(port), now)
            )
        multi_db.main_db.commit()
        logger.info(f"[saveHttpConfig] host={host} port={port}")
        return {"success": True}

    @server.register("backend.getHttpConfig")
    def get_http_config():
        """从 app_config 表读取持久化的 HTTP 配置"""
        rows = main_db.fetchall("SELECT key, value FROM app_config WHERE key IN ('http_host', 'http_port')")
        result = {}
        for r in rows:
            result[r["key"]] = r["value"]
        return {
            "host": result.get("http_host", ""),
            "port": int(result.get("http_port", 0)) if result.get("http_port") else 0,
        }

    @server.register("backend.ping")
    def ping():
        return {"pong": True, "timestamp": datetime.now().isoformat()}

    @server.register("app.checkVersion")
    def check_version(current: str = ""):
        """检查应用版本更新"""
        rows = main_db.fetchall(
            "SELECT key, value FROM app_config WHERE key IN ('latest_version', 'download_url_github', 'download_url_gitee')"
        )
        config = {r["key"]: r["value"] for r in rows}
        latest = config.get("latest_version", current)
        has_update = latest > current if current and latest else False
        return {
            "latest_version": latest,
            "has_update": has_update,
            "download_urls": {
                "github": config.get("download_url_github", ""),
                "gitee": config.get("download_url_gitee", ""),
            },
        }

    @server.register("backend.testPort")
    def test_port(port: int):
        """测试端口是否可用"""
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(('127.0.0.1', port))
                return {"port": port, "available": True}
            except OSError:
                return {"port": port, "available": False}

    # ==================== 插件管理 ====================
    if plugin_manager:
        @server.register("plugin.list")
        def list_plugins():
            plugins = plugin_manager.list_plugins()
            return {
                name: {
                    "name": info.name,
                    "version": info.version,
                    "description": info.description,
                    "loaded": name in plugin_manager._loaded,
                    "platforms": list(info.platforms) if info.platforms else [],
                }
                for name, info in plugins.items()
            }

        @server.register("plugin.get")
        def get_plugin(name: str):
            info = plugin_manager.get_plugin(name)
            if not info:
                return None
            return {
                "name": info.name,
                "version": info.version,
                "description": info.description,
                "entry": info.entry,
                "loaded": name in plugin_manager._loaded,
                "platforms": list(info.platforms) if info.platforms else [],
            }

        @server.register("plugin.load")
        def load_plugin(name: str):
            success = plugin_manager.load_plugin(name)
            return {"success": success}

        @server.register("plugin.unload")
        def unload_plugin(name: str):
            success = plugin_manager.unload_plugin(name)
            return {"success": success}

        @server.register("plugin.reload")
        def reload_plugin(name: str):
            success = plugin_manager.reload_plugin(name)
            return {"success": success}

        @server.register("plugin.install")
        def install_plugin(name: str):
            success = plugin_manager.install_requirements(name)
            return {"success": success}

    return server


# ==================== 模块管理方法（远程下载） ====================
