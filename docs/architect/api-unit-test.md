# 领域：单元测试工作区

> 对应前端：`services/unit-test-service.ts`、`stores/unit-test-store.ts`、
> `components/unit-test/*`、`pages/UnitTestPage.vue`、`types/index.ts`(UnitTest 相关)。
>
> 本域为**新增领域**，`topoCode-architect/docs` 未覆盖；契约依前端 mock 现状新写。
> 阶段 1 落地。

---

## 1. 语义

- **单元测试 = 质量验收**：工作流末阶段「质量验收」更名为「单元测试」(见 `config/workflow.ts`)。
- 单测用例(`UnitTest`)：脚本已编写，左栏列表展示；经「添加」关连脚本入库。
- 单测会话(`UnitTestSession`)：单独保留，可再进入或新建；工作区左右栏执行反馈。
- 执行通道(`TestChannel`)：`agent`(三方 coding agent) / `cli`(topocode 命令行)。
  每次执行时选定；会话级默认值(`defaultChannel`)。
- **不随任务自动执行**：`ExecutionTask.testIds` 仅在任务侧冗余关连，由用户在任务详情
  验收清单中 agent 建议 + 人工增删。
- **阶段 1 执行 = 服务端模拟**：按 `testId` 确定性判定(`ut-3` 失败)，经 WS 流式推送；
  结果落库。

## 2. 数据模型(与前端一致)

### UnitTest

```jsonc
{
  "id": "ut-1",
  "name": "订单状态机流转测试",
  "levels": ["L0", "L1"],          // TestLevel: L0|L1|L2|L3|L4|L5
  "scriptPath": "order-service/order_state_test.go",
  "source": "manual",               // UnitTestSource: requirement|manual|scan
  "status": "passed",               // UnitTestStatus: idle|running|passed|failed|error|skipped
  "lastResult": { "passed": 12, "failed": 0, "error": "…(可选)", "note": "go test …", "at": 1710000000000 },
  "createdAt": 1710000000000,
  "updatedAt": 1710000000000
}
```

### UnitTestSession

```jsonc
{
  "id": "uts-1",
  "title": "下单链路回归",
  "channel": "cli",                 // TestChannel: agent|cli
  "adapter": "opencode",
  "testIds": ["ut-1", "ut-2"],
  "status": "done",                 // created|running|done|failed|stopped
  "messages": [ /* AgentMessage[]，见下 */ ],
  "stats": { "requests": 0, "tokensIn": 0, "tokensOut": 0, "bytesIn": 0, "bytesOut": 0 },
  "createdAt": 1710000000000,
  "updatedAt": 1710000000000
}
```

### AgentMessage(复用)

```jsonc
{
  "id": "m-1",
  "role": "user|assistant|tool",
  "time": 1710000000000,
  "content": "…",
  "tool": { "type": "run-test", "label": "go test …", "detail": "12 通过 / 0 失败", "ok": true }
}
```

---

## 3. REST 接口

前缀 `/api/architect`。REST 只做查询与结构化落盘；执行与对话走 WS。

### 3.1 `GET /unit-tests`

列出全部单测。

**响应** `data`：`UnitTest[]`。示例：

```jsonc
{
  "code": 0, "message": "ok",
  "data": [
    { "id": "ut-1", "name": "订单状态机流转测试", "levels": ["L0", "L1"],
      "scriptPath": "order-service/order_state_test.go", "source": "manual",
      "status": "passed",
      "lastResult": { "passed": 12, "failed": 0, "note": "go test ./order-service -run TestOrderState", "at": 1710000000000 },
      "createdAt": 1710000000000, "updatedAt": 1710000000000 }
  ]
}
```

### 3.2 `POST /unit-tests` — 添加/关连单测

**请求** `data` 载荷(Partial<UnitTest>)：

```jsonc
{
  "name": "订单状态机流转测试",   // 必填
  "levels": ["L0", "L1"],         // 默认 []
  "scriptPath": "order-service/order_state_test.go",  // 默认 ""
  "source": "manual"              // 默认 "manual"
}
```

**响应** `data`：完整 `UnitTest`(id 由后端生成 `ut-<n>`，`status:'idle'`，
`createdAt/updatedAt` 为当前毫秒时间戳)。

**失败语义**：
- `400` name 为空 → 错误码 4001「单测名称不能为空」。

### 3.3 `GET /unit-test-sessions`

列出全部单测会话。

**响应** `data`：`UnitTestSession[]`。

### 3.4 `POST /unit-test-sessions` — 新建会话

**请求**：

```jsonc
{
  "title": "下单链路回归",          // 必填
  "channel": "cli",                 // TestChannel，必填
  "adapter": "opencode",            // 默认 AGENT_ADAPTERS[0]
  "testIds": []                     // 可选，初始关联
}
```

