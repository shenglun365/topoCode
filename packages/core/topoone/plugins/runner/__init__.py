"""topoone.plugins.runner — Coding Agent Runner 独立进程（:3458）。

管理第三方 coding agent（opencode/codex/claude-code 等）子进程：经 HTTP
接收执行任务，经 WebSocket 流式推送 agent 会话状态。core 内置服务（非插件，
无 plugin.json），由 supervisor 以 `python -m topoone.plugins.runner` 纳管。
"""
