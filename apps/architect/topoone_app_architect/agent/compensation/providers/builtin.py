"""内置补偿 Provider — 文案型补偿收编(R1.1, 行为等价 D3)。

收编来源(逐字等价, 原调用点已委托至此):
- ArchitectNoteProvider ← orchestrator 系统消息拼接(gears 策略行 architect_note)
- ElementHintProvider   ← orchestrator U 轴注入(gears ELEMENT_HINT_HIGH/MID)
- CapNoteProvider       ← task_plan cap_note 段(🛡️ 实测封顶告知)
M1 约定: 活动路径先经本模块函数取文(字节级等价), 管线 assemble() 随
ChatTurn(M3/M4)接管; Provider 登记即消费清单门禁依据(R1.2)。
"""
from __future__ import annotations

from ..carriers import PromptPiece, RunParams
from ..ctx import CompensationCtx, Purpose


# ── 取文函数(活动路径委托口; 与 Provider.assemble 同源) ──────────────

def architect_note_text(policy) -> str:
    """architect 编排指引(gears 策略行, 系统消息尾缀)。"""
    return str(getattr(policy, "architect_note", "") or "")


def element_hint_text(policy) -> str:
    """U 轴要素框架提示(A 弱升档; low → 空串不注入)。"""
    from ...governance.gears import ELEMENT_HINT_HIGH, ELEMENT_HINT_MID
    density = getattr(policy, "element_hints", "low")
    if density == "high":
        return ELEMENT_HINT_HIGH
    if density == "mid":
        return ELEMENT_HINT_MID
    return ""


def cap_note_section(policy) -> str:
    """cap_note 指令段(M1 实测封顶告知 subagent; 空串=无封顶)。"""
    if getattr(policy, "cap_note", ""):
        return ("> 🛡️ " + str(policy.cap_note)
                + "——本次任务编排已按你的实测能力边界降档, "
                  "请严格按微步/步骤粒度推进, 里程碑报告照常。\n")
    return ""


# ── Provider 形态(管线载体; conclude 在 M3/M4 随回合引擎接线) ─────────

class ArchitectNoteProvider:
    name = "architect_note"
    purposes = frozenset()              # 全目的
    consumes = frozenset({"architect_note"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        text = architect_note_text(ctx.gear)
        if text:
            prompt.pieces.append(
                PromptPiece(placement="system", key=self.name, text=text))

    def conclude(self, ctx: CompensationCtx, output):
        return None


class ElementHintProvider:
    name = "element_hints"
    purposes = frozenset({Purpose.REQUIREMENT})
    consumes = frozenset({"element_hints"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        text = element_hint_text(ctx.gear)
        if text:
            prompt.pieces.append(
                PromptPiece(placement="system", key=self.name, text=text))

    def conclude(self, ctx: CompensationCtx, output):
        return None


class CapNoteProvider:
    name = "cap_note"
    purposes = frozenset()
    consumes = frozenset({"cap_note"})

    def assemble(self, ctx: CompensationCtx, prompt) -> None:
        text = cap_note_section(ctx.gear)
        if text:
            prompt.pieces.append(
                PromptPiece(placement="section", key=self.name, text=text))

    def conclude(self, ctx: CompensationCtx, output):
        return None


# ── 落卡回合收尾文案(cv-196 收编, R1.1: 文案经 providers 单源, turns 只编排) ──
CARD_ROUND_CLOSINGS = {
    "req.propose": "📝 需求卡已创建(ready)——点「开始执行」启动。",
    "req.amend": "✏️ 规约已修订(ready)。",
    "task.propose": "📋 任务卡已保存——点「开始执行」启动。",
}


def card_closing_text(tool_name: str) -> str:
    """落卡工具的确定性收尾文案(未知工具 → 空串)。"""
    return CARD_ROUND_CLOSINGS.get(tool_name, "")


# ── 需求澄清指令模板(cv-190 收编: 规则在 requirements/clarify.py, 文案单源在此) ──

CLARIFY_FORCED_STRATEGY_TMPL = (
    "【需求澄清(强制挡 · {label})】本回合先澄清后落卡——"
    "按以下切合该目标的问题集中编号提问, 每问先给出你基于上下文的"
    "推断默认值请用户确认或补全, 禁止开放式泛问:\n{questions}\n"
    "用户答复后用 req.propose/req.amend 回填再建卡; 首轮禁止直接落需求卡。")

CLARIFY_FORCED_FREE_TMPL = (
    "【需求澄清(强制挡)】本回合先澄清后落卡——该目标不在策略库覆盖内, "
    "由你自行组织澄清问题: 按五要素框架(①目标 ②方案要点 ③允许范围 "
    "④禁止改动 ⑤验收标准)逐项给出推断默认值请用户确认, 禁止开放式泛问; "
    "用户答复后 req.propose/req.amend 回填再建卡, 首轮禁止直接落需求卡。")

CLARIFY_GAP_TMPL = (
    "【需求澄清({tag})】当前规约缺口: {gaps}——请集中一次提问补齐"
    "(每项给出推断默认值请用户确认), 用户答复后 req.amend 回填; "
    "要素齐了再提示可建卡。")


def clarify_forced_strategy_text(label: str, questions_md: str) -> str:
    return CLARIFY_FORCED_STRATEGY_TMPL.format(label=label, questions=questions_md)


def clarify_forced_free_text() -> str:
    return CLARIFY_FORCED_FREE_TMPL


def clarify_gap_text(tag: str, gaps: str) -> str:
    return CLARIFY_GAP_TMPL.format(tag=tag, gaps=gaps)
