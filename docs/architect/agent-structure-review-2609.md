# Architect Agent 结构评估与优化计划（主 agent + coding subagent）

> 日期：2026-09-15 · 性质：架构评估文档（纯分析，未改代码）
> 范围：`apps/architect/topoone_app_architect/agent/`（九层内核）、`arch_routes/exec_bridge.py`、
> `agent/execution/{pumps,runner_client}.py`、`arch_routes/req_agent.py`（工具面）、
> `packages/core/topoone/plugins/runner/`（coding subagent 执行器侧）。
> 状态注记：**agent 功能正在建设中，随时会有变动**——本评估以当日代码为准，文件行号为 2026-09-15 快照。

---

## 一、架构全景

```
用户 ⇄ WS/SSE
  │
┌─ architect 主 agent（进程 :3470）───────────────────────────────────┐
│ agent/orchestrator.py  handle_chat()  ← 回合编排（867 行）           │
│   gate(会话闸门) → router(收件人路由) → cognition(LLM 流式循环 ≤4轮)  │
│   → tools([TOOL_CALL] 文本协议执行) → fence(提案/任务围栏代落)        │
│   → reflection(防编造/意图/纠偏守卫) → persist(单流落库)              │
│ 九层: perception / cognition / planning / memory / tools             │
│       / execution / reflection / collab / governance                 │
└──────────────────────────────────────────────────────────────────────┘
        │ task.propose（LLM 工具→任务卡 pending_confirm）
        │ 用户确认 confirm_task → POST /api/implement
        ▼
┌─ coding subagent（runner :3458 + agent-sidecar Node）───────────────┐
│ TurnAdapter 协议（OpenCode / Cline / Codex 三实现）                  │
│ events 单源 schema → WS 实时订阅 + snapshot 轮询校准                  │
│ 纯下行泵: 事件→会话消息(agent=executor)，用户回复经 task_input 转达    │
└──────────────────────────────────────────────────────────────────────┘
```

**分层纪律**：主 agent 内核（`agent/`）声明单向依赖，`arch_routes/*.py` 为契约冻结的适配层
（CONV-04）；兼容 shim（ws_events/llm_dataset/model_profile/… re-export）保持存量 import
与测试 monkeypatch 接缝，撤除待外圈调用方迁移。

**子代理解耦**：经 HTTP `/api/implement*` + WS `/events` 与 runner 解耦；
`packages/core/.../runner/events.py` 是跨进程事件 schema 单源；`arch_tasks` 表为任务
生命周期一等公民（pending_confirm → running → waiting_input → 终态）。

---

## 二、完整性评估

### 已建成（完整度较高）

- 主 agent 回合管道六段式齐全；降级链完备（ZMQ 流式 ↔ llm.sync；断流 idle 超时、
  空响应、客户端断连均有兜底，`orchestrator.py:35/360/492-505`）。
- 子代理任务生命周期一等公民 + 同会话互斥（`exec_bridge.confirm_task:249`）+
  文件边界互斥（`governance/boundary.py`）+ 验收简报越界检测（`exec_bridge:133`）。
- 三执行器（cline/opencode/codex）能力分派 + 内省面
  （messages/usage/checkpoints/restore/model/approval/pending/proceed 全通）。
- 事件系统 schema 单源（core `events.py`）；统一会话单流，`agent=executor_type`
  标注区分 architect/subagent 回执。

### 结构性缺口

| # | 缺口 | 位置（快照） | 影响 |
|---|---|---|---|
| G1 | **默认执行器不一致**：4 处代码回退 `"opencode"`，注册表却标 cline 为 default | `exec_bridge.py:209`、`task_plan.py:110`、`store/tasks.py:43`、`db_schema.py:233` vs `agent_executors.DEFAULT_EXECUTORS` | 未显式绑定执行器的任务落到 opencode，与「cline 为默认」决策矛盾（→ 见 §六，仅记录） |
| G2 | **子代理→主 agent 无结构化回路**：泵纯下行（裁决#6.1），`input_required` 仅落消息，主 agent 不被唤醒 | `exec_bridge._handle_task_event:508` | 多 agent 协作停留在人工往返 |
| G3 | **主 agent 回合不可取消**：仅 60s idle 降级，无主动取消帧；subagent 有 stop(REST) | `orchestrator.py:35` | 与 subagent 不对称 |
| G4 | **无能力矩阵/注册表单源**：执行器类型字符串散落 4+ 处 | `exec_bridge:325`、`sessions:1254`、`task_plan:107`、`_build_workspace_files:460` | 加第 4 个执行器需改 7+ 处 |
| G5 | **任务泵句柄泄漏**：`_TASK_PUMPS` 仅 `task_stop` 弹出，正常 done/failed 不清理 | `exec_bridge.py:436`（写）、`:390`（唯一清理点） | 长会话累积已完成任务泵条目 |
| G6 | **双聚合逻辑**：workState 两套 | `exec_bridge:86`（jobs 账本）与 `:420`（arch_tasks） | 状态漂移风险 |
| G7 | **RunnerClient 形同虚设**：exec_bridge 6 处裸 `_runner()`，类型化封装仅 exec_cline 使用 | `exec_bridge.py:28/181/295/349/362/387`；`runner_client.py` 仅 `exec_cline.py:20` 构造 | 契约漂移、测试接缝分裂 |
| G8 | **遗留只读账本**：`conv.meta.jobs` 与 `arch_tasks` 双模型并存 | `exec_bridge:25/65-92` | 维护成本 |

