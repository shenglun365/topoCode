"""里程碑协议 Provider — 收编 task_plan 确定性指令段(R1.1 行为等价)。

收编来源(逐字等价, task_plan.assemble_task_instruction 已委托至此):
- milestone_section()  里程碑协议静态段(环节十一)
- agent_note_section() 挡位粒度/节奏分叉段(环节十二a, gears 策略行 agent_note)
cadence / schedule_discipline 的参数化(整体设计 §5.1)随 DispatchTurn(M4)接线。
"""
from __future__ import annotations

from ..carriers import PromptPiece
from ..ctx import CompensationCtx


def milestone_section(structured: bool = False) -> str:
    """里程碑协议静态段(防止无限消耗)。

    structured(R3.3): 报告优先 JSON 块契约({changed_files, verify, next})，
    文本固定行保留为兼容降级(architect 侧解析层双轨, D4 不动 runner)。"""
    base = ("## 里程碑协议（重要，防止无限消耗）\n"
            "- 预计超过约 15 次工具调用的复杂任务：先探索代码库，在首次回复中提交"
            "**里程碑计划**（按功能模块+可独立验证标准划分；每个里程碑给出：目标、"
            "涉及文件、验证方式），然后输出 [[NEED_INPUT]] 等待用户确认后再动手；\n"
            "- 每个里程碑完成后：输出里程碑报告（固定三行格式：\n"
            "  `改动文件: 文件a, 文件b, 文件c`\n"
            "  `验证: 构建与冒烟结果`\n"
            "  `下一里程碑: 名称 或 \"全部完成\"`），"
            "然后输出 [[NEED_INPUT]] 等待用户指示；**禁止未提交报告就连续跨里程碑推进**；\n"
            "- 预计 15 次工具调用以内的简单任务：直接执行，完成后输出 [[IMPLEMENT_DONE]]。")
    if structured:
        base += ("\n- **报告格式(优先)**：里程碑报告优先以 ```json 块给出：\n"
                 "  `{\"changed_files\": [\"文件a\"], \"verify\": \"构建与冒烟结果\", "
                 "\"next\": \"下一里程碑或全部完成\"}`；\n"
                 "  无法结构化时再用上面的固定三行文本(两种格式系统都能解析)。")
    return base


def agent_note_section(policy) -> str:
    """执行方式段(挡位 agent_note; 空 → 空串不注入)。"""
    note = str(getattr(policy, "agent_note", "") or "").strip()
    if not note:
        return ""
    return "## 执行方式（按任务挡位）\n" + note


class MilestoneProvider:
    name = "milestone"
    purposes = frozenset()
    consumes = frozenset({"agent_note", "cadence", "schedule_discipline"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        # R1.2(M2): cadence/schedule_discipline 消费声明——
        # RunParams 载体化(DispatchTurn M4 接线消费);
        # force_linear 正式化 task_plan depends_source="linear" 现状语义。
        from ..carriers import RunParams
        cadence = getattr(ctx.gear, "cadence", None)
        discipline = str(getattr(ctx.gear, "schedule_discipline", "") or "")
        depends = str(getattr(ctx.gear, "depends_source", "") or "")
        prompt.params = prompt.params.merge_first_wins(RunParams(
            cadence=str(cadence) if cadence else None,
            force_linear=True if (discipline == "strict_pipeline"
                                  or depends == "linear") else None))
        prompt.pieces.append(PromptPiece(
            placement="section", key="milestone_protocol",
            text=milestone_section()))
        note = agent_note_section(ctx.gear)
        if note:
            prompt.pieces.append(PromptPiece(
                placement="section", key="agent_note", text=note))

    def conclude(self, ctx: CompensationCtx, output):
        return None
