# TopoCode 架构优化点与实施方案（2026-09-05）

> 范围：全仓 —— `packages/core`（后端核心框架）+ `packages/web-core` / `packages/graph-kernel`（前端共享内核）+ `apps/*`（4 个子项目）
> 代码基线：分支工作区（约 2026-09-05）
> 性质：**问题记录 + 逐项展开的实施方案（含拆分蓝图/步骤/验证/风险），尚未实施**
> 前序文档：[architecture-issues-0902.md](archive/architecture-issues-0902.md)（2026-09-02 评估，已归档，下称"0902 评估"）
> 分级口径：沿用 0902 评估 —— P0 正确性 / P1 一致性 / P2 结构性 / P3 架构级（需决策）

---

## 0. 执行摘要

0902 评估中的 P0/P1 问题已基本修复（详见 §1 修复确认表），后端一致性纪律良好。本轮聚焦四类**仍然成立**的优化点：

| 类别 | 编号 | 一句话 |
|---|---|---|
| A 快赢（低风险高收益） | A1–A4 | 测试盲区补齐、docs 路由拆分、architect token 副本收敛、文档残留 |
| B 结构性重构 | B1–B3 | 后端 6 个巨型模块拆分、前端 5 个巨型组件拆分、节点图布局栈二选一 |
| C 架构决策 | C1–C3 | architect 半共享态、kb god-process、docs 直读 project.db 合法化 |
| D 性能/吞吐 | D1–D3 | ZMQ 并发上限可配置、agent-bus 事件驱动化、WriteQueue 写吞吐压测 |

**推进顺序建议**：A1（测试安全网）→ A2/A3/A4（快赢）→ B1（task_manager 优先）→ B2 → B3；C 类先评审拍板再动；D 类出现实际瓶颈再做。

---

## 1. 0902 评估修复确认（本轮核验）

| 0902 编号 | 问题 | 本轮核验结果 |
|---|---|---|
| C4 [P0] | PUB 端口命名+默认值漂移 | ✅ 已修复：`config.py:15` `KB_PUB_PORT=5681` 单一事实源，绑定方/订阅方同名同默认 |
| C2 [P1] | 双进程拓扑 | ✅ 已修复：`engine/app.py:297` 注释确认 `_run_distributed` 与 distributed 分发已删除 |
| C3 [P1] | kb 自 spawn 双归属 | ✅ 基本收敛：`_start_optional_services` 不再自 spawn 子进程（仅保留 IngestConsumer + Data API） |
| C1 [P1] | 进程数 9 vs 10 | ⚠️ **部分修复**：README/CONV-00 §1/CONV-04 G6 已统一为 10，但 CONV-00 §3 分工矩阵（:45"9 进程拓扑与端口表"）与 §6 角色表（:83"维护 204 基线与 9 进程拓扑"）**残留 2 处 "9 进程"** → 见 A4 |
| C5 [P1] | CLI 空壳命令 | ✅ 已修复：`cli.py` 无 "feature in development" 残留 |
| C6 [P1] | 遗留空目录 `apps/workbench/server/` | ✅ 已删除 |
| R1 [P2] | 5 套图/动画栈 | ✅ 主体已退役：`topo-animation/`（45 文件）与 `usePixiCanvas.ts` 已删除；**遗留**：节点图 D3（workbench）vs Cytoscape（docs）双栈 → 见 B3 |
| R3 [P2] | i18n 碎片 + chat 无 i18n | ✅ 部分修复：chat 已建 `apps/chat/src/i18n/{zh-CN,en-US,index}.ts` |
| R5 [P2] | architect 死依赖 | ✅ 已清理：`apps/architect/package.json` 无 cytoscape/marked |
| F2 [P2] | token/归一化 copy-paste | ⚠️ 部分修复：web-core 内部已收敛（`browser-api.ts`/`api.ts` 均 import `services/token.ts`；归一化抽至 `services/diagram-normalize.ts`）；**architect 前端仍是副本** → 见 A3 |

---

## 2. A 类：快赢项（低风险高收益，建议 1–3 天/项）

### A1 测试覆盖严重不均 【P2，最高杠杆】

**现状与证据**：

