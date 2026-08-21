"""topoone_app_workbench.server — kind=core 方法注册入口。

`register_methods(server, multi_db)` 签名与引擎注册函数一致；由核心进程
`register_all` 末尾的 manifest 加载调用（importlib + try/except 隔离）。
"""
from topoone_app_workbench.server.knowledge_service import register_knowledge_methods


def register_methods(server, multi_db):
    """注册 workbench 后端薄层的全部 RPC 方法（当前：knowledge.*）。"""
    register_knowledge_methods(server, multi_db)
