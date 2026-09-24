# TopoCode Architect 子系统架构评估文档

> 范围：`apps/architect/` —— 前端 `@topo/app-architect`（`src/`）+ 后端 `topoone_app_architect`（:3470）+ `agent_bus`（:3486）
> 代码基线：分支 `dev-1`（提交约 2026-08-30）
> 关联文档：`docs/archive/architecture-issues-0902.md`（全仓四维度评估，本文是其 architect 专项展开，已归档）；`docs/architect-ui-prototype-design.md`（architect UI/UE + 原型生成能力整体规划）
> **历史快照提示**（2026-09-11）：本文基于 2026-08-30 基线。文中描述的 plans/exec tasks 状态机、SE 任务树派发等执行机制已退役（现行为 `execution.py` 会话驱动制，见 `exec_bridge.py`）；现行迭代方向以 [product-iteration-roadmap-2026-09.md](product-iteration-roadmap-2026-09.md) 为准。
> 性质：**仅评估与修正方向，不含任何代码改动**
> 更新日期：2026-09-02

---

## 1. 定位与画像

architect 是 4 个子项目中**体量最大、最"自成体系"**的一个，也是离"独立产品"最近的一块。

| 维度 | 规模 |
|---|---|
| 后端代码量 | **21,327 行 Python**（`arch_routes/` 下数十个模块，其中 **25 个挂载为 FastAPI 路由**，其余为 store/ctx/common/网关/tagent 等支撑模块） |
| 最大单文件 | `semantic_assets.py` **5555 行**、`store.py` 1834、`req_agent.py` 1423、`websocket.py` 729、`db_schema.py` 682 |
| 前端 | 14 页 / 53 组件 / **34 service** / 16 store / i18n 2 文件（en-US 1763 行 + zh-CN 1788 行） |
| 数据 | `architect.db` 独占 **36 张 `arch_*` 表**，按项目路由 `architect/<pid>/arch.db` |
| 后端测试 | **28 个测试文件**（全场最完整；对比 docs/chat 前端无单测、workbench 仅 1 个 smoke） |
| 端口 | architect `:3470`（kind=service）+ agent_bus `:3486`（独立 broker 进程） |

**领域定位**：工作实践导向。把 KB（学习研究导向）解析出的架构资产，转化为可执行的工程闭环：**需求提案 → 需求池(概要设计) → 任务执行 → 单元测试**（`src/config/workflow.ts` 的 4 阶段 stepper）。

---

## 2. 架构剖析

### 2.1 进程与入口
- `__main__.py`：加载项目根 `.env`，uvicorn 起 :3470，注入 `KB_BASE_URL` / `MCP_BASE_URL`，显式提升 `arch_routes.*` 日志级别。
- `server.py:build_app(data_dir, kb_url, mcp_url)`：独立 FastAPI 应用，
  - `ProjectContextMiddleware`（server.py:35-70）：解析 `?project=` / `?root=` → `_resolve_project` → `ctx.set_project(pid)`（contextvar）→ **按项目路由 arch.db**；WS 不经查询串，由 WS 处理器按首条消息显式 `set_project`。
  - CORS 放行 dev(5173/5174) + 反代(3456)；挂载 SPA 静态（`/web` + `/architect.html`）。
- 与 chat/docs 同款独立进程模型（M13），由 `apps/architect/manifest.toml`（kind=service）经 supervisor 拉起。

### 2.2 数据模型（36 张 `arch_*` 表，独占 architect.db）
覆盖：项目/需求/蓝图/规格（`arch_projects/requirements/blueprints/specs/plans`）、**语义资产**（`arch_semantic_assets/semantic_refs/ast_cache`）、契约/验收（`arch_contract_items/packages/acceptance_*`）、命名治理（`arch_naming_conventions/name_tombstones/glossary`）、执行/任务树（`arch_execution_tasks/task_trees/staging_scans`）、单元测（`arch_unit_tests/_sessions/_messages`）、会话/消息（`arch_conversations/_messages/agent_sessions/agent_messages`）、**agent 总线**（`arch_bus_messages`）、MCP 审计（`arch_mcp_calls`）、KB 快照（`arch_kb_snapshots/snapshot_records`）等。
- 归属清晰：architect 独占，无跨库直连（承 CONV-04 数据归属表）。

### 2.3 核心大脑
- **`semantic_assets.py`（5555 行）— 自持语义数据资产提取/检索**（差异化核心）：
  - 二维正交分类：`kind(entity/contract/state/rule/process/decision)` × `level(business/logic/implementation)`；静态(是什么) / 动态(发生什么) 两轴。
  - **符号源：目标项目 `.codegraph/codegraph.db`**（58 处引用），提取前跑 `codegraph sync` 保鲜，缺失降级为轻量文件扫描；KB `architecture.model` 仅作组件归属/baseline 上下文。
  - 分级成本策略：**L 级确定性提取（零 LLM，代码事实层）/ M 级 LLM 按组件归纳（逻辑层）/ H 级按需聚合（业务层）**。
  - AST 锚点：LLM 以符号名引用 → 服务端按符号表解析为真实 `AstNodeRef(file/symbol/kind/startLine/endLine)`，**杜绝臆造行号**。
  - 增量：同范围重提 `src_hash` 比对，`change ∈ same|added|modified`，旧资产标 stale。
  - LLM 不可用 → 启发式降级（L 级确定性映射 / 描述=docstring/签名摘要）。