| 子系统 | 规模 | 测试现状 |
|---|---|---|
| docs 后端 | `viewer.py` 1206 行 / 27 个路由 + `doc_service.py` + `web_root.py` | `apps/docs/tests/` **完全为空** |
| workbench 后端 | `knowledge_service.py`（7 个 knowledge.* RPC） | 仅前端 `smoke.test.ts` + `unit/`，后端 RPC 零测试 |
| chat 后端 | `chat.py` 1815 行（35 路由）+ `web_tools.py` 1849 行（30 工具） | 仅 `test_tagent_chat.py` 1 个文件 |
| core 引擎 | `task_manager.py` 4070 行 + `analyst_runner.py` 1171 行（6 步分析管线）+ `report_service.py` 761 行 | `packages/core/tests/` 17 个文件中**无分析管线直接测试**（有 parser/symbol_graph/db_layout 等，但无 runTask→6 步→report 的集成测试） |

对比之下 architect 后端有 35 个测试文件（含 2696 行的 `test_semantic_assets.py`），是全仓测试标杆。

**影响**：
- B1/B2 的巨型模块拆分**没有安全网**，重构风险不可控——这是本方案集中 A1 排在首位的原因。
- docs 的 27 个路由承载 PlantUML 缓存、图编辑器多轮会话等有状态逻辑，回归全靠手测。

**方案（分四步）**：

1. **docs 路由 smoke（1 天）**：复用 architect `tests/test_route_smoke.py` 的模式——FastAPI `TestClient` + 临时 data_dir + fixture 项目库，对 27 个路由做「可达 + 参数校验 + 空数据兜底」三级断言。PlantUML/无头渲染类路由 mock 渲染器（只测缓存命中/未命中分支）。
2. **workbench knowledge.* RPC 测试（0.5 天）**：`register_methods` 注入内存 ZMQServer 假体（或直接函数级调用 `register_knowledge_methods` 返回的 handler），覆盖 CRUD + tags JSON 编解码 + getGraph 二部图构造。
3. **chat 核心路径测试（1 天）**：优先覆盖 `chat.py` 的会话/消息 CRUD、`/compress` 命令、引用解析（`ReferenceParser.parse`）；`web_tools.py` 的 30 个工具按域抽 5–6 个代表做单测（工具是纯查询函数 + 8000 字符截断，易测）。
4. **core 分析管线集成测试（1–2 天）**：建 10 文件左右的多语言 fixture 项目（py+ts，含 import/call 关系），`runTask` 走完 6 步管线，断言：
   - `graph_node/graph_edge` 行数与 provenance 分布（parser/resolution/framework）；
   - `community_hierarchy` 至少 1 层、模块度 > 0；
   - `analysis_tasks` 状态机 done=100；
   - 进度事件序列单调递增（mock PUB 收集）。
   LLM 相关步骤（Step 6 摘要）mock `llm.chat`。

**验证**：`python -m pytest apps/docs/tests apps/chat/tests apps/workbench/tests packages/core/tests -v` 全绿；CI 中纳入 `npm run test:py`。

**风险与回退**：纯新增测试，零生产代码改动；唯一风险是 fixture 设计不当导致偶发失败——多语言 fixture 固定文件内容哈希，避免随机。

**工作量**：约 3.5–4.5 人日。

---

### A2 docs 服务 viewer.py 单文件路由拆分 【P2】

**现状与证据**：`apps/docs/topoone_app_docs/viewer.py` 1206 行、27 个路由，混杂五类职责：

| 职责组 | 路由 | 行区间（约） |
|---|---|---|
| 页面 | `/doc`、`/code` | 40–60 |
| 社区/图数据 | `/api/community-{doc,files,children,graph}`、`/api/file-{graph,summary}`、`/api/file`、`/api/cascade-levels`、`/api/heatmap`、`/api/external-{graph,stats}` | 62–565 |
| PlantUML 代理与缓存 | `/api/plantuml`（GET/POST）、`/clear-cache`、`/rebuild` | 566–640 |
| 图构建/校验 | `/api/mermaid/rebuild`、`/api/diagram/{build,validate,ir-docs}` | 641–800 |
| 图编辑器多轮会话 | `/api/diagram-editor/process`（单 handler **约 270 行**）、`/api/diagram-tools/apply` | 800–1120 |
| 布局持久化 | `/api/graph-layout`（GET/POST/DELETE） | 1121–1206 |

**影响**：图编辑器会话逻辑（独立日志 `diagram-editor.log`）与纯查询路由耦合在同一文件；多人并行改动冲突面大；27 路由无法按域做依赖隔离。

