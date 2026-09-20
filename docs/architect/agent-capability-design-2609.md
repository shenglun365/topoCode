# architect Agent 能力整体设计（v1 草案）

> 状态：**整体设计稿**（待评审后进入实施）
> 日期：2026-09-19
> 性质：整体设计（接口 / 模块切分 / 文件级改动）；实现 [compensation-strategy-requirements-2609.md](compensation-strategy-requirements-2609.md) 的 R1–R3
> 范围：architect agent 内核——策略（L0）· 补偿（L1）· 回合（L2）；KB chat 内核收敛、MCP 工具面为独立轨道（见 §12）
> 关联文档：[compensation-strategy-requirements-2609.md](compensation-strategy-requirements-2609.md)（需求规格，本文实现之）· [agent-harness-evaluation-2609.md](agent-harness-evaluation-2609.md) · [orchestration-plan.md](orchestration-plan.md) · [../conventions/CONV-04-API契约与验证门禁.md](../conventions/CONV-04-API契约与验证门禁.md)

---

## 0. 决策继承与新增

继承需求规格 §0 的 D1–D7（目标排序 / 单项口径 / 行为兼容 / 契约冻结 / 双验收 / stretch / 迁移批次）。本轮评审新增（已追加至需求规格 §0，append-only）：

| # | 决策项 | 结论 |
|---|---|---|
| D8 | 内核形态 | **不整体采用 cline SDK**：sidecar 保持为 C 轴执行器之一（stdio 契约冻结不变），SDK 类型不出适配层 |
| D9 | 架构主线 | architect agent 内核**自研收敛**为「策略 L0 — 补偿 L1 — 回合 L2」三形态引擎；工具面 MCP 化为独立轨道，不阻塞本设计 |
| D10 | purpose 词表 | **四组 19 项冻结**（分析 3 / 单项 5 / 轻量 5 / 工种 6，含探测维映射，见 §2.2） |
| D11 | reasoning_effort 归属改判 | **迁出 GearPolicy**：推理强度 = 模型能力属性（探测支持位）+ **用户自选**参数，不随挡位自动变更（见 §5.2） |
| D12 | 链 3 收编门禁 | 链 3 全量收编后，`cognition/llm.py llm_sync` 仅允许被回合引擎 call 形态调用（grep 门禁强制） |

## 1. 定位与总览

### 1.1 一条主线

R1「统一补偿抽象」同时就是自研内核收敛在 architect 侧的形态：**策略字段只在 L0 出现，补偿只在 L1 表达，回合只经 L2 发生**。内核收敛后，`T0/T1/T2` 字面量不得新散落（R1.4 门禁）。

### 1.2 架构总览

```
            ┌─ perception（意图/指令入口，现状保留）─┐
            ▼                                      ▼
┌──────────────────────────── 内核 ───────────────────────────────┐
│ L0 策略层   resolve_gear 单源(governance/gears.py) → GearPolicy  │
│             + CapabilityScores（探测分目的三维）                  │
│             ↓ 解析一次                                           │
│             CompensationCtx {gear, purpose, axis, a_tier, ...}   │
│ L1 补偿管线 ProviderRegistry → assemble() / conclude() / retry   │
│             5 类载体 × 3 条管线（chat / dispatch / call）         │
│ L2 回合引擎 三形态：ChatTurn ｜ DispatchTurn ｜ CallTurn          │
│             统一：工具调用协议 / 流式 / usage 记账 / 遥测          │
└──────┬─────────────────────┬─────────────────────┬──────────────┘
   工具面                 事件面                 执行器面
 （42 工具注册表，       （SSE/WS 事件契约      （stdio JSON-RPC，
   MCP 化独立轨道）        冻结，卡片 kind 不变）   CONV-04 冻结）
                    领域服务（需求/任务/合并，不入内核）
```

### 1.3 三稳定契约（边界锁）

