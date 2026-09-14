"""兼容 shim(P5): 实现迁至 agent.reflection.evaluator(WS4 评估器)。"""
from ..agent.reflection.evaluator import (  # noqa: F401
    parse_diff_spans,
    register_evaluator_tools,
)
