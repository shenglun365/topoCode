# 模型能力分级补偿策略 — 现状对齐与迭代需求（v1 草案）

> 状态：**需求细化中**（待逐项评审完善后进入整体设计）
> 日期：2026-09-19
> 性质：现状事实对齐 + 迭代需求规格；**不含实现方案**
> 范围：architect agent（需求分析 / 架构分析设计 / 组件模块设计职能）对不同能力级别模型的调度与策略补偿
> 关联文档：[agent-harness-evaluation-2609.md](agent-harness-evaluation-2609.md)（orchestration-plan 已于 2026-09-22 清理, 残余转移 tech-debt-ledger）· [../product-iteration-roadmap-2026-09.md](../product-iteration-roadmap-2026-09.md)（L 组四级成本梯度）· [../conventions/CONV-04-API契约与验证门禁.md](../conventions/CONV-04-API契约与验证门禁.md)

---

## 0. 已拍板决策记录

| # | 决策项 | 结论 |
|---|---|---|
| D1 | 迭代首要目标排序 | **架构可扩展性（P0）→ 缺口清单收敛（P1）→ 弱模型可用性策略增量（P2）**；抽象先行，策略增量踩在抽象上落地 |
| D2 | 「单项指令分析」口径 | **全部单次专用 LLM 调用**（直通指令分析 / 需求 harness / 规划探针 / 轻任务工种，11+ 调用点）统一纳入补偿 |
| D3 | 行为兼容性 | **收编等价 + 策略变更白名单**：重构/收编要求行为等价（测试基线回归）；仅白名单项允许行为变化 |
| D4 | runner/执行器侧契约 | **本次冻结（CONV-04）**；logic_diagram / structured_output 仅在 architect 侧（指令组装与解析层）落地，兼容降级 |
| D5 | 验收标准 | **实效 + 门禁双验收**（见 §3） |
| D6 | R2.5 / R3.4 | 降为 **stretch**（P0/P1 完成后视进度决定），不影响主目标验收 |
| D7 | R3.1 迁移顺序 | 三批：① `/提取需求` + split_tasks + probe_scope（弱挡痛点）→ ② clarify/collect + 轻任务 → ③ roles 工种 + design |
| D8 | 内核形态 | **不整体采用 cline SDK**：sidecar 保持为 C 轴执行器之一（stdio 契约冻结），SDK 类型不出适配层 |
| D9 | 架构主线 | architect agent 内核**自研收敛**为「策略 L0 — 补偿 L1 — 回合 L2」三形态引擎；工具面 MCP 化为独立轨道，不阻塞本设计 |
| D10 | purpose 词表 | **四组 19 项冻结**（分析 3 / 单项 5 / 轻量 5 / 工种 6，含探测维映射） |
| D11 | reasoning_effort 归属改判 | **迁出 GearPolicy**：推理强度 = 模型能力属性（探测支持位）+ **用户自选**参数，不随挡位；A/S 轴经模型配置生效，C 轴随 CONV-04 解冻 |
| D12 | 链 3 收编门禁 | 链 3 全量收编后，`llm_sync` 仅允许被回合引擎 call 形态调用（grep 门禁强制） |

---

## 1. 体系骨架（现状事实）

- **挡位刻度**：T0（≥12B 强）/ T1（6-12B 中）/ T2（<6B 弱）；2026-09-17 由五档收敛为三档，旧值读路径归一（`agent/governance/gears.py:115`）。
- **解析链** `resolve_gear`（`gears.py:173`）：会话 `analysisMode` →
  `quick` 钉死 T0 ｜ `strict` ≡ `auto` ｜ `auto` → 实测 `tierProbed` > 人工 `capability` > 默认 T1 ｜ 显式 T0-T2 钉死。
- **三轴**：会话挡位 × **C 轴**执行器模型（`executorConfig`）× **A 轴** architect 对话模型（`agent/cognition/model_profile.py` `tier_of`）。
- **M1 实测封顶**：探针 `probeFlags.followGate` 未过 / `probeDetail` 含标记 → `apply_cap` 降档 T2，`cap_note` 随任务指令告知（仅 auto 链生效；人工显式 capability 不封顶——人的意志优先）。
- **GearPolicy = 数据驱动策略行**（frozen dataclass，`gears.py:33`）：挡位即一行策略参数，解析一次逐层传递，设计禁令「tier 字面量不得散落」。
- **M3 预留**：`MODEL_GRADIENTS = ("L","S","M","H")` 四级成本梯度常量已定义（`gears.py:30`），未接线（roadmap L 组）。

