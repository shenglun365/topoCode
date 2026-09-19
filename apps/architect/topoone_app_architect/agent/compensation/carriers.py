"""补偿载体(L1) — 五类类型化载体(整体设计 §3.1, 需求规格 8 类收编映射)。

M0 骨架: 仅载体定义, 零行为接线。
- PromptPiece 吸收 SystemNote / InstructionSection / PromptScaffold(placement 区分);
- RunParams 吸收 ToolFilter / BudgetParam / cadence / schedule_discipline 等;
  reasoning_effort 按 D11 迁出 GearPolicy, 不属于任何载体(见需求规格 §0 D11)。
合并语义: 管线按 Provider 优先级升序遍历, RunParams 取**首个非 None**值——
优先级高者先声明, 后到不覆盖(确定性, 无隐式叠加)。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional


PROMPT_PLACEMENTS = ("system", "section", "scaffold")


@dataclass(frozen=True)
class PromptPiece:
    """提示注入片段。placement: system=系统消息 / section=指令内小节 / scaffold=脚手架。"""

    placement: str
    key: str
    text: str
    priority: int = 50

    def __post_init__(self) -> None:
        if self.placement not in PROMPT_PLACEMENTS:
            raise ValueError(f"非法 placement: {self.placement!r}(合法: {PROMPT_PLACEMENTS})")


@dataclass(frozen=True)
class RunParams:
    """运行参数(R1.2 消费面; None = 本 Provider 不声明, 由高优先者决定)。"""

    tool_surface: Optional[str] = None       # full | reduced | minimal → 工具面裁剪
    ctx_budget: Optional[float] = None       # 提示预算系数
    cadence: Optional[str] = None            # milestone | key_step | every_step
    force_linear: Optional[bool] = None      # 依赖边强制线性(schedule_discipline 落地形态)
    max_iterations: Optional[int] = None     # 任务级轮次上限
    tool_rounds: Optional[int] = None        # chat 侧工具轮次上限

    def merge_first_wins(self, other: "RunParams") -> "RunParams":
        """按字段取 self 非 None 值, 缺位用 other 补(self 优先级更高)。"""
        return RunParams(
            tool_surface=self.tool_surface if self.tool_surface is not None else other.tool_surface,
            ctx_budget=self.ctx_budget if self.ctx_budget is not None else other.ctx_budget,
            cadence=self.cadence if self.cadence is not None else other.cadence,
            force_linear=self.force_linear if self.force_linear is not None else other.force_linear,
            max_iterations=(self.max_iterations if self.max_iterations is not None
                            else other.max_iterations),
            tool_rounds=self.tool_rounds if self.tool_rounds is not None else other.tool_rounds,
        )


@dataclass(frozen=True)
class OutputContract:
    """输出契约(R3.3): JSON 块优先解析, 文本协议兼容降级。"""

    contract: str                            # 契约名, 如 milestone_report / completion_summary
    schema: Dict[str, Any] = field(default_factory=dict)
    json_first: bool = True
    text_fallback: bool = True


@dataclass(frozen=True)
class GateResult:
    """ArtifactGate 单项校验结果(确定性, 不依赖 LLM 自觉)。"""

    passed: bool
    note: str = ""


@dataclass(frozen=True)
class ArtifactGate:
    """产出物确定性门禁(如 R3.2 核心逻辑图: 围栏存在且边≥3)。"""

    gate: str
    validate: Callable[[Any], GateResult]


@dataclass(frozen=True)
class RetryPolicy:
    """失败重试策略(按挡: T0 失败即报 / T1 nudge 1 / T2 nudge 2 + 确定性兜底)。"""

    max_nudges: int = 0
    nudge_hint: str = ""
    fallback: str = "none"   # none | clarify_fallback | filetree_heuristic | single_card | static_template