- **`req_agent.py`（1423 行）— 自持 harness/skills/tools 的需求分析 agent**（不经主后端 provider 注册）：
  - skills（`@register_architect_skill`）、tools（经 KB `/zmq/architecture.model` 拉真实资产 + kb_gateway/MCP）、harness（`clarify`/`collect` → `llm.sync` → 结构化产出）。
  - 降级：KB/LLM 不可达、未配置、解析失败 → 空结构/None → 回退 `requirements.py` 既有 heuristic，前端 turn 协议不变。

### 2.4 对外集成（全部 HTTP 网关，拓扑无关 + 优雅降级）
| 网关 | 目标 | 通道 | 降级 |
|---|---|---|---|
| `KbGateway`（kb_gateway.py） | KB :3459 | `call()`→`/zmq/{method}`（RPC）；`query()`→MCP（**预留未用**） | 不可达/超时→`None`→mock/heuristic；业务错→`KbError` |
| `RunnerGateway`（runner_gateway.py） | runner :3458 | 任务树 `submit/get/update/rejudge/run/skip/retry/pause/resume/cancel` | 不可达→`None/False`；进度经 runner WS 直连前端 |
| `agent_bus.py`（独立 :3486） | 自身 broker | `arch_bus_messages` 单表轮询 + WS 推送 + asyncio 分发（按 `to/topic`） | 尽力而为推送，失败踢除 |
| `mcp_collab.py` | **入向** MCP | 外部 agent → KB mcp(3460) → 转发进 architect `/mcp/calls`，记 `arch_mcp_calls` | — |

> **MCP 方向现状**（kb_gateway.py:13-15 自注）：当前生效的是 **入向**（外部→architect）+ RPC 出向；architect→KB 的 **MCP 出向 `query()` 为预留、尚无路由消费**。

### 2.5 LLM 复用（零状态）
不跑自己的 LLM provider：`req_agent` 经 `KbGateway.call('llm.sync')` 转发主后端 `/zmq/llm.sync`；模型 `arch_collab_config.llm.modelId` 优先，否则主后端默认兜底；**写日志/用量审计由主后端完成，architect 零状态**。

### 2.6 前端结构
- 34 service（`api-client.ts` + `ws-client.ts` + `backend.ts` + ~30 领域 service）——**自带一套传输，几乎不复用 web-core 传输层**。
- 16 store；i18n 2 大文件，`src/i18n/index.ts:7` **初始 `locale: 'zh-CN'` 硬编码**（用户选择经 `useArchSettingsStore.initLocale()` 后置应用）。
- **半共享 web-core**：6 处 import `@topo/web-core/topoOne*`（`useDiagramRenderer`→`useTopoRender`、`ChatMessageBlocks`/`SemanticGraphView`→`TopoDiagram`、`contract-service`/`parse-message-blocks`→`core/types`、`AcceptancePanel`→`toMermaid`），但传输/i18n 各自独立。
- 死依赖：`package.json` 声明 `cytoscape`+`cytoscape-cose-bilkent`+`marked`+`marked-highlight`，src 一处未 import（承 0902 评估 R5）。

### 2.7 工作流（`src/config/workflow.ts`）
4 阶段 stepper（声明式，顺序即展示顺序）：`pool(需求提案)` → `design(需求池/概要设计)` → `execute(任务执行)` → `accept(单元测试/验收)`，每阶段带 `matches`（路由匹配）+ `isDone`（完成判定）。

---

## 3. 评估：优点

1. **对 core 的耦合极小且正确**：后端仅 import `topoone.db.manager`(×2) + `topoone.http_logging`(×1)，**从不 import core 引擎**，对 KB 一律走 HTTP（KbGateway）。这是 CONV"进程边界=数据边界、跨进程走 RPC/HTTP"的教科书式落地，**比 workbench（kind=core，物理住进 kb 进程）干净得多**。
2. **拓扑无关 + 优雅降级**：Kb/Runner/bus 全用 env 可配 URL + 不可达降级 mock/heuristic。天然契合"未来进一步拆分/完全独立"的战略。
3. **数据归属清晰**：36 张 `arch_*` 表独占 `architect.db`，按项目 contextvar 路由，无跨库直连。
4. **后端测试全场最完整**：28 个测试文件，覆盖语义资产/契约验收/需求会话/单测生成/命名治理/bus 等。
5. **语义资产内核设计扎实**：正交分类 + codegraph 锚定（无臆造行号）+ 分级 LLM 成本 + 增量 hash + 启发式降级，是产品差异化核心，设计成熟。