## 2. 双探测轨（分级数据基座，互不相通）

| | 对话模型（A 轴） | 执行器（C 轴） |
|---|---|---|
| 位置 | `agent/cognition/model_profile.py` | `agent/execution/probes.py` + `arch_routes/agent_executors.py` REST |
| 方式 | 轻量文本探针 ~16 次小调用（工具协议×3 / JSON 围栏×4 / 指令边界×3 / 需求·架构·模块三维各×2 / 稳定性方差推导），加权 0.35/0.2/0.15/… | 真实 worktree + pytest 探针作业（单函数→模块→类递进）；得分 = pass × 迭代效率 × 边界遵守 |
| 并发治理 | `_ProbeGate` 全局互斥 + FIFO + 同模型滤重；WS 首轮懒探测（后台不阻塞） | 注册表级守卫（内存态） |
| 特有产出 | **补偿实效复核**（T2 生产同款补偿形态用例实测 → admission: pass/weak/insufficient）、**structured 支持位**（json_rate 达标）、分目的能力分（requirementScore/archScore/moduleScore）、逐用例留痕 160 字 | `tierProbed/probeScore/probeDetail` 写回注册表 config |
| 判分原则 | 差分**只降不升**（探测好也不越过启发式基档兜底） | — |

## 3. 三条补偿链现状（对齐事实）

### 3.1 链 1：用户 + KB → architect（对话回合，A 轴）

**已有机制**：

| 机制 | 位置 | 生效条件 |
|---|---|---|
| U 轴要素框架（五要素澄清 + 预填默认值 + 禁开放式泛问；HIGH/MID 两档文案） | `gears.py:225` + `orchestrator.py:515` | A 轴 tier≥1，**仅 auto 链** |
| architect_note 按挡编排指引（每挡一段系统消息） | `gears.py:75-107` → `orchestrator.py:511` | 每回合 |
| prompt 预算裁剪（tier→26k/22k/16k 字符；条件块 ir→diagram→mcp→skill 按 priority 淘汰；header/boundary/capability 恒置） | `agent/cognition/prompt.py:31,154` | 每回合按 tier |
| scope_probe 三源 grounding（git 文件树 + 历史需求边界先验 + KB 资产命中 → 带来源引用建议） | `agent/planning/scope_probe.py` | confirm 时边界为空；失败→无互斥保护继续 |
| dossier 前置上下文（摘要/备案/高优单元/需求三段/规约，24k 预算逐段截断） | `agent/memory/dossier.py` | 上下文包；不按挡缩放 |
| 模型健康提示（空返回 + probeScore<0.5 → 建议用户换模型） | `orchestrator.py:159` | 事后兜底 |

**缺口**：
- `ctx_budget` / `tool_surface` / `kb:bool` 未消费——KB 工具面**不按挡裁剪**，T0「不做检索」仅靠 architect_note 文字自觉；
- 分目的能力分（requirement/arch/module Score）已入档案 caps，**仅展示不参与策略**；
- prompt 预算裁剪顺序固定，不分目的。

### 3.2 链 2：architect → coding agent（任务下发，C 轴）

**已有机制**：

| 机制 | 位置 |
|---|---|
| pre_split 任务粒度预拆（T1 plan 级 / T2 steps 级显式文件路径+步骤序列） | `agent/planning/task_plan.py:379` |
| depends_source（T2 强制 linear；LLM 产边过 `validate_graph` 确定性校验，失败降级线性链） | `task_plan.py:424-428` |
| 确定性指令段（工作环境 / 运行时身份防误验 / DoD / 空指令三连防护：designMd 缺→需求正文兜底→规约空→强制 NEED_INPUT） | `task_plan.py:145-260` |
| 里程碑协议（15 次工具调用阈值 / 计划确认 / 固定三行报告 / `[[NEED_INPUT]]`；报告文本解析→边界回写闭环） | `task_plan` + `exec_bridge.py:1242` |
| max_iterations 按挡下发（2000/800/300 随 executorConfig） | `exec_bridge.py:497` |
| cap_note 🛡️ 实测封顶告知 subagent | `gears` → `task_plan.py:146` |
| 边界互斥 + 范围探针补全 + 预期新建声明（声明级互斥，越界靠验收事后检测） | `governance/boundary.py` + `scope_probe` + `exec_bridge.py:438-470` |
| verifyConfig 验收门禁透传（评估器机械段不依赖 LLM） | `exec_bridge` + `reflection/evaluator` |
| 执行器类型能力裁剪（multi_turn/approval/checkpoint/readonly_hard/steer） | `agent/execution/capabilities.py` |

