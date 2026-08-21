"""topoone_app_workbench — 主工作台后端薄层（kind=core，无独立进程）。

由核心引擎进程按 manifest（apps/workbench/manifest.toml）在进程内加载并注册
knowledge.* 方法（见 server.register_methods）。依赖 topoone-core（db 层 + 方法注册约定）。
"""
