# TopoCode 系统架构梳理与批次渐进重构方案

> 状态：**已评审**（2026-09-24 五项裁决经人工审阅确认；未实施） | 日期：2026-09-24
> 输入：前端四 app 深扫、packages+后端深扫、`docs/archive/architecture-issues-0905.md`（已归档，蓝图承接源）、`docs/archive/`（plan-C v1.7 / M0 / plan-C-UI / nine-layer 冻结稿，已归档）、CONV-00~04
> 性质：架构分析 + 五项裁决 + 批次计划；承接既有规划，不另起炉灶

---

## 1. 架构现状分析

### 1.1 总体拓扑

npm workspaces monorepo：4 个独立 Vite 前端应用（workbench 163 文件 38k 行 / architect 132 文件 37.5k / chat 11 文件 2.5k / docs 15 文件 2.8k）+ 2 个前端共享包（web-core 13.7k、graph-kernel 3.3k）+ 1 个 Node 产物包（agent-sidecar，被 Python subprocess spawn）+ Python 后端核心 `topoone-core`（220 py 文件 64k 行，supervisor 统管 9 进程：gateway:3456 / kb:3459 / mcp:3460 / runner:3458 / llm:3484 / agent:3482 / docs:3481 / chat:3483 / architect:3470）。

各 app 后端：architect 35k、docs 7.5k、chat 4.3k、workbench 152 行薄层（kind=core 进 kb 进程）。

### 1.2 分层纪律实测（健康面，应保持）

- core→app 反向依赖 0 处；app→app 横向 import 0 处；store 不反向依赖业务层；graph-kernel 无反向依赖 web-core
- CONV-00~04 规则被执行；RPC 218 方法基线冻结；manifest 唯一注册点；supervisor 治理完备（pid 校验/指数退避/admin 端点）

### 1.3 结构债四大集中点

| # | 债 | 核心证据 |
|---|---|---|
| 1 | 前端基建七线并行 | HTTP 客户端 ×4（token key 两套：`topocode:token` vs `topocode_token`）；i18n ×2（architect 未接 createAppI18n）；主题 ×2.5；聊天 UI ×3；节点图栈 ×3（d3/cytoscape/graph-kernel）；确认弹窗 ×2；auth-service ×2 |
| 2 | web-core 越位 + 依赖声明缺失 | `ipc.ts`(714)+`types/ipc.ts`(1,127)+`browser-api`+`useComponentId`+`statusBadge` 仅 workbench 消费却住共享层；architect 12 处 import web-core 未声明依赖（靠 hoisting）；graph-kernel 实为 architect 专用 |
| 3 | arch_routes 五层混居 + 循环依赖 | routes 包名下住 store(11,148)/sem(engine.py 4,851)/DDL(899)/req_agent(1,465)/exec_bridge(1,030)；agent↔routes 双向延迟 import 环（orchestrator 20+ 处）；8 个待删兼容 shim；server.py 引用私有函数 |
| 4 | 巨型文件 + 死代码 | 后端：sem/engine 4,851、task_manager 4,296、project.py 2,827、sessions 1,440、req_agent 1,465、exec_bridge 1,030、web_tools 1,849、chat.py 1,815、viewer.py 1,219；前端：AssetManagementWorkspace 3,296、SemanticGraphView 2,649、AnalysisChat 2,400、ChatSession 1,585(@ts-nocheck)、ReportHome 1,443、ProjectCard 1,441、community-store 1,252。死代码 ~4,700+ 行（FE）+ 8 个后端 shim(75 行) + 空目录 + 失效 alias |

### 1.4 既有规划承接

- `archive/architecture-issues-0905.md`（已归档）：A1 测试安全网、A2 docs viewer 拆分、B1a task_manager 拆分蓝图、B1b sem/engine 拆分蓝图、B2 前端组件拆分、B3 图栈二选一、C1-a architect 彻底独立（**本轮裁决采纳**）、C2 kb 薄层档、C3 WAL 直读合法化
- plan-C 系列：M0-M3 已落地，不重开；nine-layer：已完成
- 本方案不重复其蓝图细节，执行时直接引用对应章节

