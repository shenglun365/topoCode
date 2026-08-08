# 领域：执行批次 / 任务树 / 三方 coding agent / git

> 对应前端：`services/task-service.ts`、`services/agent-service.ts`、
> `services/execution-batch.ts`、`services/git-service.ts`、`stores/task-store.ts`、
> `stores/agent-store.ts`、`stores/git-sync-store.ts`、`stores/merge-baseline-store.ts`、
> `stores/unit-test-store.ts`(任务侧 testIds 关联)。
>
> 契约权威：`topoCode-architect/docs/api/execution.md`(§4.1–4.7)，本文件补充
> **持久化**、**原子 commitBatch**、**WS 流式落地**与阶段规划。阶段 2 + 阶段 4。

---

## 1. 任务树(task-tree)

**前端**：`taskService.tree(planId)` / `flatten(root)`
**后端**：`GET /api/architect/plans/{plan_id}/task-tree`

**响应** `data`：`TaskNode`(递归)：

```jsonc
{
  "id": "tp-1", "title": "下单主链路(任务方案)", "kind": "epic",
  "status": "pending", "estMin": 300,
  "context": ["需求: US-1/US-2", "由需求概要设计的执行步骤拆分"],
  "files": [],
  "children": [ /* TaskNode[]，递归 */ ]
}
```

**生命周期**：
- 执行中可能整体废弃重建(`treeRevision` 自增)；旧树缩略快照保存到 `history`(上限 20)。
- 追加需求向树末尾并入新任务并累加 `estMin`。

**持久化**：`arch_task_trees`(root JSON + revision + history JSON)。

## 2. 执行任务(批次实例)