---

## 4. 评估：问题与风险

| # | 问题 | 证据 | 严重度 |
|---|---|---|---|
| A1 | **god-file**：`semantic_assets.py` 5555 行，混装分类法 + codegraph 抽取 + LLM 编排 + AST 解析 + 增量 hash + FastAPI 路由；`store.py` 1834、`req_agent.py` 1423、`websocket.py` 729 | `arch_routes/semantic_assets.py` 等 | 🔴 可维护性最高风险 |
| A2 | **隐性硬依赖 codegraph**：语义资产符号源为目标项目 `.codegraph/codegraph.db`，提取前跑 `codegraph sync`（58 处引用），缺失降级"轻量文件扫描"；该外部工具**未见于 README 技术栈 / CONV 规约** | `semantic_assets.py:13,16` | 🟠 未文档化的脆弱依赖 |
| A3 | **表面积过大**：25 路由 + 36 表 + 34 前端 service + 16 store，"工作实践"广度（需求/设计/契约/验收/命名/单测/MCP/git/bus）已是一个独立大系统，特性蔓延风险高 | `arch_routes/`、`db_schema.py` | 🟠 复杂度 |
| A4 | **"agent" 命名 sprawl**：`req_agent` / `tagent_{chat,se,extract,utgen}` / `agent.py` / `agent_roles.py` / `agent_bus` 五套并存，语义边界模糊 | `arch_routes/` | 🟡 易混淆 |
| A5 | **前端半共享最差态**：import web-core `topoOne`/`DiagramViewer`/`useTopoRender`，却 fork 传输（`api-client`/`ws-client`/`backend`）+ i18n（`index.ts:7` 硬编码 zh-CN）。与"完全独立"战略冲突 | `src/services/`、`src/i18n/index.ts:7`、6 处 topoOne import | 🟠 战略冲突（承 issues F3） |
| A6 | **MCP 出向未落地**：`KbGateway.query()` 文档自注"预留、尚无路由消费"；当前生效 RPC 出向 + 入向 MCP。与"architect↔其他 app 走 MCP"战略有落差 | `kb_gateway.py:13-15` | 🟡 战略-现状落差 |
| A7 | **agent_bus 归属外溢**：architect 代码跑在第 10 个进程、共享 architect.db；manifest 注释"全局主库表" vs "共享 architect.db"矛盾（承 issues C7）——architect 第一个"裂出去"的碎片 | `agent_bus.py`、`apps/agent-bus/manifest.toml` | 🟡 归属含糊 |
| A8 | **前端零测试**：53 组件 / 34 service 的庞大前端无任何前端单测（`package.json` 无 test script，仅 typecheck） | `apps/architect/package.json` | 🟠 覆盖缺口 |
| A9 | CORS 硬编码 dev 端口(5173/5174)+3456，默认面向 dev 联调，生产靠 3456 反代 | `server.py:25-32` | ⚪ 轻微 |

---

## 5. 对照战略（半独立 → 可能完全独立 + MCP 互调）

**利好**：网关化 + 强降级 + 最小 core 耦合，意味着 architect 已"预拆分"好 —— 进一步独立（乃至独立 repo）的**后端改造成本很低**。

**走向"完全独立 + MCP"前的三个前置缺口**：
1. **前端解耦（A5）**：要么把 `topoOne` 内核抽成 architect 也依赖的**独立内核包**，要么彻底切断 web-core import；停在半共享最不利（共享面改动牵动 architect，fork 面各自漂移）。
2. **codegraph 依赖显式化（A2）**：写入技术栈/规约，或把"codegraph 缺失降级"提升为一等公民路径；否则独立部署时语义资产质量会**悄悄变差**。
3. **MCP 出向落地（A6）**：若战略是 architect↔KB/runner 走 MCP，需真正接上 `KbGateway.query()`；或明确"RPC 为主、MCP 为对外扩展"的分层，避免战略与实现两张皮。

**建议的拆分顺序**（A1 god-file 拆分是前置条件，否则拆不动）：
`agent_bus`（已在裂）→ **语义资产内核**（`semantic_assets` + codegraph 抽取，可独立成"资产引擎"包）→ 需求/执行 agent。

---

## 6. 结论

architect 是**后端架构最干净、前端最"半独立"、单文件最臃肿**的子项目：它离"独立产品"的战略最近，网关化与降级设计已为此铺好路；但 `semantic_assets.py` 这个 5555 行的 god-file（A1）、未文档化的 codegraph 硬依赖（A2）、以及前端半共享态（A5），是走向"完全独立 + MCP"前必须先处理的三块硬骨头。

> 本文档为评估记录，不构成已实施的变更；上述"修正方向"待后续单独立项推进。