---

## 2. 五项架构裁决（决策记录）

| # | 主题 | 结论 | 影响批次 |
|---|---|---|---|
| ① | architect 前端与 web-core 关系 | **彻底独立**（0905-C1-a）：停止 import web-core（保留 graph-kernel），传输/i18n 自持；**KB 以 MCP 方式为 architect 提供基线组件语义支持**（其余必要交互走只读 HTTP）；token 副本加 `SYNC-WITH` 锚点注释 | B2 |
| ② | apps/chat 归并 | **并入 workbench**：前端能力并入（与 AIAssistantPanel 收敛为一套），docs 两处 `/chat?taskId=` 跳转与 portal 入口改址；后端 topoone_app_chat(4,284) 迁入 workbench 域托管，:3483 退役或换主（B6 内出子方案） | B6 |
| ③ | core/chat/docs 巨型文件拆分 | **纳入 B4**：RPC 218 基线冻结下内部重构 | B4 |
| ④ | 节点图布局栈 | **统一 cytoscape，一步到位**（0905-B3；评审决议：无过渡期）：`useNodeGraph` composable，同一变更内 d3/render-worker/bundle-worker 全退役；性能验收（5k 节点布局 <3s、拖拽 ≥30fps）为切换前 gate，不达标继续调优（cose-bilkent/fcose 均为 cytoscape 布局族参数选择，非栈回退） | B6 |
| ⑤ | AST 解析与符号源归属 | **解析权唯一归 core parsers**（graph_node/graph_edge 唯一写入方，写入 CONV）；**符号源按 SLA 分工**：codegraph=architect 主源（实时符号事实），native/KB=基线认知源（组件归属/划分/命名）+ codegraph 不可用时符号兜底；`ARCH_CODEGRAPH` 默认语义 auto=codegraph 可用即用；native 直读合法化（ro+WAL+manifest 声明+`open_project_ro()`） | B3/B6 |
| ⑥ | 旧代码处置 | **增量绞杀，不做目录级重写**：逐模块「新实现落地 → 门禁全绿 → 同变更内删除旧实现」；git 即备份（每 MS 开工前打 tag `pre-MS{n}`，禁止目录拷贝备份）；隔离重写仅限模块级指定单元（图栈、chat 上提）；防干扰用**模块冻结窗**（MS 涉及模块暂停产品迭代，验收后解冻）；「彻底重构」由 MS7 终态保证（chat 并入、图栈单一、边界收口、循环清零） | 全部批次 |

裁决 ⑤ 补充：实时态领先基线时的接缝（新文件归属未定）走既有机制——unowned 清单 + `probe_impact` + `/project/baseline/sync`；符号查询结果可选带 `source` 字段（仅排障用）。

---

## 3. 批次计划（B0~B6）

> 实施节奏见 [refactor/milestones.md](refactor/milestones.md)：B0~B6 已映射为 MS1~MS7 里程碑，每阶段独立可测、先细化设计评审后开发。

> 原则：先安全网、先删除、再归一、后拆分、边界决策殿后。每子项独立 commit 可单独 revert。旧代码处置=裁决⑥（逐模块替换删除、tag 兜底、冻结窗防踩）。门禁：`npm run type-check && npm run lint && npm run test` 全绿；涉 RPC 拆分另加 `rpc-method-baseline.json` diff 为空。

### B0 安全网+快赢（~5 人日，前置：无）——实施细则见 [refactor/MS1-safety-net.md](refactor/MS1-safety-net.md)