---

## 三、拓展性评估

### 良好接缝（保持）

- **TurnAdapter 协议**（runner 侧）：新增子代理执行器只需实现 `run_turn/steer/内省`，
  能力分派自动降级——全链最干净的一层。
- **events schema 单源**：core `events.py` + architect `runner_client.parse_event` 消费。
- **Prompt Registry**（`cognition/prompt.py`：块化/priority/预算裁剪/override 通道）+
  **策略矩阵**（`cognition/strategy.py`：tier→策略集）。
- **Store 抽象 + 按项目库路由**（`store/base.py`；`TasksStore.of_conv` 经会话行路由同库）。

### 摩擦点

- **工具协议是文本 `[TOOL_CALL]`**（`tools/protocol.py` 正则 + 围栏容忍 + 未闭合块解析），
  无原生 function calling。为兜底堆叠的补偿机制是**复杂度最大来源**：
  实时转发状态机 `_LiveForward`（`orchestrator.py:49-108`）、proposal/task 围栏代落
  （:511-551）、通用任务路由纠偏（:553-580）、意图守卫（:582-613）、防编造守卫
  （:615-673）、参数修复外循环（`reflection/repair.py`）。模型每换档/换版就可能新增守卫。
- **工具文档双源**：`_ARCH_TOOLS` 注册表 vs `_CAPABILITY_DOC`（`req_agent.py:1490`）；
  `prompt.py:100` 的 `single_source` 模式可消除漂移但默认 off（"P3 实测调优时切换"）。
- **Prompt 文本散落**：能力路由 system（`orchestrator:310-327`）、挡位指引
  （`prompt.gear_guidance`）、任务指令（`task_plan:155-189`）、subagent 指派契约
  （`router:62-66`）分散在多层。
- **`handle_chat` god function**：`orchestrator.py:185-707` 约 520 行，10+ 内联
  try/except 与业务分支混排，难测难改。
- **分层边界无强制**：仅注释声明，无 import-linter/架构测试；`req_agent` 作为
  monkeypatch 总线是事实上的中心耦合点。
- **内核层测试稀疏**：orchestrator 1、tools 2、execution 2 个测试文件；
  perception/planning/memory/reflection/collab/governance **0** 个专属测试
  （行为多由 test_kb_chat_routing / test_fabrication_guard / test_exec_implement 间接覆盖）。

---

## 四、问题清单（分级汇总）

### P0 正确性/一致性
1. 泵句柄泄漏（G5）
2. exec_bridge 绕过 RunnerClient（G7）

### P1 架构健壮性
3. 能力矩阵无单源（G4，含 `"cline-sdk"` vs `"cline"` 别名不一致风险）
4. 分层边界无强制测试
5. `handle_chat` 拆解（god function）
6. 工具文档双源（single_source 未启用）

### P2 能力拓展（产品级，需拍板）
7. 子代理→主 agent 结构化回环（G2）
8. 主 agent 回合取消（G3）
9. 多 agent/团队模型（同会话单活跃互斥限制扇出）
10. 内核层补测

### 仅记录、不处理（已裁决 2026-09-15）
- **默认执行器不一致（G1）**：代码 4 处回退 `"opencode"`，注册表 default 标 cline。
  作为已知问题记录，本轮不修改代码、不统一口径。
- 双 workState 聚合（G6）、遗留 `conv.meta.jobs` 只读账本（G8）：属既有设计，
  暂不动（待旧账本自然退役）。

---

## 五、优化计划（批次 A/B/C）

### 批次 A — 正确性修复（P0，低风险，优先）

#### A1. 修复任务泵句柄泄漏
- **改动**：`exec_bridge.py`
  - `_task_pump(...)`（:596）用 `try/finally` 包裹，finally 中：
    `_TASK_PUMPS[conv_id].pop(job_id, None)`；jobs 空则弹 conv 层条目。
  - `on_lost`/`on_finished` 不需单独清理（finally 统一）。
