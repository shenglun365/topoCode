# 外部 Agent 项目源码评估与采纳路线（codex / opencode / deepseek-harness）

> 日期：2026-09-17 · 性质：架构评估文档（纯分析，未改代码）
> 评估对象：`/home/cuser/soft/codex-rust-v0.140.0`、`/home/cuser/soft/opencode-1.17.9`、
> `/home/cuser/soft/deepseek-harness-v0.1.0-rc3` + `/home/cuser/soft/deepseek-harness-dsh-v0.1.5-rc.2`（增量）
> 目的：提炼可学习/可参考的架构设计、功能设计与实现逻辑，形成与产品基调一致的采纳路线；
> 偏离本档裁决需回写本文档。
> 条目整合：docs/ 遗留评估/规划文档的未完成条目已按 §九 归位（排期不接管，只做方向归位、
> 合流裁决与状态核实）。
> ⚠️ 2026-09-22 注：文中提到的 `orchestration-plan.md`（环节十一~十五全落地）与
> `agent-harness-batch5-decisions.md`（拍板项全部收敛）已清理，残余转移
> `tech-debt-ledger-2609.md`；历史原则引用（如"orchestration-plan 原则 2/4/5/6"）
> 以 git 历史为准。

---

## 一、定位与准绳

### 1.1 产品基调四锚点（不可动摇项）

1. **KB 外脑是迭代核心**：知识的「存储 → 分析 → 使用」闭环，最终帮用户**指挥驾驭**其他 Agent
   工具——知识是主体，Agent 是被驾驭的工具（README 功能特性 §知识库）。
2. **人在环上**：任务卡 = 交接切面，用户确认任务/计划/里程碑等待指示；orchestration-plan
   设计原则 1/3 已定论——**不是**模型自主协作。
3. **有效性 = 文件状态**：git 文件状态为唯一判据，不做语义花活（orchestration-plan 原则 2）。
4. **护栏执行器无关 + 策略数据驱动 + 不建清单**（orchestration-plan 原则 4/5/6）。
5. **本地模型优先**：architect 专注本地模型解决软件开发问题，目标模型 1~30B、能力跨度大——
   模型能力是**一等调度输入**：感知能力边界、按能力层级差异化编排、最大化小模型产出。

### 1.2 核心认知

三个外部项目都是 **"agent-runtime first"**——会话/消息/工具是一等公民，知识仅以
AGENTS.md/skills 等静态文件形式存在；TopoCode 是 **"cognition first"**——知识资产
（语义资产、分析文档、任务卡、里程碑回写）是一等公民，agent 是执行器。

因此借鉴判据为：**该机制是否强化 KB 闭环、交接切面、或人在环确认？机制可抄，自主权模型不抄。**

---

## 二、三项目定位与架构速览

| 项目 | 一句话定位 | 关键形态 |
|---|---|---|
| **codex-rs** 0.140 | Rust agent 引擎，120+ crate workspace | **协议契约即产品**：`codex app-server` JSON-RPC 是唯一中枢，TUI/exec/IDE 全走同一协议 |
| **opencode** 1.17.9 | TS agent（Bun + Effect） | **Server-first**：一切逻辑在 HTTP server 后，TUI/Web/Desktop 全是客户端；SDK 由 OpenAPI 生成 |
| **dsh** v0.1.0→v0.1.5 | TS 插件化 harness（vendored Cordis，226+ 包） | **事件溯源 + 能力接缝**；v0.1.5 三主线：持久化即架构 / 宿主形态分化 / 教训制度化 |

### 架构层可学习的通用结论

- **codex 协议分层治理**（`codex-rs/app-server-protocol/`）：`protocol`（进程内
  Op/EventMsg）→ `app-server-protocol`（外部 JSON-RPC v1 冻结 / v2 演进）→ rollout JSONL
  （持久化 schema）三套契约显式分离，`TurnItem::as_legacy_events()`
  （`protocol/src/items.rs:585-607`）机械桥接新旧模型；TS + JSON-Schema 双导出 +
  schema fixture 快照测试 + PR 必审四个破坏面（`AGENTS.md:103-111`）。最强证据：
  `codex exec` 无头 CLI 也不直接驱动 core，而走 `InProcessAppServerClient`
  （`exec/src/lib.rs:775`）——单一协议面杜绝多入口功能漂移。交互契约采纳见 A6（学形不学量）。
- **codex 治理原则**：AGENTS.md 明文 "**resist adding code to codex-core**"（core 16 万行
  已过重，新功能优先拆新 crate）——佐证 agent-structure-review B2「分层边界必须机械化强制，
  仅靠注释必腐化」。
- **opencode 类型端到端**：Effect Schema 定义 API → OpenAPI（`server/server.ts:66`
  `OpenApi.fromApi`）→ hey-api codegen 生成 `@opencode-ai/sdk`
  （`packages/sdk/js/script/build.ts`）——SDK 永不与 server 漂移。
- **opencode Server-first**：TUI worker 甚至 in-process 调 `Server.Default().app.fetch`
  （`src/cli/tui/worker.ts:35`）；外部宿主嵌入有三条路：sidecar+SDK、in-process fetch、ACP。
- **dsh 事件溯源**：会话 = append-only 类型化事件日志，模型历史 `deriveMessages()` 纯派生
  （`packages/core/session/src/index.ts:708-747`）；"Model-visible ⟺ logged" 不变式由运行时
  断言执行——resume/fork/replay/UI 全从同一流导出，消灭双写不一致。
- **dsh 能力接缝三角色**（`docs/architecture.md:98-103`）：E2B POC 只换 fs/subprocess 两个
  adapter，bash/PTY/LSP 工具零改动迁入远程沙箱——对"嵌入任意执行环境"最优雅的抽象。
- **TopoCode 自有差异化优势（坚持）**：挡位策略表 T0-T4 + 能力探针评分（十二a/b）、里程碑
  协议 + 循环护栏、"有效性=文件状态"——三个项目均无对应物。外部项目对「模型能力感知与按
  能力编排」最接近的仅是：opencode 按模型族选 prompt 模板（`session/system.ts:25-39`）与
  models.dev 目录作上下文预算（`core/src/models-dev.ts`）、dsh 子 agent 启动能力协商
  （`docs/subsystems/subagent.md`）——均无「探测 → 定档 → 按挡差异化编排」的闭环。
  线三（本地模型能力分层调度）正是此优势的产品化深化。

---

## 三、线一：KB 线（产品基调主线，P0）

### K1 知识资产格式版本化

- **来源**：dsh v0.1.5 `packages/session/session-format{,-catalog,-v0-to-v1,-v1-to-v2,-v2-to-v3}`、
  `docs/session-format-status.md`、`docs/cookbook/adding-a-session-format-version.md`。
- **动机**：旧版 `SESSION_FORMAT_VERSION=0` 无迁移路径，任何结构变更都会废掉历史数据；
  v0.1.5 建立了完整迁移链（当前 v3）。KB 是 TopoCode 持久化重地，分析文档、语义资产、
  任务回执都要长期演进，同样面临「知识格式改了旧数据怎么办」。
- **机制（五件套）**：
  1. 版本常量为唯一手写权威（`packages/core/session/src/types.ts`），发布记录独立维护
     （`docs/session-format-status.md` 的 `latestReleasedVersion` + `evidenceTag` 绑 release
     tag）——**双权威**；
  2. 文件名/记录内嵌版本（`session.vN.jsonl`），每一代不可变，读旧代→迁移→写新文件，
     源文件不动；
  3. 迁移为**单遍流式 Stage**（不物化整文件数组），恢复策略两维
     `recovery: strict|recoverable` × `validation: transformed|current`；
     变基数迁移（v1→v2）带 seq 引用密集重映射，且「切点不得落在语义单元中间」；
  4. Catalog build-static：迁移边 0→current 每步恰好一个相邻包，拒绝缺口/重复/多余边，
     **运行时配置不能增删迁移边**（历史可读性不依赖用户配置）；
  5. 新增版本走 6 步流程（恒等边起步、snapshot 后继、严格恢复验证）。
- **注意**：dsh 因此**移除了 sqlite 会话后端**（provider 只剩 jsonl）——「不可变代际 +
  文件名寻址 + 流式迁移」模型与行式数据库冲突。TopoCode KB 在 SQLite 上，若采纳应以
  「表内 schema_version 字段 + 只追加迁移函数链 + 版本登记文档」形式落地，不必推翻存储引擎。
- **落点**：KB 文档表、分析产物、arch_tasks 回执的 schema 演进策略。
- **基调对齐**：外脑的地基是长期可信的历史；这直接服务「存储」环节。

