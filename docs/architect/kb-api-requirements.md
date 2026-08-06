# 对 KB 的 API 需求（architect → KB）

> 本文档从 **architect 消费侧**出发，定义 architect 对接知识库（KB，backend-core）所需的
> **API 需求清单**：每个需求对应 architect 的某条业务流，标注 KB 侧所需方法、参数、响应、
> 语义与当前状态。它是 architect 与 KB 双端集成的**需求基线**。
>
> - 配套文档：[kb-contract.md](kb-contract.md) 描述 **KB 已实现的对外契约**（P0/P1，ZMQ 方法形态）；
>   本文档则回答「**architect 需要 KB 提供什么**」——两篇合读即为完整对接依据。
> - 契约权威（architect 消费端）：`web/architect-src/types/index.ts`、`services/*`、`stores/*`。

---

## 1. 对接模型与传输约定

### 1.1 拓扑无关的双通道

| 形态 | 适用 | 说明 |
| --- | --- | --- |
| 单进程（当前） | reports 子进程 | architect 路由直连 `common.multi_db` / `common.zmq_server`，调用
  `zmq_server.methods['<method>'](**params)` 得原生结果，**无包络** |
| 多进程（分布式） | reports 与 KB 分离 | architect 代理层调 `POST http://127.0.0.1:3459/zmq/{method}`
  （data_api），响应为 `{"result": …}`，错误为 HTTP 500 `{"detail": …}` |

### 1.2 KB 侧必须满足的传输约定

1. **方法名**：ZMQ 注册名 = HTTP `/zmq/{method}` 路径段，如 `version.materialize`。
2. **参数双别名**：KB 已支持 `project_id`/`projectId`、`version_id`/`versionId` 等 snake_case 与
   camelCase 双别名；architect 统一传 camelCase，KB 须持续保持。
3. **响应形状**：KB 方法返回**业务对象**（camelCase 字段），不套通用包络；包络由 architect
   代理层负责（`{"result": …}` → architect `{code,message,data}`）。
4. **错误语义**：KB 方法对业务失败须 `raise ValueError(...)` 等可读异常（data_api 转 HTTP 500，
   detail 即 message）；architect 代理层将 500 映射为业务错误码 400 + message。**不返回裸 200 + 假数据**。
5. **时间戳**：architect 全局用**毫秒时间戳**(number)。KB 当前 `createdAt` 为 ISO 字符串——architect
   代理层须 `Date.parse(...)` 转换，或 KB 改为毫秒（二选一，需在联调前定稿）。
6. **只向前语义**：KB 基线只向前不向后；architect 只消费 KB 基线，绝不回写基线（除更新请求标记）。

### 1.3 architect 侧当前消费状态

architect 后端 `plugins/reports/architect_routes/` 现直连 `common.zmq_server`（单进程）可立即消费
KB 已实现方法；对 **KB 尚未提供**的抽取/图谱查询/资产查询，architect 路由目前以**服务端 mock**
（`knowledge.py` 的 `build_architecture_model()`、`greenfield.py` 的 `/kb/extract|baseline`）兜底，
见 §5 缺口清单。

---

## 2. 需求矩阵总表

