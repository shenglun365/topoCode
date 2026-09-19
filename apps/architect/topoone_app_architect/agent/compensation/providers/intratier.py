"""同挡个体差异 Provider — probeScore → 指令密度/粒度微调(R2.5, stretch)。

仅 T1/T2 生效(设计 §5.2-R2.5); 白名单开关 r2_5_intra_tier(缺省新行为)。
数据源: C 轴执行器探测 probeScore(executorConfig, 双探测轨); T0 不微调。
"""
from __future__ import annotations

_WEAK = 0.35     # 同挡内偏弱: 指令密度升档(更细粒度/更频繁报告)
_STRONG = 0.65   # 同挡内偏强: 粒度微调放宽(T2 减少暂停; T1 不变)


def intra_tier_note(tier: str, probe_score=None) -> str:
    """同挡密度微调段(空串=不注入)。"""
    if tier not in ("T1", "T2") or probe_score is None:
        return ""
    try:
        score = float(probe_score)
    except (TypeError, ValueError):
        return ""
    if score < _WEAK:
        return ("\n> 🎚 同挡微调：本执行器实测偏弱(同挡内)，请按**更细粒度**推进——"
                "每步只做单一动作，完成即简短报告再继续；里程碑协议照常。")
    if tier == "T2" and score > _STRONG:
        return ("\n> 🎚 同挡微调：本执行器实测偏强(同挡内)，允许将相邻强相关步骤"
                "**组合推进**，减少暂停次数；里程碑报告照常，不要跳过报告。")
    return ""


class IntraTierProvider:
    name = "intra_tier"
    purposes = frozenset()
    consumes = frozenset(set())

    def assemble(self, ctx, prompt) -> None:
        # 载体化(R2.5 落地形态): 由 DispatchTurn(M4+)经 prompt.pieces 注入;
        # 当前活动路径经 task_plan.assemble_task_instruction(probe_score=...) 委托。
        return None

    def conclude(self, ctx, output):
        return None