**缺口**：
- `logic_diagram="uml"`（T2 任务指令须附核心逻辑图）**无确定性落地**——仅 T2 architect_note 文字要求；编排层不校验图产出、不注入执行器指令；
- `structured_output`（报告走工具契约）未消费——里程碑报告仍正则解析文本固定行；
- `prompt_style` / `cadence` / `schedule_discipline` / `reasoning_effort` 声明未消费；
- 执行器个体 probeScore 只参与定挡（tierProbed），**同挡内无差异化**。

### 3.3 链 3：单项指令分析（单次专用 LLM 调用）——现状最薄弱

口径（D2）：全部单次专用调用。4 类调用点分级适配现状：

| 类别 | 调用点 | 模型路由 | 提示按档补偿 | 失败处理 |
|---|---|---|---|---|
| 直通指令 | `/提取需求`（`perception/commands.py:81`，structured 提取规约六字段） | 跟随会话模型 | ❌ 固定提示 | **一次性失败**（`cognition/llm.py:244` structured 失败只记日志；nudge 重试仅存在于 chat 循环与 `run_tools_loop`） |
| | `/执行` `/定稿` `/确认` | 零 LLM 确定性 | —（不需要） | ✅ |
| 需求 harness | `req_harness_clarify`（3-5 澄清问）/ `req_harness_collect`（structured RequirementAnalysis 八字段）；REST 入口 `arch_routes/requirements.py:296,339` | 透传会话所选 model_id | ❌ 固定提示（`req_agent.py:1775` 起） | clarify 解析失败→502 明确报错；collect 失败→None 降级 |
| 规划探针 | `split_tasks_llm`（**恰在 T1/T2 弱挡必跑**）/ `probe_scope` | ❌ | ❌ 为强模型设计的固定提示 | split 失败→回落单卡；probe 失败→无互斥保护 |
| 轻任务/工种 | light_tasks（summary/probe/distill）、roles 六工种（extract/verify/induce/pseudo/evaluate/mine；消费点 `acceptance.py:375`、`naming.py:129` 等）、`design.py` 概要设计、tAgent SE/UT（`tagent_se/utgen`，走 tAgent 内核 TextFallback 协议） | ✅ per-call model_id 路由（roles / light_tasks 架构良好） | ❌ **零 tier 感知**（tagent_*/naming/design 全仓无 tier/model_profile 引用） | 无按档重试/兜底；role note「快模型即可/强模型——严 profile」纯人工约定 |

**唯一协议级分级**：M4-A `structured_model_enabled`（探针达标→约束解码；失败显式 nudge 1 次降级文本协议）——只覆盖协议选择，**提示内容不分档**。探测套件已证明弱模型短板恰在「指令边界跟随 / 结构化输出」，而单项调用正是这两个维度的高发区。

## 4. 跨链结构性缺口

1. **GearPolicy 8 个字段声明未消费**：`tool_surface` / `ctx_budget` / `prompt_style` / `structured_output` / `reasoning_effort` / `cadence` / `schedule_discipline` / `logic_diagram`——策略表与实现已漂移，无「字段必须有消费者」的 CI 门禁。
2. **A 轴短路**：`resolve_gear` 中 quick / 显式挡直接 return（`gears.py:185-188`），A 轴补偿与探针封顶全部跳过。
3. **目的维度缺失**：探测已按目的打分（需求/架构/模块三维），但对话策略、任务策略、单项调用提示均不分目的。
4. **补偿手段无统一抽象**：散布 7+ 处（gears 文案 / prompt 块 / task_plan 组装 / scope_probe / dossier / probe 用例 / 单项调用内联提示）；链 3 完全在体系外。
5. **刻度漂移残留**：`model_profile.py` docstring 仍写 t0-t4 五档；`DEFAULT_BUDGET`、`set_manual_tier` clamp 残留 0-4 刻度（实际三档）。

---

## 5. 迭代需求规格（v1）

### 5.0 目标排序（D1）

**P0 架构可扩展性 → P1 缺口清单收敛 → P2 弱模型可用性策略增量**。

### 5.1 R1 统一补偿抽象（P0，主目标）