### K2 里程碑报告 → KB 结构化回写

- **来源**：dsh v0.1.5 `docs/subsystems/subagent.md`（+39 行）：Continuable 子 agent 结束时
  **无条件向父投递终止通知**（带最终 assistant 内容）；`descriptor 持久化快照`
  （provider/model/reasoningEffort/persona/toolFilter）支撑冷恢复；结构化输出
  `outputSchema` 强制捕获工具 + `diagnostic` 字段（≤4096B、脱敏）。
- **动机**：G2（子代理→主 agent 无结构化回路）的 KB 化解法——任务产物不只是会话消息，
  应沉淀为可检索的 KB 资产，强化「分析→使用」闭环（orchestration-plan 已有雏形：
  里程碑报告 `改动文件:` 行回写 allowedScope）。
- **落点**：`exec_bridge._handle_task_event` 事件已全量落流；增加结构化回执卡
  （done/failed 时固定 schema：改动文件/commit/验证/诊断）→ 写入 KB 资产表；
  范围探针（环节十三）grounding 数据源随之增强。
- **基调对齐**：回写仍由 architect 编排层执行，人不被绕过；符合「两层互相供数」原则 3。

### K3 turn-outline 式大纲投影

- **来源**：dsh v0.1.5 `packages/session/session-turn-outline`：pure-fold 投影出每回合
  `{seq, prompt 预览(50字符), response 预览(120字符)}`，`seq` 即分页回载目标；
  每 turn 最多推 3 次变更。
- **动机**：知识**导航**——客户端未加载的长会话/长分析报告可 O(turn) 大纲跳转，
  直接提升「人的架构认知」体验（分析显微镜的产品主张）。
- **落点**：docs 服务（:3481）与 architect 会话流前端的会话/文档大纲面板；
  后端一个只读投影接口即可。
- **基调对齐**：纯只读投影，零新协议（orchestration-plan §6 复用对照精神）。

### K4 @引用不读内容原则

- **来源**：dsh v0.1.5 `packages/context/file-reference{,-local}`：`@path` 选中候选
  **只插入普通 prompt 文本，从不读/附文件内容**；模型要看内容必须自己调 read 工具
  （provider 可装 `FILE_REFERENCE_PROMPT` 强化）；seam/provider 分离（抽象服务零 IO，
  本地 provider 负责有界发现/排名/缓存）。
- **动机**：grounding 给引用和定位符、不给全文——省上下文、强制 agent 走 KB 工具通道
  （可观测、可计费），且引用轻量化。
- **落点**：KB 工具（arch.* MCP 面）与范围探针的 grounding 语义对齐检查；
  workspaceFiles 规约落盘已有类似精神，可统一口径。
- **基调对齐**：「分析→使用」的边界纪律：知识按需取用而非倾倒。

---

## 四、线二：architect 编排线（P1）

### A1 G2/C1 改道：终止通知结构化 → KB 沉淀 → architect 感知

- **来源**：同 K2（dsh subagent 终止通知 + outputSchema/diagnostic）；
  opencode background subagent 完成后向父 session 注入 synthetic `<task_result>/<task_error>`
  文本 part 并自动续跑（`tool/task.ts:202-220`）为对照参照。
- **方案**：agent-structure-review 批次 C1 原「LLM 生成建议回复草稿」升级为：
  runner done/failed 事件 → 结构化回执（K2 schema）→ KB 沉淀 → 卡片词汇表
  （`cards.py`）新增回执种类 → architect 感知。**人确认节奏不变**，不做全自动回环。
  通道载体由 A6.1 承接（done/failed 经 `turn_completed` 反向请求到达）。
- **落点**：`exec_bridge.py`、`cards.py`、KB 资产表。

### A2 C3 机制采借：taskPlan 升级 DAG/CAS（自主权不采借）

- **来源**：dsh v0.1.5 `packages/experimental/agent-team/src/{task-board,task-graph}.ts`、
  `docs/subsystems/agent-team.md`：
  - `blockedBy` 边 + DFS 环检测（`assertTaskGraphCandidate` 拒绝 self/duplicate/missing/cycle）；
  - 状态机 `pending/in_progress/completed/deleted`（deleted 保留墓碑，删除前查无依赖者）；
  - 8 个 action，**乐观并发：expectedRevision CAS**，stale 拒绝，每次 mutation revision+1
    整快照落盘；
  - 授权 = owner 或 Lead；`writeScopes` 是**建议性路径前缀**（归一化 + 重叠告警），明确"不是锁"。
- **方案**：orchestration-plan 环节十四的 `taskPlan: [{seq, title, boundary, depends}]` 已有
  depends 雏形；升级为上述状态机语义（复用 arch_tasks + taskPlan JSON 列，必要时加
  task 依赖表）。**出入口仍是 architect + 用户确认**，不做 agent 间自由任务认领。
- **可顺带**：`writeScopes` advisory 重叠告警与既有 `check_mutex` 声明级互斥互补
  （告警在确认前提示，互斥在执行中把关）。
- **基调对齐**：机制数据化（DAG/CAS），决策权在人——符合原则 4「策略数据驱动」。

### A3 运行时身份模型可见

- **来源**：dsh v0.1.5 `docs/postmortem/0003`：Web agent 改 GUI 却不知自己跑在哪个
  URL/进程，把裸 Vite HTTP 200 当成功、验证了替身服务器。护栏 = **把当前运行时身份
  （规范 URL、模式）做成模型可见**（prompt 段 + `$DSH_WEB_URL` 环境变量）+
  验收必须外部观测目标 origin。
- **落点**：`planning/task_plan.py` 的 `build_task_instruction(policy, ...)` 注入
  worktree 路径 / 任务分支 / runner 作业 id / 宿主 URL 事实；runner 作业环境注入
  `TOPOCODE_*` 环境变量。与「任务卡=交接切面」同源。
- **基调对齐**：原则 2「有效性=文件状态」的事实面补充：agent 知道自己该在哪验证。

### A4 审批桥增强（机制级）

- **来源**：opencode `src/permission/index.ts`：
  - `reject` 可带自然语言 message → `CorrectedError` 把用户反馈传回模型（:132-138）——
    拒绝 ≠ 死路，模型可自我修正；
  - `always` 放行时**级联放行同 session 其余 pending**（:120-177）；
  - 规则 = `(permission, pattern, action)` 三元组 findLast 求值（:39-49）；
  - bash 工具用 tree-sitter 静态解析命令提取风险 pattern（`tool/shell.ts:29-66`）。
- **落点**：runner 审批桥（`/approve` `/deny` 扩展 deny 理由透传 → 下一回合反馈给
  执行器）；deny 级联与越界审批 UI 文案。权限立场不变：**审批权在人/宿主**。
- **基调对齐**：人在环的反馈质量提升；护栏执行器无关（三适配器同享）。

### A5 durable 投递语义（queued-minus-delivered）

- **来源**：dsh v0.1.5 `agent-team/src/mailbox.ts`：发送先 `queued` 落盘（Lead 日志事务内）
  → 投递（steer 语义）→ 目标侧记录并 flush 后才补 `delivered`——**queued-minus-delivered
  就是恢复邮箱**；messageId 去重；per-target FIFO 串行。
- **落点**：architect waiting_input 管道补「投递状态持久化 + 重启补投」；agent-bus（:3486）
  的轮询分发已有人工把关定位，保持其现有角色，**不引入 agent 间自由信道**。
- **基调对齐**：机制可抄（崩溃恢复保证），自主权模型不抄（投递方始终是 architect 编排层）。

### A6 交互契约 codex 化（学形不学量）

> 定位：codex app-server 的双向请求模型是三项目中「人与 agent 交互契约」完成度最高的形态
> （`app-server-protocol/src/protocol/common.rs:1180` ServerRequest 反向请求族 + 宿主应答制），
> 且与「人在环」基调天然一致——agent 每个越界动作都必须拿到宿主应答才能继续。
> **双重动机**：① **新执行器接入成本收敛**——第 N+1 个执行器只需实现固定能力子集，
> 审批/提问/输入/终止等交互流与 UI 全部复用（对齐「护栏执行器无关」原则 5）；
> ② **用户体验统一**——审批卡、提问卡、输入请求、过程 item 渲染不再随执行器漂移。
> 只采四个协议形态，不采 100+ 方法广度与 `#[experimental]` 实验面。