内核自身可被整体重写的前提是三个边界契约稳定：**工具面**（`agent/tools/registry.py` 注册表 → 后续 MCP 暴露）、**事件面**（现有 SSE/WS 事件与卡片 kind）、**执行器面**（TurnAdapter stdio JSON-RPC）。本设计不动任何一个。

## 2. L0 策略层

### 2.1 CompensationCtx

`resolve_gear` 保持单源不动（`governance/gears.py:173`）。本层新增 frozen dataclass：

```python
CompensationCtx(
    gear: GearPolicy,          # 现状策略行（8 字段处置见 §5）
    axis: Axis,                # A(对话) / C(下发) / S(单项)
    purpose: Purpose,          # §2.2 冻结词表
    scores: CapabilityScores,  # 探测三维分（R2.4：入策略，仅弱档下调）
    a_tier: int,               # 有效档 = gear.tier 经分目的细化
    flags: ProbeFlags,         # followGate / cap_note 等
    budget: BudgetParams,      # 26k/22k/16k 基线 × ctx_budget 系数
)
```

A 轴短路修复（R2.1，白名单开关 `r2_1_axis_stack`）：`resolve_gear` 中显式挡不再跳过 A 轴叠加——显式挡定**基线策略行**，A 轴补偿叠加生效；`quick` 豁免保持纯净直通（零补偿）。

### 2.2 purpose 词表（D10 冻结）

| 组 | 成员 | 探测维映射 |
|---|---|---|
| 分析（3） | requirement / architecture / module | 各对应探测一维 |
| 单项（5） | extraction / clarify / collect / split / probe | requirement ｜ module |
| 轻量（5） | summary / distill / design / se / ut | module |
| 工种（6） | role:extract / verify / induce / pseudo / evaluate / mine | module |

实现为模块级 `frozen Enum` + 探测维映射表；词表外 purpose 视为编码错误（fail-fast）。

## 3. L1 补偿管线

### 3.1 载体：需求规格 8 类 → 实现 5 类

| 载体（实现） | 吸收原 8 类 | 作用时刻 |
|---|---|---|
| `PromptPiece(placement)` | SystemNote + InstructionSection + PromptScaffold | 装配时（placement ∈ system / section / scaffold） |
| `RunParams` | ToolFilter + BudgetParam + reasoning_effort* / cadence / schedule_discipline | 构造/运行时（工具面裁剪、预算系数、迭代与节奏参数） |
| `OutputContract` | OutputContract | 收尾解析（JSON 块优先，文本协议兼容降级） |
| `ArtifactGate` | ArtifactGate | 收尾校验（确定性，如图围栏存在且边≥3） |
| `RetryPolicy` | RetryPolicy | 失败循环（nudge 次数按挡 + 确定性兜底） |

> *reasoning_effort 按 D11 迁出 GearPolicy，不进入 RunParams，见 §5.2。

### 3.2 Provider 协议

```python
class CompensationProvider(Protocol):
    name: str
    purposes: frozenset[Purpose]
    def assemble(self, ctx: CompensationCtx, prompt: AssembledPrompt) -> None:
        """贡献 PromptPiece / RunParams。"""
    def conclude(self, ctx: CompensationCtx, output: TurnOutput) -> Verdict:
        """贡献 OutputContract 解析 / ArtifactGate 校验 / Retry 判定。"""
```

- 注册表（`registry.py`）按 `(carrier, priority, name)` 排序应用；**消费清单可自省**——R1.2 门禁测试的依据。
- 管线两时刻：`assemble()`（回合构造前）与 `conclude()`（回合结束后，含 Retry 循环驱动）。

### 3.3 内置 Provider 与收编映射（R1.1 行为等价，D3）

