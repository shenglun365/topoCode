"""Parsers plugin — 语言解析器

由 analyst_runner 通过 lazy import 调用:
  from parsers.parser import parse_file
  from parsers.extract_global_symbols import extract_global_symbols
  from parsers.extract_call_graph import extract_call_graph
  from parsers.extract_dependency_graph import extract_dependency_graph

无需注册 ZMQ methods。
"""


def register_methods(server, multi_db):
    """PluginManager 调用此函数注册方法（空 — parsers 由 analyst_runner 直接 import）"""
    pass
