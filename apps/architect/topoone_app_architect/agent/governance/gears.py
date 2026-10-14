"""任务策略单源(2610 挡位体系退役版)。

裁决(2026-10-11): 取消 T0-T2 分析深度挡位——显性挡位设置(REST/菜单/预置)
与按档策略限制(cadence/pre_split/ctx_budget/tool_surface 分叉)全部退役;
策略收敛为**单一统一策略行**(原 T1 值: 任务级预拆+结构化指令+工具契约)。

保留面(非挡位限制, 不随退役):
  - GearPolicy 结构: 消费面(orchestrator/task_plan/exec_bridge/compensation)
    契约不变, 值恒定;
  - A 轴补偿(architect 模型能力档案 → 调度纪律/要素提示密度);
  - P 轴叠加(流程相位 → 对话面指引, 独立开关);
  - 模型能力测评(ConfigPage/probe/tierProbed)与执行器 capability 标定:
    独立的模型档案系统, 保留展示与探测, **不再驱动策略选择**;
  - normalize_mode: legacy 会话 analysisMode 值归一(gate 预置兼容路径)。

消费面:
  - orchestrator: architect_note(policy) → 编排者系统指引
  - task_plan.assemble_task_instruction: agent_protocol_note(policy) →
    subagent 确认节奏/粒度段
  - exec_bridge.confirm_task: policy.max_iterations → 任务级轮次下发
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

# 刻度常量保留(模型档案/注册表 capability 字段校验/补偿层引用; 策略不再分档)
GEAR_IDS = ("T0", "T1", "T2")
# M3 预留: 模型四级成本梯度(L 确定性/S 微调小模型/M 大本地/H 云端)——
# 异档分船编排按此标签路由(roadmap L 组 ↔ agent-harness-evaluation §9.3 裁决③)
MODEL_GRADIENTS = ("L", "S", "M", "H")

# ── 通用机制(全档共享; 2026-09-18 策略拆分裁决) ──────────────────────
# 普适补偿/保障一律生效, 与挡位退役无关。
UNIVERSAL_MECHANISMS: Dict[str, str] = {
    "repair_loop": "错误修复外循环(独立上下文, reflection.repair.run_repair_loop)"
                   "——参数修复/守卫修复, 全档可用",
    "structured_channel": "受限生成通道(M4-A)——按 structured 探测位启用",
}


def universal_mechanisms_note() -> str:
    """通用机制说明(回执/文档用)。"""
    return "；".join(UNIVERSAL_MECHANISMS.values())


@dataclass(frozen=True)
class GearPolicy:
    tier: str            # 恒 T1(统一策略; 字段保留供消费面契约)
    label: str           # 语义名(回执/指引用)
    kb: bool             # KB/范围探针 grounding
    pre_split: str       # architect 预拆粒度: none|plan|steps|micro(plan/steps 落地于环节十四)
    cadence: str         # subagent 确认节奏: milestone|key_step|every_step
    max_iterations: int  # 任务级轮次上限
    architect_note: str  # architect 编排指引(系统消息)
    agent_note: str      # subagent 任务指令附加段(粒度/节奏)
    cap_note: str = ""   # 退役遗留字段(恒空; 消费面契约保留)
    # ── M2: 小模型特化维度(策略表一行全量声明, 消费端按挡读取, 禁散落分支) ──
    # 职责归属(三维矩阵定则): 除 architect_note/agent_note 外各字段由单一职责轴
    # 直推——标 (C)=执行器模型能力驱动; 无标 = 编排基线。
    tool_surface: str = "full"       # (C) full|reduced|minimal(MCP注入/steer/KB写按挡裁剪)
    ctx_budget: float = 1.0          # KB grounding/任务卡/里程碑历史 预算系数
    prompt_style: str = "standard"   # (C) standard|structured|minimal(弱模型更短更清单化)
    structured_output: bool = False  # (C) True → 报告走工具契约(非文本固定行)
    tool_rounds: int = 4             # (C) M4-B: chat 侧工具轮次上限(弱档更早触顶)
    depends_source: str = "llm"      # (C) A2: 依赖边产出 llm=模型声明 | linear=编排层线性链
    logic_diagram: str = ""          # (C→A) C 弱 → 上游补核心逻辑表达: "uml"=任务指令须附
                                     #      PlantUML/Mermaid 级核心逻辑图(标准语法, 非渲染 IR)
    # ── A 轴(architect 模型能力)驱动: A 弱 → 调度机制与要素提示补偿 ──
    schedule_discipline: str = "standard"  # (A) standard|guided|strict_pipeline
                                           #     (A 弱 → 确定性调度占比升高)
    element_hints: str = "low"             # (A) low|mid|high 要素框架提示密度
                                           #     (A 弱 → 澄清/需求按要素清单展开, 引导用户喂全)


# ── 统一策略行(2610 裁决: 单行恒定, 原 T1 值) ─────────────────────────
UNIFIED_POLICY = GearPolicy(
    tier="T1", label="统一策略·任务级预拆", kb=True, pre_split="plan",
    cadence="milestone", max_iterations=800,
    architect_note=(
        "标准策略：开发类需求先做需求分析——调用 req.propose 产出需求卡"
        "(创建即 ready, 用户可直接 /执行 建任务卡并保存)，必要时检索 KB/资产地图校准边界。"
        "复杂需求应**预拆为多个小任务卡**(每卡单一模块级目标, 顺序下发), "
        "不要把大需求塞进单卡。"
        "信息问询(状态/进度/资产检索类提问)只做只读应答——不调用 req.propose "
        "起草需求卡、不创建任务(问什么答什么, 不扩大化)。"
        "内联 @执行器 前缀(如 @cline)按用户指定执行器建任务卡。"),
    agent_note="本任务为预拆后的单一模块级任务：聚焦本卡边界, 不要扩展到其他模块；里程碑协议照常。",
    tool_surface="full", ctx_budget=0.6, prompt_style="structured",
    structured_output=True,
    tool_rounds=4, depends_source="llm", logic_diagram="",
)

# ── 公开刻度常量(供补偿/回合/下发层引用; 字面量禁散落——门禁 test_grep_gates) ──
DEFAULT_TIER_ID = "T1"                # 统一策略 tier(恒定)
WEAKEST_TIER = GEAR_IDS[-1]           # 刻度常量(补偿层引用; 统一策略下不可达)
RETRY_NUDGES: Dict[str, int] = {"T0": 1, "T1": 1, "T2": 1}
# 失败重试 nudge 次数(单源: 统一策略恒 1; dict 形状保留供按 tier 索引的消费面)


def normalize_mode(mode: str) -> str:
    """legacy 会话挡位值归一(旧刻度 T3/T4 → T2; 其余原样)。

    2610 后唯一消费点: gate 预置路径识别 legacy analysisMode=quick
    (读侧经 exec_bridge.effective_executor_id 回落默认 coding 执行器)。"""
    legacy = {"T0": "T0", "T1": "T1", "T2": "T2", "T3": "T2", "T4": "T2"}
    m = str(mode or "").strip()
    return legacy.get(m.upper(), m)


# A 轴 → 补偿策略映射(职责归属: A 弱 → 调度纪律与要素提示升档)
A_AXIS_POLICY = {
    0: ("standard", "low"),        # A0 强: 正常发挥
    1: ("guided", "mid"),          # A1 中: 引导式调度 + 中密度要素提示
    2: ("strict_pipeline", "high"),  # A2 弱: 确定性管线为主 + 高密度要素提示
}


def resolve_gear(session_mode: str = "", executor_cfg: Optional[Dict[str, Any]] = None,
                 architect_model_id: str = "",
                 overrides: Optional[Dict[str, Any]] = None,
                 flow_state: str = "") -> GearPolicy:
    """策略解析单源(2610 挡位退役版): 恒返回统一策略行 + A/P 轴叠加。

    session_mode/executor_cfg 参数保留(消费面签名兼容), 不再参与选择——
    挡位分叉(T0 直通车/T2 全面补偿)与执行器 capability/tierProbed 驱动
    均已退役; A 轴(architect 模型档案)与 P 轴(流程相位)补偿照常叠加。
    未知值不再有"落默认档"语义(全部同值)。"""
    return _apply_p_axis(_apply_a_axis(UNIFIED_POLICY, architect_model_id),
                         flow_state, overrides)


def _apply_p_axis(policy: GearPolicy, flow_state: str,
                  overrides: Optional[Dict[str, Any]] = None) -> GearPolicy:
    """P 轴叠加(独立开关 p_axis_phase_overlay)。R2 面分离: 只触对话面字段
    (architect_note 追加/element_hints 单调收紧), 禁触任务面; 覆盖语义单源
    flow.p_axis_overlay_fields, 自定义注册 flow.register_phase_overlay。"""
    if not flow_state:
        return policy
    try:
        from ..compensation.overrides import override_enabled
        if not override_enabled(overrides or {}, "p_axis_phase_overlay"):
            return policy
        from . import flow as _flow
        fields = _flow.p_axis_overlay_fields(policy, flow_state)
        fields.update(_flow._custom_overlays.get(flow_state) or {})
        if not fields:
            return policy
        import dataclasses
        return dataclasses.replace(policy, **fields)
    except Exception:  # noqa: BLE001 — P 轴故障不阻塞解析链(fail-soft)
        return policy


def _apply_a_axis(policy: GearPolicy, architect_model_id: str) -> GearPolicy:
    """A 轴补偿叠加(architect 模型能力档案 → 调度纪律/要素提示密度)。"""
    if not architect_model_id:
        return policy
    try:
        from ..cognition import model_profile as _mp
        a_tier = int(_mp.tier_of(architect_model_id))
        discipline, hints = A_AXIS_POLICY.get(a_tier, ("standard", "low"))
        if (discipline, hints) != (policy.schedule_discipline,
                                   policy.element_hints):
            import dataclasses
            return dataclasses.replace(
                policy, schedule_discipline=discipline,
                element_hints=hints)
    except Exception:  # noqa: BLE001 — A 轴读取失败保持中性默认
        pass
    return policy


def default_policy() -> GearPolicy:
    return UNIFIED_POLICY


# ── U 轴: 要素框架提示(A 弱 → 引导用户按要素喂全信息, 帮 architect 补位) ──
# 要素清单 = 需求规约既有约束项(目标/方案/允许范围/禁止改动/验收), 非新词汇。
ELEMENT_HINT_HIGH = (
    "【要素澄清(模型能力补偿)】当前模型编排能力有限: 向用户澄清需求时, 必须按以下"
    "要素逐项给出框架并标注缺失项——①目标(要达成什么) ②方案要点(怎么做) "
    "③允许范围(可改哪些模块/文件) ④禁止改动(不能动的部分) ⑤验收标准(如何算完成)。"
    "每项先给出你已推断的默认值请用户确认或补全, 禁止开放式泛问；用户补全前不要落需求卡。")
ELEMENT_HINT_MID = (
    "【要素澄清】需求澄清时建议覆盖五要素(目标/方案要点/允许范围/禁止改动/验收标准), "
    "缺失关键要素时先列出推断默认值再请用户确认。")