- **A6.1 统一反向请求通道**：runner 事件面新增 ServerRequest 形态
  `{type: approval|question|input_required|turn_completed, requestId, params, deadline}`，
  architect 必须按 requestId 应答（复用既有 `/approval` `/input` REST 并升级为按 id 应答）；
  三适配器按 B1 能力矩阵降级实现（cline 全量 / opencode 权限桥 / codex 仅 input）。
  **合流约束（缺一即半成品）**：必须同时绑 A5（pending 请求持久化——codex oneshot channel
  是进程内的、跨重启失效，此处取 codex 形态 + dsh 持久化的并集）+ B1 能力矩阵（降级路由）
  + R2 fixture（契约守护）。A1 的「终止通知」并入此通道（`type: turn_completed`），
  A1 保留 KB 沉淀职责。
- **A6.2 Item 投影**：events → item 级稳定投影（tool_call / file_change / plan / reasoning），
  architect 会话流按 item 渲染，执行器差异被投影层吸收（UX 统一的主要载体）；
  `as_legacy_events()` 桥接思想（codex `protocol/src/items.rs:585-607`）用于兼容存量 events，
  不另起协议。参照：codex Thread/Turn/Item 三原语（`app-server/README.md:64-72`）。
- **A6.3 TurnContext 每轮快照**：runner 每轮持久化 `{model, approvalPolicy, executorConfig,
  baseCommit}`——三执行器统一获得低配 checkpoint（对齐「有效性=文件状态」：快照以 git
  baseCommit 为主锚），喂给续跑过期判定（环节十三 `changed_since`）与合并检查（环节十五）。
  codex 佐证：TurnContextItem（`protocol/src/protocol.rs:2952-2991`）。
- **A6.4 steer 协议化**：`steer` 与 `queue` 语义分离进协议（codex `turn/steer` +
  opencode V2 `delivery: "steer"` 双先例），消除「steer 直达为 cline 专属」的现状。

- **优先级**：A6.1 + A6.3 先行（A6.1 根治 G2/G4 且为 A1/A4/A5 合流点；A6.3 成本低、
  三执行器立即受益）；A6.2 随前端改造；A6.4 小，随需插入。
- **基调对齐**：宿主应答制 = 人在环的协议化；**通道先落在 architect↔runner 契约层，
  不把三个 TurnAdapter 各自 codex 化**（防适配器爆炸）——runner 对下仍用各执行器原生协议，
  对上统一收敛为 codex 形态；TurnAdapter「全链最干净的一层」地位保持。
- **目的对齐收紧（双重动机的工程落点，A6 验收标准）**：
  1. **适配器一致性测试套件（conformance kit）**：环节十一的伪适配器从一次性测试夹具
     升格为**参考实现**；新增统一契约测试套件（run_turn / steer / 内省 / 事件→
     ServerRequest 与 Item 映射语义逐项断言），任何 TurnAdapter——三执行器回归与
     第 N+1 执行器自证——必须全绿，防止统一协议长出 `if executor == ...` 分支
     （G4 复发）。模式参照：codex schema fixture + dsh keyless 快照测试；
  2. **N+1 接入路径文档化（五步清单，对齐 CONV-03 新子项目模板做法）**：
     ① 实现 TurnAdapter → ② 声明 B1 能力矩阵 → ③ 事件映射 Item/ServerRequest →
     ④ 能力探针校准（十二b 管道自动覆盖新执行器×模型组合）→ ⑤ 过一致性套件——
     「接入方便」以清单可度量；
  3. **UI 守门规则（归入 A6.2 验收）**：architect 前端**只渲染统一投影**
     （Item / ServerRequest 卡片），禁止按 `executorType` 分支渲染；执行器特有能力
     一律经 B1 能力矩阵显式开关（如「合并检查」按钮仅 `checkpoint: true` 时出现）——
     协议统一必须传导到渲染层，否则体验照样漂移。

---

## 五、线三：本地模型能力分层调度线（P0.5，产品差异化主线）

> 定位：architect 面向本地模型（1~30B，能力跨度极大）解决软件开发问题。现有挡位体系
> （十二a）与能力探针（十二b）已回答「给模型定档」；本线回答后续两问：**如何感知并固化
> 当前模型配置的能力边界**，以及**边界之内如何编排才能最大化小模型产出**。

### M1 能力边界档案（感知边界制度化）

- **现状**：十二b 探针结果落执行器注册表 `{tierProbed, score, detail, probedAt}` +
  needsReprobe——已有"实测定档"，缺"边界固化"。
- **演进**：升级为**模型能力档案**（per 模型配置，随执行器配置存取）：
  - **边界清单**：分探针得分明细 + 硬性上限规则（探针 4 指令跟随不过 → 上限 T3；
    context ≤8k → 禁用长 KB grounding 注入；探针 5 集成不过 → 禁并行下发）；
  - **降级路径**：当前挡位的典型失败模式 → 建议动作（T3 连续失败 → 降 T2 任务级预拆
    或收窄边界要求人工预拆）；
  - **运行时信号回流**：loopguard 触发率 / repair 外循环频次 / 越界次数按模型配置累计，
    异常升高 → 提示重探或降档。**边界是实测的，不是配置的**。
- **来源佐证**：dsh 子 agent 启动能力协商（outputSchema/depthLimit/toolFilter/persona
  四 flag，缺失即 `UNSUPPORTED_CAPABILITY` 拒绝，`docs/subsystems/subagent.md`）——
  能力边界契约化先例；opencode models.dev 目录（`core/src/models-dev.ts:142-213`）——
  模型 limit（context/input）作为预算硬输入。
- **落点**：`agent/governance/gears.py`（档案读取进 Policy 对象）+ 执行器注册表（存储）+
  capability-probe REST 面扩展。

### M2 挡位策略表增补（小模型特化维度）

- **现状**：策略表维度 = KB/探针、architect 预拆、确认节奏、轮次（十二a）。
- **增补维度（全部进 `gears.py` 策略表一行 + resolve 链，禁止散落分支，原则 4）**：
  1. **工具面收窄**：弱模型少给工具——MCP 注入 / steer / KB 写按挡裁剪。先例：
     opencode 对 gpt-* 模型用 `apply_patch` 替代 `edit/write`（`tool/registry.ts:273-276`）；
  2. **上下文预算**：小模型 context 仅 4k~32k——KB grounding 剪枝强度、任务卡长度、
     里程碑历史保留量按挡收缩（参照 opencode `overflow.ts`：usable = model.limit −
     reserved；dsh spill 策略：全文不进上下文，给预览 + 定位符）；
  3. **指令模板分档**：弱模型用更短、更结构化、少歧义的指令（`build_task_instruction`
     已按挡分叉，细化到句式与清单化程度）。先例：opencode 按模型族选 prompt 模板
     （`session/system.ts:25-39` + `session/prompt/*.txt`）；
  4. **结构化输出强制**：弱模型的里程碑报告「固定行格式」文本契约易错，可按挡升级为
     **工具契约**（强制经 `report_turn_outcome` 类工具提交，schema 校验失败即"请重写"
     反馈）。先例：opencode StructuredOutput json_schema 工具（`session/prompt.ts:1295-1302`）
     + `InvalidArgumentsError.message` 即"请重写输入"（`tool/tool.ts:24-34`）+ dsh v0.1.5
     subagent `outputSchema` 强制捕获工具；
  5. **推理档位映射**：effort/summary 参数随挡取值（codex `Reasoning{effort, summary}`，
     `codex-api/src/common.rs:124-132`）。
- **基调对齐**：最大化小模型 = 只让模型做能力圈内的事，其余由编排层兜住（预拆/结构化/
  收窄/预算）——策略数据驱动，护栏执行器无关。

### M3 轻重任务分船（mixed-fleet 编排）

- **来源**：opencode `getSmallModel`——title/summary/compaction 等轻任务固定用小模型；
  dsh v0.1.5 agent-team roster **按成员**指定 provider/model（`spawnTeammate request.provider`，
  `agent-team/src/roster.ts`）——异构模型编队先例。
- **方案**：architect 编排允许**异档协作**：范围探针/标题/汇总/KB 摘要等"编排侧轻任务"
  固定走小模型档；实施/调试走实测强档。T2 的「中模型任务级预拆」天然支持预拆者与
  执行者异档（任务卡已可绑定执行器，扩展到步骤/角色级）。长远与 A2（DAG）合流：
  DAG 节点带执行器 + 挡位标注。
- **基调对齐**：KB 供数两端（写入摘要/检索摘要）均可由小模型承担，重活留给强档——
  在显存与成本约束（README 本地模型硬件建议）下最大化产出。

### M4 小模型工具协议健壮性

- **现状痛点**：agent-structure-review §三：主 agent `[TOOL_CALL]` 文本协议 + 补偿守卫链
  是复杂度最大来源；弱模型更易错格式，每换档/换版即新增守卫。
