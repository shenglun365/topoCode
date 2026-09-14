"""兼容 shim(P5): 实现迁至 agent.reflection.mining(WS7 能力提炼闭环)。"""
from ..agent.reflection.mining import (  # noqa: F401
    register_mining_tools,
    register_promote_tools,
    router,
    start_periodic_mine,
)
