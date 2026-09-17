"""任务挡位体系(环节十二a) — T0-T4 策略表 + 解析链单源。

挡位 = 下发策略参数行(数据驱动), 不是代码分支: 解析一次 → GearPolicy
对象逐层传递(指令模板/确认节奏/轮次/architect 指引), 禁止 tier 字面量
散落各处。新增挡位 = 加一行策略, 无新代码路径。

解析链(会话 analysisMode):
  quick  → 钉死 T0(直通车·关 KB; 前端闪电钮开)
  strict → 等价 auto(legacy 值)
  auto   → 实测档位(执行器 tierProbed, 环节十二b 落地) >
           执行器配置 capability > 默认 T1
  T0-T4  → 钉死该档

消费面:
  - orchestrator: architect_note(policy) → 编排者系统指引
  - task_plan.assemble_task_instruction: agent_protocol_note(policy) →
    subagent 确认节奏/粒度段(里程碑协议按挡分叉)
  - exec_bridge.confirm_task: policy.max_iterations → 任务级轮次下发
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

GEAR_IDS = ("T0", "T1", "T2", "T3", "T4")
# 会话挡位字段合法值(REST 白名单单源)
GEAR_MODES = ("strict", "quick", "auto", *GEAR_IDS)
# M3 预留: 模型四级成本梯度(L 确定性/S 微调小模型/M 大本地/H 云端)——
# 异档分船编排按此标签路由(roadmap L 组 ↔ agent-harness-evaluation §9.3 裁决③)
MODEL_GRADIENTS = ("L", "S", "M", "H")


@dataclass(frozen=True)
class GearPolicy:
    tier: str            # T0-T4
    label: str           # 语义名(回执/指引用)
    kb: bool             # KB/范围探针 grounding(T0 关——直通车不做分析面)
    pre_split: str       # architect 预拆粒度: none|plan|steps|micro(plan/steps 落地于环节十四)
    cadence: str         # subagent 确认节奏: milestone|key_step|every_step
    max_iterations: int  # 任务级轮次上限
    architect_note: str  # architect 编排指引(系统消息)
    agent_note: str      # subagent 任务指令附加段(粒度/节奏)
    # ── M1: 实测硬上限(边界是实测的, 不是配置的) ──
    cap_note: str = ""   # 非空 = tierProbed 被探针硬上限封顶(附封顶原因)
    # ── M2: 小模型特化维度(策略表一行全量声明, 消费端按挡读取, 禁散落分支) ──
    tool_surface: str = "full"       # full|reduced|minimal(MCP注入/steer/KB写按挡裁剪)
    ctx_budget: float = 1.0          # KB grounding/任务卡/里程碑历史 预算系数
    prompt_style: str = "standard"   # standard|structured|minimal(弱模型更短更清单化)
    structured_output: bool = False  # True → 报告走工具契约(非文本固定行)
    reasoning_effort: str = "high"   # high|medium|low(推理档位映射)
    tool_rounds: int = 4             # M4-B: chat 侧工具轮次上限(弱档更早触顶, 损失有界)


_TIERS: Dict[str, GearPolicy] = {
    "T0": GearPolicy(
        tier="T0", label="强模型直通车·直出任务卡", kb=False, pre_split="none",
        cadence="milestone", max_iterations=2000,
        architect_note=(
            "快捷挡(T0 直通车)：不做需求分析(不调用 req.propose 与 KB 检索类工具)。"
            "依据用户请求直接整理实质任务(目标/方案要点/边界/验收)调用 task.propose "
            "创建任务卡供用户确认执行；请求过于模糊时先集中提问。"
            "内联 @执行器 前缀(如 @cline)直接按指定执行器建卡。"),
        agent_note="执行器自主推进, 减少不必要暂停；里程碑协议照常(计划确认+每里程碑报告)。",
        tool_surface="full", ctx_budget=1.0, prompt_style="standard", structured_output=False, reasoning_effort="high",
    ),
    "T1": GearPolicy(
        tier="T1", label="强模型+资产 grounding", kb=True, pre_split="none",
        cadence="milestone", max_iterations=2000,
        architect_note=(
            "标准挡(T1)：开发类需求先做需求分析——调用 req.propose 产出需求卡"
            "(创建即 ready, 用户可直接 /执行 建任务卡)，必要时检索 KB/资产地图校准边界。"
            "分析/问答类请求直接深入回答，不产需求卡。"
            "内联 @执行器 前缀(如 @cline)按用户指定执行器建任务卡。"),
        agent_note="执行器自主推进, 减少不必要暂停；里程碑协议照常(计划确认+每里程碑报告)。",
        tool_surface="full", ctx_budget=1.0, prompt_style="standard", structured_output=False, reasoning_effort="high",
    ),
    "T2": GearPolicy(
        tier="T2", label="中模型·任务级预拆", kb=True, pre_split="plan",
        cadence="milestone", max_iterations=800,
        architect_note=(
            "标准挡(T2 中模型)：需求分析同 T1；复杂需求应**预拆为多个小任务卡**"
            "(每卡单一模块级目标, 顺序下发), 不要把大需求塞进单卡。"),
        agent_note="本任务为预拆后的单一模块级任务：聚焦本卡边界, 不要扩展到其他模块；里程碑协议照常。",
        tool_surface="full", ctx_budget=0.6, prompt_style="structured", structured_output=True, reasoning_effort="medium",
    ),
    "T3": GearPolicy(
        tier="T3", label="弱模型·步骤级编排", kb=True, pre_split="steps",
        cadence="key_step", max_iterations=300,
        architect_note=(
            "标准挡(T3 弱模型)：需求分析同 T1；任务卡须预写**显式文件路径+步骤序列**"
            "(每步单一动作), 拆到步骤粒度再下发。"),
        agent_note="按任务上下文中的步骤序列逐步执行；关键步骤(编译前/破坏性操作/方案分叉)完成后简短报告再继续；里程碑协议照常。",
        tool_surface="reduced", ctx_budget=0.35, prompt_style="structured", structured_output=True, reasoning_effort="low",
        tool_rounds=3,
    ),
    "T4": GearPolicy(
        tier="T4", label="微步确认", kb=True, pre_split="micro",
        cadence="every_step", max_iterations=100,
        architect_note=(
            "标准挡(T4 微步)：需求分析同 T1；任务拆到**微步粒度**(单文件/单函数级), "
            "每步单独可验证, 预期频繁交互确认。"),
        agent_note="微步模式：每完成一步即输出 [[NEED_INPUT]] 等待用户确认后再进行下一步。",
        tool_surface="minimal", ctx_budget=0.25, prompt_style="minimal", structured_output=True, reasoning_effort="low",
        tool_rounds=2,
    ),
}

_DEFAULT_TIER = "T1"


def _valid_tier(v: Any) -> Optional[str]:
    return v if v in GEAR_IDS else None


def probe_hard_cap(executor_cfg: Optional[Dict[str, Any]] = None):
    """M1 实测硬上限: 从探针结果推导挡位天花板——「边界是实测的, 不是配置的」。

    识别两种形态:
    - 结构化 probeFlags: {"followGate": true} → 封顶 T3（新探测写侧, 优先）;
    - 历史 probeDetail 字符串含「上限T3/否决」标记（十二b 探测已写）→ 封顶 T3。
    返回 (cap_tier|None, note)。语义: 指令跟随不过 = 该模型**至多**按 T3 粒度编排
    （T0-T2 高强度编排超出其能力圈）。
    """
    cfg = executor_cfg if isinstance(executor_cfg, dict) else {}
    flags = cfg.get("probeFlags")
    if isinstance(flags, dict) and flags.get("followGate"):
        return "T3", "指令跟随探针未过——封顶 T3(结构化 probeFlags)"
    detail = str(cfg.get("probeDetail") or "")
    if "上限T3" in detail or "否决" in detail:
        return "T3", "指令跟随探针未过——封顶 T3(探测标记)"
    return None, ""


def apply_cap(tier: str, cap: str) -> str:
    """封顶语义: 请求挡强于上限挡(T0-T2 > T3)时**降档**到上限; 已不强于则原样。

    (T0 最强/T4 最弱——「上限 T3」= 允许 T3/T4, 请求 T1 → 落 T3。)
    """
    order = {t: i for i, t in enumerate(GEAR_IDS)}
    return cap if order.get(cap, -1) > order.get(tier, -1) else tier


def resolve_gear(session_mode: str, executor_cfg: Optional[Dict[str, Any]] = None
                 ) -> GearPolicy:
    """解析链单源: 会话挡位(+执行器能力) → GearPolicy。

    executor_cfg: 执行器注册表 config(读 capability / tierProbed[十二b])。
    未知值一律落默认 T1(显式优于静默升档)。
    M1: 实测来源(tierProbed)叠加探针硬上限封顶(cap_note 随策略携带);
    人工显式 capability 不封顶(人的意志优先)。
    """
    mode = str(session_mode or "").strip()
    if mode == "quick":
        return _TIERS["T0"]
    if mode in _TIERS:
        return _TIERS[mode]
    # strict / auto / 未知 → auto 链: 实测档位 > 配置档位 > 默认
    cfg = executor_cfg if isinstance(executor_cfg, dict) else {}
    tier = (_valid_tier(cfg.get("tierProbed"))
            or _valid_tier(cfg.get("capability"))
            or _DEFAULT_TIER)
    policy = _TIERS[tier]
    if cfg.get("tierProbed"):
        cap, note = probe_hard_cap(cfg)
        if cap:
            capped = apply_cap(tier, cap)
            if capped != tier:
                import dataclasses
                policy = dataclasses.replace(policy, tier=capped, cap_note=note)
    return policy


def default_policy() -> GearPolicy:
    return _TIERS[_DEFAULT_TIER]


def gear_note(session_mode: str) -> str:
    """会话挡位切换回执文案(REST 用)。"""
    p = resolve_gear(session_mode)
    return f"挡位 {p.tier}（{p.label}）：下次回合生效"
