# Architect Agent 通用架构对照评审 + 反思闭环演进方案

> 日期：2026-09-21 · 性质：架构评审与演进方案（纯分析 + 方案，未改代码）
> 背景：以「通用 agent 架构」（交互感知 → 认知控制核心 → 记忆/工具/协作 → 执行器 → 反思学习 → 更新记忆/策略/计划）为参照系，评审 `apps/architect/topoone_app_architect/agent/` 现状。
> 行号口径：2026-09-21 快照。

> **⚡ 裁决回执（2026-09-21，后续以 `agent-arch-gap-adoption-2609.md` 为准）**
> 本文档 9 处代码主张已全部事实核查属实。演进方案裁决：
> - **采纳**：#1 修复经验回填（P0）、#2 dataset 消费口+吞错计数（P0，吞错计数为本回执补充）、#4 溢出摘要+缓存（P0；**MemoryStore 改为退役删除**，dossier 进主链缓议）
> - **有条件采纳**：#3 仅"建议值+人审"（tierSuggested 永不自动写，D6 防线）、#5 先误路由遥测后受限 LLM 兜底（**LLM 意图不入硬闸**，cv-152 防线）
> - **缓议**：#6 评估域扩展（P2）
> - **明确不做**：缺陷7 知识图谱层（接口位保留）、缺陷4 A2A 自动移交（人工移交是产品方向本身，非缺陷）、状态迁移(derive)配置化（架构红线）、挡位刻度表进配置（本批）、全局 except:pass 清洗（仅点名路径做吞错计数）
> - 实施形态：状态/规则/策略数据驱动（`agent.flow.policy` 配置面），代码只留执行引擎与冻结缺省——完整方案与不做清单见 `agent-arch-gap-adoption-2609.md` §二/§三。

---

## 一、分层对照：结构完整度

| 通用架构层 | architect 实现 | 评价 |
|---|---|---|
| 交互与感知 | `agent/perception/`（gate/router/intent/commands） | 有，意图路由单薄（缺陷3） |
| 认知与控制核心 | `agent/orchestrator.py` 五段管线（gate→route→context→execute→land）+ `cognition/`（llm/roles/prompt/model_profile/probe_suite） | 有 |
| 记忆系统 | `agent/memory/`（working/store/units/dossier/distill/glossary） | 有，装配链有断点（缺陷2） |
| 工具/行动 | `agent/tools/`（protocol/registry）+ `execution/` | 有 |
| 协作通信 | `collab/`（cards/sse）+ exec_bridge（transfer→coding subagent）+ kb_gateway（MCP client） | 有，移交靠人工（缺陷5） |
| 执行器/环境 | `execution/`（dispatch/pumps/recover/runner_client） | 有 |
| 反思/学习 | `reflection/`（evaluator/repair/mining/dataset） | 部分，闭环断裂（缺陷1） |
| 状态管理 | sessions/ + SQLite store + 泵恢复（cv-153）+ contextvar 请求级上下文 | 扎实 |

额外还有通用图没有的 `governance/`（挡位/边界/超时）与 `compensation/`（文案/提示补偿管线），为加分项。

---

## 二、实质性设计缺陷（按架构图关键链路排序）

### 缺陷1：反思→记忆/策略的闭环断裂（对应架构图「反思→更新记忆/策略/计划」箭头）

- 模型能力探测差距只记遥测、明确"不动态升挡"（D6 裁决，`agent/turns/context.py:26-43`），`comp_gap` 事件无消费者。
- `llm_dataset`（`agent/reflection/dataset.py`）**只写不读**——唯一消费口是 `/llm-dataset/stats` 观测端点，无经验回放。
- `agent/reflection/repair.py:125` 隔离修复循环的成功/失败经验落 dataset 即止，**不回填工作记忆**——同会话内同类工具调用错误会原样重复。
- 能力提炼（mining）为 6h 周期批 + 24h 静默 + 人工采纳（`agent/reflection/mining.py:475`），会话内完全无在线学习。

### 缺陷2：工作记忆 = 定长截断，无溢出压缩

- `agent/memory/working.py:11` 仅取尾部 20 条历史；`summarize_conversation` 能力存在但 **chat 回合装配未接入**，30+ 轮前的关键约束静默丢失。
- `dossier`（前置上下文装配）只被 REST `arch_routes/sessions.py:967` 消费，主对话链 `agent/turns/context.py:118-127` 不用。
- `agent/memory/store.py` 的 `MemoryStore` 门面**零调用方**——统一记忆读面悬空，orchestrator 实际仍各自拼 store 查询。

