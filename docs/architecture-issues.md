# TopoCode 架构评估与问题修正文档

> 范围：全仓 —— `packages/core`（后端核心框架）+ `packages/web-core`（前端共享内核）+ `apps/*`（子项目）
> 代码基线：分支 `dev-1`（提交约 2026-08-30）
> 评估维度：一致性 / 拓展性 / 耦合 / 冗余
> 性质：**仅记录问题与修正方向，不含任何代码改动**
> 专项展开：[architect 子系统架构评估](architect-review.md)
> 更新日期：2026-09-02

---

## 0. 执行摘要

**宏观架构扎实，微观接缝处已出现明显侵蚀。**

后端经过 M01–M14 刻意模块化：进程拓扑、manifest 驱动注册、RPC 契约冻结、G1–G8 门禁都很成熟，是全仓最强的部分。但**前端没有跟上后端的纪律**，出现重复实现、多套并行图渲染栈、i18n 碎片化、传输层多套并存。文档与代码已开始漂移（进程数、端口、CLI 能力）。

四维度一句话结论：

| 维度 | 结论 |
|---|---|
| 一致性 | 文档/代码已漂移；同一事实（进程拓扑、PUB 端口）在多处定义且不一致 |
| 拓展性 | 后端 manifest 驱动是优秀实践；前端无脚手架/模板，新 app 会继承既有分歧 |
| 耦合 | 后端单向依赖干净但 kb 成 god-process；前端靠 copy-paste 形成"影子依赖" |
| 冗余 | 最严重：5 套图/动画栈、3 套传输、~8300 行 i18n 碎片、多处死代码/死依赖 |

**不受战略背景影响、始终成立的最高杠杆问题（Top 4）：**

1. **PUB 端口命名+默认值漂移**（正确性）：独立运行 kb 时事件桥静默失效。
2. **共享面上 copy-paste 的影子依赖**（可维护性）：token ×3、`normalizeDiagram` 在 web-core 内部就有 2 个 mermaid 单例 + 3 份归一化。
3. **i18n 碎片 + chat 完全无 i18n**（正确性）：多语言（en-US）会破。
4. **文档/代码漂移**（低成本高收益）：进程数 9 vs 10、PUB 端口、CLI 空壳命令，门禁 G6 判据与真实拓扑不符。

---

## 1. 评估口径与战略背景

以下三点为本次评估的既定前提，直接影响若干问题的**定性**（缺陷 vs 设计意图）：

### 1.1 自研 TopoScript 引擎 = legacy，倾向退役
`apps/workbench/src/lib/topo-animation`（45 个 `.ts` 文件：tokenizer→parser→semantic→codegen→AnimationEngine→SVG/Pixi 渲染器→导出）为**历史产物，倾向退役**。因此图渲染"多栈"中它不是战略多栈，而是**待下线债**。目标栈收敛为：**topoOne 内核（文本图 mermaid/plantuml）+ 一个力导向库（节点图，D3 / Cytoscape 二选一）**。

### 1.2 architect = 半独立，未来可能完全独立
- architect 前端目前**自带一套** `api-client.ts` / `ws-client.ts` / `backend.ts`（约 34 个 service 文件），几乎不共享 web-core 传输层。
- 战略：保持半独立，未来可能进一步拆分乃至完全独立；**app 之间保留 MCP 模式的接口调用**。
- 领域分野：**KB（workbench/docs/chat）= 学习研究导向；architect = 工作实践导向**。
- 结论：architect 与 KB 系"低一致性"**属设计意图，不算缺陷**。但见 §4-F3 的"半共享最差态"问题。
- MCP 互调方向**与现有架构兼容**：core 已有 `mcp` 插件（`:3460`，`/v1/tools`）+ RPC/HTTP 总线 + `/api/architect/mcp/calls`，无需新机制。

### 1.3 一致性/共享目标聚焦 KB 系
基于 1.2，"统一 i18n / 统一传输 / 上提 web-core"等整改**只针对 KB 系（workbench + docs + chat + portal）**，不再强求 architect 对齐。这使目标更聚焦：KB 系内部的多套传输/i18n/theme 才是真正的债。