| # | 需求 | 验收要点 |
|---|---|---|
| R1.1 | 补偿 Provider 管线：三条管线（chat 回合 / task 下发 / **call 单项调用**），类型化载体（SystemNote / InstructionSection / ToolFilter / BudgetParam / OutputContract / ArtifactGate / PromptScaffold / RetryPolicy） | 既有文案型补偿（architect_note、agent_note、ELEMENT_HINT、cap_note）全部收编为内置 Provider，**行为等价**（现有测试回归通过） |
| R1.2 | GearPolicy 8 个未消费字段全部处置：**每个字段 ≥1 个注册消费者，或显式删除**（不留僵尸声明） | 字段消费清单测试全绿；处置结论逐字段记录（接线 / 删除 / 转常量） |
| R1.3 | 防漂移门禁：① 策略字段消费门禁测试；② 链 3 迁移完成后业务模块禁裸调 `llm_sync` 的 grep 门禁 | 门禁进 `npm run test:py`（architect 测试目录），CI 可红 |
| R1.4 | `resolve_gear` 保持单源；Provider 解析只消费 GearPolicy/CompensationCtx，不出现新挡位字面量 | grep 门禁：`T0/T1/T2` 字面量不出新散落点 |

> 注：Provider/载体命名与切分属整体设计阶段产出，本规格仅约束**能力要求**（三条管线、类型化载体、收编等价），不锁定具体接口形态。

### 5.2 R2 缺口清单收敛（P1）

| # | 缺口 | 处置 | 白名单 |
|---|---|---|---|
| R2.1 | A 轴短路：显式挡跳过 A 轴补偿+封顶 | 显式挡决定基线策略行，A 轴补偿叠加生效 | ✅ 行为变更 |
| R2.2 | 刻度漂移（docstring 五档 / `DEFAULT_BUDGET` 0-4 / `set_manual_tier` clamp 0-4） | 清理对齐三档 | 行为等价 |
| R2.3 | probe_scope 失败=「无互斥保护」继续 | 降级为文件树启发式前缀兜底（git 树+历史边界，零 LLM）+ 卡片明示降级来源 | ✅ 行为变更（更安全方向） |
| R2.4 | 分目的能力分仅展示 | 入 CompensationCtx：a_tier 按 purpose 细化有效档 | 行为等价（弱档才触发） |
| R2.5 | 执行器同挡无个体差异（probeScore 只进挡位） | probeScore → 同挡内指令密度/粒度微调 | ✅ 行为变更（仅 T1/T2）；**stretch（D6）** |

### 5.3 R3 弱模型可用性策略增量（P2，踩在 R1 抽象上）

| # | 需求 | 说明 |
|---|---|---|
| R3.1 | **链 3 全量迁移统一入口**（D2/D7）：第一批 `/提取需求` + `split_tasks_llm` + `probe_scope` → 第二批 clarify/collect + 轻任务（summary/probe/distill）→ 第三批 roles 六工种 + design | 按 `(purpose, tier)` 注入补偿脚手架（弱档：字段逐项定义 / 编号步骤 / 输出示例 / 禁编造声明）；RetryPolicy 按档（T0 失败 1 次即报 / T1 nudge 1 / T2 nudge 2 + 确定性兜底）；`llm_dataset` 遥测带 tier+purpose |
| R3.2 | logic_diagram 落地（**architect 侧**，D4）：T2 任务指令要求附核心逻辑图 + ArtifactGate 确定性校验（图围栏存在、边≥3），缺失→回炉 nudge architect 补图后再下发 | 不动 runner 契约 |
| R3.3 | structured_output 落地（**architect 侧解析层**，D4）：里程碑报告/完成摘要优先 JSON 块契约，文本固定行保留为兼容降级解析 | 不动 runner 契约 |
| R3.4 | 对话面策略消费接线：分目的 U 轴模板（需求五要素 / 架构影响链三问 / 模块契约骨架）、KbGroundingFirst（kb 字段实消费）、ctx_budget（dossier/工具结果预算系数）、tool_surface（MCP 写/KB 写按挡裁剪） | 载体复用 R1 管线；**stretch（D6）** |

### 5.4 分目的策略矩阵（目标态意向，细节待整体设计）

**A 链（目的 × 挡位，对话面）**：

| 目的 | T0 直通车 | T1 标准兜底 | T2 全面补偿 |
|---|---|---|---|
| 需求分析 | 直出任务卡不产卡 | req.propose + KB 校准 | 五要素框架 + 每要素预填默认值 + grounding-first |
| 架构设计 | 自由 | kb.graph 影响链必查 | map.graph 图先行 + 组件档案强制引用 + 影响链三问 |
| 模块设计 | 直出 | 规约模板 | 步骤序列脚手架 + 契约字段骨架 |

**链 3 单项调用脚手架（意向示例）**：

