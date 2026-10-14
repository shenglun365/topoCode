"""topoone.gateway — 统一入口网关（:3456）。

纯基础设施：反向代理 / RPC 命名空间路由 / 事件桥 / 聚合健康 / 鉴权 + SPA 静态。
路由表与静态挂载由 apps/*/manifest.toml 驱动（M06）。入口: python -m topoone.gateway。
"""