- **方向**：
  1. provider 支持时对弱模型启用**受限生成**（Ollama/LM Studio 均支持 json_schema 约束
     解码）——用解码层约束替代文本协议守卫，从根上减少守卫存在的原因；
  2. repair 外循环按挡加密：弱模型 repair 预算更高、轮次上限更低（repair 次数进策略表）；
  3. **失败样例回流探针**：把线上真实错误格式样本沉淀为探针判分用例，探针套件随实战
     校准（orchestration-plan §7 已列"探针套件扩充/权重校准"）。
- **基调对齐**：负面空间纪律（原则 6）——优先消灭守卫存在的原因，而非继续堆守卫。

### M5 能力边界的前端感知（透明度）

- 十二b 已有「实测 T2 (4/5)」展示；扩展：**边界说明卡**（该模型不擅长哪些任务类型 →
  建议挡位 / 建议人工预拆）、运行中降档提示（M1 运行时信号触发）、探针历史曲线。
- **基调对齐**：分析显微镜的产品主张同样适用于模型本身——把模型能力做成可分析对象；
  用户驾驭 agent 的前提是知道工具（模型）的边界在哪。

---

## 六、线四：runner 契约卫生线（P2，低风险）

### R1 G7 根治：runner REST OpenAPI 化 → 生成类型化 client

- **来源**：opencode OpenAPI→SDK 管线（`packages/sdk/js/script/build.ts`：`bun dev generate`
  → `@hey-api/openapi-ts`）。
- **方案**：runner（:3458）`/api/implement*` FastAPI 面 OpenAPI schema → 生成 Python
  typed client，替换 `exec_bridge` 五处裸 `_runner()` 调用（agent-structure-review A2 的
  深化版：从手写 RunnerClient 到生成式 client）。现有 `test_exec_implement.py` /
  `test_exec_bridge_events.py` 为回归门禁。

### R2 events.py schema fixture 契约测试

- **来源**：codex `app-server-protocol/src/schema_fixtures.rs`：TS + JSON-Schema 双导出 +
  快照测试；AGENTS.md 要求 PR 显式审查四个破坏面（API/CLI 参数/config 加载/resume）。
- **方案**：`packages/core/.../runner/events.py`（跨进程事件 schema 单源）导出 JSON Schema
  快照，runner 侧与 architect 侧消费测试共同守护；runner 侧破坏面（turn_adapter 协议/
  事件 schema/续跑格式）列入 PR 审查清单。对齐 CONV-04 契约门禁精神。

### R3 RunnerFailureRule 结构化失败归因

- **来源**：dsh v0.1.5 `docs/subsystems/sandbox.md` + `docs/postmortem/0004`：
  runner 失败判定 = 非零退出（可选 `allowedExitCodes` 门）∧ 剩余 stderr 单行内命中
  `fatalSignatures` − 先按整行精确剔除 `informationalLines`；**退出码单独永不构成失败**；
  `SandboxEnforcement: full|partial` 显式类型化。
- **动机**：postmortem 0004 即真实事故——把 ripgrep「无匹配 exit 1」误判为沙箱故障。
- **落点**：`runner/loopguard.py` 错误签名检测器与 implement.py 作业循环的失败归因逻辑；
  cline/opencode/codex 三适配器同享（护栏执行器无关）。

### R4 requestId 全链路回声 + 代际基线重连

- **来源**：dsh v0.1.5 `packages/api/session-controller`：
  - 本地提交同帧上屏（`beginSubmission`），`requestId` 全链路关联，durable 事件落地后
    同帧内退休——解决「发出去了但不知服务端收没收」的 UI 假死；
  - 重连 = 代际基线整体替换（follow 流先开 + gap 尾页修复；重连发快照流整体替换），
    不做增量追补；
  - 读接口自带 `version`/字节窗，消费者可识别陈旧页。
- **落点**：`exec_bridge`/`pumps.py` 的 WS 订阅 + snapshot 校准增强；architect WS 帧协议
  （C2 取消帧可同批设计）。

---

## 七、剔除清单（防走偏，含理由）

| 项 | 来源 | 剔除理由 |
|---|---|---|
| agent-team 自主协作模型（成员互发消息/自主认领任务） | dsh v0.1.5 | 与「人在环确认、知识指挥 agent」基调相反；仅采机制（A2/A5） |
| Desktop 零端口宿主 / Electron 壳 | dsh apps/desktop | 产品形态已定 Web（:3456），无桌面端需求；staging→健康检查→原子切换事务可留档备用（执行器 sidecar 自升级） |
| sdk-minimal 极简嵌入 profile | dsh bundle | TopoCode 不做通用 harness 发行 |
| `dsh_` wire extensions / 会话日志镜像 | dsh llm-api-extensions | provider 私有通道，与知识闭环无关；且「扩展永不进 messages」的 KV-cache 约束属 agent-runtime 战场 |
| V1→V2 双核迁移（Effect/SQLite durable 重写） | opencode packages/core | 过渡期双写成本高，TopoCode 无同等规模债务 |
| compaction KV-cache 精调（摘要重放前缀等） | dsh | 本地小模型/云端混合场景收益弱，优先级低 |
| ACP / IDE 生态集成 | codex/opencode/dsh | TopoCode 交付形态是自含 Web 平台，非 IDE 插件 |
| Effect v4 beta / 新框架冒险 | opencode | 核心框架处于 beta，外部深度耦合风险大 |

---

## 八、与既有计划衔接

| 既有计划 | 本档动作 |
|---|---|
| orchestration-plan 环节十四（taskPlan 顺序下发） | A2 提供升级选项：depends → blockedBy DAG/CAS，按需立项 |
| orchestration-plan 环节十三（范围探针） | K2 回写增强其 grounding 数据源；K4 统一引用语义 |
| agent-structure-review 批次 A/B | A1（泵泄漏）→ 批次 1 复核（`recover_conv_tasks` 已部分覆盖）；A2（G7）= R1；B2→B1 上提为批次 2（A6.1/M 线前置）；B4/B3 前置 M4（批次 5）——经 9.2 代码核实均未落地 |
| agent-structure-review 批次 C1（G2） | 改道为 A1（结构化回执 → KB 沉淀 → architect 感知）；
  通道部分由 A6.1 反向请求通道承接 |
| G2 / G4（泵纯下行、能力散落） | A6.1 反向请求通道根治，通道按 B1 能力矩阵降级路由 |
| checkpoints / steer 仅 cline | A6.3 TurnContext 快照 / A6.4 steer 协议化补齐执行器无关性与体验统一 |
| agent-structure-review 批次 C2（回合取消） | 与 R4 同批设计 WS 帧协议 |
| agent-structure-review 批次 C3（多 agent） | 只采 dsh 机制（A2），协作出入口仍是 architect + 用户确认 |
| agent-structure-review B2（分层边界测试） | codex「resist adding code to core」治理原则为其佐证 |
| CONV-04 API 契约与验证门禁 | R1/R2 为其向 runner 面的延伸 |
| orchestration-plan 环节十二a/b（挡位 + 能力探测） | 线三 M1/M2/M3/M5 为其深化：能力边界档案、
  策略表小模型维度、异档分船、边界透明化 |
| agent-structure-review §三摩擦点（[TOOL_CALL] 文本协议守卫链） | M4 从「按挡加固协议健壮性」切入，
  与 B3（拆解）/B4（单源化）协同；终极方向是受限生成替代文本协议 |

### 8.1 改造开工顺序（批次制，2026-09-17 定稿）

> 原则：**安全网先行 → 参数源（挡位）先于编排 → 契约先于消费 → 需拍板项靠后**。
> 批次 0 与 L 组排期归 roadmap；本表只定归位与依赖，不重复排期。