### 1.4 问题分级口径
- **P0 正确性**：会真的产生错误行为（数据丢/多语言破/静默失效）。
- **P1 一致性**：文档/代码/实现之间不一致，误导后续开发。
- **P2 结构性**：重复/多栈/无脚手架，维护成本复合增长。
- **P3 架构级**：边界/归属层面的取舍，需产品/架构决策。

---

## 2. 维度一：一致性（Consistency）

### C1 进程数不一致 [P1]
- **现象**：README 写 10 进程，CONV-00 / CONV-04 写 9 进程，G6 门禁判据写"9 进程全 OK"，而实际 `topo serve` 拉起 **10** 个（`agent-bus` 为后加的 P3 薄服务，`_all_service_names()` 会追加为第 10 个）。
- **证据**：`README.md:117`（10）；`docs/conventions/CONV-00-总纲与分工矩阵.md:8`（9）；`docs/conventions/CONV-04-API契约与验证门禁.md:97`（G6=9）；`packages/core/topoone/supervisor/cli.py:280`（`_all_service_names` 顺序表 9 项 + agent-bus 兜底追加）。
- **影响**：门禁 G6 判据与真实拓扑不符，验收会误判；文档对新人误导。
- **修正方向**：以 `cli.py` 实际拓扑为准，统一 README/CONV-00/CONV-04/G6 为 10 进程，并明确 agent-bus 归属。

### C2 进程拓扑被定义两遍且不一致 [P1]
- **现象**：`topo serve` 走 `cli.py` 的 `_FIXED_SERVICES`（kb/gateway/llm/agent/mcp/runner）+ manifest service app（docs/chat/architect/agent-bus）；而 `engine/app.py:_run_distributed` 另注册一套 `{db_service, agent_worker, architect, mcp_server}`（旧模块路径 / 旧命名，注释已注明 "M05: agent_worker 并入 topoone.agent"）。两套拓扑并存、命名不一致、会各自漂移。
- **证据**：`packages/core/topoone/supervisor/cli.py:255-307`；`packages/core/topoone/engine/app.py:326-352`。
- **影响**：`TOPO_MODE` 默认 `monolith`（`config.py:69`），`topo serve` 又显式设 monolith，故 `_run_distributed` 基本是**死代码但仍存在并误导**。同一"进程拓扑"事实有两处权威。
- **修正方向**：让拓扑只有 `cli.py`（supervisor）一个 owner；删除或明确 deprecate `_run_distributed` 及其 worker 注册。

### C3 kb 自 spawn 与 supervisor"唯一 owner" 双归属 [P1]
- **现象**：`engine/app.py:_start_optional_services` 仍会自起 gateway / architect / mcp 子进程（Electron 兼容路径），靠 `--no-spawn` 关闭；`topo doctor` 甚至打印"web_server 含 runner/mcp：需移除"。
- **证据**：`packages/core/topoone/engine/app.py:215-260`；`packages/core/topoone/supervisor/cli.py:536`（doctor 检查）。
- **影响**：同一批进程有两个"父"，生命周期/重启/挂死检测语义不清晰；与"supervisor 唯一 owner"（CONV-00/README）表述矛盾。
- **修正方向**：明确 `--no-spawn` 为唯一生产路径，自 spawn 路径标注为 legacy/仅 Electron 兼容并收敛。

### C4 ZMQ PUB 端口命名 + 默认值漂移 [P0 正确性]
- **现象**：kb 绑定 `ZMQ_PUB_PORT`（默认 **5680**）；`topo serve` 启动 kb 时强改 env 为 **5681**；gateway 事件桥订阅的是**另一个变量名** `KB_PUB_PORT`（默认 **5681**）。同一逻辑端口使用两个 env 名 + 两个默认值；CONV-04 §3 又写 kb PUB = 5680。
- **证据**：`packages/core/topoone/config.py:12`（`ZMQ_PUB_PORT=5680`）；`packages/core/topoone/rpc/zmq_server.py:77`（默认 5680）；`packages/core/topoone/engine/app.py:88`（默认 5680）；`packages/core/topoone/supervisor/cli.py:433`（kb env `ZMQ_PUB_PORT=5681`）；`packages/core/topoone/gateway/gateway.py:114`（`KB_PUB_PORT` 默认 5681）；`docs/conventions/CONV-04-API契约与验证门禁.md:59`（写 5680）。
- **影响**：**单独运行 kb（非 `topo serve`）时 kb 绑 5680、gateway 订 5681 → 事件桥静默失效**；改端口需同步 3 处，易漏。
- **修正方向**：单一事实源——统一为**一个 env 变量名 + 一个默认值**，`config.py`/`zmq_server`/`gateway`/`cli.py` 全部引用它；同步更新 CONV-04。

