"""topoone_app_chat — AI Chat 子项目后端（M12，kind=service，独立进程 :3483）。

承载 chat 全部路由（/chat · /api/chat/* · /api/models · /api/skills ·
/api/template-locale · /api/drafts* · /api/notes · /api/archives）。
数据：topoone.db chat_drafts/chat_archives 主写；会话/消息经 llm 服务 session.*
（sessions.db）或现状内置路径（P3d 瘦身前）。

用法：python -m topoone_app_chat --data-dir <dir> [--port 3483]
"""