### 缺陷3：感知层意图路由脆弱

- `agent/perception/intent.py` 纯正则匹配（`GENERIC_EXEC_RE`），注释声明的"LLM 分级兜底(P5)"未实现；`DEFLECT_RE` 是对路由误判的补丁性正则——表达变体即误路由。

### 缺陷4：跨 Agent 上下文移交依赖人工

> 裁决标记（2026-09-21）：**不做**——"用户选史 digest + 双收件人"的人工移交是产品方向本身（人在环路），非缺陷；A2A 自动化/共享记忆违背该方向，无重开条件（除非产品方向变更）。

- transfer 时 digest 由"用户选史生成"（`agent/orchestrator.py:289`），agent 间无结构化 A2A 协议、无共享记忆（MemoryStore 是 per-conversation 门面）。

### 缺陷5：评估域过窄

- `agent/reflection/evaluator.py` 只做 plan×diff 代码变更足迹/偏差；对话质量、需求澄清质量、分析结论质量均无评估器——反思层"评估"只覆盖执行域。

### 缺陷6：系统性 `except Exception: pass`

- 感知/治理/反思装配路径大量静默吞错（`agent/turns/context.py:21,42,61` 等）。业务不阻塞是对的，但**观测器自身不可观测**——反思层会在故障时静默失效，与反思层职责自相矛盾。

### 缺陷7：知识图谱层是近似品

> 裁决标记（2026-09-21）：**不做**（接口位保留）——KB 通用知识层是产品级决策非 architect 层职责；`mining.py::promote_to_kb` 已锚定 `global-promotion-design.md §6`，待该设计立项时接通。

- semantic_assets + semantic_graph 是"项目资产锚点图"，无多跳推理；KB 通用知识层为接口位 `not_implemented`（`agent/reflection/mining.py:591-598`）。

---

## 三、需区分：有意裁剪 ≠ 缺陷

以下"缺失"有明确裁决记录，属主动安全取舍（用"人在环路"换本地小模型下的可控性），不宜直接判为设计错误，但代价是闭环周期从"回合级"退化为"小时/天级"：

| 裁决 | 内容 | 影响 |
|---|---|---|
| D6 | 探测-策略闭环只记遥测、不动态升挡（`turns/context.py:27`） | 策略静态化 |
| cv-175 | 参数/守卫自动修复外循环拆除——错误明确返回，不静默纠偏（`reflection/repair.py` 文档） | 自动纠偏仅限机械域 |
| mining 人审 | 能力提案必经设计者采纳（`mining.py:188`） | 学习周期 ≈ 天级 |

---

## 四、讨论结论：纠错子循环算不算反思能力？

**结论：算，但只是反思能力的一个子集（"纠错"象限），且架构上已归位在 `agent/reflection/`——问题不是"要不要合并"，而是离完整反思差三块。**

### 4.1 为什么算：符合反思的最小闭环

以 `agent/reflection/repair_tasks.py` 的 tool_call 修复为例：

| 反思动作 | 代码对应 |
|---|---|
| 感知失败 | 工具返回错误（`_REPAIRABLE_ERR` 命中 / 解析失败） |
| 评估 | `run_repair_loop` 解析校验产物（`repair.py:144`） |
| 归因 | 原调用+错误信息+合法工具清单喂给修复器（`repair_tasks.py:71-72`） |
| 纠错 | 隔离 LLM 调用产出修正调用 |
| 观测 | `llm_dataset.record` 落事件 |

反思层五件事「评估、归因、纠错、经验回放、优化」，它覆盖**纠错**这一件。

### 4.2 与完整反思的三个差距

1. **触发是机械的，不是自我评判。** 文献里的 reflection（Reflexion/Self-Refine）是模型批判自己产出质量后改进；architect 的触发是确定性 guard（错误正则、JSON 解析失败），更接近 **guarded recovery（守卫式恢复）**。范围刻意收窄到机械性错误（工具名/参数形状，cv-175）。
2. **修复经验不沉淀。** 每次修复成功只落 dataset（只写不读），不回填工作记忆——下回合模型对"上次怎么修好的"零记忆。闭环最后一步「更新记忆/策略」是断的，所以是**一次性的纠错**，不是**可累积的反思**。
3. **有界单次。** 每调用限 1 次修复，失败如实上抛——是预算化重试，不是"评估→再规划→迭代"的反思循环。