| Provider | 收编对象（现状位置） |
|---|---|
| ArchitectNoteProvider | `gears.py:75-107` 按挡文案（`orchestrator.py:511` 注入） |
| ElementHintProvider | U 轴五要素框架（`gears.py:225`） |
| CapNoteProvider | apply_cap 的 cap_note（`task_plan.py:146`） |
| BudgetTrimProvider | `cognition/prompt.py:31,154` 预算裁剪（系数化，dossier/工具结果纳入 ctx_budget） |
| ScopeGroundProvider | `planning/scope_probe.py` 三源 grounding + R2.3 启发式兜底 |
| MilestoneProvider | task_plan 确定性段 + 里程碑协议（cadence / schedule_discipline / tool_rounds 的消费者） |
| ToolSurfaceProvider | tool_surface / kb 字段消费者（先保守默认：T2 裁 KB 写 / MCP 写） |
| ScaffoldProvider | prompt_style 消费者 + R3.1 分目的脚手架（需求规格 §5.4 矩阵落地处） |
| StructuredOutputProvider | M4-A structured_model 扩展：里程碑报告 / 完成摘要 JSON 块契约（R3.3） |
| LogicDiagramGateProvider | R3.2：T2 下发前校验核心逻辑图围栏，缺失 → nudge architect 补图（纯 architect 侧，不动 runner） |
| RetryProvider | T0 失败即报 / T1 nudge 1 / T2 nudge 2 + 确定性兜底 |

收编等价判据：`test_compensation_equivalence.py` 基线回归（§7）。

### 3.4 OutputContract 双轨解析（R3.3，含 §6 开放点⑥ 处置）

- JSON 块 schema 草案：`{changed_files: [], verify: {command?, passed?}, next, need_input?}`；
- 解析优先级：**JSON 块 → 文本固定三行（兼容降级）→ NEED_INPUT 守卫**；
- 里程碑 / 完成摘要两处生效；runner 侧契约零变更（D4）。

## 4. L2 三形态回合引擎

| 形态 | 吸收（收编） | 输入 → 输出 |
|---|---|---|
| `ChatTurn` | orchestrator `_run_llm_tool_loop` + req_agent 对话管线 | 消息+上下文 → 流事件+工具调用（`[TOOL_CALL]` 协议唯一实现收编于此） |
| `DispatchTurn` | task_plan 组装（pre_split `:379` / depends_source `:424` / 确定性段 `:145-260`）+ exec_bridge 下发 | 任务卡 → 执行器会话（stdio 契约冻结） |
| `CallTurn` | `cognition/llm.py` 单次调用 + 链 3 全部 11+ 调用点（R3.1，D7 三批） | purpose+输入 → 结构化结果（Contract 解析 + Retry + 兜底） |

横切面（引擎统一承担，单点实现）：

- usage / 调用日志单点记账（消三处各记各的）；
- `llm_dataset` 遥测带 `{tier, purpose, axis, attempt}`；
- 模型健康提示（`orchestrator.py:159` 空返回 + probeScore 低）收编为 ChatTurn 收尾检查。

### 4.1 CallCatalog（§6 开放点⑨ 处置）

roles 六工种与 light_tasks **合并为一张统一注册表**：每条目 `{purpose, model_route, scaffold, retry, fallback}`；roles/light_tasks 词汇经别名表迁移，调用点全部改走 `CallTurn`。

## 5. GearPolicy 字段处置（R1.2 逐字段）

### 5.1 处置总表：7 接线 + 1 迁出

| 字段 | 处置 | 消费者 |
|---|---|---|
| tool_surface | 接线 | ToolSurfaceProvider |
| ctx_budget | 接线 | BudgetTrimProvider（系数） |
| prompt_style | 接线 | ScaffoldProvider（minimal / structured 映射密度） |
| structured_output | 接线 | StructuredOutputProvider（M4-A + R3.3） |
| logic_diagram | 接线 | LogicDiagramGateProvider（R3.2） |
| cadence | 接线 | MilestoneProvider（确认节奏参数化，正式化现状） |
| schedule_discipline | 接线 | MilestoneProvider（force_linear，正式化 `task_plan.py:424` 现状） |
| reasoning_effort | **迁出（D11）** | 见 §5.2，不留在策略表 |