| 批次 | 条目（依赖序） | 关键前置 | 交付 / 门禁 | 状态 |
|---|---|---|---|---|
| **0 安全网** | 0905 A1 四步测试安全网（= roadmap P1-T1~T4）；改造最小集 = core 管线集成测试 + architect 既有测试全绿基线 | — | pytest 基线数只增不减 | 最小集可先跑，全量随 roadmap Phase 1 |
| **1 卫生线**（**首批开工**） | R2 schema fixture → R1 runner REST OpenAPI 化 + RunnerClient 收敛（=G7/批次 A2）→ R4 requestId 回声 + 代际重连（C2 取消帧同批设计）→ 批次 A1 泵泄漏复核 → A3 运行时身份注入（`build_task_instruction` 注入 worktree/分支/宿主事实） | 无 | R2 fixture 常驻；`test_exec_implement` / `test_exec_bridge_events` 回归 | **已落地（2026-09-17）**，as-built 见下 |
| **2 挡位参数源** | B2 分层边界测试（先立，护住后续）→ B1 能力矩阵单源（含 `cline-sdk` 别名归一）→ M1 能力边界档案（顺修 t4 profiles 缓存 bug）→ M2 策略表增补（工具面/上下文预算/指令模板/结构化输出/reasoning 五维 + 预留 L/S 档） | 批次 1 | gears.py 策略表扩展 + 模板快照测试 | **已落地（2026-09-17）**，as-built 见下 |
| **3 交互契约** | A6.1 统一反向请求通道（+ conformance kit：伪适配器升格参考实现；A5 pending 持久化同批设计）→ A6.3 TurnContext 每轮快照 → A4 审批桥增强（reject 带反馈，迁入通道） | 批次 1（R1 类型化 client + R2 fixture）+ 批次 2（B1 降级路由） | 一致性套件全绿；G2/G4 关闭 | **已落地（2026-09-17）**，as-built 见下 |
| **4 验收与 KB 沉淀** | V 组 V1→V2→V3→V4（**R3 并入 L4 编排层**）→ V5 → K2（arch_assets 表基座 + V5 验证矩阵 = 回执 schema 主体）+ A1 KB 沉淀（rides A6.1 通道） | 批次 3 A6.1；V 组排期归 roadmap P2-T5 | 按 V 设计文档门禁（G3+G6 / G3+G4+G5+G7） | **V1~V5 + K2 后端 + 尾量四项已全部落地（2026-09-17）**：jest/vitest 适配器 / 验收配置 UI / AssetsPanel / A1 回执增强 |
| **5 专项与拍板项** | M4 协议健壮性（前置 B4 工具文档单源化 + B3 `handle_chat` 拆解；终极方向受限生成）→ M3 分船（需拍板；实现载体 L6 模型路由）→ K1 格式版本化（专项设计）→ K3/K4 → A2 DAG/CAS（需拍板） | 批次 2/4 | 各自设计小档 + 门禁 | 决策方案档已出（2026-09-17）：`agent-harness-batch5-decisions.md`；**M4 已拍板并全部落地（as-built 见决策档 §1，920 passed）**——B4 单源化/B3 五段拆解/tool_rounds 按挡/样例回流/受限生成全链（provider 透传+双通道+两段式）；其余项进展：**M3 已拍板并落地**（§2 as-built）、**三维能力矩阵专项 7 切片全落地**（收编 M1/M5/A2 depends_source，§11 as-built）、**K1 已落地（知识资产体系收敛 P0-P3，2026-09-17）**：L4 `arch_assets` 退役并入会话单元（P0）、错误提炼 error_pattern（P1，手动触发/提炼即沉淀）、词典检索侧映射（P2）、四表 schema_version+迁移链（P3，`kb-schema-versions.md` 登记）；K4 **已裁决延后**（2026-09-17，机制价值确认、让位知识资产主线，重启时机=引用语义回归实证或 mandate 勾稽立项）；**A6.2 Item 投影已落地**（升级为 A 全量+开放注册制+一次性替换，决策档 §7 as-built；含 UI 守门 vitest 与投影 conformance 全词汇断言）；**A6.4 已落地**（delivery 协议位+降级回执卡）、**K3 已落地**（回合对大纲端点+会话中心侧栏+docs H2 大纲）——**批次 5 拍板项全部收敛**（M4/M3/三维矩阵/K1/K3/A6.4/A6.2 落地，K4 延后）；余各专项尾量（A2 writeScopes/矩阵深化/M4 真机冒烟/P2-T6 提升通道）按时机触发 |
| 随需插入 | ~~A6.2/A6.4/M5~~ **已并入批次 5 决策档**（2026-09-17 裁决）；~~L 组训练侧~~ **搁置不进行**（2026-09-17 裁决；M 线合流点保留于 §9.3 裁决③） | — | — | — |

**首批开工 = 批次 1**：R2 / R1 / R4 + 泵泄漏复核 + A3——全部低风险、门禁现成。

> **批次 1 as-built（2026-09-17，全量门禁 841 passed）**：
> - **R2**：`events.py:schema_snapshot()` 单源 + `packages/core/runner-events-baseline.json`
>   + `scripts/runner-events-baseline.py`；core 侧 `test_runner_events_schema.py`（基线对账/
>   常量一致性/形状截断/宽容策略/确定性）+ architect 侧 `test_runner_events_consumption.py`
>   （活导入/单源同一性/全 kind 流经/跨环境基线对账）。
> - **R1**：`exec_bridge` 7 处裸 `_runner()` 清零 → `_client()` 晚绑定工厂（保持 monkeypatch
>   接缝）；`RunnerClient` 增 `StartResult.base_commit`、`input(steer)`；REST 面基线
>   `runner-openapi-baseline.json`（20 paths）+ `scripts/runner-api-baseline.py` +
>   `test_runner_api_surface.py`（路径/方法集对账 + WS 路由单独锁定——websocket 不进 OpenAPI）。
> - **R4（回声半套落地）**：`task_input` 转达成功 → 主流落 `task_input_echo` 持久回执
>   （cards 词汇表已注册）+ 响应透传 `requestId`；投喂路径 `echo=False` 防双写。「代际
>   重连」语义显式化为：作业句柄丢失=failed + recover_sweep 重挂（当前 runner 内存态架构下
>   跨代重放不存在），完整代际基线重连归 A5/A6.1。
> - **批次 A1/G5**：`_task_pump` finally 统一清理 `_TASK_PUMPS` 句柄（正常/异常/取消全路径）。
> - **A3**：`assemble_task_instruction(runtime=)` 注入「运行时身份(防误验)」段——分支/
>   主仓事实 + 「禁止以主目录服务 HTTP 200 为完成依据」红线；jobId 为 runner 侧生成、
>   指令时点未知，随 A6.3 TurnContext 落地。
> - 顺手修正两处脆弱测试桩：`test_pump_recovery`（桩签名 + URL 查询串匹配）、
>   `test_feed_gate`（echo 参数）。

> **批次 2 as-built（2026-09-17，core+architect 846 passed）**：
> - **B2**：`test_agent_layering.py`（纯 stdlib ast）——R1 内核禁引 arch_routes、
>   R2 层序（collab/governance 横切豁免）、R3 orchestrator 例外；**棘轮设计**：
>   存量违规冻结（R1 18 文件 / R2 3 文件），清单外新增即失败、清单只许缩短；
>   附清单自洽断言（文件消失须删条目防僵尸清单）。
> - **B1**：`agent/execution/capabilities.py` 单源——双命名空间归一
>   （`cline-sdk/codex-server` → `cline/codex`，task 行与注册表类型两套并存现状
>   不动存储语义）；`task_set_executor`/`sessions /tasks/{id}/executor`/
>   `_build_workspace_files` 三处字面判断替换为 `is_valid_type`/`caps()`；
>   workspace 映射行为保真（cline 目录约定 / 其余 AGENTS.md 回落 / 未知类型通用路径）。
> - **M1（核心：边界固化）**：`gears.probe_hard_cap()` + `apply_cap()` +
>   `resolve_gear` 叠加探针封顶——识别结构化 `probeFlags.followGate`（新）与历史
>   `probeDetail`「上限T3」标记（旧），实测来源(tierProbed)被降档至 T3 并携带
>   `cap_note`；人工 capability 与显式会话挡位不封顶（人的意志优先）。
>   **t4 缓存 bug 复核结论**：现路径（working.build_chat_messages →
>   chat_system_prompt → tier_of）每回合 fresh 读档、无缓存——v2-todo P0-5 所述
>   症状已不在（疑似 0914 提交修复），不再追改。M1 余项（运行时信号回流/
>   降级路径提示/M5 前端透明化）随 M3/M5 立项。
> - **M2**：`GearPolicy` 增五维声明（tool_surface/ctx_budget/prompt_style/
>   structured_output/reasoning_effort），T0-T4 全量赋值锁定测试；L/S 档以
>   `MODEL_GRADIENTS` 预留进 M3 立项。消费端接线归 M3/M4（需产品拍板）。