**前端**：`taskStore.createTask(planId, adapter, opts)` 等
**后端**：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/architect/exec` | 列表 ✅ |
| POST | `/api/architect/exec` | 创建(单事务 commitBatch，见 §4) ✅ |
| PATCH | `/api/architect/exec/{task_id}` | 局部更新(含 `testIds`、`stats`、`status` 等) ✅ |
| POST | `/api/architect/exec/{task_id}/stop` | 停止 → `stopped` ✅ |
| GET | `/api/architect/exec/{task_id}` | 单条 ✅ |

**`ExecutionTask` 结构**(前端 `types/index.ts` 为准)：

```jsonc
{
  "id": "ex-1", "planId": "plan-1", "adapter": "opencode",
  "model": "deepseek-v4", "reqIds": ["US-1", "US-2"],
  "connectivity": "ok",              // unknown|ok|fail
  "status": "running",               // ExecutionStatus: created|running|accepting|done|failed|blocked|stopped
  "sessionIds": ["sess-1"],
  "baseCommit": "1a2b3c4d5e6f",
  "runCount": 1, "createdAt": 1710000000000, "updatedAt": 1710000000000, "endedAt": null,
  "error": null, "treeRevision": 0,
  "stats": { "requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0 },
  "testIds": ["ut-1", "ut-2"],       // 冗余关联的单测(不随任务自动执行)
  "amendments": []                    // AppendedReq[]
}
```

**状态机**：`created → running → accepting → done`，`↘ failed / blocked / stopped`。
**互斥**：同时只有一个活动执行任务(提示性校验)。

**Store action 对应**：`setConnectivity` / `setExecStatus` / `setStats` / `stopTask` /
`passAcceptance` / `removeExecution`。

### 验收通过(passAcceptance)

`POST /api/architect/exec/{task_id}/accept`(阶段 4 新增)：
- 事务内：任务 `status → done`、`endedAt`、需求 `status → done`。

## 3. 追加需求(amendments)

**前端**：`taskStore.addAmendment` / `updateAmendment` / `mergeAmendmentIntoPlan` /
`addConversationalAmendment` / `appendFromPool`
**后端**：`POST /api/architect/exec/{task_id}/amendments`(阶段 4)

`AppendedReq`(精简 `RequirementAnalysis` + design)：
- 并入规则：任务树末尾追加任务(`kind='task'`、`estMin` 取自 analysis)、树 `estMin` 累加、
  需求状态 `executing`、执行任务回 `running`。
- 两通道：对话触发词 `追加：`/`append:`；池选择。

## 4. 原子 `commitBatch`(阶段 4 关键)

**前端**：`execution-batch.commitBatch(reqs, adapter, plan?, opts?)`
**后端**：`POST /api/architect/exec`，单事务原子完成：

1. 合成/接收批次方案 `DesignPlan`。
2. 生成任务树 `TaskNode` 并注册 `planToTaskTree[plan.taskPlanId]`。
3. `requirementStore.addPlan` + `confirmPlan`(需求状态推进)。
4. 创建 `ExecutionTask` 并 `markPlanReqsExecuting`。
5. 需求绑定 `execId`。

**实现**：仓库层显式 `BEGIN/COMMIT`；任一步失败回滚整批。
**响应** `data`：`{ "plan": DesignPlan, "exec": ExecutionTask }`。

## 5. 三方 coding agent 会话(阶段 2)

**前端接口**：`AgentAdapter`(`agent-service.ts`)：

```ts
interface AgentAdapter {
  createSession(opts: { exec: ExecutionTask; planTitle: string; keepContext?: boolean }): Promise<AgentSession>
  sendMessage(sessionId: string, content: string, opts?: { keepContext?: boolean }): Promise<AgentMessage>
  runTask(session: AgentSession, task: TaskNode, opts?: RunHooks): Promise<void>
  getStatus(sessionId: string): Promise<AgentStatus>
  terminate(sessionId: string): Promise<void>
}
```

**语义**：每个执行任务一个独立会话，会话携带「上下文包」(方案 + 需求 + 编码规约 +
相关文件)，多轮沿用同一上下文直至验收。

### WS `/api/architect/ws/coding-agent`

客户端 → 服务端：`session.create`(带 `root` 可选) / `session.message` / `task.run` / `session.stop`
服务端 → 客户端：`session_created` / `message` / `tool_call` / `status` / `tree.change` /
`done` / `failed` / `stopped`

`session.create` 携带 `root`(工程实现目录)且取到**真实 adapter**(经 `AgentInstancePool`
按 `(project, adapter, host)` 取/建实例)时按形态执行；无 `root` / 实例不可达 /
探测失败 → 回退服务端模拟(§5.4 语义)。`task.run` 时 agent 在工程目录建 task 分支提交并 push，
完成后 architect 从**只读分析副本**(`~/.topocode/arch/<proj>/analysis`) pull 该分支同步差异。

**adapter 形态(§5.6)**：
- **daemon(server)**：`opencode`、`qwen(code)`。常驻 `serve`，`session.create → POST /session`，
  `task.run` 经 `iter_events` 订阅 HTTP SSE(`/event` 或 `/session/:id/events`)逐条归一化事件。
- **cli(进程型)**：`codex`、`cline`。无常驻进程；每次 `task.run` 启动一次性子进程
  (`codex exec --json` / `cline --json`)，经 `process_events` 流式消费 stdout JSONL→归一化事件。
  resume 支持走引擎自身参数(如 `cline --resume`)。

**`AgentSession` 结构**(与 execution.md §4.4 一致)：

```jsonc
{
  "id": "sess-1", "taskId": "ex-1", "adapter": "opencode",
  "status": "idle",                 // idle|planning|working|testing|done|failed|stopped
  "messages": [
    { "id": "m-1", "role": "user|assistant|tool", "time": 1710000000000,
      "content": "…", "tool": { "type": "write-file|run-command|run-test", "label": "app/domain.go",
                                "detail": "领域对象与不变量 96 行", "ok": true } }
  ],
  "keepContext": true,
  "artifacts": ["app/domain.go"],
  "testResult": { "passed": 17, "failed": 0, "note": "go test ./app/... + 集成用例 全部通过" },
  "stats": { "requests": 5, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0 }
}
```

**落地**：`arch_agent_sessions` + `arch_agent_messages`。每收/发一条消息即落库，边流边存。
**终态**：终止事件 `type` = `done`/`failed`/`stopped`(非 `status`)，并携带 `stats/artifacts/testResult`。
`task.run` 在服务端为后台任务，`session.stop` 可在运行中被接收并中断(✅ 阶段 2 已实现)。
`arch_agent_sessions` 增 `instance_id` / `opencode_session_id`(真实会话映射)。

### task 分支与 git 单向事实源(阶段 4+ 扩展)

外部 git 仓库为**唯一代码事实源**，角色单向：
- 编码 agent 实例：工程实现目录(`root_path`)建 `arch/<task_id>` 分支(或人工指定)提交并 push；
- ARCHITECT：独立只读分析副本(`~/.topocode/arch/<proj>/analysis`，`arch_git.py`)按 task 分支 pull；
- KB：既有 git_service + version_sync 拉取。

`ExecutionTask` 增 `instance_id` / `task_branch` / `branch_mode`：
- `branch_mode='auto'` → `task_branch=arch/<task_id>`(默认)；`='manual'` → 人工指定分支。
- 任务启动前基线校验(§6 语义)不通过 → 提示先提交/清理，避免把未提交状态混进 agent 改动。
- 验收通过后由用户触发把 task 分支合并到目标分支(人工)。

**与 `coding_agent_runner`(3458) 对接(阶段性)**：
- 主后端 `POST http://127.0.0.1:3458/tasks` 提交任务。
- 桥接 runner 的 `/ws/agent` 流回 `/ws/coding-agent`。
- runner 不可达 → 回退服务端模拟流式(与单测域一致，服务端模拟容错)。
- 完整接管 runner 为延后项，非阶段 2 阻塞。

**连通性探测**：`GET /api/architect/agent/adapters/{adapter_id}/connectivity`
→ `{ status: 'ok'|'fail' }`，支撑 `TaskCreateView.testConnectivity`。✅ 已实现：
已知 adapter(经 `agent_adapters.list_adapters()` 注册的开源 engines) → ok(含 version)，
未知 → fail。各 adapter 还可经 `GET /agent/adapters/{id}/connectivity` 做真实
env_check/probe。

### 5.6 多 adapter 支持(4 引擎已接入)

注册表 `agent_adapters._ADAPTERS`(见 `api-agent-config.md` §adapter 清单)：

| adapter | 形态 | 运行方式 | 模型来源 | 接入状态 |
| --- | --- | --- | --- | --- |
| `opencode` | daemon | `opencode serve` + SSE(`/event`) | agent 自身 provider | ✅(原有) |
| `qwen` | daemon | `qwen serve --no-web` + ACP(`/session/:id/events` SSE) | agent 自身 model | ✅ 阶段 5 接入 |
| `codex` | cli | `codex exec --json` 一次性子进程 | `~/.codex` 或临时 CODEX_HOME(local baseUrl) | ✅ 阶段 5 接入 |
| `cline` | cli | `cline --json` 一次性子进程 | cline 引擎登录态(需预先登录) | ✅ 阶段 5 接入(连通性探测，运行需登录) |

- **探测**：daemon 型 `probe()` 探测后端 HTTP health；cli 型 `probe()` 校验二进制存在
  (codex/cline 实例 `health()` 同样只校验 binary)。
- **cli 消息流**：`_run_opencode_task` 对 `mode=="cli"` 走 `process_events`
  (起子进程→逐行 JSONL→归一化 status/message/tool_call→终态)，daemon 型走既有
  `send_fut + iter_events`。
- **环境**：codex 可携带 `cfg.baseUrl/apiKey/model`，`CodexSession.build_env` 动态生成
  临时 `CODEX_HOME`(wire_api=responses) 指向本地 OpenAI 兼容服务；cline 使用引擎自身登录态。
- **边界**：cline 可用性探测通过即视为已适配，但真实运行需该引擎自带登录(架构师不存
  第三方密码/密钥，见 §5.4 语义)。

## 6. git 服务(阶段 4 补齐)

**前端**：`GitService`(`git-service.ts`)。✅ 阶段 4 已实现：`HttpGitService`
全部方法改调后端(`/git/status|log|head|working-tree|checkout|reset`)，后端不可达
返回空结果，不中断 UI。

| 前端方法 | 后端 |
| --- | --- |
| `head(repo)` | `GET /git/status` → `{ commit: branch, dirty }` ✅ |
| `checkout(repo, commit)` | `POST /git/checkout`(body: `{ commit }`) ✅ |
| `resetToBase(repo, commit)` | `POST /git/reset`(body: `{ commit }`) ✅ |
| `changes(repo)` | `GET /git/status` ✅ |
| `log(repo, from, to)` | `GET /git/log?from=&to=` ✅ |
| `workingTree(repo)` | `GET /git/working-tree` ✅ |

额外：`GET /git/head`、`POST /git/commit|push`、`GET /git/diff`(服务端模拟，供全链路联调)。

`GitFileChange`：`{ "path": "app/domain.go", "status": "A|M|D|R", "add": 42, "del": 3 }`
`GitCommit`：`{ "hash": "a1b2c3d4e5f6", "short": "a1b2c3d", "message": "feat(outbox): …",
"author": "dev-li", "date": 1710000000000, "files": [/* GitFileChange[] */] }`

- 仓库路径：mock 固定 `PROJECT_GIT_PATH`；真实后端忽略 repo 参数，使用绑定项目
  (经 `main_db.projects.root_path` 按需读取)。
- 基线校验：`head.commit === plan.baseCommit && !head.dirty` 才允许执行。

## 7. 与前端服务方法映射

| 前端服务 | 后端 |
| --- | --- |
| `taskService.tree(planId)` | `GET /plans/{plan_id}/task-tree` |
| `taskStore.createTask/…` | `POST /exec`、`PATCH /exec/{id}`、`POST /exec/{id}/stop` |
| `executionBatch.commitBatch` | `POST /exec`(单事务) |
| `agentAdapter.*` | `/ws/coding-agent` + `GET /agent/adapters/{id}/connectivity` |
| `gitService.*` | `/git/*`(补齐 checkout/reset/log/working-tree) |
| `taskStore.passAcceptance` | `POST /exec/{id}/accept`(阶段 4) |
| `taskStore.addAmendment` | `POST /exec/{id}/amendments`(阶段 4) |

## 8. 验证

- ✅ `POST /exec` 单事务：harness `/tmp/opencode/p3p4_test.py` 验证需求/计划/任务三者一致(含 confirm/release/accept/amendments/stop/patch)。
- ✅ 重启后任务树历史、执行任务、agent 会话仍可读(阶段 0/1/2 已验)。
- ✅ WS coding-agent：`/tmp/opencode/p2_agent_test.py` 流式序列与落库、中断、终态全绿。
- ✅ `git` 新接口 harness 验证(status/log/head/working-tree/checkout/reset/commit)。