> tool_rounds / depends_source / max_iterations / element_hints 等既有消费字段维持现状归属（分别归 MilestoneProvider / DispatchTurn / exec_bridge / ElementHintProvider）。

### 5.2 reasoning_effort 迁出设计（D11）

问题定性：字段标注 `(C)` 执行器能力驱动，但执行器侧契约本轮冻结（D4）；改挂 architect 自身调用则违背归属——**是归类错误，不是补偿缺口**。目标形态：

1. **探测支持位**：A 轴探测套件新增 1 个轻量用例（带 `reasoning_effort` 参数发起请求，按端点接受度判定），产出 capability bit 写入模型档案 caps——复用 M4-A structured 支持位的既有通道与形态（不属于"探测套件重构"，§5.7 范围外约束不触发）。
2. **用户自选**：模型配置（model_configs.params）新增可选键 `reasoning_effort`（`auto`=不发送｜low｜medium｜high），仅支持位为真的模型可选；默认 `auto`。
3. **透传**：回合引擎请求构造层按模型配置透传参数；端点拒绝 → 记日志并降级不发送。
4. **生效范围**：A 轴 / S 轴（architect 自身调用）本轮生效；C 轴（执行器模型）随 CONV-04 解冻作为候选轨道，落点为 executors 注册表 config。

原则重申（本轮评审确认）：**agent 执行策略与模型能力分级适配（GearPolicy 的职责）；模型推理强度在模型支持范围内由用户自选（模型配置的职责）**——两者正交。

## 6. 白名单行为变更与回退开关（§6 开放点⑧ 处置）

全局 config 键 `agent.comp.overrides.<id>`，逐项可回退，默认 = 新行为；开关语义内嵌（如 `r2_1_axis_stack` 生效时 quick 豁免为固定语义）：

| 开关键 | 对应白名单项 | 项 |
|---|---|---|
| `r2_1_axis_stack` | A 轴叠加（quick 豁免写死在键语义内） | R2.1 |
| `r2_3_probe_fallback` | probe_scope 启发式兜底 | R2.3 |
| `r2_5_intra_tier` | 同挡个体差异（stretch） | R2.5 |
| `r3_2_logic_gate` | 核心逻辑图 ArtifactGate | R3.2 |
| `r3_3_json_report` | 里程碑/摘要 JSON 契约 | R3.3 |
| `r3_4_dialogue_wiring` | 对话面策略接线（stretch） | R3.4 |

## 7. 门禁与测试（R1.3 / R1.4 + D5）

落点 `apps/architect/tests/`，pytest 自检脚本形态（§6 开放点⑦ 处置），进 `npm run test:py` 可红：

1. `test_compensation_equivalence.py`——收编前先固化基线（M0 产出）：gear 解析、任务指令组装 golden 文件、`/提取需求` 输出形状、chat 回合冒烟；
2. `test_policy_consumption_gate.py`——import 注册表自省：§5.1 七个接线字段各有 ≥1 注册消费者；`reasoning_effort` 不再出现在 agent 策略代码（grep 断言）；
3. `test_grep_gates.py`——纯文本断言：① 业务模块禁裸调 `llm_sync`（仅 `turns/` 白名单，D12）；② 源码无新增 `T0/T1/T2` 字面量散落点（白名单文件清单除外）；
4. `test_file_size_gate.py`——行数**软门禁**：新增文件软上限 **400 行**（超限红灯或显式白名单）；存量文件允许小幅漂移（容差 +5%、最低 10 行），失控增长红灯提示"宜拆分"——拆分节奏由 §8.2 各阶段把握，门禁只防失控（2026-09-19 评审放宽：软性限制，非硬性强制拆分）。

## 8. 文件级落点

### 8.1 大文件拆分原则（本次改造硬约束）

本次改造涉及多个千行级源文件，**收编即拆分**：被收编代码迁入新模块的同时，原文件必须同步薄化或溶解为兼容门面（迁移完成后删除），不允许"收编后原文件原样保留"。细则：