> **批次 3 as-built（2026-09-17，全量门禁 869 passed）**：
> - **3a ServerRequest 契约**：`events.py` 增 `SERVER_REQUEST_TYPES`
>   （approval_request/input_required）+ `is_server_request` + `TURN_COMPLETED_KINDS`
>   映射，schema_snapshot 纳入（events 基线已同步重生成）——codex 宿主应答制的
>   类型枚举契约落到单源。
> - **3b conformance kit**：`packages/core/tests/adapter_conformance.py`——
>   `ReferenceAdapter` 参考实现（可执行文档：start→NEED_INPUT→user_input 续跑→done）
>   + 方法面/形状断言 + `EXPECTED_ADAPTER_CAPABILITIES` 能力对账表；三真适配器
>   （opencode/cline/codex）静态面断言不启 sidecar；architect 侧
>   `test_executor_capabilities.py::test_adapter_capability_parity_with_matrix`
>   跨层镜像（↔ capabilities.py 双护栏）。
> - **3c A6.3 + A5 切片**：`ImplementJob.turn_context`（作业级 model/base/branch/
>   root/executorId + 每轮 {turn,startedAt,model} 尾窗 20 存 5 曝）进 snapshot；
>   `pending_requests` 登记表（cline approval_request 时登记 / `/approval` 应答销账）
>   → `snapshot.pendingApprovals`——断线重连后宿主可见挂起请求（queued-minus-delivered
>   最小形态）。SNAPSHOT golden 契约有意变更（+turnContext/pendingApprovals）。
> - **A4 验证确认**：deny reason 透传断言已在 `test_exec_cline_routes`（reject 带
>   反馈链路成立，无需新码）。
> - **M1 接线收尾**：`assemble_task_instruction` 封顶时注入「实测能力边界降档」提示段。
> - 余项归位：exec_bridge 存档 turnContext 到 arch_tasks（需 store 列扩展）随 K2
>   （批次 4）；完整代际基线重连随 A5 主体（批次 4）。

> **批次 4 as-built（2026-09-17 起，V1 切片；全量门禁 881 passed）**：
> - **V1 门禁核心**（`runner/verify.py` + `ImplementJob._run_verify_gate`）：
>   - L1 发现链 P0 config（start payload.verify）→ P1 CI（workflows run 行/Makefile
>     test: 目标）→ P2 约定（package.json scripts / pyproject [tool.pytest] / go.mod /
>     Cargo.toml）→ P3 启发（test_*.py 存在 → pytest）→ 未命中 C 档 NO_VERIFY_CONFIG；
>   - L2 执行：cwd=worktree + 白名单拒绝（rm/curl/sudo/git push 等，WHITELIST_REJECTED）
>     + 超时分级（build 300s/test 600s × timeoutMul，TIMEOUT 原因码）+ 输出头尾截断；
>   - 级别判定：overall B（有执行）/ C（想验验不了：无命令或白名单拒绝——宁可不验
>     不可假验）/ D（diff 纯文档资源 → 仅人工审查）；A 档待 V2 结构化适配器；
>   - 事件：done 分支 emit `verify`（kind append-only，events 基线 17 kinds 已同步），
>     只观测不改终态（V4 编排后续作）；`RUNNER_VERIFY_DISABLE=1` 运维逃生；
>     无有效 worktree（测试桩/异常作业）跳过。
> - **批次 4 余项**（V2 语言适配器→V3 回归基线→V4 修复回注/升级（R3 并入）→V5
>   反馈落流与 DONE 诚实化 → K2（arch_assets 基座+矩阵=回执 schema）→ A1 KB 沉淀）
>   按 V 设计文档续作——V5 的矩阵消费面与本档 K2/A1 合流点不变。

> **批次 4 续作 as-built（2026-09-17，全量门禁 884 passed）**：
> - **V2 结构化适配器（A 档）**：pytest 自动注入 `--junitxml`（幂等防重）+ go test
>   `-json`；junit XML/go JSON 解析 → perTest/summary；退出码 0 但报告有失败 →
>   以报告为准（防假通过）。结构化即 overall 升 A。
> - **V3 回归基线**：`run_baseline/load_baseline`——基点临时 worktree 跑基线测试 +
>   磁盘缓存（key: root+base+cmd 哈希）；job start 异步预跑（不阻塞实施）；
>   对比语义：仅存量失败 → `PASS_WITH_KNOWN`；无基线 → regression
>   UNVERIFIABLE(NO_BASELINE) 不阻塞 test 判定。
> - **V4 修复回注编排（R3 并入）**：`classify_failure` L1 编译 / L2 定位明确测试失败
>   / L3（TIMEOUT、结构化失败 >5、轮次尽）；L1/L2 → `_repair_queue` 自动回注
>   （上限 verify_max_attempts，`autoRepair:false` 可关），prompt 明示「仅修复、
>   不改测试断言」；修毕 PASS → done（attempts 计失败验证次数）。
> - **V5 DONE 诚实化 + 反馈落流**：先实测后定终态——DONE 与实测不符不再落 done；
>   连续 2 轮不符 → waiting_input 退回并明示「模型可能不足以胜任，建议降档」；
>   architect 泵 verify 分支：矩阵进任务 progress（verifyOverall/分环节），
>   PASS 不落流防刷屏，FAIL/C 落 `task_verify` 简短消息。
> - **配置透传**：confirm payload 增 `verify`（任务行 verifyConfig → runner 发现链
>   P0 来源；验收配置 UI 随 K2/前端立项）。
> - 余项：V2 尾量（jest/vitest 适配器）、验收配置设置界面、K2（arch_assets 表 +
>   矩阵回执 KB 沉淀）、A1——已列入批次 4 续作清单。

> **批次 4 K2 切片 as-built（2026-09-17，全量门禁 890 passed）**：
> - **arch_assets 表基座**（v2-todo P1 规划落地）：db_schema 项目库新表
>   （五类词汇 requirement/todo/plan/data_asset/analysis + source 标写入方
>   manual/llm/task_receipt/milestone/verify + meta JSON 载荷，conv/kind 双索引）；
>   `store/assets.py` AssetsStore（CRUD + of_conv 过滤/检索，非法 kind 拒绝）。
> - **K2 沉淀接线**：done/failed 回执 → kind=plan 执行快照（meta 携 taskId/branch/
>   changedFiles/verifyOverall 与分环节结果）；里程碑报告 → kind=analysis
>   （meta.files = 改动文件清单）——「分析→存储」闭环的入库端。
> - **asset 工具面**：`asset.upsert / asset.list / asset.delete` 注册
>   （LLM 可读写，会话作用域，llm 来源标记）——「存储→使用」的工具出口。
> - **REST**：`GET /conversations/{id}/assets`（kind/q/limit）。
> - 批次 4 真余项：A1 里程碑报告结构化回执的规约边界回写增强（已有雏形）、
>   AssetsPanel 前端、验收配置 UI、V2 尾量适配器。

> **批次 4 尾量 as-built（2026-09-17，全量门禁 900 passed）**——批次 4 全项关闭：
> - **V2 尾量（jest/vitest 适配器）**：`verify.py` 新增 `_node_test_runner`
>   （package.json scripts+依赖检测 vitest/jest）→ discover P2 挂 `adapter` 标记、
>   P0 从命令文本推断；`augment_command` 按 adapter 注入报告旗标（npm/yarn/pnpm
>   走 ` -- ` 透传；vitest `--reporter=json --outputFile=`、jest `--json
>   --outputFile=`，幂等）；`_parse_jest_json`（两家 reporter 均兼容 jest JSON
>   形状）；`_attach_structured` 支持 jest.json（退出码 0 但报告有失败 → 以报告
>   为准）；adapter 全链路透传（_run_stage/verify_and_judge/run_baseline/
>   implement._prepare_baseline 基线同款报告旗标）。A 档覆盖前端栈。
> - **验收配置 UI**：arch_tasks 新列 `verify_config`（JSON，迁移 `_add_cols`）+
>   `PUT /tasks/{id}/verify-config`（白名单收敛 + 越界钳制：maxAttempts≤6、
>   timeoutMul∈[0.5,10]、命令≤500 字符；仅 pending_confirm 可改——running 已
>   下发不生效）+ TaskCard 折叠面板（构建/测试命令、超时倍率、修复轮次、
>   autoRepair 开关；留空=自动发现）。P0 链路闭环：任务行 → confirm payload
>   `verify` → 发现链。
> - **AssetsPanel 前端**：`components/chat/AssetsPanel.vue` 折叠面板（kind 过滤
>   +标题/正文检索+删除；meta 展示 文件数/验收状态/来源）挂 AnalysisChat
>   输入区上方；REST 补 `DELETE /assets/{id}`。
> - **A1 增强**：里程碑回执 ms_note 携带**验收状态**（verifyOverall A/B/
>   PASS_WITH_KNOWN/C/D/FAIL → 语义标注）与**边界规模**（allowedScope 总数、
>   本次并入数）；里程碑资产 meta 落 `verifyOverall`——事实→边界、状态→回执
>   双向回写闭环。