**响应** `data`：完整 `UnitTestSession`(id `uts-<n>`，`status:'created'`，含一条
`role:'user'` 初始化消息：「创建单测会话「{title}」· 执行通道: …」)。

### 3.5 `GET /unit-test-sessions/{session_id}`

按 id 取会话(含全部消息)。`404` 未命中。

### 3.6 任务关联(复用，非本域新接口)

`ExecutionTask.testIds` 的增删沿用现有 `PATCH /api/architect/exec/{task_id}`
(body 携带 `testIds`)。本域不新增任务关联接口。

---

## 4. WebSocket：`/api/architect/ws/unit-test`

执行与对话走单条 WS 连接。服务端保持会话消息有序；每写一条即落库。

### 4.1 客户端 → 服务端

| type | 字段 | 说明 |
| --- | --- | --- |
| `run` | `sessionId`, `testIds` | 执行指定单测；服务端逐用例执行并流式回推 |
| `message` | `sessionId`, `content` | 用户向 agent 对话(修复反馈/指令) |
| `stop` | `sessionId` | 请求停止当前执行(仅影响正在 run 的会话) |
| `ping` | — | 心跳 → `pong` |

### 4.2 服务端 → 客户端(流式)

| type | 字段 | 说明 |
| --- | --- | --- |
| `tool_call` | `tool: { type:'run-test', label, detail, ok }` | 每个用例「开始」或「结束」的 tool 消息(与前端 mock 一致，开始 ok:true 无结果) |
| `result` | `testId`, `status: 'passed'\|'failed'\|'skipped'\|'error'`, `lastResult` | 每个用例执行终态(落库) |
| `status` | `sessionId`, `status: 'running'\|'done'\|'stopped'\|'failed'` | 会话状态变化 |
| `message` | `role:'assistant'`, `content` | 汇总(「本轮执行完成：X 通过 / Y 失败」)或对话修复回复 |
| `pong` | — | 心跳应答 |

### 4.3 执行语义(阶段 1 服务端模拟)

对 `run` 的每个 `testId`，服务端依次：

1. `status(running)`
2. 发 `tool_call`(detail:「开始执行「{name}」」, ok:true)
3. 短暂延迟后判定(模拟延迟可在服务端 ~600ms/用例)
4. 发 `result`：`ut-3` 判定 `failed`(lastResult: passed 5 / failed 2,
   error 'TestRelayRetry: 重试退避断言失败')；其余 `passed`
   (passed 12 或 8，failed 0)
5. 发 `tool_call`(失败 detail:「失败: {error}」ok:false；通过 detail:「通过: {n} 用例」ok:true)
6. 若收到 `stop` 且尚未完成 → 当前用例置 `skipped`，会话 `stopped`，终止
7. 全部完成 → `status(done)`，发 `message` 汇总(有失败则含失败计数)

> 若目标用例含 `ut-3`，多用例场景下 `ut-3` 需恰在待执行集合中才失败；单个跑 `ut-3` 同样失败。

### 4.4 对话语义

对 `message`：
- 追加用户消息到会话。
- 生成 `role:'assistant'` 回复并落库回推：
  - `channel==='cli'` → 「已接收指令。请回到左栏选择失败用例重新执行，或补充修复提示。」
  - `channel==='agent'` → 「收到，将基于报错「{content前24字符}」分析并修复，修复后可重新触发关联单测。」

---

## 5. 与前端服务方法映射

| 前端 `unitTestService` | 后端 |
| --- | --- |
| `listTests()` | `GET /unit-tests` |
| `listSessions()` | `GET /unit-test-sessions` |
| `addTest(data)` | `POST /unit-tests` |
| `createSession(opts)` | `POST /unit-test-sessions` |
| `runTests(session, targets, opts)` | WS `run` + 流式 `tool_call/result/status/message` |
| `sendMessage(session, content)` | WS `message` |

## 6. 数据流与落库

- 每次 `result` 更新 `arch_unit_tests.status/last_result`。
- 每条会话消息追加 `arch_unit_test_messages`；会话 `status/updated_at` 更新
  `arch_unit_test_sessions`。
- 前端 store 的 `passedCount`(工作流 stepper 判定)来自 `GET /unit-tests` 中
  `status==='passed'` 计数。

## 7. 验证

- `curl` 4 个 REST 接口，确认包络与 id 生成。
- WS 用小客户端：`run` ut-1/ut-3 → 断言 `tool_call → result → status(done)` 序列与
  `ut-3` 失败。
- 前端 WS 助手接入后：新建会话 → 左栏 Run(agent/cli) → 右栏反馈 → 对话 → 再执行；
  刷新页面历史仍在。
