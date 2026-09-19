"""同挡个体差异 Provider — probeScore → 指令密度/粒度微调(R2.5, stretch)。

仅中/弱挡生效(设计 §5.2-R2.5); 白名单开关 r2_5_intra_tier(缺省新行为)。
数据源: C 轴执行器探测 probeScore(executorConfig, 双探测轨); 强挡不微调。
形态(A3 审计收敛): 函数库形态——活路径经 task_plan 直接导入; 不设 Provider
壳(probeScore 非 GearPolicy 字段, 不入消费清单门禁)。
"""
from __future__ import annotations

from ...governance.gears import GEAR_IDS, WEAKEST_TIER

_WEAK = 0.35     # 同挡内偏弱: 指令密度升档(更细粒度/更频繁报告)
_STRONG = 0.65   # 同挡内偏强: 粒度微调放宽(弱挡减少暂停; 中挡不变)


def intra_tier_note(tier: str, probe_score=None) -> str:
    """同挡密度微调段(空串=不注入)。"""
    if tier not in GEAR_IDS[1:] or probe_score is None:
        return ""
    try:
        score = float(probe_score)
    except (TypeError, ValueError):
        return ""
    if score < _WEAK:
        return ("\n> 🎚 同挡微调：本执行器实测偏弱(同挡内)，请按**更细粒度**推进——"
                "每步只做单一动作，完成即简短报告再继续；里程碑协议照常。")
    if tier == WEAKEST_TIER and score > _STRONG:
        return ("\n> 🎚 同挡微调：本执行器实测偏强(同挡内)，允许将相邻强相关步骤"
                "**组合推进**，减少暂停次数；里程碑报告照常，不要跳过报告。")
    return ""
