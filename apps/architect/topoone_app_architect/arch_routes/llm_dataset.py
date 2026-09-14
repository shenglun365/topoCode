"""兼容 shim: 实现迁至 agent.reflection.dataset(P1 纵切抽取)。

存量 `from . import llm_dataset` 路径保持可用; 新代码请用 agent.reflection.dataset。
"""
from ..agent.reflection.dataset import record, router, stats  # noqa: F401
