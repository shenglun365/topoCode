# TopoCode Architect · UI/UE 设计与原型生成能力 · 设计规划文档

> 范围：`apps/architect`（前端 `@topo/app-architect` + 后端 `topoone_app_architect`）新增 **UI/UE 设计** 与 **原型生成** 能力的**整体规划**
> 代码基线：分支 `dev-1`（约 2026-08-30）
> 关联文档：`docs/architect-review.md`（architect 现状评估）、`docs/archive/architecture-issues-0902.md`（全仓四维度评估，已归档）
> 性质：**整体规划 / 架构方向。非详细设计** —— 不定义 IR 具体字段、不写 DDL、不拆任务清单
> 更新日期：2026-09-02

---

## 1. 背景与目标

### 1.1 现状
architect 是**工作实践导向**的架构工作台，现有闭环为 **需求提案 → 概要设计 → 任务执行 → 单元测试**（`src/config/workflow.ts` 的 4 阶段）。其核心资产引擎 `semantic_assets.py` 面向**既有代码**，提取结构/行为/规则/契约等语义（`kind × level` 二维正交分类，codegraph 锚定 + LLM 分级 + 增量 hash）。

现有 `design.py` / `DesignPanel.vue` 的"设计"偏**架构/概要设计**，**缺少 UI/UE（视觉 + 体验）设计**与**可交互原型**能力。

### 1.2 目标
让 architect 从需求与语义资产**派生 UI/UE 设计**，并**生成分级、可交互、可追溯的原型**，把闭环扩展为：

```
需求 → 语义资产 → UI/UE 设计 → 原型(分级) → 任务执行 → 验收
```

原型 L3（生产级）可**晋升**进既有 runner 任务树执行，形成"设计验证态 → 生产执行态"的衔接。

### 1.3 非目标（本文不含）
- 不定义 UI 设计 IR 的具体字段 / JSON Schema（留给详细设计）
- 不写数据表 DDL（仅概念级列名）
- 不拆到可执行任务（仅阶段级交付物）

---

## 2. 核心设计原则（对齐 architect 既有骨架）

本能力的**根本取向**：不做"新功能"，而是 architect 四大既有骨架的**正交延伸**，最大化复用、避免新增 god-file（承 `architect-review.md` A1 教训）。

| # | 原则 | 落地含义 |
|---|---|---|
| P1 | **自持** | UI 设计 agent 仿 `req_agent`：自持 harness/skills/tools，LLM 走 `KbGateway.call('llm.sync')`，不经主后端 provider 注册，architect 零状态 |
| P2 | **网关化 + 降级** | 渲染/预览/外部能力走拓扑无关网关（仿 `runner_gateway`）；不可达降级到确定性/启发式产出 |
| P3 | **语义资产正交扩展** | UI/UE 资产并入既有 `arch_semantic_assets` 引擎：新增 kind（screen/component/user_flow/interaction/design_token/visual_state）+ 新增关切轴（presentation/interaction），复用锚定/增量/stale |
| P4 | **分级成本/保真度** | 原型分 L0–L3（见 §3.2），对齐语义资产的 L/M/H 分级成本思想 |
| P5 | **拓扑无关** | 原型渲染/预览可内建起步、预留独立 `prototype` 服务（仿 runner 横向扩展/隔离） |
| P6 | **单一事实源（IR）** | 定义 **UI 设计 IR** 作为唯一事实源 → 原型可增量/diff/重生成/追溯；这是能力上限的决定项 |
| P7 | **与语义资产同源** | 从目标项目**反向提取既有 design system**（前端组件/样式文件也是代码，codegraph 可锚定），再允许用户扩展——不凭空捏一套 |

---

## 3. 能力全景

### 3.1 UI/UE 设计能力（三层，对齐 `level` 轴）

| 层 | 内容 | level |
|---|---|---|
| UX / 概念层 | 用户流、personas、用户故事→屏幕映射、关键任务路径 | business |
| 设计系统层 | design tokens（色板/间距/字体/圆角/阴影）、组件规格库、栅格、响应式断点、交互模式、无障碍(a11y) | logic |
| 界面实现层 | 每个 screen 的组件树、数据绑定、视觉状态（loading/empty/error/hover/focus）、微交互 | implementation |

> **"UE"（体验）**落在用户流 + 交互状态 + 反馈，非纯视觉 → 资产须含 `user_flow` / `interaction` / `visual_state`，而非仅 `screen`。

### 3.2 原型生成能力（四级，对齐分级成本）

```
L0 线框图 wireframe     —— 零/低 LLM，确定性布局，验证信息架构
L1 静态 mockup          —— tokens + 组件树渲染，验证视觉
L2 可交互原型 clickable —— 用户流串联 + 状态切换 + 假数据，验证体验（建议默认档）
L3 生产级 UI 代码       —— 目标框架组件（Vue 优先），可晋升进 runner 任务树
```

