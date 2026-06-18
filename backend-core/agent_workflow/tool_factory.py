"""
共享工具工厂 — 供 RPC 和 RouterHarness 复用 tool 注册逻辑。
"""

from __future__ import annotations

from typing import Callable

from .tools import ToolRegistry


def build_analyst_tools(
    llm_chat_fn: Callable,
    render_prompt: Callable = None,
    save_result_fn: Callable = None,
) -> ToolRegistry:
    """构建 ArchAnalyst 的工具集"""
    from .workflows.arch_analyst import (
        _AnalyzeCommunityTool, _GenerateDiagramTool,
        _GenerateOverviewTool, _SaveResultsTool,
    )
    tools = ToolRegistry()
    tools.register(_AnalyzeCommunityTool(llm_chat_fn, render_prompt))
    tools.register(_GenerateDiagramTool())
    tools.register(_GenerateOverviewTool(llm_chat_fn, render_prompt))
    if save_result_fn:
        tools.register(_SaveResultsTool(save_result_fn))
    return tools


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
