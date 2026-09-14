"""兼容 shim: 实现迁至 agent.memory.units / agent.memory.dossier(P4)。

存量 `from . import context_registry` / `from .context_registry import X`
路径保持可用(sessions/asset_map_tools/orchestrator/MCP)。
"""
from ..agent.memory.units import (  # noqa: F401
    CTX_CAPABILITY_LINES,
    TOOLS,
    ctx_get,
    ctx_search,
    ctx_summarize,
    record_tool_call,
    register_chat_tools,
    register_probe_tool,
    run_probe,
    run_tool,
    summarize_conversation,
)
from ..agent.memory.dossier import _DOSSIER_BUDGET, assemble_dossier  # noqa: F401
