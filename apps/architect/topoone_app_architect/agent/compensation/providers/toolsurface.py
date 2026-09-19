"""工具面 Provider — tool_surface 字段消费者(R1.2)。

保守策略(M2): 仅把策略行的 tool_surface 声明为 RunParams 载体;
裁剪动作(KB 写/MCP 写按挡收窄)随 ChatTurn 消费 RunParams 时生效(M3)。
"""
from __future__ import annotations

from ..carriers import PromptPiece, RunParams
from ..ctx import CompensationCtx


class ToolSurfaceProvider:
    name = "tool_surface"
    purposes = frozenset()
    consumes = frozenset({"tool_surface"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        surface = getattr(ctx.gear, "tool_surface", None)
        if surface:
            prompt.params = prompt.params.merge_first_wins(
                RunParams(tool_surface=str(surface)))

    def conclude(self, ctx: CompensationCtx, output):
        return None