**方案**：按 `doc_service.py`/`web_root.py` 既有先例，拆为 `viewer/` 子包，路由路径**零变化**：

```
topoone_app_docs/
├── viewer.py            → 兼容 shim：from .viewer import router（保留 1 个版本后删除）
└── viewer/
    ├── __init__.py      # 聚合 router（APIRouter include）
    ├── pages.py         # /doc /code
    ├── community.py     # 社区/文件/热力图数据（10 路由）
    ├── plantuml.py      # PlantUML 代理 + 缓存管理（4 路由）
    ├── diagram_api.py   # mermaid rebuild + diagram build/validate/ir-docs（4 路由）
    ├── diagram_editor.py# 图编辑器多轮会话 + tools/apply（2 路由，最大块）
    └── layout.py        # graph-layout CRUD（3 路由）
```

拆分纪律：只搬移不改逻辑；共享 helper（项目库定位、PUB 发布）入 `viewer/common.py`；每步搬移后跑 A1 的 smoke。

**验证**：`python -m pytest apps/docs/tests -v`（依赖 A1 先行）；手动核对 `/api/topo`、`/api/plantuml` 行为不变；`npm run type-check`。

**风险与回退**：低。风险点是循环 import——`common.py` 保持零业务依赖即可。回退 = revert 单个 commit。

**工作量**：1 人日（含 smoke 回归）。

---

### A3 architect 前端 token 副本收敛 【P2】

**现状与证据**：`apps/architect/src/services/api-client.ts:11-19` 是 web-core `packages/web-core/src/services/token.ts` 的 copy-paste（同样的 `#token=` → `localStorage['topocode:token']` → Bearer 语义，注释自述"与 web-core 一致"）。web-core 内部（browser-api.ts/api.ts）已 import 单一源，但 architect 未接入。另外 `normalizeDiagram` 类归一化在 `apps/architect/src/utils/diagram-gen.ts` 与 workbench `useDiagramRenderer.ts` 仍有本地副本（web-core 已有 `services/diagram-normalize.ts`）。

**影响**：token 语义若调整（如改 key、加过期），architect 会静默分叉——正确性问题（0902 F2 的残余）。

**方案**（两档，按 C1 决策联动）：
- **最小改（若 C1 选"加深共享"）**：architect `api-client.ts` / `ws-client.ts` 改为 `import { readToken, authHeaders } from '@topo/web-core/services/token'`，删除本地副本；`diagram-gen.ts` 归一化改 import `@topo/web-core/services/diagram-normalize`。约 0.5 天。
- **彻底解耦（若 C1 选"完全独立"）**：token 逻辑保留自持副本但**加注释锚点**（`# SYNC-WITH: packages/web-core/src/services/token.ts`），并在两文件头部互相引用；同时把该约束写入 CONV。约 0.5 天。

**验证**：`npm run type-check && npm run build -w @topo/app-architect`；手动 `#token=` 首开流程回归。

**风险**：极低。web-core token 模块无 Vue 依赖，纯函数。

**工作量**：0.5 人日。

---

### A4 文档残留："9 进程"两处 【P1】

**现状与证据**：CONV-00 修复 C1 时遗漏两处——
- `docs/conventions/CONV-00-总纲与分工矩阵.md:45`（§3 分工矩阵·核心框架行）："…RPC 204 方法基线、**9 进程拓扑**与端口表…"
- `docs/conventions/CONV-00-总纲与分工矩阵.md:83`（§6 角色表·核心组行）："…维护 204 基线与**9 进程拓扑**…"

**影响**：0902 C1 的残余；G6 门禁判据已是 10 进程，规约正文与门禁不一致会误导新人。

**方案**：两处 "9 进程" → "10 进程"；顺带全仓 grep `9 进程|9 个进程` 确认无其他残留。

**验证**：`grep -rn "9 进程\|9 个进程" README.md docs/ packages/ apps/ --include="*.md"` 零命中。

**工作量**：5 分钟。

---

## 3. B 类：结构性重构（中风险，需 A1 安全网先行）

### B1 后端巨型模块拆分 【P2】

**现状与证据**（wc -l Top 12）：