### C5 CLI 广告了未实现的命令 [P1]
- **现象**：`topo session`（待实现）、`topo arch` / `topo track` / `topo diff` 均只 `print("feature in development ...")`，无实际行为。
- **证据**：`packages/core/topoone/supervisor/cli.py:11`（session 待实现）；`:854`（arch）；`:879`（track）；`:891`（diff）。
- **影响**：对外能力与实际能力不符；用户/CI 误以为可用。
- **修正方向**：未实现命令加 `(planned)` 标注或暂时隐藏；已实现则补集成。

### C6 遗留空目录 `apps/workbench/server/` [P1]
- **现象**：该目录仅含 `.gitkeep`；workbench 真实后端在 `apps/workbench/topoone_app_workbench/server/`（`knowledge_service.py`）。
- **证据**：`apps/workbench/server/`（仅 `.gitkeep`）；`apps/workbench/topoone_app_workbench/server/knowledge_service.py`。
- **影响**：目录结构误导，易误判 workbench 有独立后端服务。
- **修正方向**：删除遗留空目录，或在 manifest/文档中说明二者关系。

### C7 agent-bus 数据归属含糊 [P3]
- **现象**：`apps/agent-bus/manifest.toml` 注释同时写"轮询 arch_bus_messages（全局主库表）"与"共享 architect.db（经 --data-dir）"，且代码物理上住在 architect 包内（`topoone_app_architect.agent_bus`）却是独立进程。
- **证据**：`apps/agent-bus/manifest.toml`；CONV-04 §5 数据归属表未单列 agent-bus。
- **影响**：与"进程边界 = 数据边界"铁律存在张力，归属不清晰。
- **修正方向**：在 CONV-04 数据归属表明确 agent-bus 读哪一库、是否只读、写边界。

---

## 3. 维度二：拓展性（Extensibility）

### 强项（应保留）
- **manifest 驱动注册是真·零核心改动**：`discover_apps` + `validate_registry`（前缀/端口/命名空间冲突即 fail-fast），新增后端子项目对 core 零改动。这是全仓最好的拓展性设计。
  - 证据：`packages/core/topoone/manifest.py:212-284`。
- RPC 命名空间路由、topoOne 图内核（schema 先行 + mermaid/plantuml 引擎可插拔）方向正确。
  - 证据：`packages/core/topoone/gateway/gateway.py:56-126`；`packages/core/topoone/diagram/schema.py`。

### 问题
### E1 "新子项目模板"只对后端成立 [P2]
- **现象**：CONV-03 §7 声称有子项目模板，但**前端无脚手架**：4 个 app 各自手写 stores/services/i18n/传输，已分化为 4 种形态。新增 app 会继承既有分歧。
- **证据**：`apps/{workbench,docs,chat,architect}/src/{stores,services,i18n,composables}` 各自独立；web-core 无 app bootstrap 模板。
- **修正方向**：对齐后端 CONV-03，补一个**前端 app 脚手架/模板**（标准 main.ts / router / i18n 初始化 / 传输接入），让新 app 无法再 fork。

### E2 前端无统一 app bootstrap [P2]
- **现象**：6 种 i18n 机制；`window.api` 仅 workbench 使用（见 §5-R2）；新 app 作者没有"标准起点"。
- **证据**：见 §5-R3（i18n 机制枚举）。
- **修正方向**：web-core 提供一个 `createAppShell()` 式入口，统一 i18n/token/传输初始化。