| ID | 域 | architect 消费点 | KB 方法 / 接口 | 需求状态 |
| --- | --- | --- | --- | --- |
| KB-REQ-01 | A 基线读取 | R2 需求分析：基线清单 | `version.list` | ✅ 已满足(P0) |
| KB-REQ-02 | A 基线读取 | R2 需求/设计：重建基线文件清单 | `version.materialize` | ✅ 已满足(P0) |
| KB-REQ-03 | A 基线读取 | R2 设计：单基线详情(含文件) | `version.get` | ✅ 已满足(P0) |
| KB-REQ-04 | A 基线读取 | R2 设计：社区/摘要知识支撑 | `presummary/community` 查询(待定) | ⏳ 待补(P2/P3) |
| KB-REQ-05 | B 迁移/资产 | R3 架构迁移：基线间文件级差异 | `version.diff` | ✅ 已满足(P0) |
| KB-REQ-06 | B 迁移/资产 | R3 数据资产变化：分析级差异 | `version.diff` 扩展 | ⏳ 待补(P1+) |
| KB-REQ-07 | C 更新请求 | R4 发起基线更新 | `knowledge.pullRequest` | ✅ 已满足(P0) |
| KB-REQ-08 | C 更新请求 | R4 待更新列表 | `knowledge.pendingUpdates` | ✅ 已满足(P0) |
| KB-REQ-09 | C 更新请求 | R4 KB 确认拉取+预览 | `knowledge.updateConfirm` | ✅ 已满足(P0) |
| KB-REQ-10 | C 更新请求 | R4 取消更新 | `knowledge.updateCancel` | ✅ 已满足(P0) |
| KB-REQ-11 | C 更新请求 | R4 无副作用预览 | `version.preview` | ✅ 已满足(P0) |
| KB-REQ-12 | C 更新请求 | R4 执行增量更新 | `version.sync` | ✅ 已满足(P0/P1) |
| KB-REQ-13 | D 导入/基线 | 绑定 KB 项目 | `project.import` | ✅ 已满足(P0) |
| KB-REQ-14 | D 导入/基线 | 手工设置基线 | `project.saveBaseline` | ✅ 已满足(P0) |
| KB-REQ-18 | D 导入/基线 | 首页「路线1 选择项目」项目清单 | `project.list` | ✅ 已满足(P0) |
| KB-REQ-15 | E 抽取 handoff | greenfield→existing 真实抽取 | 抽取聚合接口(待定，见 §5) | ⏳ architect 现 mock |
| KB-REQ-16 | F 复合查询 | kb-query-agent 图谱查询 | 图谱查询接口(待定，见 §5) | ⏳ architect 现 mock |
| KB-REQ-17 | G 资产查询 | 组件模型/资产/代码映射/编码规约 | 现有 `knowledge.*` 查询 | ⏳ architect 现 mock |

---

## 3. 已满足需求（P0/P1，KB 已实现，architect 消费核对）

> 方法与签名详见 [kb-contract.md](kb-contract.md)。以下仅列 architect 侧**必须核对**的消费语义。

### KB-REQ-01 / 03 — `version.list` / `version.get`

- **architect 用途**：需求分析入口列出项目基线，选取当前基线作为知识支撑。
- **核对项**：返回 `ProjectVersion[]`（`id/projectId/parentVersionId/label/branch/head/changeType/
  fileCount/*Count/isBaseline/createdAt`）；`createdAt` 需按 §1.2-5 统一时间口径。

### KB-REQ-02 — `version.materialize`

- **architect 用途**：R2 需求分析/设计时，重建**任意基线 head 的完整文件清单**，作为
  知识基线的支撑知识（可结合社区/摘要查询，见 KB-REQ-04）。
- **响应**：`[{ file_path, content_hash, language, size, file_name }]`。
- **核对项**：任意已归档基线可重建（`活表(version_from<=V) UNION 历史表(version_from<=V AND version_to>V)`）。

### KB-REQ-05 — `version.diff`（文件级，KB-REQ-06 见 §4 待补）

- **architect 用途**：R3 架构迁移/数据资产变化视图——对比两个 KB 基线的文件级差异。
- **响应**：`{ fromVersion, toVersion, added[], modified[], deleted[], *Count }`。
- **限制（须在 UI 声明）**：仅限 KB 基线之间；当前为 manifest 级（content-hash 文件 diff），
  分析级差异见 KB-REQ-06。

### KB-REQ-07~11 — 更新请求状态机（`knowledge.*` + `version.preview`）

- **architect 用途**：R4 基线更新请求。architect 仅**写入待更新标记**（不执行拉取/增量）。
- **流程**：`pullRequest`（status=pending）→ KB 界面 `updateConfirm`（选 pull/worktree，拉代码+
  返回预览）→ `version.sync`（选环节执行）→ `pendingUpdates`/`updateCancel` 查询与撤销。
- **响应形状**：`UpdateRequest`（`source: 'architect'`）；`updateConfirm` 返回
  `VersionPreview + { projectId, requestId, branch, head }`。

### KB-REQ-12 — `version.sync`（增量更新执行）

- **architect 用途**：R4 更新请求被 KB 确认后的实际执行（architect 可传 `requestId` 令完成时
  置待更新标记为 done，`taskId` 指定目标分析任务）。
- **P0/P1 语义**：`ast`/`graph` 环节已增量执行（`implemented=true`，AST 只解析 A/M 文件 +
  符号 upsert + δ 归档；图重解析变更文件 + 保留活边）；`presummary/community/llm` 为
  `implemented=false` 占位。
