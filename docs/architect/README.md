# Architect 后端开发计划与 API 协议

> 本文档目录为 TopoCode Architect 后端的**开发计划**与**接口协议**合集。
> 前端以 `web/architect-src/` 为当前设计(mock)来源；契约权威参考
> `topoCode-architect/docs/backend-api.md` 与 `docs/api/*.md`、`docs/greenfield/backend.md`。
> 本文档与既有 `docs/plan/architect-design.md`(架构设计)互补：前者讲「本体如何设计」，
> 本目录讲「后端如何落地、接口长什么样」。

## 目录

| 文档 | 内容 |
| --- | --- |
| [README.md](README.md) | 本页：合并开发计划 + 决策记录 |
| [conventions.md](conventions.md) | 通用约定：包络 / 错误码 / ID / 时间 / 传输 / 持久化(architect.db) |
| [kb-contract.md](kb-contract.md) | **KB 对外契约**：版本基线 / 增量更新 / 待更新标记（architect 对接 KB 的权威依据） |
| [kb-api-requirements.md](kb-api-requirements.md) | **对 KB 的 API 需求**：architect 消费侧需求清单（KB-REQ-01~17），含已满足核对与缺口责任 |
| [api-unit-test.md](api-unit-test.md) | 领域：单元测试工作区(REST + WS) |
| [api-execution.md](api-execution.md) | 领域：执行批次 / 任务树 / 三方 coding agent / git |
| [api-knowledge-greenfield.md](api-knowledge-greenfield.md) | 领域：知识库分析 agent / Blueprint / Scaffold / Extract |
| [api-overview.md](api-overview.md) | **概览页聚合接口**：`GET /overview` 一次返回四组栏目数据(launch/recent/adapters/kb/missions) |
| [api-dirs.md](api-dirs.md) | **宿主机目录浏览**：打开新项目弹窗的目录浏览/新建/自动识别(`/dir/list` `/dir/create` `/dir/analyze`) |
| [api-agent-config.md](api-agent-config.md) | **Agent 连接配置 + 连通性测试**：三方 agent 接入(先 opencode)/ KB 配置与测试 |

---

## 1. 合并开发计划

> **2026 架构拆分**：Architect 现为**独立服务** `plugins/architect/`（自身 FastAPI + 自有
> SPA，端口 `3470`）。数据经 `arch_routes/ctx`（`architect.db`，唯一写入者）+ `KbGateway`
> （KB `data_api /zmq` 3459 + MCP `/v1/tools` 3460）访问，**不再**内嵌 reports。
> `plugins/reports` 已摘除 architect 路由/SPA，仅保留 `/architect` 302 → `{host}:3470/architect`。
> 下文历史表格中 `plugins/reports/architect_routes/*` 路径均已迁至 `plugins/architect/arch_routes/*`。

### 1.1 现状

- **后端**：`plugins/architect/`(独立 FastAPI：`server.py::build_app()` + `__main__.py`，
  挂载 `/api/architect`，端口 3470)。路由位于 `plugins/architect/arch_routes/`，全部落库。
- **旁路进程**：`coding_agent_runner`(3458)、MCP(3460，工具转发到 architect)、KB(3459 data_api)。
- **前端契约**：`web/architect-src/services/*` 经 `api-client.ts`(`VITE_ARCH_API_BASE`，默认同源
  `/api/architect`)走 `{code,message,data}` 包络；WS 基址跟随 `VITE_ARCH_API_BASE`。
- **KB 支撑**：已实现方法(`version.*`、`knowledge.pullRequest/…`)经 `kb_gateway.call_kb` 直达；
  KB-REQ-15/16/17(代码抽取/图谱复合/组件索引)仍为占位，标注待 KB 实现。

### 1.2 已确认决策

1. 覆盖**全部**剩余 mock 域，分阶段推进。
2. 状态落库：**从现在起用 `MultiDBManager`(sqlite)**。
3. 单元测试执行：**服务端模拟**(确定性通过/失败，`ut-3` 失败)，经 WS 流式推送。
4. **持久化归属**：独立全局 `architect.db`(与 knowledge/sessions 同层)，
   label `architect`；**不**并入 `topoone.db`，**不**随项目库。
5. **项目根路径**：不跨库 JOIN，需要 `execRoot`/`kbRoot` 时按需从 `main_db.projects`
   现读(复用 `MultiDBManager._get_project_root`)。
6. ID 生成：按前缀单调递增序列(阶段 0)。