### E3 依赖无中心锁定 [P2]
- **现象**：每个 app 重声明 vite / typescript / vue-tsc / plugin-vue / pinia / vue 等；`vue` 声明 5 次（今日恰好同为 3.5.13，属脆弱一致）。
- **证据**：`package.json`（root）+ `apps/*/package.json`；`@types/d3` 同时出现在 root 与 workbench devDeps。
- **影响**：版本漂移风险；升级需改多处。
- **修正方向**：前端公共依赖上提到 root（workspaces hoist），app 仅声明业务依赖。

### E4 端口 / env 膨胀 [P2]
- **现象**：新增一个进程需同时改 `cli.py` 固定表 + manifest + 可能 `config.py`；PUB 端口散落在 3 处（见 C4）。
- **影响**："零核心改动"承诺有漏边。
- **修正方向**：端口/env 收敛到单一配置源，manifest 为主、`config.py` 仅兜底默认值。

---

## 4. 维度三：耦合（Coupling）

### 后端
### B1 kb 成 god-process [P3]
- **现象**：kb 进程同时承载核心引擎 + data API（:3459）+ ingest 消费 + kind=core 的 workbench `knowledge.*` 方法（进程内注册），还（可选）自 spawn。workbench 后端物理上住在 core 进程内。
- **证据**：`packages/core/topoone/engine/app.py:112-178`（`register_all` + `_register_core_app_methods`）；`apps/workbench/manifest.toml`（`kind=core`, `python_entry=topoone_app_workbench.server:register_methods`, `rpc_namespaces=[knowledge]`）。
- **影响**：`kind=core` 是必要妥协，但模糊了 manifest 想划的 app/core 边界；workbench 无独立生命周期/DB。
- **修正方向**：若 workbench 继续长大，评估是否升级为独立进程 + 独立 DB（与 docs/chat/architect 对齐）；或正式文档化 `kind=core` 为"薄层档"。

### 前端
### F1 硬依赖规则 0 违规（合格）
- **现象**：web-core 未 import 任何 app（已核验 0 处 `@topo/app*` / `../../apps`）。单向依赖规则层面合格。

### F2 软耦合：copy-paste 的"影子依赖" [P2]
- **现象**：多处"本应共享却被复制"的逻辑，改 web-core 一处算法，2–3 份拷贝会静默分叉——比干净的 import 更难维护。
- **证据**：
  - token bootstrap（`#token=`→`topocode:token`→Bearer）copy-paste ×3：`packages/web-core/src/services/browser-api.ts:17-31`、`packages/web-core/src/services/api.ts:12-26`、`apps/architect/src/services/api-client.ts:13-27`（注释"与 web-core 一致"，是复制而非 import）。
  - mermaid 源码归一化 ×3（重叠正则）：`packages/web-core/src/services/render.ts`、`apps/workbench/src/composables/useDiagramRenderer.ts`、`apps/architect/src/composables/useDiagramRenderer.ts`。
  - theme 逻辑 ×3（见 §5-R4）；settings-store ×2（见 §5-R4）。
- **修正方向**：共享面（KB 系）改为 import 单一实现；architect 若独立则彻底解耦（见 F3）。

### F3 architect 处于"半共享"最差态 [P3]
- **现象**：architect 既 import web-core 的 `topoOne`/`DiagramViewer`（共享），又 fork 了传输（`api-client`/`ws-client`）与 i18n（独立）。半共享 = 共享的部分改动会牵动 architect，fork 的部分又各自漂移。
- **证据**：`apps/architect/src/components/assets/SemanticGraphView.vue`（import topoOne）；`apps/architect/src/services/{api-client,ws-client,backend}.ts`（独立传输）；`apps/architect/src/i18n/index.ts`（独立 i18n，初始 locale 硬编码 zh-CN）。
- **影响**：与 1.2 战略（可能完全独立）冲突——停在半共享是最不利状态。
- **修正方向**：二选一，别停在半共享：
  - (a) 若走向完全独立 → **彻底解耦**，停止 import web-core 内部，仅保留必要契约（MCP/HTTP）；
  - (b) 若继续用 topoOne 内核 → 把内核抽成 architect 也依赖的**独立内核包**，共享面干净。

---

## 5. 维度四：冗余（Redundancy）