### 3.3 能力关系（概念）

```
需求(arch_requirements) ─┐
语义资产(arch_semantic_assets) ─┼─► UI/UE 设计(ui_agent) ─► UI 设计 IR(单一事实源)
既有代码 design system ─┘                              │ 分级渲染(可插拔 renderer)
                                                       ├─ L0/L1/L2 ─► 沙箱预览
                                                       └─ L3 ─► 晋升 runner 任务树 ─► 执行/验收
```

---

## 4. 与现有架构的映射（复用矩阵）

| 新能力 | 复用的既有骨架 | 落点（概念级） |
|---|---|---|
| UI/UE 资产 | `semantic_assets` 引擎（codegraph 锚定 + LLM 分级 + 增量 hash） | 扩展 `arch_semantic_assets` 的 kind + 关切轴（不另开资产表） |
| 设计 agent | `req_agent` 自持 harness/skills/tools 模式 | 新增 `ui_agent`（architect 进程内自持） |
| 原型执行/预览 | `runner_gateway` 独立执行宿主模式 | 内建起步 → 预留独立 `prototype` 服务（沙箱化） |
| 设计可视化 | topoOne 内核（flowchart/component 图） | 渲染 user flow / 组件结构图（**原型本体是独立 IR，非图**） |
| 对外能力 | MCP **出向**（`KbGateway.query()` 预留位，承 A6） | 注册"生成原型 / 查设计规范 / 校验一致性"为对外 MCP 工具 |
| 既有 design 模块 | `arch_routes/design.py` + `DesignPanel.vue` | 扩展出 UI/UE 设计**子域**（边界见 §9） |

**关键洞察**：前端组件/样式文件**本身是代码** → codegraph 可锚定 → 能**从目标项目反向提取现有 design system**，使"设计系统"与"语义资产"同源一致（P7）。

---

## 5. 目标架构（概念级）

### 5.1 新增模块（概念清单，不展开内部设计）
- **后端**（`arch_routes/`，遵循既有 `router + store` 模式）：
  - `ui_agent.py` —— UI/UE 设计自持 agent（仿 `req_agent`）
  - `ui_design.py` —— UI/UE 设计规格路由（screens/components/flows）
  - `design_system.py` —— design tokens / 组件规格 / 既有提取
  - `prototype.py` —— 原型 IR 管理 + 分级渲染调度 + 预览
- **前端**（`src/`，遵循既有 page/service/store 分层）：
  - 页面：`UIDesignPage.vue`、`PrototypePage.vue`（或并入 `DesignPanel` 扩展）
  - service：`ui-design-service.ts`、`prototype-service.ts`
  - store：`ui-design-store.ts`、`prototype-store.ts`
  - 组件：`components/prototype/`（预览器/沙箱 iframe/IR 编辑器）
- **可选独立服务**：`prototype` 预览/渲染服务（仿 runner，沙箱 + 横向扩展），初期内建、后续拆出。

### 5.2 数据模型（概念级列域，非 DDL）
推荐**并入 `arch_semantic_assets`**（复用增量/stale），按需补充少量规格/版本表：

```
arch_semantic_assets      # 扩展 kind: screen/component/user_flow/interaction/design_token/visual_state
arch_ui_screens           # screen 规格（组件树/数据绑定/状态）——若需独立生命周期
arch_prototypes           # 原型版本（ir_hash/保真度 L0-L3/状态/预览URL/关联 screen）
arch_ui_asset_refs        # 可追溯关联：UI 资产 ↔ 需求 ↔ 语义资产 ↔ 代码锚点
```
> 取舍：能用 `arch_semantic_assets` 承载的不另开表，保持"语义资产是唯一事实源"（P3/P6）。

---

## 6. 原型生成管线（概念级）

```
需求 / 设计意图
   │  ui_agent：派生 screens/flows/tokens，锚定既有组件（P7）
   ▼
UI 设计 IR   ← 单一事实源（tokens + 组件树 + 布局 + 交互 + 数据绑定 + 状态）
   │  分级渲染（可插拔 renderer，仿 topoOne engine 可插拔）
   ├─ L0 wireframe ─► SVG/HTML
   ├─ L1 mockup    ─► HTML/CSS（tokens 驱动）
   ├─ L2 clickable ─► HTML/CSS/JS（iframe 沙箱预览）
   └─ L3 生产代码   ─► Vue 组件（晋升 runner 任务树）
   ▼
沙箱预览 + 导出（设计稿 / 前端代码）
   │  需求变更 → IR 增量 diff（src_hash，复用资产引擎）→ 原型增量更新
```

