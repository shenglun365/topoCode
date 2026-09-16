"""兼容 shim(P5): 修复外循环(agent.reflection.repair)——策略矩阵已拆除(cv-175)。

存量 `from .adaptation import X` 路径保持可用(sessions/units/planning/req_spec)。
"""
from ..agent.reflection.repair import (  # noqa: F401
    RepairTask,
    json_dumps,
    run_repair_loop,
    summarize_task,
)