| 文件 | 行数 | 内部结构核验 |
|---|---|---|
| `arch_routes/sem/engine.py` | 4690 | 单文件混装：增量 reconcile + 提取 + 层级聚合 + 关系推导 + 查询 + codegraph 适配 |
| `engine/task_manager.py` | 4070 | `register_analysis_methods`（:220）单函数 **~3600 行**，内含 8+ 个 `# ==== 分区 ==== 注释块` 与上百个闭包 handler |
| `engine/service/project.py` | 2832 | 15 个模块级函数 + 107 处 `server.register(` |
| `db/manager.py` | 2137 | `SQLiteContext`（:31）+ 5 段内联 DDL（`MAIN_DB_TABLES_SQL` :229 独占 ~426 行；`PROJECT_DB_TABLES_SQL` :799 ~494 行）+ `MultiDBManager`（:1293） |
| `chat/web_tools.py` | 1849 | 30 个 web_* 工具定义 + 执行器 |
| `chat/chat.py` | 1815 | 35 路由单文件 |
| `arch_routes/req_agent.py` | 1527 | harness + skill 注册表 + 协议解析 |
| `llm/service.py` | 1500 | 三模式 + provider 路由 + 上下文装配 |
| `parsers/core/walker.py` | 1397 | 单类多职责（visit/usage flush/emit） |
| `agent/.../runtime.py` | 1303 | AgentRuntime 核心循环 |
| `docs/viewer.py` | 1206 | → A2 单独处理 |
| `engine/analyst_runner.py` | 1171 | 6 步管线编排（结构尚可） |

**影响**：
- `task_manager.register_analysis_methods` 是全仓最大函数：任务 CRUD / 社区查询 / agent 调度 / subdoc CRUD / git 探测 / 布局持久化七类职责内联交错，修改任何一个方法都要在 3600 行里定位；
- `sem/engine.py` 的提取/聚合/推导三阶段共享大量模块级私有函数，与查询面（api_search/semantic_graph）耦合，测试只能走整链；
- DDL 内联使 `MultiDBManager` 的 diff 阅读几乎不可行。

**方案**：

**B1a. `task_manager.py` 拆分（优先，2–3 天）**——目标结构：

```
engine/
├── task_manager.py            # 兼容 shim：re-export register_analysis_methods
└── task_api/
    ├── __init__.py            # register_analysis_methods = 顺序聚合下列五组
    ├── tasks_crud.py          # listTasks/createTask/runTask/stopTask/rerun/清扫残留（:223-805 段）
    ├── community_query.py     # getCommunityGraph/getCascadeLevels/getSymbolDetail/getEdgeDetail/
    │                          # getCrossCommunityEdges/getCommunityFileGraph/getExternalStats/
    │                          # fileStats/社区 LLM 结果查询（:806-2242 段）
    ├── agent_dispatch.py      # startPipeline/startOverview/analyzeComponents/startPreSummary/
    │                          # getAgentProgress/cancel/pause/resume（:2243-3497 段，含 distributed 兼容注释块）
    ├── subdocs.py             # report.createSubDoc 等 5 个写方法（:3498-3829 段）
    ├── git_info.py            # detect/save/get_git_info + check_import_status（:3851-3980 段）
    └── positions.py           # save/load/list/clear_positions（:3981-4070 段）
```

拆分纪律：
1. 每个模块导出 `register(server, multi_db, ...)` 风格函数，`__init__.py` 按原注册顺序聚合（保持方法注册顺序 = rpc_ids 基线稳定）；
2. 共享闭包（`_ensure_project_db`/`_get_project_root`/`_make_agent_history_cb`）上提为模块级函数或入 `common.py`；
3. 每拆一块跑 `test_rpc_ids.py` + A1 的管线集成测试 + `python -c "from topoone.engine.app import BackendApp"` 导入烟测；
4. **冻结契约**：`rpc-method-baseline.json` 不变（方法集与编号零变化），拆分后重生成基线 diff 必须为空。

**B1b. `sem/engine.py` 拆分（3–4 天）**——沿既有 `sem/` 子包模式（incremental.py/compare.py/codegraph.py/context.py 已存在）继续切：

