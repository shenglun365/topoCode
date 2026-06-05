"""Community plugin — 社区分析 (Louvain)

由 analyst_runner 通过 lazy import 调用:
  from community_analysis import analyze_communities

无需注册 ZMQ methods。
"""


def register_methods(server, multi_db):
    """PluginManager 调用此函数注册方法（空 — community 由 analyst_runner 直接 import）"""
    pass