### 4.3 易混淆点：前馈 ≠ 反馈

- `probe_suite`（能力探测）→ `gears`（挡位降档）→ `compensation`（cap_note 降档告知）是**前馈式元认知**：事先测量能力、预先补偿 prompt。反思是**反馈式**：失败之后回头评估归因。两者互补（两样都有是优点），但把"预防"记成"反思"会高估闭环成熟度。
- "architect 外循环（编排者）"是任务分解与委托，也不属于反思。

**称谓建议**：文档口径写"反思层的纠错子循环（机械域、有界、隔离）"，避免误读为完整 self-reflection。

---

## 五、演进方案：从"纠错子集"到"反思闭环本体"

不动五段管线结构，全部有现成挂点：

| # | 改造 | 挂点 | 消除 | 裁决(2026-09-21) |
|---|---|---|---|---|
| 1 | **修复经验回填工作记忆**：修复成功/失败后写一条上下文单元（"刚修过 X，下次注意 Y"），下回合装配时注入 | `reflection/repair.py` `run_repair_loop` 收尾（已有 `llm_dataset.record` 处） | 缺陷1（会话内重复错误） | ✅ 采纳 P0（S1；注入规则走 policy 配置） |
| 2 | **llm_dataset 消费口**：失败模式聚合（按 kind/tool/model 统计失败率、修复成功率），暴露给治理层与 mining | `reflection/dataset.py` 已有 `stats()` 旁扩展 | 缺陷1（数据坟场） | ✅ 采纳 P0（S2；含吞错计数——回执补充） |
| 3 | **失败数据喂回 gears**：聚合结果修正挡位解析，挡位从"静态配置"变"被失败数据修正的策略"（需复核 D6 裁决边界：可先做"建议值+人审"而非自动升挡） | `governance/gears.py` `resolve_gear` | 架构图「反思→更新策略」断箭头 | ⚠️ 有条件采纳 P1：**仅建议值+人审**；不进 resolve_gear 输入（防第五轴）；永不自动写 tier（D6） |
| 4 | **工作记忆溢出摘要**：历史超窗时将溢出段摘要注入 system（`summarize_conversation` 已存在，接线即可）；主对话链接入 dossier 或至少 MemoryStore 读面 | `memory/working.py` `history_window` / `turns/context.py` 装配段 | 缺陷2 | ✅ 拆半采纳 P0（S3）：摘要+缓存采纳；**MemoryStore 退役删除**（非接线）；dossier 进主链缓议 |
| 5 | **意图识别 LLM 兜底落地（P5）**：正则未命中或低置信时走一次轻量 LLM 分类 | `perception/intent.py` | 缺陷3 | ⚠️ 有条件采纳 P1：先误路由遥测（#2 数据）后受限兜底；LLM 意图只建议不触发不可逆动作、不入硬闸 |
| 6 | **评估域扩展**（远期）：对话质量/需求澄清质量评估器，复用 evaluator 的"归一为统一评估对象"思路 | `reflection/evaluator.py` | 缺陷5 | ⏸ 缓议 P2（依赖 #2 数据先行） |

**优先级建议**：P0 = #1 + #2 + #4（直接补架构图最核心的回流箭头，改动小、收益立现）；P1 = #3 + #5；P2 = #6 与知识图谱层（缺陷7）。
**裁决后优先级**（回执）：P0 = S0 驱动基座 + #1 + #2 + #4 轻半 + MemoryStore 退役；P1 = #3 + #5；P2 不变；知识图谱层与 A2A 不做（见回执）。
**改造原则**：延续既有裁决精神——经验回填与消费口只"告知"，不自动改写业务决策；涉及策略变更（#3）保留人审接口。

---

## 附：评审覆盖的代码快照

- `agent/orchestrator.py`（五段管线：`handle_chat`/`_chat_gate`/`_chat_route`）
- `agent/turns/{context,chat}.py`（装配与执行段）
- `agent/memory/{working,store,units,dossier}.py`
- `agent/perception/{intent,gate,router}.py`
- `agent/reflection/{repair,repair_tasks,mining,evaluator,dataset}.py`
- `agent/cognition/`、`agent/governance/gears.py`、`agent/compensation/providers/builtin.py`
- `arch_routes/{ctx,llm_dataset,mcp_collab,sessions}.py`