```
sem/
├── engine.py                  # 只留门面：_lazy_reconcile + search/detail/api_search + 公共 re-export
├── reconcile.py               # reconcile_semantic + 新鲜度判定（依赖既有 incremental.py）
├── extract_primary.py         # 启发式主类型判定族（_primary_kind_for_node/_heuristic_extract_primary/
│                               # _is_route_handler/_config_carrier_signal/_is_contract_boundary_node/_branch_dense）
├── extract_scope_impl.py      # extract_scope/save_agent_assets/_save_assets + 字段抽取族
├── aggregate.py               # _leaf_components/_postorder_component_nodes/_aggregate_one_batch/
│                               # _aggregate_high(_best_effort)/_link_parent/_inherit_ast_refs_from_aggregates
├── edge_derive.py             # _cg_* codegraph 适配 + _derive_project_edges(_kb)/_derive_indirect_edges/_cached_derived_edges
└── (query 面留在 engine.py 门面，后续可再抽 query.py)
```

依赖方向：`engine.py → {reconcile, extract_*, aggregate, edge_derive}`，四者互不 import（现在也基本无交叉，纯物理切分）。architect 的 35 个测试文件是现成安全网。

**B1c. `db/manager.py` 拆分（1 天）**：DDL 按库拆 `db/schema/{main,knowledge,sessions,chat,project}.py`（各导出 `*_TABLES_SQL` 常量），`manager.py` 只留 `SQLiteContext` + `MultiDBManager`；加一条契约测试：拼接后的五段 SQL 与旧常量字符串全等。

**B1d. `chat.py` / `web_tools.py`（1.5 天）**：chat.py 拆 `chat_api/{sessions,messages,drafts_notes,archives,models_skills}.py`（FastAPI 子 router）；web_tools.py 拆 `web_tools/{defs,executor,project_tools,arch_tools,file_tools,symbol_tools,session_tools}.py`。

**验证**（每步）：`npm run test:py` + `npm run type-check`；task_manager 拆分额外要求基线 diff 为空；sem 拆分要求 architect 测试全绿。

**风险与回退**：
- 最大风险 = 注册顺序变化影响 rpc_ids 或启动顺序 → 用聚合函数锁序 + 基线比对兜底；
- 循环 import → 各子模块只依赖 `common`，门面单向依赖子模块；
- 回退 = 每个子模块独立 commit，可单独 revert。

**工作量**：合计 8–10 人日（B1a 最优先，可独立交付）。

---

### B2 前端巨型组件拆分 【P2】

**现状与证据**（wc -l）：

| 文件 | 行数 | 问题 |
|---|---|---|
| `apps/architect/src/pages/AssetManagementWorkspace.vue` | 2823 | 资产管理中枢：图谱视图 + 矩阵窗 + 索引窗 + 命名治理 + 伪代码解释 + 代码变更弹窗全在一文件 |
| `apps/architect/src/components/assets/SemanticGraphView.vue` | 2580 | 多视图语义图谱 + 交互 + 布局 + 主题 |
| `apps/chat/src/pages/ChatSession.vue` | 1585 | 会话列表 + 消息流 + 输入 + 各类对话框 |
| `apps/workbench/src/components/report/ReportHome.vue` | 1431 | 报告首页多 section |
| `apps/workbench/src/stores/community-store.ts` | 1261 | 社区浏览 + LLM 分析流水线调度 + 音效/杂项混杂 |
| `apps/docs/src/pages/DocViewer.vue` | 1122 | 文档/目录/文件/热力图/笔记五合一 |

**影响**：这 6 个文件恰是各 app 迭代最频繁的热点——合并冲突高发、props/emits 边界模糊、局部状态全局化、i18n 键与逻辑耦合难测。

**方案**（统一模式：**面板子组件 + composable 抽逻辑**，键位/行为零变化）：

1. **AssetManagementWorkspace**（2.5 天）：按现有窗口组件继续下沉——`SemanticGraphView`/`GraphMatrixWindow`/`AssetIndexWindow` 已是独立组件，把页面内剩余大块（KbQuery 区、Impact/ChangeMap 区、NamingGovernance 区、PseudoExplainer 区）各抽子组件；页面只留布局 + 窗口开关状态（可抽 `useAssetWindows()`）。
2. **SemanticGraphView**（2 天）：抽 `useSemanticLayout()`（布局计算）、`useGraphSelection()`（节点选择联动）、`useGraphTheme()`；渲染层按视图模式（graph/matrix/index）拆子组件。
3. **ChatSession**（1.5 天）：会话侧栏/消息流/输入区已是子组件，把页面内剩余逻辑抽 `useChatStream()`（SSE 消费 + 状态机，沉淀对 `consumeChatSse` 的封装）、`useMessageActions()`（复制/引用/续写/删除批量）、`useChatCommands()`（/compress /help 与 @引用补全）。
4. **community-store**（1 天）：把「组件批量 LLM 分析流水线」调度（analyzeComponents/agent 任务/预摘要/结果保存命名）抽 `composables/useComponentAnalysis.ts`，store 只留社区浏览数据态；音效移 `utils/sound`。
5. ReportHome / DocViewer（各 1 天）：按 section/面板抽子组件 + composable。

