"""补偿上下文(L0) — 策略解析结果的类型化传递(整体设计 §2)。

M0 骨架: 仅类型定义与词表冻结, 零行为接线(D3 收编等价前提)。
- purpose 词表 D10 冻结: 四组 19 项, 词表外 purpose 视为编码错误(fail-fast);
- CompensationCtx 由管线在回合构造前组装一次, 逐层只读传递;
- 挡位刻度经 governance.gears.GEAR_IDS 单源引用(字面量禁散落,
  门禁 test_grep_gates); 挡位语义一律经 gear(GearPolicy) 表达。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class Axis(str, Enum):
    """补偿管线轴: A=对话回合 / C=任务下发 / S=单项调用(整体设计 §4)。"""

    A = "A"
    C = "C"
    S = "S"


class Purpose(str, Enum):
    """目的词表(D10 冻结, 四组 19 项; 整体设计 §2.2)。"""

    # ── 分析组(3) ──
    REQUIREMENT = "requirement"
    ARCHITECTURE = "architecture"
    MODULE = "module"
    # ── 单项组(5) ──
    EXTRACTION = "extraction"
    CLARIFY = "clarify"
    COLLECT = "collect"
    SPLIT = "split"
    PROBE = "probe"
    # ── 轻量组(5) ──
    SUMMARY = "summary"
    DISTILL = "distill"
    DESIGN = "design"
    SE = "se"
    UT = "ut"
    # ── 工种组(6) ──
    ROLE_EXTRACT = "role:extract"
    ROLE_VERIFY = "role:verify"
    ROLE_INDUCE = "role:induce"
    ROLE_PSEUDO = "role:pseudo"
    ROLE_EVALUATE = "role:evaluate"
    ROLE_MINE = "role:mine"


# 探测维映射(目的 → 三维能力分键; 对齐 model_profile 分目的分数)
PROBE_DIMENSION: Dict[Purpose, str] = {
    Purpose.REQUIREMENT: "requirement",
    Purpose.CLARIFY: "requirement",
    Purpose.COLLECT: "requirement",
    Purpose.EXTRACTION: "requirement",
    Purpose.ARCHITECTURE: "arch",
    Purpose.DESIGN: "arch",
    Purpose.MODULE: "module",
    Purpose.SPLIT: "module",
    Purpose.PROBE: "module",
    Purpose.SUMMARY: "module",
    Purpose.DISTILL: "module",
    Purpose.SE: "module",
    Purpose.UT: "module",
    Purpose.ROLE_EXTRACT: "module",
    Purpose.ROLE_VERIFY: "module",
    Purpose.ROLE_INDUCE: "module",
    Purpose.ROLE_PSEUDO: "module",
    Purpose.ROLE_EVALUATE: "module",
    Purpose.ROLE_MINE: "module",
}


@dataclass(frozen=True)
class CapabilityScores:
    """探测三维能力分(R2.4: 入策略, 仅弱档下调); None = 未探测。"""

    requirement: Optional[float] = None
    arch: Optional[float] = None
    module: Optional[float] = None

    def dimension(self, purpose: Purpose) -> Optional[float]:
        return getattr(self, PROBE_DIMENSION[purpose], None)


@dataclass(frozen=True)
class ProbeFlags:
    """探测事实(followGate 封顶 / cap_note 告知)。"""

    follow_gate: bool = False
    cap_note: str = ""


@dataclass(frozen=True)
class BudgetParams:
    """提示预算: 基线(26k/22k/16k 按挡) × ctx_budget 系数(R3.4 接线点)。"""

    base_chars: int = 26_000
    coefficient: float = 1.0

    @property
    def effective_chars(self) -> int:
        return int(self.base_chars * self.coefficient)


@dataclass(frozen=True)
class CompensationCtx:
    """一次 LLM 交互的补偿上下文(整体设计 §2.1)。

    gear: governance.gears.GearPolicy(策略行, 单源解析产物);
    a_tier: 有效档——gear.tier 经分目的细化(R2.4, 仅弱档下调); 0=未细化。
    """

    gear: Any
    axis: Axis
    purpose: Purpose
    scores: CapabilityScores = field(default_factory=CapabilityScores)
    flags: ProbeFlags = field(default_factory=ProbeFlags)
    budget: BudgetParams = field(default_factory=BudgetParams)
    a_tier: int = 0

    @property
    def tier(self) -> str:
        return str(getattr(self.gear, "tier", ""))

    def purpose_score(self) -> Optional[float]:
        """本目的对应的三维分(R2.4 消费口)。"""
        return self.scores.dimension(self.purpose)


# R2.4: 分目的弱分阈值——该目的探测分低于此值 → 有效档降一档(只降不升)。
PURPOSE_WEAK_SCORE = 0.40

from ..governance.gears import GEAR_IDS as _TIER_ORDER


def resolve_ctx(gear: Any, axis: Axis, purpose: Purpose,
                scores: Optional[CapabilityScores] = None,
                flags: Optional[ProbeFlags] = None,
                budget: Optional[BudgetParams] = None) -> CompensationCtx:
    """组装 CompensationCtx(R2.4): a_tier = gear.tier 经分目的细化。

    细化语义(只降不升, 行为等价——弱档才触发): 本目的探测分存在且
    < PURPOSE_WEAK_SCORE → 有效档向弱侧移一档(最弱挡封底);
    分数良好或未探测 → 有效档=挡位原档。挡位本身不改动(策略行单源不变)。"""
    scores = scores or CapabilityScores()
    tier = str(getattr(gear, "tier", "") or "")
    a_tier = _TIER_ORDER.index(tier) if tier in _TIER_ORDER else 1
    score = scores.dimension(purpose)
    if score is not None and score < PURPOSE_WEAK_SCORE and a_tier < len(_TIER_ORDER) - 1:
        a_tier += 1
    return CompensationCtx(gear=gear, axis=axis, purpose=purpose,
                           scores=scores, flags=flags or ProbeFlags(),
                           budget=budget or BudgetParams(), a_tier=a_tier)