1. **行数软上限 400 行**/文件（单一职责前提下）；超限即再按职责切分或登记白名单；
2. **单一职责**：一个文件只回答一个问题（工具实现 / 下发状态机 / 合并域 / 恢复泵 / 子会话编排各归各文件）；
3. **结构性拆分（行为不动）优先**：纯搬迁类拆分排在行为变更阶段之前或并行，独立提交可回退；
4. **迁移期兼容门面**：原路径 re-export 保持旧 import 不断，随对应阶段验收后删除门面。

### 8.2 存量大文件拆分表（基线 2026-09-19）

| 文件 | 现状 | 拆分去向 | 阶段 |
|---|---|---|---|
| `arch_routes/req_agent.py` | 2027 行 | ① ~30 个工具实现函数 → `agent/tools/impl/{kb,semantic,map,asset,diagram}.py`（按域，每个 ≤400）；② `run_arch_tool` 分发+审计 → `agent/tools/exec.py`；③ req_harness_clarify/collect → `agent/requirements/harness.py`（CallTurn 调用点）；④ 原文件溶解为兼容门面，M4 验收后删除 | ①② M3 前置（结构性行）· ③ 随链3①（M3）· 溶解 M4——**M3 已落地：① 全量（注册随定义点，re-export 保接缝）+ ③（harness 迁出，M4 转 CallTurn）；② run_arch_tool 留驻（`ra.run_arch_tool` 打桩面广，随 M4 接缝重构评估）；mcp 三件套留驻（`_kb_gateway` 打桩接缝）** |
| `arch_routes/exec_bridge.py` | 1688 行 | ① propose/confirm/task_input/执行器设置 → `agent/execution/dispatch.py`（与 DispatchTurn 协作）；② merge 族（precheck/chain_base/cleanup/merge_branch）→ `agent/execution/merge.py`；③ pump/recover_sweep → `agent/execution/recover.py`；④ 原文件留 REST 门面 + 兼容 re-export | M4（②③ 可 M2 结构性先行）——**M2 已落地：② 全量 + ③ sweep 对账三件套（泵核 `_task_pump`/`_handle_task_event` 与 `eb.*` 打桩面深耦合，随 M4 迁出）；runner 打桩接缝经调用期解析保持** |
| `arch_routes/sessions.py` | 1538 行 | ① 会话 REST → `arch_routes/sessions_routes.py`；② coding 子会话编排 → `agent/sessions/coding.py`；③ `_GUIDE_SYSTEM` 等按挡文案 → 静态文案模块（后续归 ScaffoldProvider 消费） | M2（行为不动，纯结构）——**M2 已落地（实现形态微调）：② coding 编排迁 `agent/sessions/coding.py`；③ 文案+state 迁 `session_guide.py`；备案文档域迁 `session_docs.py`（独立 APIRouter，URL 不变）；① 会话 REST 保留原文件名 sessions.py（避免全量 import 翻动，路由面不再细分）** |
| `agent/orchestrator.py` | 1004 行 | ① 工具调用循环 → `turns/chat.py`（收编）；② `_chat_context`/dossier 装配 → `turns/context.py`；③ 剩入口编排（gate/route/land，目标 ≤400） | M1 |
| `agent/planning/task_plan.py` | 541 行 | ① 组装/协议段 → DispatchTurn + MilestoneProvider；② 剩 pre_split / depends_source（目标 ≤300） | M1 |
| `agent/cognition/prompt.py` | 427 行 | ① 预算裁剪 → BudgetTrimProvider；② 剩能力文档/头部装配（目标 ≤300） | M1 |
| `agent/cognition/llm.py` | 316 行 | 不拆；API 收窄为 `turns/call.py` 专属底层（目标 ≤300） | M3 |

### 8.3 新增/拆分后目录树