- **测试**：新增 `test_exec_bridge_pump_cleanup.py`
  - 事件流到 done → 断言 `_TASK_PUMPS` 该 conv/job 条目移除；
  - on_lost 路径 → 同样清理；
  - `task_stop` 路径回归不破。
- **验证**：architect 测试子集全绿。

#### A2. exec_bridge 收敛到 RunnerClient
- **改动**：
  - `runner_client.py`：`input()` 增补 `steer: bool = False` 参数
    （当前 `task_input` 直接传 `{"text", "steer": True}`，:362-366）。
  - `exec_bridge.py`：模块级 `_client = RunnerClient(_runner)`（`_runner` 仍是 transport，
    现有 `monkeypatch.setattr(eb, "_runner", ...)` 接缝不变）；
    替换 5 处调用：
    | 行 | 现调用 | 改为 |
    |---|---|---|
    | :181 | `_runner(f"/api/implement/{id}/finish", …)` | `_client.finish(job_id)` |
    | :295 | `_runner("/api/implement", payload, 20.0)` | `_client.start_implement(payload)`（消费 StartResult 字段 `.ok/.job_id/.branch/.worktree/.session_id/.error`） |
    | :349 | `_runner(f"…/approval", …)` | `_client.approval(...)` |
    | :362 | `_runner(f"…/input", {"text", "steer"})` | `_client.input(job_id, text, steer=…)` |
    | :387 | `_runner(f"…/finish", …)` | `_client.finish(job_id)` |
  - `governance.boundary.check_mutex` 仍传 `runner=_runner`（path-callable 接口不同，保留）；
    `pumps.run_event_pump` 的 `runner` 实参保持 `_runner`。
- **风险**：`StartResult.error` 文案需与旧兜底 `"runner 服务不可达(:3458)"` 一致
  （runner_client 已内置同文案）。
- **测试**：现有 `test_exec_implement.py` / `test_exec_bridge_events.py` 全绿即证接缝未破。

### 批次 B — 架构健壮性（P1）

#### B1. 执行器能力矩阵单源
- **新增**：`topoone_app_architect/agent/execution/capabilities.py`
  ```python
  CAPABILITIES = {
    "cline":    {"multi_turn": True, "approval": True,  "checkpoint": True,
                 "readonly_hard": True,  "steer": True,
                 "workspace_rules": ".cline/rules", "workspace_agents": ".cline/agents"},
    "opencode": {"multi_turn": True, "approval": False, "checkpoint": False,
                 "readonly_hard": False, "steer": False, "workspace_rules": "AGENTS.md"},
    "codex":    {"multi_turn": True, "approval": False, "checkpoint": False,
                 "readonly_hard": True,  "steer": False, "workspace_rules": "AGENTS.md"},
  }
  def executor_types() -> list[str]: ...
  def is_valid_type(t: str) -> bool: ...
  def caps(t: str) -> dict: ...        # 含 "cline-sdk"→"cline" 别名归一
  ```
- **替换点**：`exec_bridge.task_set_executor:325`、`sessions.py:1254`、
  `task_plan.propose_task_tool:107` 的元组成员判断 → `is_valid_type`；
  `_build_workspace_files:460` 的 `if executor_type == "cline-sdk"` → `caps(t)["workspace_rules"]`。
- **⚠️ 关键注意**：注册表 type 用 `"cline-sdk"`，任务行 `executorType` 用 `"cline"`——
  capabilities 必须显式做别名归一，否则 P5 workspace 规则映射回归。这是本项最大风险点。
- **保持**：默认回退 `or "opencode"` 语义不动（G1 仅记录）。
- **可选**：`agent_executors.py` 暴露 `GET /agent/executor-types` 供 UI 下拉动态化。
- **测试**：新增 `test_executor_capabilities.py`（类型集合/别名/workspace 映射）。

#### B2. 架构分层边界测试
- **新增**：`apps/architect/tests/test_agent_layering.py`（纯 stdlib `ast`，零新依赖）
  - 规则1：`agent/**` 不得 import `arch_routes/*`（内核不得反向依赖适配层）；
  - 规则2：层序 `perception < cognition/planning/memory/tools < execution < reflection`，
    低层不得 import 高层；`collab/governance` 为横切白名单；
  - 规则3：`agent.orchestrator` 例外（顶层编排可 import 各层）；
  - 失败输出违规 import 链；首次落地先记录存量违规，确有必要的进白名单并注明。
- **价值**：B1 的别名/引用改动由它护住。

