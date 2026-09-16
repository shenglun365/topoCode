"""模型分级策略矩阵(认知层) — tier → 启用策略集(真相源)。

P1 自 adaptation.py 迁入。策略消费者(草稿卡收敛/意图追问分级/宽容解析分级)
按 strategies_for_model(model_id) 取当轮策略集。
"""
from __future__ import annotations

from typing import Any, Dict

from . import model_profile

_DEFAULT_STRATEGIES: Dict[str, Any] = {
    "arg_coerce": True,            # 参数类型强转(所有档开启)
    "guard": True,                 # 防编造守卫
    "guard_extract_first": True,   # guard 修复确定性提取前置
    "intent_followup": False,      # 意图追问(小模型开)
    "draft_card": False,           # 草稿卡确定性收敛【A】(t2+ 开)
    "postprocess": False,          # 输出后处理: 编号回填/重复声明去噪(t3+)
    "single_focus": False,         # 极简 system/单轮单任务(t4)
    "lenient_parse": "base",       # 工具块宽容解析级别 base|high|max
}

STRATEGY_MATRIX: Dict[int, Dict[str, Any]] = {
    0: {**_DEFAULT_STRATEGIES},
    1: {**_DEFAULT_STRATEGIES},
    2: {**_DEFAULT_STRATEGIES, "intent_followup": True, "draft_card": True,
        "lenient_parse": "high"},
    3: {**_DEFAULT_STRATEGIES, "intent_followup": True, "draft_card": True,
        "postprocess": True, "lenient_parse": "high"},
    4: {**_DEFAULT_STRATEGIES, "intent_followup": True, "draft_card": True,
        "postprocess": True, "single_focus": True, "lenient_parse": "max"},
}


def strategies_for_tier(tier: int) -> Dict[str, Any]:
    return STRATEGY_MATRIX.get(max(0, min(4, int(tier)))) or dict(_DEFAULT_STRATEGIES)


def strategies_for_model(model_id: str) -> Dict[str, Any]:
    return strategies_for_tier(model_profile.tier_of(model_id or ""))