```
apps/architect/topoone_app_architect/agent/
├── governance/gears.py        # resolve_gear 单源保留；GearPolicy 去 reasoning_effort；R2.2 清刻度残留
├── compensation/              # ★ 新增（L1）
│   ├── ctx.py                 #   CompensationCtx / Purpose / Axis / CapabilityScores
│   ├── carriers.py            #   PromptPiece / RunParams / OutputContract / ArtifactGate / RetryPolicy
│   ├── registry.py            #   ProviderRegistry + 消费清单自省（门禁依据）
│   ├── pipeline.py            #   assemble() / conclude() / retry 循环
│   └── providers/
│       ├── builtin.py  budget.py  toolsurface.py  scaffold.py
│       └── milestone.py  output.py  retry.py
├── turns/                     # ★ 新增（L2）
│   ├── base.py                #   TurnSpec / TurnResult / usage / 遥测
│   ├── chat.py                #   收编 orchestrator 工具循环 + req_agent 对话管线
│   ├── context.py             #   _chat_context / dossier 装配（自 orchestrator 迁入）
│   ├── dispatch.py            #   收编 task_plan 组装 + exec_bridge 下发
│   └── call.py                #   单项调用统一入口（链 3；llm_sync 唯一白名单调用方）
├── tools/
│   ├── registry.py            #   登记面保留（后续 MCP 化独立轨道）
│   ├── exec.py                #   run_arch_tool 分发 + 审计（自 req_agent 迁入）
│   └── impl/                  #   工具实现按域拆分（自 req_agent 迁入）
│       ├── kb.py  semantic.py  map.py  asset.py  diagram.py
├── requirements/
│   └── harness.py             #   req_harness_clarify / collect（CallTurn 调用点）
├── sessions/
│   └── coding.py              #   coding 子会话编排（自 arch_routes/sessions.py 迁入）
├── execution/                 # 现有目录扩展
│   ├── dispatch.py  merge.py  recover.py   # ★ 自 exec_bridge 迁入
│   └── ...                    #   probes / pumps / capabilities 等现状保留
├── cognition/                 # prompt.py 裁剪逻辑迁出；llm.py 收窄为 call.py 底层
├── planning/task_plan.py      # 薄化为 pre_split / depends_source
└── ...                        # perception / memory / reflection 现状保留
apps/architect/tests/          # §7 四门禁 + 既有 28 个测试文件回归
```

## 9. 迁移路线（对齐 D1 排序与 D7 批次）

| 阶段 | 内容 | 验收（需求规格 §5.6 映射） |
|---|---|---|
| M0 基线 | 等价基线测试冻结 + compensation/ 骨架 + 行数基线清单（§8.2）+ 四门禁上线（零行为变化） | 基线全绿 |
| M1 收编 | ArchitectNote / ElementHint / CapNote / BudgetTrim / Milestone 收编（行为等价）+ R2.2 刻度清理 + reasoning_effort 迁出（零消费，行为中性）；**拆分：orchestrator（→turns/chat+context）、prompt.py、task_plan.py** | 等价回归 + 消费门禁（部分字段） |
| M2 缺口 | R2.1（开关）/ R2.3 / R2.4 + 7 字段处置齐 + 门禁全量；**拆分（结构性行为不动）：sessions.py 三分、exec_bridge ②③（merge/recover）** | 门禁全绿 |
| M3 链3① | extraction + split + probe 迁 CallTurn（脚手架 + Retry + 兜底，D7-①）；**拆分：req_agent 工具实现 → tools/impl + tools/exec（前置结构行）、requirements/harness.py、llm.py 收窄** | T1/T2 三痛点成功率提升（实效面 2） |
| M4 链3②③ + R3.2/R3.3 | clarify / collect / 轻任务 → roles 六工种 + design（CallCatalog 统一表）+ 图门禁 + JSON 报告；**拆分：exec_bridge ①（dispatch）+ REST 门面、req_agent 门面删除** | 门禁 + 实效双验收；黄金路径 T1/T2 走通——**功能面已落地（2026-09-19）：R3.2 图门禁（计划步骤豁免）/ R3.3 双轨报告 / clarify·collect·轻任务·六工种·design 迁 CallTurn + CallCatalog（配置域按 mixed-fleet 裁决分列，目录入口统一）；llm_sync 白名单 10→7（余：探测套件 §5.7 范围外、reflection 通用机制、chat 循环、sem/engine M 级提取 tAgent SE 域）；拆分余量（dispatch 迁出/门面溶解）随实效验收后执行** |
| M5 stretch | R2.5 同挡个体差异（intra_tier_note：弱分密度升档/T2 强分并步，开关 r2_5_intra_tier）；R3.4 对话面接线（tool_surface/kb 工具面裁剪 + ctx_budget 系数，开关 r3_4_dialogue_wiring；分目的 U 轴模板挂 ElementHintProvider 待意图轨道）；探测-策略闭环（comp_gap 遥测只记不升挡） | **已落地（2026-09-19）** |

