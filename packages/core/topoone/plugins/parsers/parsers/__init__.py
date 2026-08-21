"""
parsers — 多语言语义图谱引擎 (v2)

基于 tree-sitter + LanguageExtractor 声明式架构。

架构:
- core/        : 核心引擎 (walker, resolver, emitter, synthesis, node_types, symbol_model)
- languages/   : 18种语言提取器 (声明式 LanguageExtractor 接口)
- frameworks/  : 框架感知解析器 (Django, Flask, Spring, Express, React)
- language_loader.py : tree-sitter parser 加载与缓存
- db_adapter.py : SQLite 适配层

数据流:
  源文件 → TreeSitterWalker → [Node] + [UnresolvedReference]
       → GraphEmitter → graph_node (SQLite)
       → ResolutionEngine → [Edge]
       → GraphEmitter → graph_edge (SQLite)
       → DynamicSynthesizer → 合成边
       → 社区分析 + 结果汇总

数据存储: SQLite graph_node (19列) + graph_edge (新表)
"""
