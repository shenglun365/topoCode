"""Reports plugin — 文档预览 HTTP 服务 (FastAPI + uvicorn)

由 main.py 在启动时检查安装状态后调用:
  from reports import start_http_server

无需注册 ZMQ methods。
"""


def register_methods(server, multi_db):
    """PluginManager 调用此函数注册方法（空 — reports 由 main.py 直接调用）"""
    pass
