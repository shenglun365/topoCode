"""兼容 shim: 实现迁至 agent.cognition.model_profile(P1 纵切抽取)。

存量 `from . import model_profile` 路径保持可用(websocket/adaptation/mcp_collab)。
"""
from ..agent.cognition.model_profile import (  # noqa: F401
    TIERS,
    all_profiles,
    get_profile,
    get_profile_or_lazy,
    guess_params_b,
    heuristic_tier,
    probe_model,
    probe_model_gated,
    set_manual_tier,
    tier_of,
)