### R1 多套并行图 / 动画栈 [P2，最高冗余]
- **现象**：至少 5 套并存 ——
  1. **topoOne 内核**（mermaid/plantuml，37 文件，`packages/web-core/src/topoOne/`）——声明的"统一"文本图内核。
  2. **D3 布局 + SVG**（workbench：`workers/render-worker.ts` 力导向/树布局 + `topo-animation` 渲染器 `SVGRenderer/force/hierarchy`；消费方 `D3ForceGraph.vue`/`useD3Graph.ts`/`render-manager.ts`）。
  3. **PixiJS WebGL**（workbench：`composables/usePixiCanvas.ts` + `topo-animation/renderer/canvas/CanvasRenderer.ts`）。
  4. **自研 TopoScript `topo-animation`**（workbench：45 文件，**legacy 倾向退役**）。
  5. **Cytoscape**（docs：`composables/useGraphState.ts`）。
- **交叉证据**：`apps/workbench/src/components/knowledge/KnowledgeGraph.vue` 同一份数据既走 `D3ForceGraph` 又走 topoOne `MermaidViewer`；`apps/workbench/src/components/visualization/` 下 `D3ForceGraph.vue`（D3）/`MermaidViewer.vue`（topoOne）/`AnimationStage.vue`（TopoScript）三套并存。
- **web-core 内部冗余**：2 个 mermaid 单例/队列（`services/render.ts` vs `topoOne/engines/mermaid/mermaid.ts` + `useTopoRender`）；3 份重叠归一化（见 F2）。
- **并行动画子系统**：`packages/web-core/src/topoOne/animation/` 与 `apps/workbench/src/lib/topo-animation` 两套。
- **修正方向**（基于 1.1）：退役 `topo-animation`；文本图统一到 topoOne 内核；节点图 D3/Cytoscape 二选一保留；删 web-core 内第 2 个 mermaid 单例与冗余归一化。

### R2 传输层多套 + 事件流多套 + 全局注入不对称 [P2]
- **现象**：
  - HTTP client ×3：`packages/web-core/src/services/api.ts`、`packages/web-core/src/utils/http.ts`、`apps/architect/src/services/api-client.ts`。
  - 事件/流 ×4：web-core `services/browser-api.ts`（`/ws/events`）、`apps/architect/src/services/ws-client.ts`（`ArchWs`）、`apps/chat/src/pages/ChatSession.vue`（内联 fetch + ReadableStream SSE 循环）、workbench `services/llmClient.ts`（`window.api.llm.subscribe`）。
  - `window.api` / `installBrowserAPI` **仅 workbench 使用**（约 15 个文件引用），docs/chat/architect 均为 0。
  - 两套 web-core 传输并存：`services/ipc`（`window.api`）与 `services/api`（fetch）指向同一 gateway。
- **影响**：同一 gateway 有多种访问方式，鉴权/重试/超时行为不一致；`window.api` 的"共享契约"名不副实（1/4 app 用）。
- **修正方向**（聚焦 KB 系）：收敛到**一套传输**（统一 `window.api`/`installBrowserAPI`，或统一一个 http client + 一个 token 助手），token 逻辑 import 而非 copy；architect 按 F3 处理。

### R3 i18n 碎片化（~8300 行）[P2，含正确性]
- **现象**：
  - 体量：workbench 50 文件 / 4735 行；architect 2 文件 / 3564 行（初始 locale 硬编码 `zh-CN`，`apps/architect/src/i18n/index.ts:7`）。
  - **4 个 "common" 字典**各自重定义同样 ~9 个基础词（workbench 215 键 / architect 33 / portal 10 / web-locales 11）。
  - **auth 词表 ×2**：web-core `portal/i18n.ts`（auth 66 键）与 workbench `i18n/en-US/auth.ts`（100 键）64 键重叠，workbench 全量仍保留。
  - **6 种 locale 机制**：workbench vue-i18n（`createAppI18n`）、architect vue-i18n（硬编码初始 locale）、web-core `web-locales.ts`（`navigator.language`）、web-core `shell/i18n.ts`（`topoone-locale`）、docs `DocViewer.vue` 内联 `_()` 字典、**chat 无 i18n**（硬编码中文，`apps/chat/src/pages/ChatSession.vue`）。