#### B3. 拆解 `handle_chat`
- **新增**：`agent/reflection/pipeline.py`，四个守卫/围栏搬为纯函数（deps 回调注入）：
  - `apply_fences(final_content, tools_used, run_tool_cb, ctx) -> (content, extra_meta)`
    （搬 :511-551 proposal/task 围栏代落）；
  - `apply_routing_guard(...)`（搬 :553-580 通用任务纠偏）；
  - `apply_intent_guard(...)`（搬 :582-613 意图追问）；
  - `apply_fabrication_guard(...)`（搬 :615-673 防编造 → guard_meta，含编号笔误更正分支）。
- **目标**：`handle_chat` 只留 gate→route→LLM 循环→pipeline→persist，降到 ~300 行。
- **纪律**：行为保真逐块搬迁；现有 `test_fabrication_guard.py` / `test_kb_chat_routing.py`
  必须持续全绿。
- **测试**：新增 `test_reflection_pipeline.py`（四函数输入→输出契约：围栏代落、编号更正、
  推诿纠偏、编造拦截、failed_try 区分）。

#### B4. 工具文档单源化（保守两步）
- **第一步（本轮）**：保持 `single_source` 默认 off；新增等价性快照回归测试
  `test_prompt_single_source.py`——开启 override 渲染 vs `_CAPABILITY_DOC`（`req_agent.py:1490`）
  做「工具名集合 + 协议段」等价断言。
- **第二步（择期）**：等价成立且关键工具描述覆盖后，默认切 on（文案差异影响模型行为，
  必须有快照兜底再切）。

### 批次 C — 能力拓展（P2，需产品拍板后再细化）

#### C1. 子代理 → 主 agent 结构化回环（G2）
- **方案（半自动，低风险）**：`input_required`/`done` 事件时后台调一次 architect 轻上下文
  （`req_agent.llm_sync`）生成「建议回复/审阅意见」草稿消息（`meta.kind=agent_draft`），
  仍由用户确认发送。
- **决策点**：是否要全自动回环（architect 直接回 subagent 无人工确认）——涉及审批与失控风险。

#### C2. 主 agent 回合取消（G3）
- **方案**：WS 增 `{type:"cancel", requestId}` 帧；orchestrator 维护
  `_inflight: {requestId: asyncio.Task}`，取消传播 `CancelledError` 进 `_iter_llm_events`，
  补 `error/aborted` 事件与落库。
- **决策点**：取消时已生成文本是否保留落库。

#### C3. 多 agent / 团队模型
- **现状约束**：同会话单活跃任务强互斥（`confirm_task:249`）；cline teams 仅透传配置，
  architect 无团队语义。
- **方案（大工程，建议单独立项）**：`arch_tasks` 增 `parent_task_id`/`depends_on`
  支持顺序/并行扇出 + 汇总；或独立 `teams` 表。

#### C4. 内核层补测（可与 B 并行）
为 `perception`(router/gate)、`planning`(task_plan)、`governance`(boundary) 补契约测试，
固化现有行为（不加新行为）。低成本，显著提升 B3 拆解安全垫。

---

## 六、落地顺序与门禁

```
第1步  A1 → A2            （P0，回归面最小，先做）
第2步  B2 → B1 → B4 → B3  （B2 边界测试先立，B1 靠它护住别名风险）
第3步  C4                 （补测打底）
第4步  C1/C2/C3           （需产品确认后单独立项）
```

每步门禁：`npm run test:py`（全仓）、`npm run test:fe`、`npm run type-check`。
批次 A/B 不涉 sidecar/runner 代码，无需重建 dist。

---

## 附：关键文件索引（2026-09-15 快照）

| 文件 | 行数 | 角色 |
|---|---|---|
| `agent/orchestrator.py` | 867 | 回合编排（handle_chat god function 所在） |
| `arch_routes/req_agent.py` | 2001 | 工具执行环/围栏提取/守卫判定（monkeypatch 总线） |
| `arch_routes/exec_bridge.py` | 744 | 主 agent ↔ runner 任务桥（泵/生命周期/事件落流） |
| `agent/execution/pumps.py` | 125 | 单一事件泵（WS 订阅优先 + snapshot 校准） |
| `agent/execution/runner_client.py` | 164 | 类型化 runner 访问端（当前仅 exec_cline 使用） |
| `agent/tools/protocol.py` | 143 | `[TOOL_CALL]` 文本协议解析 |
| `agent/governance/boundary.py` | 77 | 交托边界解析 + 全局作业互斥 |
| `agent/planning/task_plan.py` | 190 | 任务卡围栏提取 + 指令组装 |
| `agent/cognition/prompt.py` | 278 | Prompt Registry（块化/预算/single_source） |
| `arch_routes/store/tasks.py` | 119 | arch_tasks 存储 |
| `packages/core/.../runner/turn_adapter.py` | ~1500 | 三执行器适配器（子代理侧核心） |
