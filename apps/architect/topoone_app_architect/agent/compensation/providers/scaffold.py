"""脚手架 Provider — prompt_style 字段消费者(R1.2 / R3.1 分目的脚手架落点)。

M2: 消费位声明(消费清单门禁依据); 分目的脚手架内容(需求规格 §5.4 矩阵)
随链 3 迁移(M3/M4)经本 Provider 的 assemble 注入 PromptPiece(scaffold)。
"""
from __future__ import annotations

from ..carriers import PromptPiece, RunParams
from ..ctx import CompensationCtx


class ScaffoldProvider:
    name = "scaffold"
    purposes = frozenset()
    consumes = frozenset({"prompt_style"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        # M3 落地点: 按 (purpose, prompt_style) 注入弱档脚手架;
        # M2 仅登记消费事实(见 consumes), 不产生提示内容(行为等价)。
        return None

    def conclude(self, ctx: CompensationCtx, output):
        return None
