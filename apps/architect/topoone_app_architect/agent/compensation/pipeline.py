"""补偿管线(L1) — assemble / conclude 两时刻 + Retry 循环(整体设计 §3.2)。

M0 骨架: 管线机制(装配合并 / 收尾聚合), 零行为接线。
- assemble: 按 Provider 优先序调用 assemble(), 汇集 PromptPiece(按 priority 稳定排序)
  与 RunParams(first-wins 合并);
- conclude: 聚合 Provider 收尾判定——任一 Provider 返回需要重试的 Verdict 即触发
  Retry 循环; ArtifactGate 校验注记全部收集, 全过才 ok。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .carriers import ArtifactGate, GateResult, PromptPiece, RunParams, RetryPolicy
from .ctx import CompensationCtx
from .registry import ProviderRegistry


@dataclass
class AssembledPrompt:
    """装配产物: 基础提示 + 注入片段 + 运行参数。"""

    base: str
    pieces: List[PromptPiece] = field(default_factory=list)
    params: RunParams = field(default_factory=RunParams)

    def by_placement(self, placement: str) -> List[PromptPiece]:
        return [p for p in self.pieces if p.placement == placement]

    def system_notes(self) -> List[str]:
        return [p.text for p in self.by_placement("system")]

    def render(self) -> str:
        """渲染最终提示: base + section/scaffold 片段按序拼接(M1 接线收编时细化)。"""
        parts = [self.base]
        for p in self.pieces:
            if p.placement in ("section", "scaffold"):
                parts.append(p.text)
        return "\n\n".join(x for x in parts if x)


@dataclass
class TurnOutput:
    """回合产出(待收尾判定): 文本 + 已提取产物(JSON 块/图围栏等)。"""

    text: str
    artifacts: Dict[str, str] = field(default_factory=dict)


@dataclass
class Verdict:
    """收尾判定: ok=放行; retry 非 None = 触发重试; gate_notes = 门禁校验留痕。"""

    ok: bool
    text: str = ""
    gate_notes: List[str] = field(default_factory=list)
    retry: Optional[RetryPolicy] = None


def assemble(ctx: CompensationCtx, registry: ProviderRegistry,
             base_prompt: str) -> AssembledPrompt:
    """装配时刻: 收集各 Provider 的 PromptPiece / RunParams。"""
    prompt = AssembledPrompt(base=base_prompt)
    for provider in registry.providers(ctx.purpose):
        provider.assemble(ctx, prompt)
    prompt.pieces.sort(key=lambda p: (p.priority, p.key))
    return prompt


def conclude(ctx: CompensationCtx, registry: ProviderRegistry,
             output: TurnOutput) -> Verdict:
    """收尾时刻: 聚合 Provider 判定(契约解析 / 门禁 / 重试)。"""
    notes: List[str] = []
    retry: Optional[RetryPolicy] = None
    ok = True
    for provider in registry.providers(ctx.purpose):
        v = provider.conclude(ctx, output)
        if v is None:
            continue
        notes.extend(v.gate_notes)
        if v.retry is not None and retry is None:
            retry = v.retry
        if not v.ok:
            ok = False
    return Verdict(ok=ok, text=output.text, gate_notes=notes, retry=retry)


def run_with_retry(ctx: CompensationCtx, registry: ProviderRegistry,
                   produce: Any, max_loops: int = 4) -> Verdict:
    """Retry 循环骨架: produce(nudge_count) -> TurnOutput; 由各形态回合引擎驱动。

    M0 仅供测试与后续接线; produce 由 ChatTurn/CallTurn 提供真实调用。
    """
    nudged = 0
    while True:
        out = produce(nudged)
        v = conclude(ctx, registry, out)
        if v.ok or v.retry is None or nudged >= min(v.retry.max_nudges, max_loops):
            return v
        nudged += 1