- **已知限制（须在 UI 声明）**：文件粒度增量下「未变→变更」跨文件符号边可能缺失；目标为空
  的模块/调用边保守保留。需要完整图时走全量任务重跑（`analysis.runTask`）。

### KB-REQ-13 / 14 — `project.import` / `project.saveBaseline`

- **architect 用途**：绑定 KB 项目（多模式导入：static/git-local/git-remote，导入后自动注册
  初始基线）；手工设置版本基线。
- **核对项**：`project.import` 返回 `Project`（含 `currentVersionId`）；`saveBaseline` 返回
  `{ ok, version? }`。

### KB-REQ-18 — `project.list`（首页路线1 选择源）

- **architect 用途**：首页无项目态「路线1：从 KB 选择已 git 关联项目」。
- **architect 消费**：`GET /api/architect/project/kb/list` 代理 KB `project.list`，
  映射为 camelCase 并派生 `gitLinked`(import_mode∈git-local/git-remote) 与
  `hasBaseline`(current_version_id 非空)；仅二者为真的项目可绑定（避免错误关联），
  绑定后 `rootPath` 取 `source_cache_dir`、`baselineId` 取 `current_version_id`。
- **KB 需保证**：`project.list` 返回全部项目含 `import_mode/remote_url/local_repo_path/
  source_cache_dir/current_version_id/done_task_count`（P0 已满足）。

---

## 4. 待补需求（architect 现 mock，KB 侧按本文档实现）

### KB-REQ-06 — `version.diff` 扩展：分析级差异（P1+）

- **需求**：在文件级 diff 之上，输出两个基线间**分析层差异**——社区归属变化、受影响节点集合、
  需重摘要文件。供 R3 数据资产变化视图展示"影响面"而非仅文件清单。
- **建议形态**（在现有 `version.diff` 响应追加字段，保持向后兼容）：
  ```jsonc
  { "fromVersion": …, "toVersion": …,
    "added": […], "modified": […], "deleted": […], "addedCount": …, "modifiedCount": …, "deletedCount": …,
    "analysis": {
      "nodeIdsAffected": […], "affectedCommunities": […],
      "filesToResummarize": […], "communitiesToReanalyze": […]
    } }
  ```
- **依赖**：P2/P3 的 presummary/community 增量执行完成后自然可得；在此之前可用
  `version.preview.impact`（AST/图已实现）近似。

### KB-REQ-04 — 社区/摘要知识查询（P2/P3）

- **需求**：architect R2 需求/设计需要"某基线里某模块的社区归属与摘要"作为知识支撑。
  KB 需提供按版本 + 符号/模块查询社区与预摘要的只读接口（方法名待定，如
  `knowledge.communities` / `knowledge.summaries`）。
- **依赖**：presummary/community 环节增量执行（P2/P3）。

---

## 5. 缺口清单（architect 现为服务端 mock，需 KB 真数据接管）

> 以下三组是 architect 与 KB 联动的**显式缺口**。architect 路由当前以 `build_architecture_model()`
> 固定假数据兜底，KB 提供真实能力后，architect 侧改为调用 KB 并把 mock 降为不可达回退。
> 响应形状以 `web/architect-src/types/index.ts` 为准（前端直接消费）。

> **2026 更新**：architect 已独立为服务(`plugins/architect`)，并接通 KB**已实现**的方法：
> `version.list/materialize`(基线/文件清单)、`knowledge.pullRequest/pendingUpdates/updateConfirm/
> updateCancel`(基线更新状态机)经 `arch_routes/kb_gateway.call_kb` 直达(不可达回退占位)。
> 下列 KB-REQ-15/16/17 仍需 **KB 新增**方法实现，architect 侧保留占位。

### KB-REQ-15 — 真实代码抽取（greenfield → existing handoff）

- **architect 消费点**：`extract-service.ts` → `POST /api/architect/kb/extract`（现 `greenfield.py`
  服务端模拟）；`/kb/baseline` 建基线快照。
