"""预算裁剪 Provider — 收编 cognition/prompt.py 预算裁剪(R1.1 行为等价)。

M1: 裁剪循环逐字迁入(trim_optional_blocks), prompt.render_system 委托;
ctx_budget 系数化(R3.4, stretch)暂不生效——Provider 仅声明消费位。
"""
from __future__ import annotations

import logging
from typing import Any, List, Tuple

from ..carriers import PromptPiece, RunParams
from ..ctx import CompensationCtx


def trim_optional_blocks(
        rendered: List[Tuple[Any, str]], budget: int, tier: int,
        logger: logging.Logger) -> Tuple[List[Tuple[Any, str]], List[str]]:
    """条件块按 priority 降序淘汰直到达标(恒置块保留; prompt.render_system 委托)。

    rendered: [(block, text)]; block 需有 .required / .priority / .block_id。
    返回 (裁剪后 rendered, dropped block_id 清单)。"""
    total = sum(len(t) for _, t in rendered)
    optional = sorted([r for r in rendered if not r[0].required],
                      key=lambda r: -r[0].priority)
    dropped: List[str] = []
    for blk, text in optional:
        if total <= budget:
            break
        total -= len(text) + 2
        rendered.remove((blk, text))
        dropped.append(blk.block_id)
    if dropped:
        logger.info("[prompt-registry] tier=%s 预算 %s 裁剪块: %s", tier, budget, dropped)
    return rendered, dropped


class BudgetTrimProvider:
    name = "budget_trim"
    purposes = frozenset()
    consumes = frozenset({"ctx_budget"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        coefficient = getattr(ctx.gear, "ctx_budget", None)
        if coefficient is not None:
            prompt.params = prompt.params.merge_first_wins(
                RunParams(ctx_budget=float(coefficient)))

    def conclude(self, ctx: CompensationCtx, output):
        return None
