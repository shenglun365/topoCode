"""TopoOne 核心基础框架。

模块分层（自底向上）：
  db / rpc / messaging  — 共享内核（零产品逻辑）
  engine                — 核心引擎（kb 进程 :3459）
  llm                   — llm 服务（:3484）
  agent                 — agent 服务（:3482）
  gateway               — 统一端口网关（:3456）
  supervisor            — 进程治理 + topo CLI + TUI
  plugins               — 本地插件（parsers/community/...）+ 生态（mcp/runner）

设计文档：docs/plan/split/README.md
"""

__version__ = "0.3.0"