### 1.3 阶段划分

| 阶段 | 范围 | 关键产出 | 状态 |
| --- | --- | --- | --- |
| 0 | 持久层 + 约定 | `architect.db` + 13 表、`store.py` 仓库层、`_id()` 改造、`init_architect_db()` | ✅ 已实现 |
| 1 | 单元测试域(新增) | `unit-tests`/`unit-test-sessions` REST + `/ws/unit-test` 流式执行 | ✅ 已实现 |
| 2 | coding agent 会话域 | `AgentSession` 落库、`/ws/coding-agent` 真流式、连通性探测 + 前端 WS 接线 | ✅ 已实现 |
| 3 | 知识分析 + Greenfield | `analyze/clarify|collect`、blueprint、scaffold、extract、launch/guide | ✅ 已实现 |
| 4 | 加固已 HTTP 域 | 原子 `commitBatch`、amendments、git 全量、plans confirm/release、tags/collab/mcp 落库 | ✅ 已实现 |
| 5 | 多 adapter 接入 | qwen/daemon(ACP)、codex/cline(cli 一次性进程)、`AgentConfigDialog` adapter 切换、映射单测 | ✅ 已实现 |

### 1.4 各阶段验证

- 重启服务 → 数据保留(证明 sqlite 落库生效)。✅ 已验证(阶段 0/1/2)
- `curl` 每个 REST 接口，校验包络与错误码。✅ 已验证(阶段 0/1/2/3/4)
- WS：小测试客户端或重建后的前端服务，断言流式序列与终态。✅ 已验证(`/ws/unit-test` + `/ws/coding-agent`)
- 前端 WS 接入后重跑 `npx tsc -p web/architect.tsconfig.json --noEmit` + `npx vite build --config vite.web.config.ts`(architect-src 区域)。✅ 已通过(阶段 2 接线 + 阶段 3/4 接线)
- 后端 harness：`/tmp/opencode/p3p4_test.py`(阶段 3+4 全部 REST + 事务)全绿。✅ 已验证

### 1.5 风险 / 注意

- 前端 WS 客户端已就绪(`services/ws-client.ts`)，服务默认后端优先、后端不可达自动回退本地 mock。
- sqlite 写多路复用：reports 走写代理(`db_client`)，架构写入须走同一 write_queue(label `architect`)。
- 原子性：阶段 0 多写与阶段 4 `commitBatch` 需在仓库层显式 `BEGIN/COMMIT`。
- 运行中的 3456 Electron 栈仍为旧代码，需重启才加载新路由(`/unit-tests`、`/ws/coding-agent` 等)。

### 1.6 KB 侧对接（本仓库 KB 会话改动，architect 会话对照 `kb-contract.md`）

> KB（backend-core）侧已完成 P0+P1，为 architect 提供"版本基线 + 增量更新 + 待更新标记"能力，
> 全部经 `data_api /zmq/{method}` HTTP 代理暴露（拓扑无关）。architect 开发时对照 `docs/architect/kb-contract.md`。

- **两界模型**：KB 导入源码为知识快照（branch/head 基线，只向前）；architect 面向工程目录/迭代中代码。对比仅在 KB 基线之间。
- **architect 可消费**（R2/R3/R4）：
  - `version.materialize(projectId, versionId)` → 某基线文件清单（需求/设计的知识支撑）。
  - `version.diff(fromId, toId)` → 基线间文件/社区差异（架构迁移/数据资产变化）。
  - `knowledge.pullRequest({projectId, repoUrl, branch, head})` → 写待更新标记；由 KB 界面确认后 `pull`/`worktree` 拉代码并增量更新。
- **KB 侧 schema 新增**（见 `kb-contract.md`）：`project_versions`/`project_version_files`/`project_update_requests`（主库）；
  `source_files.version_from` + `source_files_history`/`community_overrides` + 分析表 `*_history`（项目库）。
- **状态**：P0 落地（导入多模式/版本基线/待更新标记）；P1 落地（AST/图环节增量执行，`implemented=true`）；
  presummary/community/llm 增量与历史视图 UI 属 P2/P3。

---

## 2. 已实现清单(阶段 0 + 1 + 2 + 3 + 4)

### 后端文件改动

