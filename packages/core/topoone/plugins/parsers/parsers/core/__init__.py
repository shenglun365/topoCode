"""parsers.core — 统一语法分析核心引擎

架构:
  walker.py      — TreeSitterWalker: 统— AST 遍历器，按 LanguageExtractor 分发
  node_types.py  — NodeKind / EdgeKind 枚举
  symbol_model.py— Node / Edge / FileSymbolTable / UnresolvedReference
  emitter.py     — GraphEmitter: 写入 graph_node + graph_edge
  resolver.py    — ResolutionEngine: 两阶段跨文件名称解析
  synthesis.py   — DynamicSynthesizer: 回调/框架动态边合成
"""
