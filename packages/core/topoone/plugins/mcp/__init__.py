"""topoone.plugins.mcp — MCP Server 独立进程（:3460）。

对外部 agent/工具暴露 Model Context Protocol；工具调用转发至 architect
服务（默认 :3470）并记录外部调用日志。core 内置服务（非插件，无 plugin.json），
由 supervisor 以 `python -m topoone.plugins.mcp` 纳管。
"""
