# 领域：知识库分析 agent / Blueprint / Scaffold / Extract

> 对应前端：`services/kb-analysis-agent.ts`、`services/blueprint-agent.ts`、
> `services/scaffold-service.ts`、`services/extract-service.ts`、`stores/requirement-store.ts`、
> `stores/architecture-store.ts`、`stores/project-store.ts`、`stores/spec-store.ts`。
>
> 契约权威：`topoCode-architect/docs/api/requirements.md`(§3.4 分析 agent)、
> `docs/greenfield/backend.md`(§3–§7)、`docs/api/knowledge-base.md`。
> 本文件补充持久化与 WS 落地细节。阶段 3。

---

## 1. 知识库分析 agent(kb-analysis)

**前端**：`RequirementAnalysisAgent.clarify/collect`(`kb-analysis-agent.ts`)

```ts
interface RequirementAnalysisAgent {
  clarify(req: KbAnalysisRequest): Promise<ClarifyResult>
  collect(ctx: { turns: KbAnalysisTurn[]; base: KbAnalysisRequest; answers: Record<string, string>; note?: string }): Promise<CollectResult>
}
```

### REST 形态(建议)

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/architect/requirements/analyze/clarify` | 首轮澄清(问题列表) |
| POST | `/api/architect/requirements/analyze/collect` | 收集作答，产出分析报告 |

或走 WS `/api/architect/ws/kb-analysis`(`clarify`/`answer` 消息，见既有 websocket.py 骨架)。
两种形态二选一，本计划建议 **REST 优先**(请求/响应是同步完整的)，WS 保留给真正需要
流式的场景。

**clarify 请求**(`KbAnalysisRequest`)：

```jsonc
{
  "title": "用户下单全链路",
  "desc": "用户浏览商品后可提交订单…",
  "priority": "P0",
  "kind": "user-story",
  "preferredAssetIds": ["c-order"],
  "mode": "existing"               // greenfield 时走领域建模分支
}
```

**clarify 响应**(`ClarifyResult`)：

```jsonc
{
  "turns": [ { "role": "assistant", "content": "…", "questions": [ /* QuestionItem[] */ ] } ],
  "questions": [
    { "key": "scope", "label": "需求影响范围", "type": "text", "hint": "…" },
    { "key": "priority", "label": "优先级", "type": "select", "options": ["P0", "P1", "P2"] }
  ]
}
```

**collect 响应**(`CollectResult`)：`turns` + `formDraft`(含 `RequirementAnalysis`，
`functionalScope`/`entityBoundary`/`feasibility`/`assetScope`)。

### greenfield 分支(backend.md §3.1)

`mode==='greenfield'` 时 clarify 返回领域建模导向问题
(`boundaries`/`entities`/`flows`)，collect 的 `assetScope` 以 `p-` 前缀引用规划资产，
不走 `matchAssets` 命中。

### 降级模式(未绑定项目)

未绑定项目时(首页无项目态) KB 无内容支撑，**existing 与 greenfield 均降级**：
- `analyze_clarify/collect` 响应追加 `degraded: true`；无资产命中(`hits: []`)，
  collect 的 `assetScope` 为空(仅保留手动项)，`assessmentSummary`/文案注明「未绑定项目 · KB 能力降级」。
- 流程与已绑定项目一致，仅信息与接口能力受限；前端 `RequirementWorkspace` 显示降级横幅。

### 持久化

分析轮次与最终 `RequirementAnalysis` 存 `arch_requirements.analysis`(JSON)；
`arch_requirements` 表状态推进(raw → analyzed / pool)。

## 2. Blueprint(蓝图)

**前端**：`blueprintAgent.init/refine/freeze/confirm`(`blueprint-agent.ts`)
**后端**(backend.md §4)：

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| POST | `/api/architect/blueprint/init` | `{ reqIds, productForm, stack }` | `BlueprintInitResult`(turns + blueprint) |
| POST | `/api/architect/blueprint/refine` | `BlueprintRefineRequest` | `BlueprintRefineResult`(blueprint + questions) |
| POST | `/api/architect/blueprint/demo-freeze` | `{ blueprintId }` | `BlueprintFreezeResult`(blueprint + taskTreeHint) |
| POST | `/api/architect/blueprint/confirm` | `{ blueprintId }` | `{ status: 'confirmed' }` |

`BlueprintRefineRequest`：

```jsonc
{
  "blueprintId": "bp-1",
  "action": "lock | drill-down | backtrack | update-what | update-how",
  "nodeId": "node-order", "what": "订单管理", "how": "拆为 下单/支付/对账 三个子模块",
  "parentId": "node-order", "childWhat": "下单服务要做成什么样？"
}
```

**持久化**：`arch_plans` 或独立 `arch_blueprints` 表(阶段 3 落地时按需拆分；
README 表清单中的 `arch_plans` 可承载，或新增 `arch_blueprints`)。

## 3. Scaffold(脚手架)

**前端**：`scaffoldService.generate/confirm`(`scaffold-service.ts`)
**后端**(backend.md §5)：

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| POST | `/api/architect/scaffold/generate` | `ScaffoldGenerateRequest` | `{ files: ScaffoldFile[], validation }` |
| POST | `/api/architect/scaffold/confirm` | `{ token, execRoot, commitMessage }` | `{ commit, filesWritten, buildPass }` |

`ScaffoldGenerateRequest`：

```jsonc
{
  "execRoot": "/home/dev/projects/my-service",
  "stack": { "language": "Go", "framework": "gin" },
  "blueprintId": "bp-1",
  "layers": [1, 4, 5],
  "productForm": "io"
}
```

`ScaffoldFile`：`{ "path": "go.mod", "action": "create", "summary": "Go module init" }`

**失败语义**：`execRoot` 不可写、`blueprintId` 未确认 → 错误码。

## 4. Extract(知识库抽取, greenfield → existing handoff)

**前端**：`extractService.run/commitBaseline`(`extract-service.ts`)
**后端**(backend.md §6)：

| 方法 | 路径 | 请求 | 响应 |
| --- | --- | --- | --- |
| POST | `/api/architect/kb/extract` | `{ execRoot, kbRoot, commit, baselineVersion }` | `{ snapshotId, model, mappings, metrics }` |
| POST | `/api/architect/kb/baseline` | `{ extractToken }` | `{ baselineId, commit, mode: 'existing' }` |

`ExtractResult`：

```jsonc
{
  "snapshotId": "snap-xxx",
  "model": { /* ArchitectureModel */ },
  "mappings": [ /* CodeMapping[] */ ],
  "metrics": { "components": 3, "entities": 7, "flows": 2, "mappings": 12 }
}
```

**落地**：对指定 commit 运行 codegraph / AST 抽取(真实后端)，产出 `ArchitectureModel`
+ `CodeMapping`；建基线快照 `snap-v0`。此后 `ProjectInfo.mode` 切换 `existing`。

## 5. Launch / Guide

- `GET /api/launch`(backend.md §2)：启动信息 `{ execRoot, kbRoot, mode, productForm, scaffold }`。
  前端 `onMounted` 填充 `project-store`。
- `GET /api/guide/missions?mode=…`(backend.md §7，可选)：guide 示例可内置前端
  (`guide-patterns.ts`)，后端动态示例为可选项。

## 6. 已有知识库 REST(对齐 docs/api/knowledge-base.md)

后端 `knowledge.py` 已实现，阶段 3 仅做持久化核对：
`GET /kb/model`、`GET /kb/assets/{id}`、`GET /kb/assets/search`、`GET /kb/code-mappings`、
`GET /kb/coding-rules`、`POST /kb/query`。无需新契约，仅确认与前端形状一致。

## 7. 与前端服务方法映射

| 前端服务 | 后端 |
| --- | --- |
| `analysisAgent.clarify/collect` | `POST /requirements/analyze/clarify|collect`(或 `/ws/kb-analysis`) |
| `blueprintAgent.init/refine/freeze/confirm` | `POST /blueprint/init|refine|demo-freeze|confirm` |
| `scaffoldService.generate/confirm` | `POST /scaffold/generate|confirm` |
| `extractService.run/commitBaseline` | `POST /kb/extract`、`POST /kb/baseline` |
| `projectStore` 启动填充 | `GET /launch` |

## 8. 验证

- ✅ 阶段 3 已实现：`/requirements/analyze/clarify|collect`(existing/greenfield 两分支)、`/blueprint/init|refine|demo-freeze|confirm`、`/scaffold/generate|confirm`、`/kb/extract|baseline`、`/launch`、`/guide/missions`。
- ✅ 前端已切后端优先：`kb-analysis-agent`/`blueprint-agent`/`scaffold-service`/`extract-service`/`kb-query-agent` 均先调后端，不可达回退本地 mock。
- ✅ harness `/tmp/opencode/p3p4_test.py` 全绿：clarify 问题集(3/4)、collect 报告(assetScope/estMin)、blueprint 四步、scaffold 落盘 commit、extract 快照 + baseline 切 existing；**无项目降级**：clarify/collect `degraded=true`、无资产命中。
- ✅ 现有 kb 接口形状对齐前端；`arch_blueprints`/`arch_kb_snapshots` 落库。