- **需求**：KB（codegraph/AST 索引）对指定 `commit` 产出：
  ```jsonc
  // ExtractResult（architect-src/types/index.ts）
  { "snapshotId": "snap-xxx",
    "model": /* ArchitectureModel：components/erTables/ormMappings/entityClasses/executionFlows */,
    "mappings": [ /* CodeMapping[]：{ id, targetType, targetId, targetName, file, line, level, note } */ ],
    "metrics": { "components": 3, "entities": 7, "flows": 2, "mappings": 12 } }
  ```
- **建议**：KB 暴露聚合方法（如 `knowledge.extractSnapshot`，内部复用 `analysis.runTask` +
  graph 查询 + code-mappings），architect `greenfield.py` 调它并落 `arch_kb_snapshots`。

### KB-REQ-16 — 知识图谱复合查询（kb-query-agent）

- **architect 消费点**：`kb-query-agent.ts` → `POST /api/architect/kb/query`（现 `knowledge.py`
  返回固定数据）。
- **需求**：KB 图谱按 `KbQuerySpec` 查询并返回 `KbQueryResult`：
  ```jsonc
  // KbQuerySpec: { kind: 'depends'|'calls', compIds[], sections: ['basic'|'structure'|'flow'], note? }
  // KbQueryResult:
  { "id": "kq-…", "spec": …, "skills": [ { "name": "kb.graph", "detail": "…" } ],
    "summary": "…", "compResults": [
      { "componentId", "name", "kind",
        "relMd": "## 依赖组件\n\n…",      // 依赖/被调用聚合 MD
        "basicMd": "## 基本信息\n\n…",
        "structureMd": "## 核心数据结构\n\n…",
        "flowMd": "## 核心流程\n\n…" } ],
    "cached": false, "baselineTag": "v1.0.0", "createdAt": 1710000000000 }
  ```
- **建议**：KB 提供 `knowledge.graphQuery`（或复用现有 graph skill），architect `knowledge.py`
  改调它；`baselineTag` 取当前基线 gitTag。

### KB-REQ-17 — 组件模型 / 资产 / 代码映射 / 编码规约（现有 `knowledge.*` 查询接管）

- **architect 消费点**：`knowledge.py` 的 `GET /kb/model|assets/{id}|assets/search|code-mappings|
  coding-rules`（现为 mock）。
- **需求**：KB 以真实索引提供：
  - 组件模型（`ArchitectureModel` 的 components 域：`id/name/kind/lang/change/desc/responsibilities/
    owns/dependsOn`）；
  - 资产详情与搜索（按 id 精确 / 按名称模糊）；
  - 代码映射（file/line 级 → 组件）；
  - 编码规约（Markdown 原样返回）。
- **建议**：直接复用 KB 现有 `knowledge.*` ZMQ 方法（listDocs/getDoc 等）的索引层，
  或按 architect 形状新暴露只读查询。

---

## 6. 验收映射（architect 流程 ↔ KB 需求）

| architect 流程 | 页面 / 服务 | 依赖需求 |
| --- | --- | --- |
| 需求分析（基线支撑） | RequirementsPage / kb-analysis-agent | KB-REQ-01/02/03/04 |
| 架构迁移 / 数据资产变化 | ArchMapPage / git-sync | KB-REQ-05/06 |
| 基线更新请求（R4） | staging / merge-baseline | KB-REQ-07~12 |
| KB 项目绑定 | project-store / ProjectSetupDialog | KB-REQ-13/14 |
| Greenfield handoff | ExtractView / extract-service | KB-REQ-15 |
| 系统基线复合查询 | BaselineView / kb-query-agent | KB-REQ-16 |
| 资产与编码规约 | ArchitectureStore / AssetsPage | KB-REQ-17 |

---

## 7. 状态与责任

| 项 | 责任方 | 状态 |
| --- | --- | --- |
| P0 版本基线/更新请求方法 | KB | ✅ 已实现，architect 按 §3 核对 |
| P1 AST/图增量执行 | KB | ✅ 已实现（`version.sync` ast/graph） |
| 时间戳口径统一 | 双端 | ⚠️ 联调前定稿（§1.2-5） |
| KB-REQ-06/04（分析级差异 / 社区摘要） | KB | ⏳ P2/P3 |
| KB-REQ-15/16/17（抽取/图谱查询/资产查询） | KB 提供能力 + architect 改接 | ⏳ architect 现 mock 兜底 |
| 单进程直连 `common.zmq_server` 消费 | architect | ✅ 可立即消费 P0/P1 |
