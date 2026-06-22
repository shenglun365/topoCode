"""Recipe 定义：每个分析场景用哪些 ingredient。"""

# 组件摘要（非 Agentic）— 完整分析
RECIPE_COMPONENT_ANALYSIS = [
    "community_info",
    "file_list",
    "directory_tree",
    "exported_symbols",
    "file_centrality",
    "edge_relations",
    "parent_chain",
    "import_external",
]

# 组件摘要（Agentic 模式）— 精简引导，LLM 自己工具探索
RECIPE_COMPONENT_ANALYSIS_AGENTIC = [
    "community_info",
    "directory_tree",
    "exported_symbols",
    "edge_relations",
]

# 架构分析（每个 L0 社区的上下文）
RECIPE_ARCH_COMMUNITY = [
    "community_info",
    "file_list",
    "directory_tree",
    "exported_symbols",
    "file_centrality",
    "edge_relations",
]

# 架构总览（最终概括所有社区）
RECIPE_ARCH_OVERVIEW = [
    "community_info",
    "edge_relations",
]

# 文件预摘要
RECIPE_FILE_SUMMARY = [
    "file_metadata",
]