| 文件 | 改动 |
| --- | --- |
| `backend-core/sqlite_ctx.py` | 新增 `ARCHITECT_DB_TABLES_SQL`(13 表)；`MultiDBManager` 增加 `architect_db`、`init_architect_db()`/`init_architect_tables_remote()` |
| `plugins/reports/web_server.py` | `create_app` 在 `set_globals` 后初始化 architect 表 |
| `plugins/reports/architect_routes/store.py`(新) | 仓库层：camel↔snake 互转、JSON 列自动编解码、序列 ID(`next_id`/`bump_seq`)、各分域访问器 |
| `plugins/reports/architect_routes/requirements.py` | 改 store 落库 + 种子(首次空库写入 RQ-1..3，`bump_seq` 对齐) |
| `plugins/reports/architect_routes/execution.py` | plans/task-tree/exec 改 store 落库 |
| `plugins/reports/architect_routes/project.py` | 活动项目落 `arch_projects`(默认种子 + config PATCH 持久化) |
| `plugins/reports/architect_routes/mcp_collab.py` | mcp calls / interactions 落库 |
| `plugins/reports/architect_routes/unit_test.py`(新) | 单测 REST：`GET/POST /unit-tests`、`PATCH /unit-tests/{id}`、`GET/POST /unit-test-sessions`、`GET /unit-test-sessions/{id}` |
| `plugins/reports/architect_routes/agent.py`(新) | agent 会话 REST：`GET /agent/adapters`、`GET /agent/adapters/{id}/connectivity`、`GET/DELETE /agent/sessions[/{id}]`、`GET /agent/sessions/{id}/messages` |
| `plugins/reports/architect_routes/websocket.py` | `/ws/unit-test`(`run/message/stop` ↔ `tool_call/result/status/message`，ut-3 失败)；**`/ws/coding-agent` 真流式**(`session.create/message`、`task.run`、`session.stop` ↔ `session_created/message/tool_call/status/tree.change` + 终态 `done/failed/stopped`，边流边落库，后台任务可中断) |
| `plugins/reports/architect_routes/__init__.py` | 注册 `unit_test.router`、`agent.router` |
| `plugins/reports/architect_routes/requirements.py` | 新增 `POST /requirements/analyze/clarify|collect`(KB 澄清/收集 → `RequirementAnalysis`，existing/greenfield 两分支)、`GET /requirements/{req_id}` |
| `plugins/reports/architect_routes/execution.py` | 重写为阶段 4：`POST /exec` **原子 commitBatch**(经 `store.run_atomic`/`WriteQueue.execute_batch` 单事务合成方案→任务树→建确认方案→建执行任务→绑定需求)；`GET /exec`、`GET/PATCH /exec/{id}`、`POST /exec/{id}/stop|accept|amendments`；plans `GET/POST/PATCH` + `POST /plans/{id}/confirm|release`；`GET /plans/{id}/task-tree` |
| `plugins/reports/architect_routes/git.py`(新) | git 域全量(服务端模拟)：`status/log/head/working-tree/checkout/reset/commit/push/diff` |
| `plugins/reports/architect_routes/greenfield.py`(新) | Blueprint `init/refine/demo-freeze/confirm`、Scaffold `generate/confirm`、Extract `kb/extract`+`kb/baseline`、`GET /launch`、`GET /guide/missions` |
| `plugins/reports/architect_routes/store.py` | 加 `run_atomic`(单事务)、`BlueprintsStore`/`SnapshotsStore`/`TagsStore`/`CollabConfigStore`/`StagingScansStore`；JSON 列集合补 `related_to`/`preferred_asset_ids` |
| `backend-core/sqlite_ctx.py` | `_architect_migrations`：`arch_blueprints`、`arch_kb_snapshots`、`arch_tags`、`arch_collab_config`、`arch_staging_scans`、`arch_snapshot_records` 建表 + `arch_requirements` 幂等补列(`plan_id/exec_id/remarks/parent_id/related_to/merged_into/preferred_asset_ids`，local/remote 双路径) |
| `plugins/reports/architect_routes/tags.py`(新) | tags 域：`GET/POST /tags`、`GET/PATCH /tags/{id}`、`POST /tags/{id}/offline`(offline int→bool 对齐前端契约) |
| `plugins/reports/architect_routes/mcp_collab.py` | collab mode 落 `arch_collab_config`(GET/PUT 持久化) |
| `plugins/reports/architect_routes/arch_change.py` | 变更域接 store：staging scan 落 `arch_staging_scans`、`GET /arch/staging/log` 读库、spec 落 `arch_specs`(GET/POST confirm)；移除与 `git.py` 冲突的 `/git/status` |
| `plugins/reports/architect_routes/project.py` | 新增 `POST /project/snapshots` 落 `arch_snapshot_records`；**无项目态 + URL 项目选择改造**：去掉默认项目种子与全局 `active` 语义，`GET /project/bound|status` 无 URL 参数返回 null、`/project/snapshots` 返回 []；`_resolve_project(root, project)` 按 URL 解析项目(?project=KB id / ?root=路径，工作目录 id 按 root 哈希稳定)；新增 `GET /project/kb/list`(代理 KB `project.list`，snake→camel + `gitLinked`/`hasBaseline` 标注)、`POST /project/bind`(校验 + `upsert` 登记)、`POST /project/unbind`(仅清 URL) |
| `plugins/reports/architect_routes/requirements.py` | `analyze_clarify/collect` 按请求透传的 root/project 判定降级：`_kb_degraded()` 依据解析项目是否有 KB 基线，existing+greenfield 均返回 `degraded: true`，无资产命中、assetScope 为空(仅手动)，文案注明「KB 能力降级」 |
| `plugins/reports/architect_routes/store.py` | `ProjectsStore.get_by_root(root)`(按 root_path 查项目) + `upsert(project_id, data)`(存在更新/否则插入) |
| `backend-core/sqlite_ctx.py` | `_architect_migrations` 追加 `arch_projects` 幂等补列 `kb_project_id`/`git_linked` |