1. 0905-A1 测试盲区：docs 全路由 smoke（36 条业务路由；"27"系 0905 笔误，viewer 实为 26 条）、workbench knowledge.* RPC、chat 核心路径、core 6 步管线集成测试
2. architect package.json 临时补声明 `@topo/web-core`（B2 独立化完成后移除）
3. `render-worker-bundled.js` git untrack——**已完成**（实测已 untracked+ignored，转验证项）
4. `topoone_app_architect/static/architect.html` 出 git
5. 进程口径修正：代码实测 **9 进程**（agent-bus 已退役；`supervisor/cli.py` 逐行核证），本方案原「10 进程」为笔误；README/CONV 现行「9 进程」口径保持不动
6. ~~根 test:py 指向修正~~ 实测指向无误（空目录不致 pytest 收集失败）；真缺陷为 **CI backend job 未装 4 个 app 包**（与 scripts/setup.sh 不一致）——补齐对齐
7. （MS1 探查新发现）viewer.py:852 悬空 `from web_tools import ...` → `POST /api/diagram-editor/process` 必 500；修复指向 `topoone_app_chat.web_tools` + docs 临时依赖声明（MS5 重估）

### B1 删除清零（~3 人日，前置：B0）

1. 前端死代码 ~4,700 行：
   - architect：services（asset-validator/blueprint-agent/extract-service/guide-patterns/mainkb-service）+ stores（collaboration/git-sync/kb-query 死岛）+ 组件（BaselineSummaryBar/ComponentListView/KbQueryView/KbQueryHistory/PseudoExplainer/DesignPanel/ProjectSetupDialog/AssetDetailModal/ScopeProposalModal）
   - workbench：agent-usage-store/plugin-store/TaskCard/ProjectList/providers.ts/mock.ts 约 600 行/`@topo-animation` 失效 alias
   - web-core：fileColors/DiagramRebuildDialog/zmq.ts
2. 后端 8 个兼容 shim 删除（adaptation/capability_mining/context_registry/evaluator/llm_dataset/model_profile/prompt_registry/ws_events，引用方改直达 `agent/`）
3. `apps/{chat,docs}/server/` 空目录
4. KnowledgePage 退役裁决（ActivityBar 入口已注释，路由/页面/store/i18n ~1,500 行；默认建议：退役，执行时无异议即删）

### B2 前端职能归一（~8 人日，前置：B1，方向=裁决①）

1. architect 独立化：12 处 web-core import 替换为自持实现（token/传输/i18n/shell/useTopoRender），api-client/ws-client 加 `SYNC-WITH` 锚点，最后移除 `@topo/web-core` 依赖声明；KB 基线组件语义支持收口为 MCP 通道（kb_gateway）
2. KB 系（workbench/chat/docs）归一：token key 统一为 `topocode:token`（web-core token.ts/api.ts、graph-kernel auth.ts 三处多数派，仅 web-core/utils/http.ts 一处需改）、useConfirm→useDialog、StarLogoMark/svg/auth-service/Markdown 渲染合一
3. web-core 瘦身：ipc.ts/types/ipc.ts/browser-api/useComponentId/statusBadge 下沉 workbench；图域逻辑（render/diagram-normalize/diagramStateStore）归口 graph-kernel
4. agent-sidecar npm 名归一 `@topo/cline-sidecar`

### B3 后端职能归位（~10 人日，前置：B0；architect 35 测试文件即安全网）

1. arch_routes 拆层：routes/ + store/ 独立归位 + sem/ 独立 + db_schema→schema/
2. req_agent.py(1,465)+exec_bridge.py(1,030) 移入 agent/ → orchestrator 20+ 处 `..arch_routes` import 清零断环
3. sessions.py(1,440) 收尾拆分（消息/流 items/分组/摘要）
4. tracking 同名澄清（路由 vs store/tracking）、tagent_* 四件(508 行)归一、server.py 去私有引用
5. sem/engine.py(4,851) 五域拆分（0905-B1b 蓝图：reconcile/extract_primary/extract_scope_impl/aggregate/edge_derive+query 门面）
6. symbols.py/codegraph.py 契约注释升级（裁决⑤三元分工）

