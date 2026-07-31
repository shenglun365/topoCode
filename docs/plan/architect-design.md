# TopoCode Architect 设计文档（含与主应用交互方案）

> 文件名: `docs/plan/architect-design.md`
> 版本: v1.4（草案）| 日期: 2026-07-31
> 关联: `docs/plan/phase5-coding-agent.md`（Coding Agent 编排）、`docs/plan/restructure-plan.md`（四子系统规划）
> 状态: 设计讨论结论汇总，待定决策点见 [§10](#10-待定决策点)

---

## 目录

1. [背景与目标](#1-背景与目标)
2. [总体架构：三组件 + 一层接口](#2-总体架构三组件--一层接口)
3. [知识库基线模型（architect 的底座）](#3-知识库基线模型architect-的底座)
   - 3.1 基线 / 工作区暂存 / 重基线
   - 3.2 增量机器（分级闸门 + 分层增量 + 硬约束 + 懒重解释）
   - 3.3 人工覆盖层（community_overrides）
   - 3.4 增量日志与 diff 视角
   - 3.5 增量合并（Merge）模型
4. [Architect 本体设计](#4-architect-本体设计)
   - 4.1 双向架构定位（Mode A 编排 / Mode B MCP）
   - 4.2 职责与边界
   - 4.3 架构规约（Architecture Spec）
   - 4.4 任务编排流（Mode A）
   - 4.5 合规校验引擎
   - 4.6 模块划分
5. [Architect ↔ TopoCode 主应用交互方案](#5-architect--topocode-主应用交互方案)
   - 5.1 通信形态
   - 5.2 MCP 接口清单
   - 5.3 rebaseline 握手协议
   - 5.4 工作区层 vs 基线层
   - 5.5 认证、权限与人工门控
   - 5.6 契约版本化
6. [数据流闭环](#6-数据流闭环)
7. [人工确认门与安全护栏](#7-人工确认门与安全护栏)
8. [与现有代码的落地映射](#8-与现有代码的落地映射)
9. [实施路线](#9-实施路线)
10. [待定决策点](#10-待定决策点)

---

## 1. 背景与目标

TopoCode 主应用的"组件架构自动化语义分析"目前是**一次性快照流水线**：AST 解析 → 社区检测（Leiden/Louvain）→ LLM 语义命名 → 可视化。工程常态（代码持续变更、重命名、结构演化）暴露出三个痛点：

1. **陈旧**：分析结果没有"上次分析之后代码变了什么"的概念，旧数据被当作现状。
2. **昂贵**：任何变更都要全量重跑，社区 ID 由枚举序号生成，聚类一变 → LLM 语义数据全数失联 → 最贵的语义层被反复重复分析。
3. **无 diff 视角**：开发者无法回答"这次改动影响了哪些组件"。

本设计引入 **TopoCode Architect**——一个独立于主应用的工具，配合知识库使用：

- 作为**主 Agent**，持有架构规约，调度第三方 AI coding agent 执行任务；
- 作为**辅助 MCP**，向其他 coding agent 提供架构变更检测能力；
- 所有暂存工作变更都在 architect，工作完成后经人工确认并入 TopoCode 知识库成为**新基线**。

设计目标：

| 目标 | 说明 |
|------|------|
| 基线锁版本 | 全量 LLM 分析作为知识库基线，配合 GIT 锁定 commit 哈希 |
| 增量更新 | 后续变更按文件范围增量更新，局部重新解释，不频繁重跑全量 |
| 稳定 ID | 保留节点/社区 ID 一致，减少调用链关联修改与语义数据失联 |
| 人工可介入 | 社区文件划分支持人工手动划分，不完全依赖算法 |
| 可追溯 | AST/社区/语义数据叠加存储不覆盖旧数据，上一基线可查 |
| 独立解耦 | Architect 独立工具，经 API/MCP 与知识库交互 |

---

## 2. 总体架构：三组件 + 一层接口

```
    ┌──────────────── TopoCode Architect（独立工具）────────────────┐
    │ 规约持有 · 任务编排 · 合规校验 · 暂存管理 · 人工确认门          │
    │ 派发第三方 coding agent（Claude Code / Cursor / opencode …）   │
    │ UI: WebUI（页面资源+API由主应用代理） / TUI（经 MCP 对接）      │
    └───────────────────────────┬──────────────────────────────────┘
                                │ 仅经 MCP / REST（窄接口，不碰内部实现）
                                │ architect 不提供独立 HTTP 服务
                                ▼
    ┌────────────────── TopoCode 知识库（主应用）───────────────────┐
    │ 内核: AST 解析 / 社区检测 / LLM 语义 / 内容寻址 ID/AST         │
    │ 存储: SQLite（graph_node/edge/graph_doc/hierarchy/llm_results）│
    │ 维度: baseline_id（叠加存储） + community_overrides（人工层）   │
    │ 出口: MCP Server + REST API + ZMQ IPC（桌面 UI 现有）          │
    └───────────────────────────────────────────────────────────────┘
                                ▲
                                │ Mode B: 只读 MCP 调用
    ┌───────────────────────────────────────────────────────────────┐
    │ 第三方 coding agent（Claude Code / Cursor / opencode …）       │
    └───────────────────────────────────────────────────────────────┘
```

> **UI 形态**：architect 支持 WebUI + TUI 两种模式，且 **architect 不提供独立 HTTP 服务**。WebUI 为**独立 SPA**，经主应用同源挂载（静态资源由主应用托管，后端 API 由主应用代理、转发给 architect 后端进程，进程内/本地 IPC，不对外暴露端口）；TUI 下主应用经 **MCP** 与 architect 对接（见 [§5.1](#51-通信形态)）。**设计动机：知识库、AI chat、architect 三块共用主应用同一浏览器端口（`common.http_port`），按路径路由，避免多端口记忆与混淆。**

职责边界：

| 组件 | 拥有 | 不拥有 |
|------|------|--------|
| Architect | 工作区 worktree、暂存层、编排期规约执行、任务状态 | 持久知识库、基线、语义层 |
| 知识库 | 持久 KB、基线（baseline_id）、语义数据、人工覆盖层 | 代码修改、暂存 |
| 第三方 agent | 执行具体代码修改 | 规约、基线、知识库 |

基线 git commit 归属知识库单方持有，architect 只查询、只在人工确认后调用 `rebaseline`——避免双写冲突。

---

## 3. 知识库基线模型（architect 的底座）

Architect 的全部价值建立在知识库的**基线 + 增量**模型上。以下是该模型的完整定义（这是 architect 能"感知变更、约束改动、确认并入"的前提）。

### 3.1 基线 / 工作区暂存 / 重基线

采用类 git 的双层模型：

```
[基线层]   baseline_id = N（只读，锁 git commit，全量 LLM 数据）
[工作区层] 暂存分析（可读，对应当前 worktree，带脏标记）
[重基线]   人工确认 → 原子写入 baseline_id = N+1 + 新 git commit
```

- **基线不随每次代码修改变更**，只在人工确认后建立新基线。
- 工作区层可随时查询，默认对应当前工作区分析。
- 知识库不随 git 提交（KB 不是版本库），只保存基线记录。

账本（轻量）：

```
baseline_records(baseline_id, git_commit, analyzed_at, manifest_hash, scope)
file_ast_map(file_path → content_hash → ast_record_id)   // 内容寻址
```

`file_ast_map` 是"仅更新变更文件 AST"成立的基础。git commit 由主应用现有 `detectGitInfo`/`saveGitInfo`（`backend-core/core_service.py` + `src/types/ipc.ts` 的 `GitInfo`）提供。

### 3.2 增量机器（分级闸门 + 分层增量 + 硬约束 + 懒重解释）

**① 变更探测与分级闸门**

`git diff(baseline_commit ~ worktree)` → 变更文件清单 → 按**幅度 × 方向**分级：

| 级别 | 判定（幅度×方向） | 动作 |
|------|-------------------|------|
| S | 少量文件、无删除、不触枢纽 | 仅刷文件层 + 预摘要，社区层置脏不重算 |
| M | 中等范围、含删除/修改枢纽 | 社区层精化（refinement） |
| L | 大范围 / 用户判断 | 提示全量重检（人工确认） |

- 幅度指标：变更文件数、变更边数、受影响社区数（脏集大小）、是否触及枢纽/关键节点。
- 方向判定：新增=加法低危；删除=高危（走反向依赖闭包）；修改=看是否破坏社区间边。
- 文件预摘要按**内容哈希**键控（复用 `backend-core/agent_workflow/file_summary_cache.py` 雏形），分级闸门本身几乎零成本，可每次变更都跑。

**② 分层增量（局部性边界）**

| 层 | 增量策略 |
|----|---------|
| 符号/文件层（graph_node/graph_edge） | **严格局部**：只重解析变更文件的 AST（哈希复用），更新边；删除节点走**反向依赖闭包**（谁依赖它全部重解析），并对被破坏的调用链显式标记 |
| 社区层（graph_doc/hierarchy） | **精化而非全量**：用旧 partition 作种子跑 Leiden refinement；算法分组不能保证 100% 一致，全量重跑会造成无谓变动 |
| 语义层（community_llm_results） | **脏标记向上传播 + 懒重解释**：变更文件 → 所属社区置脏 → 父社区级联置脏；仅在重基线或用户浏览到该节点时按队列重跑；未脏社区直接继承基线结果。即使全量重检，也通过 Jaccard 对齐继承 LLM 结果，语义层永不清零 |

**③ 稳定 ID（前置条件）**

当前 `comm-{task}{et}{Lv}{parent_short}{i}` 为**枚举序号**生成（`plugins/community/community_analysis.py:_save_communities`），任何聚类结果变化序号全变。为达成"保留节点 ID 一致"，必须：

- 社区 ID 改为**内容寻址**（成员集合内容哈希）或增加 `stable_id` 列；
- 符号/文件节点 ID 以 `文件路径 + 符号名` 为身份（天然稳定）；
- 明确：**节点 ID 稳定 ≠ 边不变**——边集必须随变更更新，保边会毁掉正确性；稳定的是身份，变的是拓扑。

### 3.3 人工覆盖层（community_overrides）

社区文件划分支持**人为手动划分**，不依赖算法：

- 独立表 `community_overrides(file_path → community_key, meta)`，**不改写** `graph_doc` 算法原始结果（与"叠加不覆盖"哲学一致）。
- 重跑/精化后自动叠加回去，人工意图跨基线永存。
- 冲突规则：**用户意图优先**，同时给出"覆盖 vs 算法"差异标记。
- 新增文件默认落算法分组并标记"未人工指派"；删除文件的人工指派记录保留为历史。
- 增量精化与 architect 合规校验中，人工边界是**硬约束**：人工划分内/边界的文件不允许被算法移动，不允许被 agent 改动跨界。

### 3.4 增量日志与 diff 视角

每次暂存更新产生一条增量记录（变更文件、变更边、重解释社区列表、边界变化）。它是：
- 开发者"这次改动影响了哪些组件"的直接答案；
- 架构变更检测（Mode B MCP）的底层数据；
- 两个基线天然可比的来源（diff/回滚白送）。

### 3.5 增量合并（Merge）模型

**库分离 + merge=commit**：architect 库（暂存/工作区）与主库（基线）分离。architect 库经主库接口产出文件级事实并持有"待合并差异集"；merge 把差异集并入主库，对齐当前 git 版本哈希 H，合并后 H 成为新基线头哈希——语义等同一次 git commit。

**文件级叠加语义（新版替代旧版）**：

| 数据 | 处理 | 说明 |
|------|------|------|
| AST / 依赖 / 调用 | 新版替代旧版（按文件 upsert） | 只重解析变更文件，哈希复用未变文件 |
| 文件功能预摘要 | 新版替代旧版（内容哈希键控） | 重命名跨版本复用 |
| 删除文件 | 墓碑 + 移出成员 | 边从新事实重派生，不手工补传播 |
| LLM 语义 | **叠加不覆盖**（按输入版本键控） | 保留解释历史，供对比/回滚 |

**传播的正确性边界**：architect 驱动编程，删除/重构若未解决传播则编译不过——事实层（边）从变更后代码重派生即可保证正确性；但编译覆盖不了**语义意图漂移**（动态语言重构常编译过而职责漂移），故语义层仍由 stale 标记 + 懒重解释兜底。正确性靠代码编译，语义意图靠语义层。

**社区成员更新规则（默认不变）**：

| 变更类型 | 处理 |
|----------|------|
| 文件删除 | 移出成员（简单） |
| 文件新增 | 算法建议归属 + architect/人工指派 |
| 文件重命名 / 重构 | merge 前**人工或算法辅助判定**归属 |
| 内部结构变更 | **默认从属不变**，记录变化供语义层置 stale |

**变更幅度触发（建议复核归属，仅 advisory）**：merge 时对内容变化的文件，比较新旧边集（均为 merge 重派生数据，零额外成本）：

| 指标 | 计算 | 触发 |
|------|------|------|
| `edge_similarity` | 新旧边集 Jaccard | `< 0.3` → 建议复核该文件归属 |
| `cross_ratio` | 新边中跨出本社区比例 | 显著升高（如 `<0.2 → >0.5`）→ 建议考虑划入/靠近对方社区 |

- 只产出"建议清单"，**不自动改归属**（符合用户意图优先）；
- 触发文件所在社区的 LLM 重解释优先级提高（大改优先重解）。

**Merge 流程**：

```
[前置] verify_commit(H) ─ 对齐当前基线头哈希
1. git diff(prev_head ~ H) → 变更文件清单 + content_hash
2. 事实层 upsert（新版替代旧版）：AST / 依赖/调用 / 预摘要
   · 删除文件 → 墓碑 + 移出成员；边从新事实重派生
   · 传播正确性靠代码编译，语义意图靠语义层兜底
3. 社区成员（默认不变）：
   · 新增 → 算法建议 + 指派；重命名/重构 → 人工/辅助判定；内部变更 → 默认不变 + 变更幅度触发建议
4. 语义层：受影响社区置 stale（叠加不覆盖），写 doc_deltas 增量日志
5. 原子提交：新基线头 = H；幂等（manifest hash 判重）
[merge 后] LLM 异步消费"需重解释队列"按需重解释（独立触发）
```

**分析逻辑单一来源（复用不拷贝）**：architect 库不维护自己的解析/分析副本，调用主库同一内核（同一模块/API）产出文件级事实，只持有待合并差异集——避免两套实现漂移。现有流程不够灵活时，拓展主应用入口（见 §5.2 增量/合并接口）而非拷贝逻辑。

---

## 4. Architect 本体设计

### 4.1 双向架构定位

| 模式 | 角色 | 说明 |
|------|------|------|
| **Mode A（主 Agent 编排）** | 控制架构规约，第三方 agent 为 subagent 执行任务 | 主动派发、校验、暂存、确认重基线 |
| **Mode B（辅助 MCP）** | 向第三方 coding agent 提供架构变更检测 | 只读、被动、无需编排器，最易先落地 |

两模式共享同一底层（知识库 + 增量机器 + 规约），只是接口形态不同——一个对外派发，一个被调取用。

### 4.2 职责与边界

- Architect 拥有：worktree、暂存层、编排期规约执行、任务状态。
- 知识库拥有：持久 KB、基线、语义层、人工覆盖层。
- Architect 不接触知识库内部实现（AST/社区检测/SQLite），只消费派生知识：组件、规约、变更影响面、合规结论。

### 4.3 架构规约（Architecture Spec）

规约 = 三层来源，一等公民：可编辑、可版本化、**变更需人工确认**（agent 不可自改规约）。

```
architecture_spec
├── 人工覆盖层（community_overrides）   // 手动划分、关键文件钉点
├── 用户显式规则                        // "组件X不得依赖Y"、"核心文件禁止删改"
└── KB 派生约束                         // 社区职责、依赖方向、关键节点保护
```

规约存储为独立版本化文件（如 `.topocode/spec.md` + 版本号），与知识库基线解耦，可独立演进。

### 4.4 任务编排流（Mode A）

```
用户需求
  → architect 读取规约 + 查询知识库（受影响组件/上下文）
  → 拆解为子任务 → 派发第三方 agent（隔离 worktree / 限定读写权限）
  → agent 编辑 worktree
  → 合规校验（每次 diff：边界越界 / 规约违反 / 关键节点破坏 → 阻断或标记）
  → 任务完成 → 批量增量扫描（git diff → 分级 → 文件层/社区层/语义层更新）→ 暂存
  → 人工确认（三个独立门：代码合并 / 规约变更 / 基线创建）
  → 确认 → architect 调 KB `rebaseline(commit, manifest)` → 新基线 N+1
```

增量节奏：**按任务里程碑批量**，不按每次击键高频刷新。

### 4.5 合规校验引擎

Mode A 新增的核心组件：对 agent 输出的每次 diff 做合规检查。

| 检查项 | 输入 | 判定 |
|--------|------|------|
| 边界越界 | diff 中移动的文件 vs 人工覆盖层 | 被钉文件跨边界 → 违规 |
| 规约违反 | diff 新增依赖/调用 vs 显式规则 | "组件X不得依赖Y" → 违规 |
| 关键节点破坏 | diff 删除/改名 vs 关键节点清单 | 反向依赖闭包非空 → 阻断 |
| 依赖方向 | diff 前后依赖关系变化 vs KB 派生约束 | 反转依赖方向 → 标记 |

校验吃增量机器的输出（git diff → 范围 → 受影响组件）作为输入，两者共用同一扫描逻辑。

### 4.6 模块划分

```
topocode-architect/
├── orchestrator.py        # Mode A 编排器：需求→拆解→派发→校验→暂存
├── spec.py                # 架构规约加载/版本化/变更审计
├── compliance.py          # 合规校验引擎
├── staging.py             # 暂存管理（工作区层）
├── adapters/              # 第三方 coding agent 适配器（复用 phase5 模式）
│   ├── base.py
│   ├── claude.py
│   ├── cursor.py
│   └── opencode.py
├── mcp_client.py          # 调用知识库 MCP（写侧：rebaseline / 覆盖层）
├── mcp_server.py          # Mode B：对外暴露只读变更检测能力（TUI/第三方经此对接）
├── api.py                 # 内部 API 路由（仅供主应用代理调用，不监听 HTTP）
├── webui.py               # WebUI 后端：接收主应用转发的请求（进程内/本地 IPC）
└── tui.py                 # TUI 入口：以 MCP 为交互通道
```

说明：
- **无独立 HTTP 服务**：`api.py`/`webui.py` 只暴露进程内/本地 IPC 接口，由主应用代理转发，architect 不监听任何对外端口。
- WebUI 页面资源由主应用托管；architect 后端进程仅处理业务逻辑。

---

## 5. Architect ↔ TopoCode 主应用交互方案

### 5.1 通信形态

**Architect 不提供独立 HTTP 服务**，所有对外交互经主应用承载或经 MCP。按 architect 的两种 UI 模式：

| Architect UI 模式 | 交互通道 | 说明 |
|-------------------|----------|------|
| **WebUI** | 主应用代理分发 | 页面资源由主应用托管；页面 API 请求由主应用代理 → 转发给 architect 后端进程（进程内/本地 IPC，不对外暴露端口） |
| **TUI** | MCP | 主应用经 MCP 与 architect 对接（交互/控制通道） |

**设计动机（统一浏览器端口）**：

本地知识库、AI chat、architect 三块功能共用一个浏览器端口，避免多端口记忆与混淆、降低用户使用难度。主应用现有 Web 服务（`plugins/reports/web_server.py`，`common.http_port`）已经是统一网关——`/doc`（viewer）与 chat 已同源同端口；architect 直接挂到同一 origin，按路径路由：

| 统一入口 | 路径 | 承载 |
|----------|------|------|
| 知识库 | `/doc` / chat 路由 | 主应用 Web 服务 |
| architect 静态页 | `/architect/` | 主应用 `app.mount` 挂载 **architect 独立 SPA** 产物（`architect.html`） |
| architect API | `/api/architect/*` | 主应用转发 → architect 后端进程（本地 IPC） |

**architect WebUI 是独立 SPA**：自有 HTML 入口（`architect.html`）+ Vite entry（`entry-architect.ts`），与现有 viewer/chat/web-root 多 SPA 同一模式（`vite.web.config.ts` 各自 entry + 主应用 rewrite 分发）。它不是既有 SPA 内的路由，不动现有 SPA，经主应用同源挂载在 `/architect/`。

同源收益：单一 URL、免 CORS、统一本地会话/令牌、无需记住"哪块在哪个端口"。

知识库侧通道：

| 形态 | 用途 | 说明 |
|------|------|------|
| **MCP（主）** | architect / 第三方 agent ↔ 知识库 | 所有 AI 客户端天然协议 |
| **REST（辅）** | 主应用 Web UI / 脚本 | 只读查询 + 管理操作 |
| **ZMQ IPC（现有）** | 主应用桌面 UI ↔ 内核 | 已有（`backend-core/zmq_server.py`），不动 |

**WebUI 代理分发（主应用职责）**：

```
浏览器 (architect 独立 SPA 页面资源由主应用托管，同源 http://127.0.0.1:{http_port})
   │ 页面资源请求 /architect/* ──► 主应用静态托管（app.mount，architect SPA 构建产物）
   │ API 请求 /api/architect/* ──► 主应用网关
   │                               ├─ 鉴别路由（architect 专属路径前缀）
   │                               └─ 转发 ──► architect 后端进程（本地 IPC，无端口）
   ◄── 响应原路返回
```

- 主应用网关对 `/api/architect/*` 等前缀做**路由鉴别 + 转发**，其余请求照旧；
- architect 独立 SPA 构建产物经 `app.mount("/architect", StaticFiles(...))` 挂载，与现有 `"/web"` 挂载同一模式；
- architect 后端进程仅被主应用拉起并持有句柄（子进程 / 进程内模块），不监听端口；
- architect 内部调用知识库的 MCP/REST 走主应用本地通道，不经过外部网络。

MCP Server 做成知识库内核之上的**薄适配层**（复用现有内核与插件，不新建核心）。本地优先（桌面场景）：本地 HTTP / Unix socket / MCP stdio，不依赖云端。

### 5.2 MCP 接口清单

存在**两个 MCP 面**，职责不同：

| MCP 面 | Server | Client | 用途 |
|--------|--------|--------|------|
| **知识库面** | 知识库（薄适配层） | architect / 第三方 agent | 读写知识库（下文清单） |
| **Architect 面** | architect（`mcp_server.py`） | 主应用 TUI / 第三方 agent | 架构变更检测 + 编排状态（Mode B / TUI 对接） |

**知识库面 — 读侧（开放，任意 agent 可调）**

| Tool | 输入 | 输出 |
|------|------|------|
| `get_architecture_spec` | — | 规约（人工层 + 显式规则 + 派生约束） |
| `get_component_context` | `component_id` | 文件、依赖、摘要、人工钉点、当前基线 |
| `detect_changes` | `diff` 或 `commit_range` | 受影响组件/文件清单（增量机器） |
| `check_compliance` | `diff` | 违规/跨界清单（复用合规引擎规则） |
| `list_baselines` | — | 基线列表（baseline_id / git_commit / 时间） |

**知识库面 — 写侧（人工确认门控）**

| Tool | 输入 | 说明 |
|------|------|------|
| `rebaseline` | `commit`, `manifest` | 暂存并入新基线（唯一新基线入口） |
| `save_overlay` | `file → community_key` | 人工覆盖层增删 |
| `update_component_meta` | `component_id, name, summary` | 组件命名与摘要更新 |

**知识库面 — 增量/合并接口（对接 architect 的核心，复用现有内核）**

| 入口 | 输入 | 输出 | 复用基础 |
|------|------|------|----------|
| `analyze_files` | `commit`, `file_list` | 文件级事实（AST/依赖/调用/预摘要 + content_hash） | 现有 parsers + ingest 管线 |
| `verify_commit` | `commit` | 基线哈希与 scope 一致性校验 | `detectGitInfo` 已有 |
| `merge_increment` | `manifest` | 原子 merge 结果（文件 upsert + 墓碑 + 社区成员更新 + doc_deltas） | `analysis_store` / ingest consumer |
| `enqueue_reinterpret` | `comm_list` | 需重解释队列已入队（merge 不触发 LLM，只排队列） | `community_llm_results` 更新路径 |

- 这四个入口即"分析逻辑单一来源（复用不拷贝）"的载体——architect 库经此调主库算，只持差异集；
- `analyze_files`/`merge_increment` 属写侧计算服务，受人工确认门控；`verify_commit` 读侧开放。

**Architect 面 — 供 TUI / 第三方 agent 调用（Mode B）**

| Tool | 输入 | 输出 |
|------|------|------|
| `arch_get_status` | — | 编排状态 / 任务列表 / 暂存摘要 |
| `arch_detect_changes` | `diff` 或 `commit_range` | 受影响组件/文件清单（复用 KB 增量机器） |
| `arch_check_compliance` | `diff` | 违规/跨界清单（复用合规引擎） |
| `arch_task` | 任务描述 | 触发 Mode A 编排（经主应用转人工确认门） |

- TUI 模式下主应用即此面的 Client，经 MCP stdio/Unix socket 对接；
- WebUI 模式下同一能力由主应用代理的 `/api/architect/*` 提供（见 [§5.1](#51-通信形态)）；
- **同一内部 API，两种出口**：WebUI 走同源 `/api/architect/*`，TUI 走 MCP，能力一致、统一心智。

### 5.3 rebaseline 握手协议

```
architect                          知识库
   │  verify_baseline(commit, manifest_hash) ──►  校验基线哈希与 scope 一致
   │  ◄──── ok / mismatch
   │  rebaseline(commit, manifest)  ──────────►  原子写入 baseline_id=N+1
   │  ◄──── { baseline_id, status:"committed" }
```

- `manifest` = 变更文件清单 + 变更边摘要 + 重解释社区列表（增量日志）。
- 原子性：全成或全不成，KB 永不半陈旧。
- 重复调用幂等（同 commit + 同 manifest_hash 返回已存在基线）。

### 5.4 工作区层 vs 基线层

读侧查询默认对应当前 worktree 的**工作区分析层**；`rebaseline` 后切到新基线。所有查询工具带 `layer: "working" | "baseline:N"` 参数，默认 `working`。

### 5.5 认证、权限与人工门控

- 本地令牌 + 读写分级；
- 写工具必须携带人工确认标记（来源自 architect 确认门）才能执行；
- 三个独立确认门：**代码合并 / 规约变更 / 基线创建**，不得合并为一个"全部同意"。

### 5.6 契约版本化

`detect_changes` / `rebaseline` 等握手接口定版本、留兼容字段（如 manifest 结构）；architect 与知识库独立演进。

---

## 6. 数据流闭环

```
        ┌──────────── TopoCode Architect（工作区/编排/暂存）────────────┐
        │ 规约(人工层+显式规则+KB派生) → 派发 agent → 改代码            │
        │   → 合规校验(违规阻断) → 任务结束批量增量扫描 → 暂存           │
        │   UI: WebUI(主应用代理) / TUI(MCP对接)，无独立 HTTP 服务      │
        └──────┬──────────────────┬──────────────────────────┬────────┘
               │ 读:规约/影响面    │ 写:变更增量(增量日志)      │ 确认后: rebaseline(commit)
               ▼                  ▼                          ▼
        TopoCode 知识库 ── baseline_id 叠加 + community_overrides
            │  读侧(开放): get_spec / get_context / detect / compliance
            │  写侧(门控): rebaseline / save_overlay / update_meta
            ▼
        第三方 coding agent ── Mode B 经 MCP 只读调用知识库
```

闭环收益：知识库喂给 architect 上下文与约束，architect 的产出回流知识库成为新基线——KB 因 architect 保持新鲜，architect 因 KB 保持正确。

---

## 7. 人工确认门与安全护栏

| 项 | 设计 |
|----|------|
| 三个确认门 | 代码合并 / 规约变更 / 基线创建 独立确认 |
| Agent 沙箱 | 每个第三方 agent 限定 worktree 读写范围（复用 `backend-core/agent_workflow/sandbox.py`、`tools_executor.py` 先例） |
| 人工覆盖不可被改 | agent 不得修改规约与覆盖层，违反即阻断 |
| 合规前置 | 每个 diff 即时校验，不等到重基线才发现 |
| 可回滚 | 叠加存储使上一基线始终可查；清理需显式导出备份 |

---

## 8. 与现有代码的落地映射

| 能力 | 落地位置（现有） | 改动 |
|------|------------------|------|
| 全量基线流水线 | `backend-core/agent_workflow/workflows/pipeline.py` + `component_analyst.py` | 增加 baseline_id 维度 |
| 社区检测/递归分层 | `plugins/community/community_analysis.py` | ID 改内容寻址/加 stable_id；refinement 种子支持；人工边界硬约束 |
| 查询层 | `backend-core/community_data.py` | 增加 baseline 参数（默认工作区层）；读时叠加 overlay |
| 任务/运行记录 | `backend-core/task_manager.py`（run_id/run_number 已有） | 扩展为 baseline_records 账本 |
| git 信息 | `backend-core/core_service.py` + `src/types/ipc.ts: GitInfo` | 复用，无需新建 |
| 预摘要缓存 | `backend-core/agent_workflow/file_summary_cache.py` | 改为内容哈希键控（跨重命名复用） |
| 导出/备份 | `backend-core/export_service.py` / `import_service.py` | 按 baseline 粒度导出/清理 |
| 桌面通信 | `backend-core/zmq_server.py` + `plugins/reports` | MCP Server 做薄适配层 |
| 变更探测 | 无（新建） | `git diff` + mtime 探针，产出变更文件清单 |
| 人工覆盖层 | 无（新建） | `community_overrides` 表 + 查询叠加逻辑 |
| 合规引擎 / 编排器 | `docs/plan/phase5-coding-agent.md` 的 coder/ 基础 | 在 phase5 基础上扩展 |
| architect 独立 SPA | `vite.web.config.ts`（新增 architect entry）+ 主应用 rewrite | 与现有 viewer/chat/web-root 多 SPA 并列，`/architect → architect.html` |
| 增量/合并入口（analyze_files / merge_increment / enqueue_reinterpret） | 现有 parsers + ingest 管线 + `analysis_store` / ingest consumer + `community_llm_results` | 文件级封装为 MCP 接口（§5.2），改覆盖式为叠加式（停 consumer DELETE） |
| 变更幅度触发（建议复核归属） | 基于 merge 重派生的边集 | 新旧边集 Jaccard + cross_ratio 计算，输出建议清单 |

---

## 9. 实施路线

| 阶段 | 内容 | 价值 |
|------|------|------|
| **P0 基线模型** | baseline_id 叠加、git commit 锁定、账本、稳定 ID、导出/清理 | 变更可追溯、旧基线可查 |
| **P1 增量机器** | git diff 探测、分级闸门、文件层局部重解析、社区精化、脏标记懒重解释、增量日志 | 变更后增量更新，成本大降 |
| **P1b 增量合并** | Merge 模型落地：architect 库/主库分离、文件级叠加、墓碑、社区成员更新规则、变更幅度触发、4 个增量/合并 MCP 入口 | 增量内容以 merge=commit 并入主库，对齐 git 哈希 |
| **P2 人工覆盖层** | community_overrides 表、读时叠加、硬约束接入精化 | 用户意图优先，算法结果稳定锚 |
| **P3 Mode B MCP** | 只读检测接口（get_spec/detect/compliance/context）薄适配层 | 立刻被第三方 agent 使用，验证增量机器 |
| **P4 Mode A 编排** | 规约、合规引擎、任务编排、暂存、rebaseline 握手 | 完整闭环，知识库新鲜度自举 |
| **P5 UI 承载** | WebUI（主应用代理分发 + architect 后端进程）+ TUI（MCP 对接） | 提供交互入口，验证代理/对接链路 |

P0→P2 为主应用内部改造，P3→P5 引入 architect。风险最低的切入点是 P3（复用增量机器做只读 MCP），但依赖 P1 完成。UI 承载（P5）可在 P4 编排器完成后叠加，WebUI 代理与 TUI MCP 共用同一内部 API。

---

## 10. 待定决策点

| # | 决策 | 倾向 | 影响 |
|---|------|------|------|
| D1 | 人工覆盖层存储：独立 `community_overrides` 表（读时叠加） vs `graph_doc` 物化 + provenance 列 | **独立表读时叠加**（与"叠加不覆盖"哲学一致，增量零侵入） | 查询/写入路径设计 |
| D2 | 手动划分范围：仅"边界调整"（移动文件） vs 一步到位也支持"手动新建社区" | 先边界调整，再新建社区 | 新建社区涉及层级归属/命名/子社区递归 |
| D3 | 社区 ID：内容寻址替换 vs 保留现有 + 新增 `stable_id` 列 | 新增 `stable_id` 列（兼容存量数据） | 迁移成本 vs 查询复杂度 |
| D4 | MCP Server 进程位置：知识库主进程内置 vs 独立包装器 | 知识库内置薄适配层 | 部署形态 |
| D5 | 写接口人工确认门在 MCP 语义中的表达：approval callback 走 UI vs 走 architect | architect 承载确认门，KB 只校验令牌+确认标记 | 交互协议 |
| D6 | 图数据（graph_edge/graph_node）叠加策略：全基线叠加 vs "最新+上一基线/差异存储" | 语义层叠加为主，图数据限层数（体积） | 存储体积与查询复杂度 |
| D7 | WebUI 代理分发：architect 后端进程形态（主应用子进程 vs 进程内模块）与路径前缀约定 | 主应用子进程 + 静态 `/architect/` + API `/api/architect/*`，统一挂 `plugins/reports` 网关 | 进程生命周期与路由规则 |
| D8 | Architect 与知识库的 MCP 走主应用本地通道（stdio/Unix socket）的具体绑定方式 | 由主应用统一注册/托管 | 连接管理与调试 |

> 注：D7/D8 与 UI 模式（WebUI 代理 / TUI MCP）绑定，已确定"architect 无独立 HTTP 服务"这一原则，具体进程形态与路由前缀待实现时定。