### 前端文件改动(阶段 3/4 接线)

| 文件 | 改动 |
| --- | --- |
| `web/architect-src/services/ws-client.ts`(新) | 共享 WS 客户端(`ArchWs`：按 type 订阅、`once` 等待、发送)，走 Vite `/api` 代理 |
| `web/architect-src/services/agent-service.ts` | 改为后端优先(WS 会话/执行/停止 + REST 状态)，后端不可达回退 `mock/agent-service.ts` |
| `web/architect-src/services/mock/agent-service.ts`(新) | 原 mock agent 适配器保留为兜底 |
| `web/architect-src/services/unit-test-service.ts` | 改为后端优先(REST + WS)，不可达回退 `mock/unit-test-service.ts` |
| `web/architect-src/services/mock/unit-test-service.ts`(新) | 原 mock 单测服务保留为兜底 |
| `web/architect-src/components/coding/TaskCreateView.vue` | `testConnectivity` 改调 `GET /agent/adapters/{id}/connectivity` |
| `web/architect-src/stores/agent-store.ts` / `unit-test-store.ts` | `sendMessage` 传会话引用；`load()` 对后端不可达容错 |
| `vite.web.config.ts` | `/api` 代理加 `ws: true` |
| `web/architect.tsconfig.json` | include/paths 修正为覆盖 `architect-src`(此前指向不存在的 `src/`)，入口 `entry-architect.ts` 加入(引入 pinia-persist 类型增强) |
| `web/architect-src/services/backend.ts`(新) | 共享可达性探针(`GET /git/status`，一次性；旧栈无此路由 → 回退 mock) |
| `web/architect-src/services/execution-batch.ts` | `commitBatch` 后端优先(`POST /exec` 原子 commitBatch)，失败回退本地 mock 落盘 |
| `web/architect-src/services/git-service.ts` | 全部方法改调后端(`/git/status|log|head|working-tree|checkout|reset`)，不可达返回空结果 |
| `web/architect-src/stores/task-store.ts` | `load()` 后端优先(`GET /exec` + `GET /plans/{id}/task-tree`)，回退 mock；`setExecStatus/setStats/stopTask/passAcceptance/addAmendment` 写穿后端(best-effort) |
| `web/architect-src/stores/requirement-store.ts` | `load()` 后端优先(`GET /requirements` + `GET /plans`)，回退 mock；`confirmPlan/releasePlan` 写穿后端(best-effort) |
| `web/architect-src/services/kb-analysis-agent.ts` | `clarify/collect` 后端优先(`POST /requirements/analyze/*`)，不可达回退本地 mock |
| `web/architect-src/services/blueprint-agent.ts` | `init/refine/freeze/confirm` 后端优先(`POST /blueprint/*`)，不可达回退本地 mock |
| `web/architect-src/services/scaffold-service.ts` | `generate/confirm` 后端优先(`POST /scaffold/*`)，不可达回退本地 mock |
| `web/architect-src/services/extract-service.ts` | `run/commitBaseline` 后端优先(`POST /kb/extract|baseline`)，不可达回退本地 mock |
| `web/architect-src/services/kb-query-agent.ts` | `query` 后端优先(`POST /kb/query`)，不可达回退本地 mock |
| `web/architect-src/stores/collaboration-store.ts` | `load/setMode/resolve/enqueue` 后端优先(`/collab/*`)，回退 mock |
| `web/architect-src/stores/mcp-store.ts` | `load` 后端优先(`GET /mcp/calls`)，`record` 写穿后端(best-effort) |
| `web/architect-src/stores/spec-store.ts` | `load` 后端优先(`GET /spec`)，`confirm` 写穿后端 |
| `web/architect-src/stores/staging-store.ts` | `load/runIncrementalScan/verifyBaseline/commitRebaseline/setGate` 后端优先(`/arch/staging*`、`/arch/baseline/*`)，回退 mock |
| `web/architect-src/types/index.ts` / `project-service.ts` / `project-store.ts` | 新增 `KbProject` 类型与 `listKbProjects/bindKbProject/bindWorkingDir/unbind`；**项目选择写/读 URL**：`currentProjectParams()` 从路由 query 读 `root`/`project` 并随请求透传，`bindKb/bindDir` 经 `router.replace` 写 `?project=`/`?root=`、`unbind` 清 URL；`load()` 对后端不可达容错(置空不崩溃) |
| `web/architect-src/components/project/ProjectPicker.vue`(新) | 无项目首页：路线1 从 KB 已 git 关联项目选择(仅 git 关联+有基线可绑定，其余置灰注明)、路线2 直接打开宿主机工作目录(宿主机路径提示 + 远程调用说明)、KB 降级支持面板(进入需求分析)、Greenfield 次要入口 |
| `web/architect-src/pages/OverviewPage.vue` | 无项目时渲染 `ProjectPicker`(替换原 createProject 段)；有绑定项目时项目卡片加「解绑」按钮 |
| `web/architect-src/pages/RequirementWorkspace.vue` / `i18n/zh-CN.ts` | 无项目降级横幅(`kbDegraded` = 未绑定项目，流程不变信息受限) + 新增 `overview.noProject.*`/`requirement.degradedHint` 文案 |

