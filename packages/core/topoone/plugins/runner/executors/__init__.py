"""执行器实现 — 会话化三方 coding agent 适配层。

- opencode.py   OpenCodeSessionExecutor（opencode serve 真实会话 API：session/message/
                permissions/abort/diff，按项目根自动拉起 serve 进程）
- cline.py      ClineSdkExecutor（@topocode/cline-sidecar Node 常驻进程，stdio JSON-RPC，
                architect 自主模式，支持资产地图工具注入）
- codex_server.py CodexServerExecutor（codex app-server JSON-RPC 会话模式，S2）

统一约束：实现 topocode_agent.subagent.CodingAgentExecutor 协议
（execute / execute_stream / health_check / env_check），调度器零感知。
"""