## 10. 需求规格 §6 开放点处置汇总

| # | 开放点 | 处置 |
|---|---|---|
| ① | 载体取舍 | 8 → 5（§3.1） |
| ② | purpose 词表 | D10 冻结四组 19 项（§2.2） |
| ③ | 分目的脚手架内容 | ScaffoldProvider 模板，M3/M4 落地；实效以 probe_suite 用例形态验证（§3.3/§9） |
| ④ | R2.1 quick 豁免 | 豁免——quick 保持零补偿纯净直通（§2.1） |
| ⑤ | R2.5 挡内刻度 | stretch M5；阈值与 C 轴双轨判据统一口径后定（§9） |
| ⑥ | R3.3 JSON 契约 | schema 草案 + 三级解析优先级（§3.4） |
| ⑦ | 门禁落点 | pytest 自检脚本，进 test:py（§7） |
| ⑧ | 回退开关 | 全局 config 键 `agent.comp.overrides.<id>`（§6） |
| ⑨ | roles/light_tasks 合并 | CallCatalog 统一注册表 + 别名迁移（§4.1） |
| ⑩ | 探测-策略闭环 | M5 仅记差距遥测，不动态升挡（§9） |

## 11. 实施约束（重申 D3/D4）

- 收编等价 + 白名单行为变更（§6 六项开关可回退）；
- **收编即拆分（§8.1）**：原文件同步薄化/溶解，禁止"收编后原文件原样保留"；结构性拆分独立提交，可独立回退；
- runner / 执行器侧契约零变更（CONV-04）；链 2 输出契约变更全部在 architect 侧解析层兼容落地；
- 测试先行：收编前固化基线（§7-1）。

## 12. 与其他轨道的关系

| 轨道 | 关系 |
|---|---|
| 意图识别工具化（perception 演进） | 正交；CallTurn 就绪后 `req.extract` 类意图可直接映射为 call 调用点，列 M5 后轨道 |
| MCP 工具面 | 42 工具注册表是本内核工具源；MCP 暴露独立推进（D9），不阻塞任何阶段 |
| KB chat 内核收敛 | 复用本设计 L1/L2 抽象，独立立项 |
| CONV-04 解冻 | reasoning_effort C 轴接线、执行器个体参数为首批候选 |

## 13. 维护约定

- 本文为整体设计稿；实施中的接口变更回写本文对应章节，行为变更须同步需求规格 §0 白名单决策（append-only）；
- §3.3 / §5.1 收编映射表与代码强耦合，对应阶段合入后回写校验（对齐 agent-session-flow.md 维护约定）；
- 决策记录新增追加行，不修改既有行。

---

## 14. 审计与处置记录（2026-09-19）

### 14.1 已处置项