### 行为要点

- **持久化**：数据在 `~/.topocode/architect.db`，重启保留(已实测)。
- **ID**：按前缀序列 `RQ-`/`plan-`/`ex-`/`ut-`/`uts-`/`sess-`/`m-`/`mcp-`/`it-`，与 docs §2.4 对齐。
- **WS 单测执行**：`run` 逐用例 `tool_call(开始) → result → tool_call(结束)`，汇总 `message` + `status(done)`；`ut-3` 确定性失败；会话消息与测试状态全程落库。
- **WS coding-agent**：`task.run` 后台任务流式 `status(planning) → message×2 → status(working) → tool_call×4(+tree.change) → status(testing) → message → done`；`session.stop` 可中断(置 cancelled，任务在检查点终止为 `stopped`)；终态事件携带 `stats/artifacts/testResult`。
- **连通性**：已知 adapter → `ok`，未知 → `fail`(服务端模拟，阶段 2)。
- **种子**：已移除默认种子数据——`arch_projects` 不再自动种入示例项目、`arch_requirements` 不再自动写入 RQ-1..3（空库即空列表，页面按真实 KB 数据展示；测试 harness 自行创建需求）。
- **原子 commitBatch(阶段 4)**：`POST /exec` 在单事务(WriteQueue `execute_batch`)内创建确认方案 + 任务树 + 执行任务，并把需求 `plan_id/exec_id/status=planned` 绑定；任一失败整体回滚。
- **需求状态机**：`finalize/direct` → 入池(analyzed)；`confirm` → planned；commitBatch → planned + 绑定；`accept`(事务) → done；`release/reflow` → 回 analyzed。
- **amendments**：`POST /exec/{id}/amendments` 事务内追加需求(独立 `am-*` 行，挂 `exec_id`)、任务树尾部并入新任务并累计 `estMin`、exec → running。
- **git 全量**：服务端确定性模拟(status/log/head/working-tree/checkout/reset/commit/push/diff)，供前端 git 域(同步/合并基线)全链路联调。
- **Blueprints/Scaffold/Extract**：`arch_blueprints`/`arch_kb_snapshots` 落库；blueprint 四步 `init→refine→demo-freeze→confirm`；extract 产出快照 → baseline 切 `existing` 模式。
- **前端后端优先策略**：probe `/git/status` 可达 → 全部走真实后端(load/commitBatch/git/confirm/release/accept/stop/amendments)；不可达 → 静默回退本地 mock，UI 不报错(运行中旧栈兼容)。
- **收尾域落库**：tags(CRUD + offline，`arch_tags`)、collab mode(`arch_collab_config`)、staging scan(`arch_staging_scans`)、spec(`arch_specs`)、架构快照(`arch_snapshot_records`)全部持久化；`/git/status` 冲突路由移除，由 `git.py` 统一提供。
- **knowledge/greenfield 前端切后端优先**：`kb-analysis-agent`(clarify/collect)、`blueprint-agent`(init/refine/demo-freeze/confirm)、`scaffold-service`(generate/confirm)、`extract-service`(run/commitBaseline)、`kb-query-agent`(query)后端优先，不可达回退本地 mock；`collaboration/mcp/spec/staging` stores 同步切后端优先。
- **无项目态首页**：空库不再种入默认项目，`GET /project/bound|status` 返回 null、`/project/snapshots` 返回 []；首页进入「选择项目」态——路线1 从 KB 已 git 关联项目选择(`/project/kb/list` 代理 `project.list`，仅 `gitLinked && hasBaseline` 可绑定，rootPath 取 `source_cache_dir`、基线取 `current_version_id`)，路线2 直接打开宿主机工作目录(提示路径在宿主机、支持远程)。
- **项目选择持久化在 URL 内**：不再用 `arch_projects.active` 全局态；`?project=<kb-id>`(路线1) / `?root=<path>`(路线2) 决定当前项目，后端每次按 URL 参数解析(`_resolve_project`)，`/project/bound|status|snapshots|config|snapshots` 均读 root/project 参数，可多页签各处理不同项目；`/project/unbind` 仅清 URL。`arch_projects` 仅作按 root 的配置/登记缓存(`get_by_root` + `upsert`，id 按 root 哈希稳定)。无基线(无项目/工作目录直开)即 KB 降级。
- **需求分析降级模式**：无项目或项目无 KB 基线(工作目录直开)时 `analyze_clarify/collect` 返回 `degraded: true`(existing + greenfield 均降级)，无资产命中、assetScope 为空(仅手动)，前端 RequirementWorkspace 显示降级横幅；流程与已绑定一致，信息与接口能力受限。

