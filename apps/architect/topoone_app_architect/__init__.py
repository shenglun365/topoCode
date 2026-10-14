"""topoone_app_architect — Architect 工作台子项目后端（M13，kind=service，独立进程 :3470）。

承载 architect 全部路由（/architect 页面 + /api/architect/* + /web 静态 +
/ws/kb-analysis WS）+ 语义资产提取 agent（经 llm 服务）+ KbGateway（经 kb 服务）。
数据：architect.db 唯一主写方（arch_* 全部表）；project.db/topoone.db 只读（经 HTTP）。

用法：python -m topoone_app_architect --data-dir <dir> [--port 3470]
"""
