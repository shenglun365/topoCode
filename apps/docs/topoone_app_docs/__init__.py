"""topoone_app_docs — 文档浏览子项目后端（M11，kind=service，独立进程 :3481）。

承载 doc viewer 全部路由（/doc · /code · /api/community-* · /api/file* ·
/api/heatmap · /api/diagram* · /api/graph-layout）+ web_root 业务 API
（/api/projects · /api/tasks · /api/docs · /api/import* · /api/export* ·
/api/verify*）+ render.*/report.* RPC 方法。数据：共享 project.db 只读。

用法：python -m topoone_app_docs --data-dir <dir> [--port 3481]
"""