### 已验证

- REST 全部接口包络/错误码(含空 name → 400)。
- WS 执行流序列与终态：coding-agent `planning→working→testing→done`、`stopped` 中断、消息/统计落库后 REST 可读；单测 `ut-3` 失败、其余通过。
- 重启服务数据保留(需求/单测/会话/项目 config / agent 会话 / tags / collab mode / spec / staging scan / 快照)。
- 前端 `tsc -p web/architect.tsconfig.json --noEmit` 与 `vite build` 均通过(阶段 2 + 阶段 3/4 接线后)。
- 后端 harness `/tmp/opencode/p3p4_test.py` 全绿：analyze(clarify/collect) 两分支、commitBatch 原子绑定、plans confirm/release、accept 事务、amendments(任务树增长 + 需求落库)、exec patch/stop、git 全量、blueprint/scaffold/extract/launch/guide、tags/collab/staging/spec/snapshot 落库、**无项目态(bound/status null + 降级 analyze) + KB list 代理 + 两条绑定路线 + 解绑**。
- 阶段 2 harness `/tmp/opencode/p2_agent_test.py` 复跑无回归。

### 未做(后续阶段)

- 运行中的 3456 Electron 栈需重启以加载新路由与真实数据(本次改动均为代码层完成)。

---

## 2. 实现约定(与既有代码对齐)

- `architect_routes/common.py` 保留 `_ts()`、`ok()/err()` 包络；`_id()` 改造为序列式。
- 路由保持细薄，数据访问统一走新增 `architect_routes/store.py`(经 `common.multi_db.architect_db`)。
- `web_server.create_app(multi_db)` 在 `common.set_globals(...)` 后调用 `multi_db.init_architect_db()`。
- WS 端点统一挂 `/api/architect/ws/*`，消息格式见各领域文档。

---

## 3. 参考

- 现有架构设计：[docs/plan/architect-design.md](../plan/architect-design.md)
- 契约权威：`topoCode-architect/docs/backend-api.md`、`docs/api/*.md`、`docs/greenfield/backend.md`
- 前端 mock 边界：`web/architect-src/services/*` + `services/mock/*`