| 审计项 | 处置 |
|---|---|
| A1 图门禁误伤 `/执行` 直通 | `commands.py` 单卡路径 `gate_diagram=False`（无 LLM 在环不可回炉）；门禁仅适用于 chat `task.propose` 路径；回归测试 `test_audit_fixes.py` ×2 |
| A2 门禁再生纪律 | 再生脚本入库 `tests/goldens/regen_baselines.py`（默认 dry-run diff 预览，`--confirm` 落盘；显式豁免文件不入基线）；挡位字面量清理 8 文件出白名单（刻度常量单源 `gears.DEFAULT_TIER_ID/WEAKEST_TIER/RETRY_NUDGES`）；`dispatch.py` 显式 `NEW_FILE_WHITELIST` 登记（替换追溯豁免） |
| A3 纸面管线 | 函数库形态声明（§0 注）；`IntraTierProvider` 空壳删除；JSON 报告提示单源 `output.JSON_REPORT_HINT`（milestone/dispatch 同源）；StructuredOutput/LogicDiagramGate 的 assemble 重复文案删除 |
| B1 工具面执法边界 | `prompt._filter_tools` 显式标注"提示级"；硬执法列 §12 后续轨道 |
| B5/B6 | session_guide 别名清理（规范名单源导入） |

### 14.2 已知残留（验收时定夺）

- **B3 测试基线侵蚀**：全程修改既有测试约 10 处——机械适配（桩签名 `+policy/+tier`、patch 目标迁移 `turns.base`、`gate_diagram=False`）与覆盖变化（gears confirm 测试绕过图门禁，由 `test_audit_fixes` 补 chat 路径覆盖）混合；台账即本节。
- **B4 golden 两度再生**：等价基线含 R3.3 白名单文案变更，未分离存档；后续 golden 变更经 regen 脚本 diff 显式化。
- **B2 D12 未收口**：`llm_sync` 白名单 7 项（探测套件 §5.7 范围外 / reflection 通用机制 / chat 循环 / sem M 级 tAgent SE 域）——按规格"链 3 全量收编后仅 turns/call"未实现为硬门禁，现为带理由冻结。
- **req_agent 门面（§8.2-④）**：工具实现部分已溶解；余量 1207 行为 A 轴 chat 管线 + mcp/规约工具 + re-export 的**永久驻留**形态，建议验收时确认此结论并更新 §8.2。
- **C 项低危**：`llm.py` 317 行（目标 ≤300 边际未收）；harness `degraded` 未透出 REST；R3.2 拒绝文案前端卡片化呈现未验证；`_eb()` 间接 30+ 处（DispatchTurn 重构时收敛）。

### 14.3 卡片默认保存(2026-09-20 产品裁决落地)

| 决策 | 结论 |
|---|---|
| 任务卡 | `propose_task` 创建即 `saved`(默认保存, 可多张并存, 不阻塞互斥/转达); 执行=手动触发(卡片「开始执行」/`/执行`/REST confirm, `confirm_task` 接受 saved\|pending_confirm) |
| 对话更新 | 同需求重复 `task.propose` → **改写**最近一张 saved 卡(v2 修订卡追加, 不产生重复卡——较 cv-174 去重更上游) |
| 主动忽略 | REST `POST /tasks/{id}/ignore`(仅 saved, 409 otherwise)/`POST /requirements/{id}/ignore`; 软删终态 `ignored`(置灰可追溯), 卡片词汇表 +`task_ignored`/`req_ignored` |
| 保留门禁 | 合并确认 / 里程碑 NEED_INPUT / 运行互斥 / R3.2 图门禁(propose 校验不变) |
| 存量 | pending_confirm 行原状(确认/取消按钮照旧); 新卡不再产生该状态 |
| 语义排除 | saved 不入 `ACTIVE_STATES`: 不吸收转达、不算执行中、`active_task_of` 不返回; `task_input` 对 saved 明确指引先启动 |
| 前端 | TaskCard: saved=[开始执行|忽略]、ignored=置灰终态; `taskAction` 动作面 +`ignore` |
| 需求忽略 UI | REST 就绪; 台账面板按钮列后续批次(当前无需求卡独立组件) |