**验证**：`npm run test:fe`（graph-kernel/web-core 契约测试不受影响）+ `npm run build -w @topo/app-*` + 手动回归各页核心交互；architect 的 `workflow.test.ts`/`settings-store.test.ts` 必须全绿。

**风险与回退**：中等——Vue 拆分易引入响应式丢失（解构 reactive）。纪律：composable 返回 `computed`/ref 而非解构 props；每组件拆分独立 commit。

**工作量**：合计 9–10 人日，可按 app 并行。

---

### B3 节点图布局栈二选一（D3 vs Cytoscape）【P2，0902 R1 遗留决策】

**现状与证据**：
- workbench：`d3@7.9.0`（`apps/workbench/package.json:17`），力导向/树布局在 Web Worker 中动态导入（`src/workers/render-worker.ts:20` `await import('d3')`，规避 Vite IIFE code-splitting 问题），消费方 `D3ForceGraph.vue`；
- docs：`cytoscape@^3.34.0` + `cytoscape-cose-bilkent@^4.1.0`（`apps/docs/package.json:18-19`），`composables/useGraphState.ts` + `useGraphLayout.ts`（含稳定色相配色）。

**影响**：同一"社区图/文件图"概念两套实现：布局参数、交互（缩放/拖拽/选中）、配色、性能特征各自维护；修 bug 与调优无法互通。

**方案（建议统一到 Cytoscape + cose-bilkent，1.5–2 周）**：

理由：a) cose-bilkent 布局质量优于手调 d3-force；b) docs 侧已沉淀稳定色相/布局持久化（`/api/graph-layout`）；c) Cytoscape 可运行于 Web Worker（官方支持 headless 模式），可保留 workbench 的 Worker 化布局成果。

步骤：
1. web-core 新增 `composables/useNodeGraph.ts`：封装 Cytoscape 实例生命周期 + cose-bilkent 布局 + Worker 化布局选项 + 视图状态（zoom/pan 持久化对接 `/api/graph-layout`）——对齐 0902 §1.1 "文本图归 topoOne 内核 + 节点图一个库" 的目标栈；
2. workbench `D3ForceGraph.vue` 内部改用 `useNodeGraph`，**对外 props/emits 接口不变**（消费方 D3ForceGraph 的 4 处引用零改动）；
3. docs `useGraphState/useGraphLayout` 迁移到同一 composable，删除本地副本；
4. 移除 `d3` 与 `@types/d3`（root）依赖，`render-worker` 退役（或改造为 Cytoscape headless worker）；
5. 性能验收：5k 节点图首次布局 < 3s、拖拽帧率 ≥ 30fps（与现 D3 版本对比不回退）。

**验证**：`npm run build` 全量 + workbench/docs 图交互手动回归 + 大图性能对比记录。

**风险与回退**：中高（0902 已标注"最大项"）。cose-bilkent 大图性能需先 spike（>3k 节点可能需降级 fcose）；保留 `D3ForceGraph.vue` 旧实现一个版本期，feature flag（settings）切换。

**工作量**：7–10 人日（含 spike 与性能调优）。

---

## 4. C 类：架构决策项（先拍板，再立项）

### C1 architect "半共享最差态" 【P3，0902 F3 未决】

**现状**：architect 前端同时共享（`@topo/graph-kernel` TopoDiagram、web-core DiagramViewer）与 fork（`api-client.ts`/`ws-client.ts`/`backend.ts` 共 34 个 service、独立 i18n、A3 的 token 副本）。共享部分变动牵动 architect，fork 部分各自漂移。