### B4 core/chat/docs 巨型拆分（~8 人日，前置：B0，裁决③）

1. task_manager.py(4,296) 五域拆分（0905-B1a 蓝图：tasks_crud/community_query/agent_dispatch/subdocs/git_info/positions；聚合函数锁注册顺序）
2. db/manager.py DDL 外置 `db/schema/{main,knowledge,sessions,chat,project}.py` + 拼接全等契约测试
3. chat.py(1,815)/web_tools.py(1,849) 拆分（顺序：**先拆后迁**——B4 原位拆好并补测试，B6 纯迁移，降低单批次风险）
4. docs viewer/ 子包拆分（0905-A2 蓝图：pages/community/plantuml/diagram_api/diagram_editor/layout）

### B5 前端巨型组件拆分（~9 人日，前置：B2）

统一「子组件+composable」模式，键位/行为零变化：

- architect：AssetManagementWorkspace(3,296：KbQuery/Impact/ChangeMap/NamingGovernance 各抽子组件 + useAssetWindows)、SemanticGraphView(2,649：useSemanticLayout/useGraphSelection/useGraphTheme)、AnalysisChat(2,400)
- workbench：ReportHome(1,443)、ProjectCard(1,441)、community-store(1,252 抽 useComponentAnalysis)

### B6 边界决策落地（~12 人日，前置：B4/B5，裁决②④⑤）

1. chat 并入 workbench：ChatSession(1,585，去 @ts-nocheck) 先拆 useChatStream/useMessageActions/useChatCommands，再上提为 workbench 聊天能力（与 AIAssistantPanel 二选一收敛）；docs/portal 跳转改址；topoone_app_chat 迁入 workbench 域托管（默认建议：保留独立进程与 :3483，目录迁 apps/workbench/ 域，避免 workbench 升 kind=service 的连带改动；B6 时出子方案确认）
2. 项目列表三处归一（workbench HomePage/docs ProjectList/architect OverviewPage → 门户 AppHome 单一入口或明确分工）
3. 图栈统一（一步到位，无过渡）：`useNodeGraph`（cytoscape headless worker；性能 gate：5k 节点布局 <3s、拖拽 ≥30fps）；同一变更内删 d3/@types/d3、render-worker、bundle-worker.mjs 构建步骤，无 feature flag、无 D3 保留期
4. native 直读合法化（ro+WAL+manifest+open_project_ro）——范围收窄：仅符号兜底路径（architect symbols.py native fallback）与 docs viewer 查询；KB→architect 基线组件语义走 MCP（裁决①）
5. C2 薄层档准入标准入 CONV-03、C3 WAL 档入 CONV-04
6. architect 独立化收尾验证（与 KB 系交互仅剩：MCP 基线组件语义 + 必要只读 HTTP；grep 验收 web-core import 清零）

**依赖链**：B0 → B1 → B2 ∥ B3 → B4 ∥ B5 → B6。总计 ~55 人日，每批次独立交付可中止。

---

## 4. 风险与对策（Top 4）

| 风险 | 对策 |
|---|---|
| B2 独立化断供 | B0 先补声明 → B2 自持替换 → 最后删依赖，任一步可停 |
| B3/B4 循环 import 复发 | 拆分纪律「子模块只依赖 common，门面单向依赖子模块」；延迟 import 以 grep 清零验收 |
| B4 RPC 注册顺序漂移 | 聚合函数锁序 + `test_rpc_ids.py` + 基线 diff 为空三重兜底 |
| B6 图栈性能风险 | 性能验收为切换前 gate：不达标继续调优（布局参数/headless worker）直至达标再切；一步到位裁决，不设 D3 回退 |

## 5. 文档动作

每批次完成在本方案 §3 对应条目标注状态（0905 已归档不再维护）；裁决⑤写入 CONV-04 数据归属表（「符号源」行）与 CONV-00 场景边界；B6 后产出 `architecture-review-YYYYMMDD.md` 归档全记录。