**门禁**（沿用）：`npm run test:py` / `test:fe` / `type-check`；runner 侧改动加 R2 fixture
与一致性套件；纯 KB 线先出设计小档再动码。

---

## 九、遗留评估文档未完成条目整合

> 2026-09-17 对 docs/ 下遗留评估/规划文档全面盘点，把与当前四线 + A6 方向一致的未完成
> 条目归位到本档条目。**排期不接管**（仍归原计划：roadmap / v2-todo / V 设计），只做
> 方向归位、合流裁决与状态核实（代码核实 = 2026-09-17 工作区快照）。

### 9.1 遗留文档盘点与处置

| 文档 | 状态 | 处置 |
|---|---|---|
| agent-structure-review-2609.md | 现行（09-15 快照） | 批次 C1/C3 已被本档 A1/A2 改道；批次 A/B 经代码核实**均未落地**（9.2）；批次 B 建议随 A6 上提优先级 |
| architect-v2-todo.md | 现行（09-13） | P0/P1/P2/P3 逐条归位（9.2）；P0-1/2 真机验证类不归本档 |
| product-iteration-roadmap-2026-09.md | **现行主线** | Phase 1~3 + L 组为排期真相源，本档只做条目归位 |
| runner-verify-gate-design.md | **设计定稿待实现** | V1~V5 成为本档 R3/K2/M3/A6 的实施蓝本（9.3 裁决①） |
| kb-unified-components-plan.md | Stage 0~4 已完成 | Stage 5 清理待办，保持 roadmap P1-T5 排期 |
| architecture-issues-0905.md | 部分完成 | A 类（测试安全网等）仍待办且是本档各线前置；D2 已失效（9.2） |
| architect-review.md | 历史快照（执行机制已退役） | 仍有效条目：god-file 拆分（=0905 B1）、codegraph 依赖显式化、MCP 出向落地——归卫生/生态线，保持原排期 |
| global-promotion-design.md | 设计定稿待实现 | G 提升 → 并入 K 线（9.3 裁决②关联） |
| local-small-model-finetune.md | 讨论归档 | 结论并入 roadmap L 组；L 组与本档 M 线合流（9.3 裁决③） |
| architect-ui-prototype-design.md | 整体规划 | 与 A6.2 Item 投影在会话流渲染面有交集，立项时对齐 |
| archive/plan-A、plan-B、0902、architect-reconstruction/* | 已归档/已落地 | 九层内核已落地为 `agent/`；不再整合 |

### 9.2 条目归位表（未完成 → 现行条目）

| 遗留条目（出处） | 归位 | 代码核实（09-17） |
|---|---|---|
| v2-todo 小问题：`[[NEED_INPUT]]` 回合标记契约评审（P3） | **A6.1**（文本契约 → ServerRequest 结构化，落地后删除该标记） | 仍在 |
| v2-todo 小问题：`_task_instruction` prior_brief 未接线（重试前情简报） | **A3**（交接切面连续性要素） | 未接线 |
| v2-todo P1：arch_assets 资产表 + asset.upsert/list/delete 工具面 + 可执行 skills + 轮后提取钩子（资产 draft 入库）+ AssetsPanel | **K2**（表设计复用 arch_assets 规划，不另起） | 仅 `knowledge.py` `search_assets` 只读端点；工具面/钩子未落地 |
| v2-todo P0-3：task_done 验收入口（worktree diff 按钮） | V5 验证矩阵消费面 | 待办 |
| v2-todo P3：codex app-server 接入实测 | **A6.1 的 N+1 演练**（codex 从文本标记契约迁统一通道 = 首个接入验证案例） | codex 适配器已有（文本标记），未走统一通道 |
| roadmap P2-T4：mandate 质量加固（符号可解析到 AstNodeRef） | **K4**（同源：锚定而非臆造的引用语义） | AST 锚点机制已有，mandate 勾稽未做 |
| roadmap P2-T6：G 提升（项目库→主库，global-promotion 设计） | **K1/K2**（主库提升对象 = 带版本知识资产；K1 设计时预留提升通道 schema） | 未实现 |
| roadmap P3-T1~T3：MCP 工具面做厚 / 接入文档 / 调用度量 | K 线「使用」闭环对外出口；P3-T1「工具描述面向外部 agent」= K4 语义 | 待办 |
| roadmap P2-T9 / 0905 D2：agent-bus 事件驱动化 | **决策正确、条目作废**：broker 随生命周期重构 v2（S0）退役——职责已被 S2 双收件人路由 + exec_bridge 泵 + waiting_input 吸收（与「单流+过滤器」基线一致，避免双消息机制并存）；`d2d10ee` 摘除注册（防崩溃重启环）、`arch_bus_messages` 已入 `_DROPPED_TABLES` 显式清除。**残留收尾两项**：① README:96/114/116 与 CONV-00 仍写 agent-bus /「10 进程」，实际拓扑为 9 进程，需回写（0905 A4 同类问题复发）；② P2-T9 建议正式关闭，消息面归宿 = A5/A6.1 | 已核实（git cf7fb08→5711708→376a999→d2d10ee） |
| structure-review 批次 A1（泵泄漏 try/finally） | 卫生（前置） | 泄漏清理未见；但 `recover_conv_tasks`/sweep 泵恢复机制已存在（cv-153），与 A5 durable 语义部分重叠 |
| structure-review 批次 A2（exec_bridge 收敛 RunnerClient）= G7 | **R1** | **未做**（exec_bridge 无 `_client`）——R1 成立 |
| structure-review 批次 B1~B4 | **A6.1/M1 前置**（B1 能力矩阵 = A6.1 降级路由依据；B4 单源化 = prompt 契约化前置） | **均未落地**（无 capabilities.py / test_agent_layering.py / reflection/pipeline.py / test_prompt_single_source.py）——建议优先级上提 |
| v2-todo P2：旧机制清退（exec_bridge jobs 账本 600 行=G8、websocket 规约域、req_agent propose/finalize/amend 物理删除、前端旧键） | 卫生（原则 7 失效代码即拆） | 待办 |
| v2-todo P0-5：t4 软提示不重判（模型切换 profiles 缓存不刷新） | **M1**（needsReprobe 既有 bug 佐证，随 M1 修复） | 待办 |
| roadmap L 组 L1~L7（微调专项） | **M 线训练侧**（9.3 裁决③） | 未启动（Phase 2 末排期） |
| roadmap P2-T10：L 级零 LLM 推广到管线 | **M2**（策略表增补「L 确定性层」档位，对齐 L/S/M/H 四级成本梯度） | 未做 |
| roadmap P2-T8：sidecar/runner 稳定性（崩溃恢复/超时/可观测） | R 线前置 | 待办 |
| 0905 A1 四步测试安全网 / A4「9 进程」文案 / 0905 B1~B3 巨型拆分 | 本档各线前置（安全网）与卫生线 | A4 五分钟项仍残留；其余按 roadmap §8 排期 |

### 9.3 三条合流裁决

1. **V 组 = 实施蓝本**：runner-verify-gate-design（V1~V5）与本档多线交汇——V5 验证矩阵
   = K2 回执的 schema 主体；V4 修复回注 / L3 升级换模型 = M3 分船的执行面（与 A4
   reject-带反馈同源）；R3 RunnerFailureRule 并入 V 组 L4 编排层实现；DONE 诚实化
   （V 设计 §8.3）= A6.1 `turn_completed` 反向请求的诚实性条款。V 组落地时本档条目
   不重复设计，按 V 文档实施并回写差异。
2. **arch_assets = K2 表基座**：v2-todo P1 的资产表规划（requirement/todo/plan/
   data_asset/analysis 五类 + 工具面 + 轮后提取钩子）是 K2「里程碑→KB 回写」的表设计
   基座，K2 立项时合并设计，不另起 KB 资产表。
3. **L 组 = M 线训练侧**：微调专项与本档 M 线互为表里——L6 模型路由（S 档自动选中）
   是 M3 分船的实现载体；§6.3 哑铃型模型成本曲线（大模型在头尾、小模型在腰）是 M 线
   理论依据；§6.5「结构化输出 + function-call 微调」与 M4 受限生成同向；十二b 能力探针
   = L4 评测门禁的管线级形态（探针评分对微调模型同样适用）。M2 策略表增补时预留
   S 档（微调模型）行，并与 L 档（确定性）对齐四级梯度。

---

## 附录 A：三项目详录（要点压缩）

### A.1 codex-rs v0.140.0（`/home/cuser/soft/codex-rust-v0.140.0`）

- **协议**：`protocol/src/protocol.rs`（Op 枚举 :494-648 / EventMsg :1180-1377 /
  AskForApproval :807-838 / SandboxPolicy :901-949）；`app-server-protocol/src/protocol/common.rs`
  （ClientRequest/ServerRequest/ServerNotification 声明式宏）；v2 按资源拆 27 文件
  （`protocol/v2/`）；Thread/Turn/Item 三原语（`app-server/README.md:64-72`）。
- **嵌入路径**：`initialize`→`initialized`→`thread/start`→`turn/start`→消费
  `item/*`+`turn/completed`；宿主应答 `item/*/requestApproval` 反向请求；`turn/steer`
  运行中注入；`outputSchema` 强制 JSON 输出；备选 `codex exec --json` / MCP 工具形态。
- **循环**：`core/src/session/turn.rs:137-411`（run_turn：pre-compact→注入→采样循环→
  auto-compact/新 context window）；`FuturesOrdered` 并发工具；重试耗尽 WS→HTTPS 传输降级
  （`core/src/responses_retry.rs:22-67`）。
- **沙箱/审批**：`SandboxManager`（`sandboxing/src/manager.rs`）统一
  Seatbelt/bwrap+seccomp/Windows restricted token；`safety.rs` assess_patch_safety；
  Starlark execpolicy；execve 级 shell-escalation。
- **持久化**：rollout JSONL（`rollout/src/recorder.rs`）——ResponseItem + TurnContext
  （每轮 cwd/approval/sandbox/model 随历史落盘）+ EventMsg；resume/fork/rollback 建立其上。
- **工程**：95 个 core 集成测试 + wiremock 挂 SSE mock；thiserror 领域错误 +
  anyhow 胶水；clippy deny unwrap_used；Cargo+Bazel 双构建（成本提示）。
- **不足**：core 16 万行过重；v2 协议面 100+ 方法且实验面大；WireApi 只剩 Responses
  （Chat Completions 硬移除，非 OpenAI 兼容后端受限）。

### A.2 opencode 1.17.9（`/home/cuser/soft/opencode-1.17.9`）

- **分层**：`packages/opencode/src/`（session/agent/tool/provider/server/plugin/project/bus/
  permission/lsp/snapshot...）+ `packages/core`（V2 durable session 双写过渡）。
- **server 面**：`server/routes/instance/httpapi/groups/session.ts:78-105`（prompt/abort/
  summarize/revert/fork/permissions 全套 REST）；SSE `GET /event`（instance 过滤 + 10s
  heartbeat + instance disposed 终止）。
- **权限**：`permission/index.ts` 三元组 findLast :39 / ask 挂起 Deferred :78 /
  always 级联 :120 / reject 带反馈 :132；bash tree-sitter pattern 提取 `tool/shell.ts:29`；
  MCP 工具整体一个 permission。
- **上下文**：`compaction.ts` + `overflow.ts`（usable = limit − reserved，保留 tail turns）；
  `tool/truncate.ts` 两级截断（内存 2000 行/50KB + 磁盘全量 7 天）；snapshot 隐藏 git 仓
  （`snapshot/index.ts`）支撑 revert/unrevert。
- **模型适配**：models.dev 目录（5min 磁盘缓存 + Flock 锁，`core/src/models-dev.ts:142-213`）
  作 limit/参数来源；`getSmallModel` 轻任务降档（title/summary/compaction）；按模型族选
  prompt 模板（`session/system.ts:25-39`）；StructuredOutput json_schema 强制输出
  （`session/prompt.ts:1295-1302`）；`agent.steps` 上限 + 末步 MAX_STEPS_PROMPT prefill
  （`session/prompt.ts:1231`）；校验失败 message 即"请重写输入"（`tool/tool.ts:24-34`）。
- **子 agent**：`tool/task.ts`（task_id 续跑同子会话；background 注入 synthetic
  task_result 自动续跑 :202-220；权限派生 `agent/subagent-permissions.ts`）。
- **嵌入通道**：`opencode serve` + SDK（`x-opencode-directory` 路由）；session 级
  permission 注入（`groups/session.ts:52`）；`OPENCODE_CONFIG_CONTENT` 内联配置最后合并
  （`config/config.ts:467-475`）；`permission.asked` 事件 → reply API。
- **不足**：V1/V2 双轨；Effect v4 beta；无模型 fallback 链；权限状态进程内不持久。

### A.3 deepseek-harness v0.1.0-rc3（`/home/cuser/soft/deepseek-harness-v0.1.0-rc3`）

- **事件溯源**：`packages/core/session/src/index.ts:708-747` deriveMessages；
  "Model-visible ⟺ logged"（`docs/architecture.md:94-97`）。
- **能力接缝**：Service Definition/Provider/Consumer 三角色（`docs/architecture.md:98-103`）；
  E2B POC 换 adapter 不换工具（`packages/e2b/README.md`）。
- **权限**：单调 ToolGuard（只能减权限）+ 审批 fail-closed（`docs/subsystems/approval.md`）。
- **重试即新 turn**：`packages/llm/llm-retry`（adapter 调用恒单次，失败 chunk 永不入派生消息）。
- **compaction 三事件锁**：start/summary/end，崩溃孤儿锁可检测
  （`docs/subsystems/compaction.md`）；KV cache 全链路自觉。
- **测试**：per-file 100% 覆盖门禁 + keyless 快照测试 + 「验证世界而非自述」
  （`docs/testing.md`）+ 生成物新鲜度 CI 门禁（`docs/tool-catalog.md`）。

### A.4 dsh v0.1.5-rc.2 增量（`/home/cuser/soft/deepseek-harness-dsh-v0.1.5-rc.2`）

- **agent-team（experimental）**：`packages/experimental/agent-team/src/`（types/mailbox/
  task-board/task-graph/journal/projection/roster/lifecycle/activity）；隐式根模型
  `TeamId = root SessionId`；4 种领域事件（member/task/message queued/delivered）；
  `foldTeam()` 重放恢复；durable 只存 `provisioning→active|failed`，running/idle/inactive
  为派生视图（`docs/subsystems/agent-team.md`）。
- **session 格式版本化**：见 K1；`docs/session-format-status.md` + 迁移链五包 +
  `session-turn-outline`（见 K3）。
- **API controller**：session-controller（requestId 回声/代际重连，见 R4）、
  settings-controller（引用视图无值槽位，密钥结构上不可回读）、workspace-controller、
  workspace-files（version 防陈旧）。
- **subagent.md 大扩**：4 provider（codex/claude-code/dsh-sdk/acp）；Continuable 子 agent
  三态派生；终止通知无条件投父；descriptor 持久化快照；outputSchema + diagnostic。
- **能力协商与异构编队**：subagent start 四 flag 能力协商（outputSchema/depthLimit/
  toolFilter/persona，缺失即 `UNSUPPORTED_CAPABILITY`）；v0.1.5 agent-team roster 成员级
  provider/model（`spawnTeammate request.provider`，`agent-team/src/roster.ts`）——异档
  编队先例。
- **credentials/authorization**：flow 注册表 + 必须提交才 authorized + 拒绝是结果不是错误；
  headless 默认惰性。
- **native/system**：Landlock launcher + POSIX flock 绑定；Windows ACL 后端
  （`subprocess/win32-process`，kill-on-close Job Object）；`SandboxEnforcement full|partial`；
  RunnerFailureRule（见 R3）。
- **postmortem 4 篇**：0001 插件导出规范 + keyless 真 Loader 测试；0002 快照刷新是
  fixture 生产不是正确性审查（需独立语义断言）；0003 运行时身份模型可见（见 A3）；
  0004 失败归因分类（见 R3）。
- **其他**：SAFETY.md（沙箱/审批只是减险不是隔离保证）；benchmarks/（5 场景）；
  `fs/tool-present`（产出文件声明为交付物）；client-resources（`dsh-resource://` 协议-
  提供者-地址模型 + 四态快照）；conversation.md（(kind,id) 稳定 id 装配层）。

---

## 附录 B：评估方法与证据约定

- 证据路径为 2026-09-17 快照；行号引用对应上述四个检出目录。
- 三次分析会话：codex/opencode/dsh-v0.1.0 深度走读、dsh-v0.1.5 目录 diff + 增量深读、
  产品基调过滤裁决（KB 线/本地模型分层调度线/编排线/契约卫生线四线 + 剔除清单），合并入本档。
- 本档为纯分析文档；立项时各条目需按第八节顺序出实施小档（对齐 CONV-00 分工矩阵）。
