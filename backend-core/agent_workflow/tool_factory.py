"""
共享工具工厂 — 供 RPC 和 RouterHarness 复用 tool 注册逻辑。
"""

from __future__ import annotations

from typing import Callable, Optional

from .tools import ToolRegistry


def build_sentinel_tools(
    llm_chat_fn: Callable,
    project_root: str,
    render_prompt: Callable = None,
) -> ToolRegistry:
    """构建 ArchSentinel 的工具集"""
    from .workflows.arch_sentinel import (
        _SnapshotTool, _DiffTool, _SummarizeTool, _SaveDeltaTool,
    )
    from .jsonl_store import append_jsonl as _append

    tools = ToolRegistry()
    tools.register(_SnapshotTool(lambda fp, e: _append(project_root, fp, e)))
    tools.register(_DiffTool())
    tools.register(_SummarizeTool(llm_chat_fn, render_prompt))
    tools.register(_SaveDeltaTool(lambda fp, e: _append(project_root, fp, e)))
    return tools


def build_component_analyst_tools(
    llm_chat_fn: Callable,
    render_prompt: Callable = None,
    save_result_fn: Callable = None,
) -> ToolRegistry:
    """构建 ComponentAnalyst 的工具集"""
    from .workflows.component_analyst import (
        _AnalyzeComponentTool, _AnalyzeComponentBatchTool
    )
    tools = ToolRegistry()
    tools.register(_AnalyzeComponentTool(llm_chat_fn, render_prompt, save_result_fn))
    tools.register(_AnalyzeComponentBatchTool(llm_chat_fn, render_prompt, save_result_fn))
    return tools


def build_agentic_component_tools(
    project_root: str = "",
    project_db=None,
    path_sandbox=None,
    project_id: str = "",
    task_id: str = "",
    multi_db=None,
    concurrency: int = 1,
) -> ToolRegistry:
    """构建 AgenticComponentAnalyst 的工具集（LLM 可见的读写工具）"""
    from .toolkits.file_tools import ReadFileTool, SearchContentTool, SummarizeFileTool
    from .toolkits.symbol_tools import GetSymbolDetailTool, SearchSymbolsTool, GetSymbolCodeTool
    from .toolkits.graph_tools import GetCommunitySubgraphTool, GetCallChainTool, GetASTNodeTool
    from .toolkits.edge_tools import GetEdgeDetailTool

    tools = ToolRegistry()
    tools.register(ReadFileTool(project_root=project_root, path_sandbox=path_sandbox))
    tools.register(SearchContentTool(project_root=project_root, path_sandbox=path_sandbox))
    tools.register(SummarizeFileTool(
        project_root=project_root, project_db=project_db,
        project_id=project_id, task_id=task_id,
        multi_db=multi_db, path_sandbox=path_sandbox,
        concurrency=concurrency,
    ))
    if project_db:
        tools.register(GetSymbolDetailTool(project_db=project_db, project_root=project_root))
        tools.register(SearchSymbolsTool(project_db=project_db, project_root=project_root))
        tools.register(GetCommunitySubgraphTool(project_db=project_db, project_root=project_root))
        tools.register(GetCallChainTool(project_db=project_db))
        tools.register(GetASTNodeTool(project_db=project_db))
        tools.register(GetEdgeDetailTool(project_db=project_db))
        tools.register(GetSymbolCodeTool(project_db=project_db, project_root=project_root))
    return tools