**决策选项**：
- **(a) 彻底独立**（符合"工作实践导向、未来完全独立"战略）：停止 import `@topo/web-core`（`@topo/graph-kernel` 本就是独立内核包，可保留）；传输/i18n 自持；与 KB 系只经 MCP(:3460)/HTTP 交互。工作量约 3–5 天（替换 DiagramViewer 引用为 graph-kernel 的 TopoDiagram + A3 的锚点注释）。
- **(b) 加深共享**：api-client/ws-client 改造为 web-core 传输层的参数化实例（web-core 需先支持自定义 baseUrl + `{code,message,data}` 响应约定），i18n 接入共享 locale 键。工作量约 5–8 天，且 web-core 传输层要先泛化。

**建议**：(a)。理由：领域分野明确（KB=学习研究 / architect=工作实践），MCP 互调机制已就绪（core mcp 插件 + `/api/architect/mcp/calls`），(a) 一次性消除半共享税且不给 web-core 增加抽象负担。

**决策后动作**：CONV-00 §2/§3 更新 architect 行的"冻结契约"（明确允许不再对齐 KB 系一致性整改）；A3 按选项联动。

### C2 kb god-process（workbench kind=core）【P3，0902 B1 未决】

**现状**：kb 进程承载核心引擎 + data API(:3459) + IngestConsumer + workbench 的 7 个 `knowledge.*` 方法（进程内注册）。

**建议**：**维持现状 + 文档化**。理由：workbench 后端仅 7 个只读为主的薄方法，无独立生命周期/DB 需求；`kind=core` 已是 manifest 正式机制。动作：CONV-03 把 kind=core 定义为正式"薄层档"（准入标准：≤20 个方法、无独立 DB、无长任务）；设触发线——workbench 后端方法数 > 20 或出现长阻塞任务时，升级为独立进程（对齐 docs/chat 模式）。

### C3 docs 直读 project.db 的边界规则合法化 【P3】

**现状**：docs 服务直接只读共享各项目 `project.db`（SQLite WAL 多进程读），未走 kb HTTP——与 CONV-00 边界规则 2"跨进程取数只许 RPC/HTTP"存在张力（规则只认可 architect 的 HTTP 只读为范本）。

**权衡**：改走 HTTP 会给 27 个查询路由增加一跳且 kb 需扩一批透传方法（性能损失明确、收益仅是规约洁癖）；WAL 只读共享是 SQLite 官方支持模式且 docs 已稳定运行。

**建议**：**合法化该模式**——CONV-04 §5 数据归属表新增"只读 WAL 共享"档：允许同机服务以 `mode=ro` + WAL 直接打开他库，约束三条：a) 只读（禁写事务）；b) 禁止跨机；c) 必须在 manifest 注释声明共享哪些库。同步在 `docs` manifest 注明。同时在 `MultiDBManager` 增加 `open_project_ro()` 工厂固化只读连接，防止误写。

---

## 5. D 类：性能/吞吐（出现实际瓶颈再做，先留观测点）

### D1 ZMQ 并发上限可配置 + 分级 【P2】

**现状**：`rpc/zmq_server.py:273` `self._ipc_sem = asyncio.Semaphore(10)` 硬编码——大项目分析期间（长查询 getCommunityGraph/getSymbolDetail 可能秒级），前端控制类轮询（task 状态）可能占满 10 槽导致 UI 卡顿。

**方案**：
1. 上限 env 化：`config.py` 增加 `RPC_CONCURRENCY`（默认 10）；
2. 方法分级：快查询（task/progress/config 类，<50ms 预期）走独立 `Semaphore(20)`，长分析类走现有池——在 `rpc_ids` 或方法注册时声明 `fast=True`；
3. 饱和观测：`/zmq/status` 增加 semaphore 待队计数（现 `get /zmq/status` 已存在，补两字段）。

**工作量**：1 天。**验证**：压测脚本并发 30 个混合请求，断言快查询 P95 不随长查询排队劣化。

### D2 agent-bus 轮询改"即时触发 + 轮询兜底" 【P3】

**现状**：`agent_bus.py` `_dispatch_loop` 1s 轮询 `arch_bus_messages` 单表（create → pending → delivered/failed）。当前消息量小，无实际瓶颈。

**方案**（仅在 agent 协作频度上升后实施）：`publish` 入库成功后直接 `asyncio.create_task(_dispatch_one(msg))` 即时分发；轮询降为 5s 兜底（扫 pending 超时重投）。收益：handoff/clarify 延迟从 ~1s 均值降至 ~0；改动局部（broker 单文件），低风险。

**工作量**：0.5 天 + 回归 `test_agent_bus.py`。

