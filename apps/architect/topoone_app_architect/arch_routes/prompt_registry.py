"""兼容 shim: 实现迁至 agent.cognition.prompt(P1 纵切抽取)。

存量 `from . import prompt_registry` 路径保持可用(req_agent 等)。
"""
from ..agent.cognition.prompt import (  # noqa: F401
    DEFAULT_BUDGET,
    PromptBlock,
    budget_for,
    capability_doc_from_tools,
    register_block,
    render_system,
    set_overrides,
)
