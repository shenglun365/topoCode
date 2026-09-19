"""任务挡位体系(环节十二a) — T0-T2 策略表 + 解析链单源。

策略与分数解耦(2026-09-18 裁决):
  - 挡位 = 执行策略选择, 固定三档 T0/T1/T2, 不随评分细分;
  - 评分(综合分)与挡位之间只有**默认区间映射**(≥0.90→T0 / ≥0.52→T1 / 其余→T2),
    非硬性绑定——模型策略可手动调整, 手动优先于映射(probe 不覆盖 manual 档);
  - 策略定义分两组:
    · 通用机制(UNIVERSAL_MECHANISMS): 全档共享的补偿/保障, 不随 tier 分叉
      (错误修复外循环(独立上下文)/受限生成通道(按 structured 探测位)/实测硬上限);
    · 能力匹配字段(下表 C/A 标注): 业务拆分粒度/确认节奏/工具面/预算等,
      按模型能力匹配——这是挡位间的真正差异。

解析链(会话 analysisMode):
  quick  → 钉死 T0(直通车·关 KB; 前端闪电钮开)
  strict → 等价 auto(legacy 值)
  auto   → 实测档位(执行器 tierProbed, 环节十二b 落地) >
           执行器配置 capability > 默认 T1
  T0-T2  → 钉死该档

消费面:
  - orchestrator: architect_note(policy) → 编排者系统指引
  - task_plan.assemble_task_instruction: agent_protocol_note(policy) →
    subagent 确认节奏/粒度段(里程碑协议按挡分叉)
  - exec_bridge.confirm_task: policy.max_iterations → 任务级轮次下发
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

GEAR_IDS = ("T0", "T1", "T2")
# 会话挡位字段合法值(REST 白名单单源)
GEAR_MODES = ("strict", "quick", "auto", *GEAR_IDS)
# M3 预留: 模型四级成本梯度(L 确定性/S 微调小模型/M 大本地/H 云端)——
# 异档分船编排按此标签路由(roadmap L 组 ↔ agent-harness-evaluation §9.3 裁决③)
MODEL_GRADIENTS = ("L", "S", "M", "H")

# ── 通用机制(全档共享, 不随 tier 分叉; 2026-09-18 策略拆分裁决) ──────────
# 普适补偿/保障对所有挡位一律生效——能力差异只由 GearPolicy 的能力匹配字段
# 表达, 通用机制不「按档开关」。
UNIVERSAL_MECHANISMS: Dict[str, str] = {
    "repair_loop": "错误修复外循环(独立上下文, reflection.repair.run_repair_loop)"
                   "——参数修复/守卫修复, 全档可用",
    "structured_channel": "受限生成通道(M4-A)——按 structured 探测位启用, 非按档",
    "gear_cap": "实测硬上限封顶(probe_hard_cap)——边界是实测的, 不是配置的",
}


def universal_mechanisms_note() -> str:
    """通用机制说明(回执/文档用)。"""
    return "；".join(UNIVERSAL_MECHANISMS.values())


@dataclass(frozen=True)
class GearPolicy:
    tier: str            # T0-T2
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


# ── 刻度细则(三维矩阵定则: 语义由本细则定义, 不靠命名) ─────────────────
# T0 强模型直通车     全能力——直出任务卡, 关闭多余兜底(前置分析不做)。
# T1 中模型标准兜底   任务级预拆(plan) + 结构化指令 + 报告走工具契约。
# T2 弱模型全面补偿   步骤级编排(steps) + 降线性依赖 + 核心逻辑图表达 +
#                     工具面收窄 + 轮次有界 + 准入提示(测评不足仍可运行)。
# 旧刻度迁移: 旧 T0→T0, T1→T1, 旧 T2/T3/T4→T2(2026-09-17 三维矩阵裁决;
# 旧值在读取路径归一, 会话/执行器存量一个版本后清理)。
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
        tool_surface="full", ctx_budget=1.0, prompt_style="standard",
        structured_output=False,
        tool_rounds=4, depends_source="llm", logic_diagram="",
    ),
    "T1": GearPolicy(
        tier="T1", label="中模型标准兜底·任务级预拆", kb=True, pre_split="plan",
        cadence="milestone", max_iterations=800,
        architect_note=(
            "标准挡(T1)：开发类需求先做需求分析——调用 req.propose 产出需求卡"
            "(创建即 ready, 用户可直接 /执行 建任务卡)，必要时检索 KB/资产地图校准边界。"
            "复杂需求应**预拆为多个小任务卡**(每卡单一模块级目标, 顺序下发), "
            "不要把大需求塞进单卡。"
            "内联 @执行器 前缀(如 @cline)按用户指定执行器建任务卡。"),
        agent_note="本任务为预拆后的单一模块级任务：聚焦本卡边界, 不要扩展到其他模块；里程碑协议照常。",
        tool_surface="full", ctx_budget=0.6, prompt_style="structured",
        structured_output=True,
        tool_rounds=4, depends_source="llm", logic_diagram="",
    ),
    "T2": GearPolicy(
        tier="T2", label="弱模型全面补偿·步骤级编排", kb=True, pre_split="steps",
        cadence="key_step", max_iterations=300,
        architect_note=(
            "标准挡(T2 弱模型全面补偿)：需求分析同 T1；任务卡须预写**显式文件路径+步骤序列**"
            "(每步单一动作), 拆到步骤粒度再下发。"
            "任务指令须附**核心逻辑图**(PlantUML/Mermaid 标准语法, activity/sequence 类)——"
            "执行器能力有限, 用图补足方案理解, 不依赖其自行推断。"),
        agent_note="按任务上下文中的步骤序列逐步执行；关键步骤(编译前/破坏性操作/方案分叉)完成后简短报告再继续；里程碑协议照常。",
        tool_surface="reduced", ctx_budget=0.35, prompt_style="structured",
        structured_output=True,
        tool_rounds=3, depends_source="linear", logic_diagram="uml",
    ),
}

# 旧刻度别名(读路径归一; 写路径一律新刻度)
_LEGACY_TIER_MAP = {"T0": "T0", "T1": "T1",
                    "T2": "T2", "T3": "T2", "T4": "T2"}

_DEFAULT_TIER = "T1"


def _valid_tier(v: Any) -> Optional[str]:
    """刻度归一: 新刻度原样; 旧刻度(T3/T4 等)映射新刻度; 未知 → None。"""
    t = str(v or "").strip().upper()
    if t in GEAR_IDS:
        return t
    return _LEGACY_TIER_MAP.get(t)


def normalize_mode(mode: str) -> str:
    """会话挡位值归一(REST 写侧用): 旧刻度值映射新刻度, 其余原样。"""
    m = str(mode or "").strip()
    if m.upper() in _LEGACY_TIER_MAP:
        return _LEGACY_TIER_MAP[m.upper()]
    return m


def probe_hard_cap(executor_cfg: Optional[Dict[str, Any]] = None):
    """M1 实测硬上限: 从探针结果推导挡位天花板——「边界是实测的, 不是配置的」。

    识别两种形态:
    - 结构化 probeFlags: {"followGate": true} → 封顶 T2（新探测写侧, 优先）;
    - 历史 probeDetail 字符串含「上限T3/上限T2/否决」标记（旧刻度探测已写）→ 封顶 T2。
    返回 (cap_tier|None, note)。语义: 指令跟随不过 = 该模型**至多**按 T2 补偿粒度
    编排（T0-T1 的编排强度超出其能力圈）。
    """
    cfg = executor_cfg if isinstance(executor_cfg, dict) else {}
    flags = cfg.get("probeFlags")
    if isinstance(flags, dict) and flags.get("followGate"):
        return "T2", "指令跟随探针未过——封顶 T2(结构化 probeFlags)"
    detail = str(cfg.get("probeDetail") or "")
    if "上限T3" in detail or "上限T2" in detail or "否决" in detail:
        return "T2", "指令跟随探针未过——封顶 T2(探测标记)"
    return None, ""


def apply_cap(tier: str, cap: str) -> str:
    """封顶语义: 请求挡强于上限挡(T0-T1 > T2)时**降档**到上限; 已不强于则原样。

    (T0 最强/T2 最弱——「上限 T2」= 允许 T2, 请求 T1/T0 → 落 T2。)
    """
    order = {t: i for i, t in enumerate(GEAR_IDS)}
    return cap if order.get(cap, -1) > order.get(tier, -1) else tier


# A 轴 → 补偿策略映射(职责归属: A 弱 → 调度纪律与要素提示升档)
A_AXIS_POLICY = {
    0: ("standard", "low"),        # A0 强: 正常发挥
    1: ("guided", "mid"),          # A1 中: 引导式调度 + 中密度要素提示
    2: ("strict_pipeline", "high"),  # A2 弱: 确定性管线为主 + 高密度要素提示
}


def resolve_gear(session_mode: str, executor_cfg: Optional[Dict[str, Any]] = None,
                 architect_model_id: str = "",
                 overrides: Optional[Dict[str, Any]] = None) -> GearPolicy:
    """解析链单源(三维矩阵): 会话挡位 + 执行器能力(C 轴) + architect 模型(A 轴)。

    executor_cfg: 执行器注册表 config(读 capability / tierProbed[十二b]) → C 轴字段。
    architect_model_id: architect 对话模型(A 轴) → schedule_discipline/element_hints;
      无 id 或无档案 → 字段保持中性默认(现行为)。
    overrides: 补偿白名单开关(compensation.overrides, R2.1)。
    未知值一律落默认 T1(显式优于静默升档)。
    M1: 实测来源(tierProbed)叠加探针硬上限封顶(cap_note 随策略携带);
    人工显式 capability 不封顶(人的意志优先)。
    R2.1(开关 r2_1_axis_stack, 默认新行为): 显式挡决定**基线策略行**, A 轴补偿
    叠加生效; quick(直通车)豁免保持零补偿纯净直通。开关关闭 → 回退旧短路语义。
    """
    mode = normalize_mode(str(session_mode or "").strip())
    if mode == "quick":
        return _TIERS["T0"]
    if mode in _TIERS:
        policy = _TIERS[mode]
        if not _axis_stack_enabled(overrides):
            return policy          # 旧短路语义(回退开关)
        # R2.1: 显式挡不封顶(人的意志优先), 仅叠加 A 轴补偿
        return _apply_a_axis(policy, architect_model_id)
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
    return _apply_a_axis(policy, architect_model_id)


def _axis_stack_enabled(overrides: Optional[Dict[str, Any]]) -> bool:
    """R2.1 白名单开关(缺省 = 新行为; 显式 false 回退旧短路)。"""
    from ..compensation.overrides import override_enabled
    return override_enabled(overrides or {}, "r2_1_axis_stack")


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
    return _TIERS[_DEFAULT_TIER]


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


def gear_note(session_mode: str) -> str:
    """会话挡位切换回执文案(REST 用)。"""
    p = resolve_gear(session_mode)
    return f"挡位 {p.tier}（{p.label}）：下次回合生效"