- **影响**：**chat 无 i18n → en-US 界面破**；多字典重复维护；机制不一导致 locale 切换不一致。
- **修正方向**（聚焦 KB 系）：一套 i18n 机制 + 一个共享 common 字典；给 chat 补 i18n；去重 auth 词表；docs 内联字典并入。

### R4 同概念组件 / 资产重复 [P2]
- **现象**：
  - theme ×3：workbench `stores/theme.ts`（~300 行 pinia store）、architect `composables/useArchTheme.ts`（27 行 web-core 通用版硬编码克隆，**0 引用 = 死代码**）、web-core `composables/useTheme.ts`（通用版，docs/chat 用）。
  - settings-store ×2：workbench `stores/settings-store.ts`（202 行）与 architect `stores/settings-store.ts`（65 行），同一 `topoone-locale`/`topoone-font-size` 域。
  - `useDiagramRenderer.ts` ×2：workbench（111 行）/ architect（65 行），重复归一化/转义/注入。
  - `StatusBar.vue` ×2（workbench shell / architect layout）；`ProjectList.vue` ×2（docs 200 行 / workbench 535 行）。
  - star-logo SVG ×4 字节相同（architect/chat/docs/web-core 各一份）。
  - web-core `utils/time.ts` **0 消费者**（死共享工具）。
- **修正方向**：theme/settings 上提 web-core（KB 系）；删死拷贝（`useArchTheme.ts`、`utils/time.ts`）；logo 资产单一源。

### R5 死依赖 [P2]
- **现象**：architect 声明 `cytoscape` + `cytoscape-cose-bilkent` + `marked` + `marked-highlight`，但 src 一处未 import（Cytoscape 仅 docs 用；markdown 用 `markdown-it`）；`vue` 声明 5 次；两套 markdown 引擎（`marked` in web-core vs `markdown-it` in workbench/architect）并存。
- **证据**：`apps/architect/package.json`（依赖声明）vs `apps/architect/src`（无对应 import）；`packages/web-core/src/services/render.ts`（marked）vs workbench/architect（markdown-it）。
- **修正方向**：清理 architect 4 个死依赖；markdown 引擎二选一；`vue` 等公共依赖上提 root。

### R6 后端冗余 [P2]
- **现象**：双进程拓扑（`cli.py` vs `engine/app.py:_run_distributed`，见 C2）；遗留自 spawn 路径（见 C3）；CLI 空壳命令（见 C5）；遗留空目录（见 C6）。
- **修正方向**：与 C2/C3/C5/C6 一致——单一拓扑 owner、删死代码/空目录。

---

## 6. 风险与影响分层

| 层 | 问题 | 后果 |
|---|---|---|
| 正确性（会出错） | C4 端口漂移；R3 chat 无 i18n；F2 多份 mermaid 归一化 | 独立运行丢事件流；en-US 界面破；跨 app 渲染不一致 |
| 可维护性（复合增长） | R1 多图栈；F2/R2 影子依赖多套传输；R3 i18n 碎片 | N 倍编辑成本；上手难；修 bug 难对齐 |
| 漂移（持续恶化） | C1/C2/C5 文档-代码不一致；E3 依赖无锁定 | "持续迭代"下越差越远；门禁误判 |

> 产品当前可正常运行，以上非阻断性故障，但技术债将随迭代复合增长。

---

## 7. 问题优先级总表（修正方向，非实施）