### D3 WriteQueue 写吞吐压测与批量提交 【P2】

**现状**：KB 侧所有写经 `WriteQueue` 单写线程串行（消除 SQLITE_BUSY 的正确设计）；5k+ 文件项目导入/解析期，`graph_node/graph_edge` 批量写入集中在该线程。

**方案**：
1. 先压测：构造 5k/20k 文件 fixture，记录 Step1-4 各阶段写队列深度与耗时分布（WriteQueue 加排队计数直方图）；
2. 若确认瓶颈：a) GraphEmitter 的 `edge_callback` 流式批写从逐条改批量事务（`executemany` 分组，现有机制已支持批回调，核对批大小默认值）；b) 解析期临时 `PRAGMA synchronous=NORMAL` + 加大 `cache_size`（WAL 下安全）；
3. 验收：20k 文件项目 Step1 耗时相对基线下降 ≥ 30% 或确认非瓶颈后关闭。

**工作量**：压测 1 天 + 优化 1–2 天（视结果）。

---

## 6. 实施路线图与依赖

```
第 1 周   A4(5min) → A1(测试安全网, 4.5d) → A3(0.5d, 若 C1 已决)
          └ C1/C2/C3 架构评审会（拍板，不阻塞 A/B）
第 2 周   A2(viewer 拆分, 1d) → B1a(task_manager 拆分, 3d) → B1c(db/manager, 1d)
第 3 周   B1b(sem/engine 拆分, 4d) ∥ B2 前端拆分启动（可按 app 并行）
第 4 周   B1d(chat 拆分) → B2 收尾 → B3 spike（cose-bilkent 大图性能）
第 5 周   B3 实施（若 spike 通过）→ C1 落地（按决策）
按需      D1（可提前，独立无依赖）→ D3 压测 → D2
```

**依赖关系**：A1 是 B1/B2/B3 全部的前置；B1a 是 B1b/B1d 的模式样板；C1 决策决定 A3 走哪档；D 类相互独立。

**门禁对齐**（CONV-04 G1–G8）：每个 B 类 PR 必须全绿 `npm run type-check && npm run lint && npm run test`；B1a 额外要求 `rpc-method-baseline.json` diff 为空；涉及 gateway/supervisor 的改动（本方案无）才触发 G7/G8。

---

## 7. 附录：证据索引（本轮核验）

- 巨型文件行数：`wc -l`（2026-09-05）——sem/engine.py 4690 / task_manager.py 4070 / project.py 2832 / db/manager.py 2137 / web_tools.py 1849 / chat.py 1815 / req_agent.py 1527 / llm/service.py 1500 / walker.py 1397 / runtime.py 1303 / viewer.py 1206；前端 AssetManagementWorkspace.vue 2823 / SemanticGraphView.vue 2580 / ChatSession.vue 1585 / ReportHome.vue 1431 / community-store.ts 1261 / DocViewer.vue 1122
- task_manager 内部分区注释：`engine/task_manager.py:223,239,806,888,1472,2243,3498`；模块级尾部函数：`:3830-4070`
- sem/engine.py 函数清单：`:48-2145+`（reconcile/extract/aggregate/edge_derive 各族行号见 B1b）
- viewer.py 27 路由：`:40-1182`；diagram-editor/process 单 handler 约 `:800-1073`
- db/manager.py DDL 区间：MAIN `:229-655` / KNOWLEDGE `:655` / SESSIONS `:675` / CHAT `:735` / PROJECT `:799-1293` / MultiDBManager `:1293`
- 测试盲区：`apps/docs/tests/`（空）、`apps/workbench/tests/`（smoke + unit）、`apps/chat/tests/`（1 文件）、`packages/core/tests/`（17 文件，无管线集成测试）
- 布局双栈：`apps/workbench/package.json:17`（d3）、`apps/workbench/src/workers/render-worker.ts:20`（动态导入）、`apps/docs/package.json:18-19`（cytoscape + cose-bilkent）
- token 副本：`apps/architect/src/services/api-client.ts:11-19` vs `packages/web-core/src/services/token.ts`
- ZMQ 信号量：`rpc/zmq_server.py:273`
- 文档残留：`docs/conventions/CONV-00-总纲与分工矩阵.md:45,83`

> 本文档为评估记录与实施方案，不构成已实施的变更；各项待按 §6 路线图单独立项推进。