**IR 设计取向**（详细设计阶段落实）：借鉴 topoOne `DiagramSchema` 风格 —— pydantic + `extra=forbid` + **分 concern 分 model**（tokens / screens / flows / interaction）+ JSON Schema 校验 + 前后端 schema 对齐。**切忌**做成大而全的 god-schema。

---

## 7. 关键设计决策（规划级假设，详细设计时确认）

| # | 决策 | 规划级推荐 |
|---|---|---|
| D1 | 原型默认保真度档 | **L2 可交互**（体验验证价值最高）；L0/L1 快速路径，L3 走晋升 |
| D2 | IR 是否独立 schema | **是**（能力上限决定项，P6） |
| D3 | 前端框架绑定 | **框架无关 IR + 目标框架 renderer（Vue 优先）** |
| D4 | 预览：内建 vs 独立 | 初期内建（iframe sandbox）→ 预留独立 `prototype` 服务（原型=LLM 不可信代码，必须沙箱） |
| D5 | 设计系统来源 | **双向**：从既有代码提取（codegraph 锚定）+ 用户扩展（P7） |
| D6 | 与 Coding Agent 边界 | 原型=**设计验证态**（快速/可弃/可迭代）；生产=**经任务树执行态**（runner，含验收/单测）；L3 可晋升衔接，两者不重叠 |

---

## 8. 分阶段规划（Roadmap，阶段级交付物）

> **硬前置（M0）**：先拆分 `semantic_assets.py`（5555 行 god-file，承 `architect-review.md` A1）——否则新增 UI kind 会雪上加霜，且拆不动后续演进。

| 阶段 | 目标 | 交付（概念级） | 关键依赖 |
|---|---|---|---|
| **M1 最小闭环** | 设计规范 + 屏幕规格 + L0/L1 原型 + 沙箱预览 | design tokens / screen spec；L0/L1 渲染；iframe 沙箱预览；UI 资产并入 `arch_semantic_assets` | M0（拆 semantic_assets）；ui_agent v1 |
| **M2 交互与追溯** | 用户流 + L2 可交互 + 双向绑定 + 增量 | user_flow / interaction / visual_state；L2 clickable；需求↔原型可追溯；IR 增量 diff 更新 | M1 |
| **M3 生产级 + 对外** | L3 代码导出 + MCP 出向 + 独立预览服务 | L3 Vue 组件导出（晋升 runner）；MCP 工具（生成原型/查规范/校验）；独立 `prototype` 服务 | M2；MCP 出向落地（承 A6） |
| **M4 智能增强** | LLM 驱动的设计评审/一致性 | a11y 检查、品牌一致性、组件复用率、与既有 design system 偏离度提示 | M3 |

**每阶段验收口径（概念级）**：M1 能"从需求出 L0/L1 原型并预览"；M2 能"流串联 + 需求变更增量更新原型"；M3 能"原型晋升为可执行任务 + 外部 agent 经 MCP 调原型能力"；M4 能"给出设计一致性/a11y 评审意见"。

---

## 9. 风险与边界

| 风险 | 缓解 |
|---|---|
| 高保真 LLM 生成贵且漂移 | 分级（默认 L2）+ 锚定既有组件（codegraph，P7），不凭空造组件 |
| IR 膨胀成 god-schema | 分 concern 分 model，`extra=forbid`，借鉴 topoOne schema 风格（§6） |
| 与 `design.py` 边界不清（再造 god-file） | 明确：`design.py`=架构/概要设计，UI/UE 为**子域**，独立 `ui_design.py`/`prototype.py` 模块（§5.1） |
| 前端预览安全（不可信 LLM 代码） | iframe sandbox / 独立进程，禁网络 / 禁主域（D4） |
| 语义资产引擎已 5555 行（A1） | **先拆 semantic_assets 再加 UI kind**（M0 硬前置） |

**边界声明**：原型态（设计验证，快速可弃）与生产态（runner 任务树，含验收/单测）**职责分离**；仅 L3 经"晋升"衔接，避免原型逻辑污染生产执行链路（D6）。

---

## 10. 与既有文档的关系 & 后续

- 本文件是 **architect UI/UE + 原型能力** 的**整体规划**；现状与问题见 `docs/architect-review.md`，全仓问题见 `docs/archive/architecture-issues-0902.md`。
- **后续详细设计（另行立项）**：
  1. UI 设计 IR 的 JSON Schema（对齐 topoOne `diagram.schema.json` 风格，分 concern）
  2. 数据表 DDL + `store.py` 扩展
  3. M1 最小闭环的可执行任务拆解
  4. `semantic_assets.py`（M0）拆分方案

> 本文件为规划记录，不构成已实施的变更；§7 决策为规划级假设，待详细设计与原型验证后收敛。
