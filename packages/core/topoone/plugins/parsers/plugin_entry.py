"""Parsers plugin — 多语言语法分析引擎 (v2)

由 analyst_runner 通过 lazy import 调用:
  from parsers.core.walker import TreeSitterWalker
  from parsers.core.resolver import ResolutionEngine
  from parsers.core.emitter import GraphEmitter
  from parsers.languages import EXTRACTORS

架构:
  core/       — 核心引擎 (walker, resolver, emitter, synthesis)
  languages/  — 18 种语言提取器 (声明式 LanguageExtractor)
  frameworks/ — 框架感知解析器 (Django, React, Spring, ...)

无需注册 ZMQ methods。
"""


def register_methods(server, multi_db):
    """PluginManager 调用此函数注册方法（空 — parsers 由 analyst_runner 直接 import）"""
    pass
