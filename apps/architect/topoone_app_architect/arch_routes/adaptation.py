"""兼容 shim(P5): 策略矩阵(agent.cognition.strategy) + 修复外循环(agent.reflection.repair)。

存量 `from .adaptation import X` 路径保持可用(sessions/units/planning/req_spec)。
"""
from ..agent.cognition.strategy import (  # noqa: F401
    STRATEGY_MATRIX,
    _DEFAULT_STRATEGIES,
    strategies_for_model,
    strategies_for_tier,
)
from ..agent.reflection.repair import (  # noqa: F401
    RepairTask,
    anchor_back,
    json_dumps,
    run_repair_loop,
    summarize_task,
)
