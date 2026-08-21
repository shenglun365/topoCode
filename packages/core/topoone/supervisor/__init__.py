"""topoone.supervisor — 进程治理（supervisor + topo CLI + TUI）。

- supervisor.py: 子进程生命周期管理（spawn/心跳/HTTP 探针/崩溃重启/backoff）
- cli.py: `topo` CLI 入口（serve/status/doctor/...），入口 `python -m topoone.supervisor.cli`
- tui/: Textual 终端界面（服务状态/任务/日志三标签）
进程注册表由 apps/*/manifest.toml 驱动（kind=service app + 固定核心进程）。
"""