| purpose | T2 补偿脚手架 | 确定性兜底 |
|---|---|---|
| extraction（/提取需求） | 六字段逐项定义 + 对话无据留空禁编造 + 字段示例 | 解析失败→回落澄清问询而非直接失败 |
| clarify | 问题模板槽位（目标/边界/验收缺失各 1 问保底） | None→静态三问模板 |
| collect | 八字段逐项 + scope 只能来自命中清单 | nudge 重试后维持 502 |
| split | 步骤模板「每步=文件+动作+验证」+ 禁跨模块 | 单卡（现状） |
| probe | 逐文件带 source 标注示例 | 文件树启发式前缀兜底（R2.3） |
| 轻任务/工种 | T2 档最小化提示（prompt_style=minimal） | 不变 |

### 5.5 约束（D3/D4）

- **行为兼容**：收编等价 + 策略变更白名单（仅 R2.1 / R2.3 / R2.5 / R3.2 / R3.3 / R3.4 允许行为变化，逐项开关或挡位门控，可回退）。
- **runner/执行器侧契约冻结（CONV-04）**：链 2 输出契约变更全部先在 architect 侧解析层兼容落地。
- **测试先行**：收编前固化关键路径基线测试（gear 解析 / 任务指令组装 / 单项调用入口；基于 architect 现有 28 个测试文件标杆）。

### 5.6 双验收标准（D5）

- **门禁面**：R1.2 / R1.3 / R1.4 门禁测试全绿；收编部分行为等价回归通过；`npm run type-check` + `test:py`（architect）+ `test:fe` 全绿。
- **实效面**：
  1. 探测套件 / 补偿复核分数不回退；
  2. `/提取需求`、split、probe 三痛点在 T1/T2 档成功率提升（弱模型环境脚本/手动验证）；
  3. T1/T2 档黄金路径（需求→卡→执行→验收）可走通。

### 5.7 明确不做（本次范围外）

runner 侧契约变更 ｜ M3 异档分船（L/S/M/H）落地（仅保留常量与扩展位）｜ 探测套件重构 ｜ 多人协同 / G 提升 ｜ architect 前端大改（仅挡位/探测状态展示按需微调）

---

## 6. 待细化清单（评审时逐项考虑）

> 以下为进入整体设计前需要逐项拍板的开放点，评审时可增删。
>
> **2026-09-19 更新**：以下十项已随整体设计逐项处置，结论见 [agent-capability-design-2609.md](agent-capability-design-2609.md) §10。

- [ ] **载体类型取舍**：8 类载体是否合并精简（如 PromptScaffold 并入 OutputContract？ToolFilter 与 BudgetParam 是否同属「执行参数」载体）。
- [ ] **purpose 词表冻结**：需求分析/架构设计/模块设计/执行/各单项 purpose 的枚举与探测三维分数的映射关系。
- [ ] **分目的脚手架内容**：§5.4 矩阵仅意向示例，各目的弱档脚手架的具体文案与判分（是否复用 probe_suite 用例形态验证实效）。
- [ ] **R2.1 A 轴叠加语义**：显式挡叠加 A 轴后，`quick`（T0 直通车）是否豁免（保持零补偿纯净直通）。
- [ ] **R2.5 个体差异的挡内刻度**：probeScore 分档阈值与指令密度映射；与 C 轴探测双轨判据是否需要统一口径。
- [ ] **R3.3 JSON 块契约格式**：里程碑/完成摘要 JSON schema（changed_files/verify/next 等）与文本固定行双轨解析优先级。
- [ ] **门禁落点**：字段消费清单测试与 llm_sync 裸调 grep 门禁放 `apps/architect/tests/` 的具体形态（pytest 自检脚本 or 纯断言）。
- [ ] **回退开关设计**：白名单行为变更项的开关粒度（会话级挡位门控 / 全局 config 键）。
- [ ] **roles 工种与 light_tasks 是否合并路由**：两者同为 per-call model_id 路由，是否统一为一个工种注册表（涉及词汇表迁移）。
- [ ] **探测-策略闭环**：分目的分数弱（如 archScore 低）时是否允许动态升挡补偿（跨目的借用更强的脚手架），还是严格按定档执行。

---

## 7. 维护约定

- 本文档为**需求规格**，整体设计（接口/模块切分/文件级改动）另立设计文档，落点建议 `docs/architect/`。
- 现状事实部分（§1-§4）与代码强耦合，代码合入后须回写校验（对齐 agent-session-flow.md 的维护约定）。
- 决策记录（§0）新增决策追加行，不修改既有行（append-only）。
