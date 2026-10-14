"""tierSuggested 挡位建议(#3, 建议值+人审; 采纳文档 2609 P1)。

D6 三重防线(防守线②): 本模块**纯读**——绝不写 tier/capability, 不进
resolve_gear 输入轴(挡位分数解耦裁决); 建议值只经 REST 展示, 采纳 = 人工
调用既有 PUT /llm/model-profiles/{model_id}(manual 档, 探测不覆盖)。
人工已设(source=manual)时建议让位(tierSuggested=null + manualPinned)。
规则数值走 policy.tierSuggestion(状态/规则/策略驱动); 挡位刻度语义单源
gears/model_profile, 本模块只做方向判断(高失败→升档/低失败→降档省算力)。
"""
from __future__ import annotations

from typing import Any, Dict


def suggest_tiers() -> Dict[str, Any]:
    """dataset 失败画像 → 每模型挡位建议(只读)。

    数据源: aggregate_failures(policy.aggregation.windowDays) 的 byModel 维度。
    返回 {windowDays, suggestions: [{modelId, tier, tierSuggested, manualPinned,
    failRate, calls, fails}]}; 任何失败返回空表(观测口不碍主链)。
    """
    try:
        from ... import store as _s
        from ..cognition import model_profile as _mp
        from ..governance.flow_policy import load_flow_policy
        from . import dataset as _ds
        _get = _s.CollabConfigStore.get
        pol = load_flow_policy(_get)
        cfg = pol.get("tierSuggestion") or {}
        min_calls = int(cfg.get("minCalls") or 10)
        fail_high = float(cfg.get("failHigh") or 0.35)
        fail_low = float(cfg.get("failLow") or 0.1)
        window = int((pol.get("aggregation") or {}).get("windowDays") or 14)
        agg = _ds.aggregate_failures(window)
        profiles = _mp.all_profiles()
        rows = []
        for model, ms in (agg.get("byModel") or {}).items():
            calls = int(ms.get("total") or 0)
            fails = int(ms.get("fail") or 0)
            rate = (fails / calls) if calls else 0.0
            prof = profiles.get(model) or {}
            tier = prof.get("tier") if isinstance(prof.get("tier"), int) else 1
            tier = max(0, min(2, tier))
            manual = str(prof.get("source") or "") == "manual"
            sug = None
            if not manual and calls >= min_calls:
                if rate >= fail_high and tier > 0:
                    sug = tier - 1          # 高失败 → 建议升档(更强)
                elif rate <= fail_low and tier < 2:
                    sug = tier + 1          # 低失败 → 建议降档(省算力)
            rows.append({"modelId": model, "tier": tier,
                         "tierSuggested": sug, "manualPinned": manual,
                         "failRate": round(rate, 4), "calls": calls,
                         "fails": fails})
        rows.sort(key=lambda r: (-r["failRate"], -r["calls"]))
        return {"windowDays": window, "suggestions": rows}
    except Exception:  # noqa: BLE001 — 观测口 fail-soft
        try:
            from . import dataset as _ds
            _ds.swallow("tier.suggest")
        except Exception:  # noqa: BLE001
            pass
        return {"windowDays": 0, "suggestions": []}