| 编号 | 优先级 | 问题 | 修正方向（一句话） | 主要影响面 | 风险 |
|---|---|---|---|---|---|
| C4 | P0 | PUB 端口命名+默认值漂移 | 统一为单一 env 名 + 单一默认值，config/zmq/gateway/cli 全引用它，更新 CONV-04 | core（config/rpc/gateway/supervisor） | 低 |
| C1 | P1 | 进程数 9 vs 10 | 文档/门禁统一为 10，明确 agent-bus | docs + G6 门禁 | 极低 |
| C2 | P1 | 双进程拓扑 | 拓扑仅 `cli.py` 一个 owner，删/deprecate `_run_distributed` | engine/app.py | 低 |
| C3 | P1 | kb 自 spawn 双归属 | `--no-spawn` 为唯一生产路径，自 spawn 标注 legacy | engine/app.py | 中 |
| C5 | P1 | CLI 空壳命令 | 未实现命令标注 `(planned)` 或隐藏 | supervisor/cli.py | 极低 |
| C6 | P1 | 遗留空目录 | 删除 `apps/workbench/server/` | workbench | 极低 |
| F2 | P2 | 影子依赖 copy-paste | KB 系共享面改为 import 单一实现（token/归一化/theme/settings） | web-core + workbench + chat | 中 |
| R1 | P2 | 多图/动画栈 | 退役 `topo-animation`；文本图归 topoOne；节点图 D3/Cytoscape 二选一 | web-core + workbench | 高（最大项） |
| R2 | P2 | 传输/事件流多套 | KB 系收敛到一套传输 + 单一 token 助手 | web-core + KB 系 apps | 中 |
| R3 | P2 | i18n 碎片 + chat 无 i18n | 一套机制 + 共享 common 字典；补 chat i18n；去重 auth | web-core + KB 系 apps | 中 |
| R4 | P2 | 组件/资产重复 | theme/settings 上提；删死拷贝（useArchTheme/utils-time）；logo 单一源 | web-core + apps | 低 |
| R5 | P2 | 死依赖 | 清 architect 4 死依赖；markdown 二选一；公共依赖上提 root | architect + root | 低 |
| E1/E2 | P2 | 前端无脚手架 | 补前端 app 模板/`createAppShell` 入口 | web-core | 中 |
| E3/E4 | P2 | 依赖/端口膨胀 | 公共依赖上提 root；端口 env 收敛单一源 | root + core | 低 |
| F3 | P3 | architect 半共享 | 二选一：彻底解耦（独立 + MCP）或内核抽独立包 | architect + web-core | 需决策 |
| B1 | P3 | kb god-process | 评估 workbench 是否升独立进程+DB，或文档化 kind=core | core + workbench | 需决策 |
| C7 | P3 | agent-bus 数据归属 | CONV-04 数据归属表明确其读写库 | docs | 极低 |

> P0 建议先做（正确性 + 低风险）；P2 中 R1（图栈收敛）为最大也最高风险项，需专项推进；P3 需产品/架构决策后再动。

---

## 8. 附录：关键证据索引

**后端**
- 进程拓扑（两处）：`supervisor/cli.py:255-307`、`engine/app.py:326-352`
- PUB 端口：`config.py:12`、`rpc/zmq_server.py:77`、`engine/app.py:88`、`supervisor/cli.py:433`、`gateway/gateway.py:114`
- kb god-process / manifest kind=core：`engine/app.py:112-178`、`apps/workbench/manifest.toml`
- RPC 路由 / manifest 驱动：`gateway/gateway.py:56-126`、`manifest.py:212-284`
- 自 spawn 遗留：`engine/app.py:215-260`、`supervisor/cli.py:536`
- CLI 空壳：`supervisor/cli.py:11,854,879,891`

**前端**
- 图栈：`packages/web-core/src/topoOne/`（37 文件）、`apps/workbench/src/lib/topo-animation/`（45 文件）、`apps/workbench/src/workers/render-worker.ts`（D3）、`apps/workbench/src/composables/usePixiCanvas.ts`（Pixi）、`apps/docs/src/composables/useGraphState.ts`（Cytoscape）
- 传输：`packages/web-core/src/services/{browser-api,api,ipc}.ts`、`packages/web-core/src/utils/http.ts`、`apps/architect/src/services/{api-client,ws-client}.ts`、`apps/chat/src/pages/ChatSession.vue`
- i18n：`apps/workbench/src/i18n/`、`apps/architect/src/i18n/index.ts`、`packages/web-core/src/portal/i18n.ts`、`apps/chat/src/pages/ChatSession.vue`
- 组件/工具重复：`apps/{workbench,architect}/src/stores/settings-store.ts`、`apps/workbench/src/stores/theme.ts`、`apps/architect/src/composables/useArchTheme.ts`、`packages/web-core/src/composables/useTheme.ts`、`packages/web-core/src/utils/time.ts`
- 依赖：`apps/architect/package.json`（cytoscape/marked 未用）、`package.json`（root 与各 app 重复声明）

> 本文档为评估记录，不构成已实施的变更；上述"修正方向"待后续单独立项推进。
