# B1-W1 实施文档：前置 + 快赢组（prompt 快照 / request 转义 / WS 序列号）

> 组：W0 前置(0.5d) + W1(3d) · 依赖：无 · 决策依据：计划 §三 W0/W1 任务卡
> 性质：安全网与基础设施——先建回归防线，再动上下文工程（W2+）

---

## 1. 模块操作总表

| 模块 | 操作 | 摘要 |
|---|---|---|
| `tests/test_prompt_goldens.py` | **新增** | prompt 分型 golden 断言 |
| `tests/goldens/prompt/*.json` | **新增** | golden 资产（按分型一文件） |
| `agent/cognition/prompt.py` | **变更** | 新增 `wrap_user_request()`；用户内容装配点接线 |
| `agent/execution/context_pack.py` | **变更** | 指令尾契约段走同一转义 |
| `arch_routes/websocket.py` | **变更** | 会话事件附单调 `seq` |
| `arch_routes/sessions.py` | **变更** | 消息查询支持 `since_seq` 增量参数 |
| `src/services/ws-client.ts` | **变更** | 事件透出 `seq` 字段 |
| 会话消息 store（`src/stores/`） | **变更** | 丢弃 `seq <= lastSeq`；重连走增量补偿 |
| SSE `msgCount` 统计 | **变更** | 修正含 reasoning 的粗粒度计数（v2-todo 已知小问题） |
| 移除 | 无 | — |

## 2. 逐模块明细

### 2.1 `agent/cognition/prompt.py`（W1-2 转义）

**改动**：新增 `wrap_user_request(text: str) -> str`——输出 `<request>…</request>` 包裹；文本内部出现 `</request>` 时替换为全角 `＜/request＞`（或计数闭合注释，实现时二选一并注释理由）。在用户内容进入 system/prompt 信封的既有装配点调用（chat 分型与任务分型两处）。

**上游**：用户输入文本（会话消息/需求草稿）。
**下游**：所有 prompt 消费方获得注入防护；W1-1 的 golden 会锁定包裹形态（转义属契约变更，模板版本 +1，走成对版本化）。

### 2.2 `agent/execution/context_pack.py`（W1-2 第二装配点）

**改动**：指令尾契约段中引用用户需求原文处，改走 `wrap_user_request`。

**下游**：执行器（cline/opencode/codex）载荷契约文本变化——纯内容包装，无 schema 变化，对执行器透明。

### 2.3 `tests/test_prompt_goldens.py` + `tests/goldens/prompt/`（W1-1）

**改动**：按 prompt 分型（chat 角色 / 任务角色 / 摘要 / 命名，以 `prompt.py` 实际分型函数为准）各出一 golden JSON；断言三维：① 分段结构（标题/定界符序列）② 关键契约句存在（如"执行前先读"强指引）③ 字数预算区间（接 `prompt_sections` 分层字数遥测口径）。再生成走显式 `pytest --regen-goldens`（conftest 注册自定义 flag），**禁止测试内自再生成**。

**上游**：`prompt.py` 组装函数（喂固定 fixture 输入）。
**下游**：CI 漂移即红；W3 模板变更、W6 skills 注入段变更都会触发 golden diff——这是设计目的（模板变更必须显式过版本）。

### 2.4 `arch_routes/websocket.py` + `arch_routes/sessions.py`（W1-3 后端）

**改动**：① 会话级单调计数器（进程内存 dict；进程重启后以 DB 会话消息 max(seq) 续，防回退）；事件出队时附 `seq` 字段。② sessions 消息查询口新增 `since_seq` 参数：`seq > since_seq` 增量返回（消息落库时持久化 seq，复用既有会话消息表加一列或复用既有单调 id——**实现时核验既有 id 是否已单调，若已单调则直接用之，不新增列**）。

**上游**：执行器过程流（process_stream 单源）、LLM 流式事件。
**下游**：所有 WS 消费方（前端 store）；老客户端忽略未知字段，天然兼容。

### 2.5 `src/services/ws-client.ts` + 会话消息 store（W1-3 前端）

**改动**：① ArchWs 事件回调透出 `seq`；② store 合并逻辑：`seq <= lastSeq` 丢弃并计数（便于测试断言）；③ 重连补偿：`ready()` 后先 `getMessages(since_seq)` 拉增量再续订（ArchWs 建连时序在 ws-client 内已有，插入一步）。④ `msgCount` 修正为非 reasoning 计数。

**上游**：后端 seq 协议。
**下游**：ChatFeedPanel/ExecutorProcessStrip 等渲染组件无感（store 层吸收）。

## 3. 数据与契约变更

| 契约 | 变更 | 兼容性 |
|---|---|---|
| WS 事件 schema | 新增可选字段 `seq` | 老前端忽略；新前端在后端缺 seq 时退化为现行为 |
| 消息查询 API | 新增可选 query `since_seq` | 纯增量参数 |
| prompt 形态 | `<request>` 包裹（两装配点） | 契约变更走模板版本 +1；golden 同步 |

## 4. 测试计划

- BE：`test_prompt_goldens.py`（分型 ×4）；转义对抗用例（伪 `</request>`/伪 `</system>` 提前闭合）——放 `tests/test_prompt_request_escape.py` 或并入 goldens 文件；WS seq 单调/重启续号/增量查询——`tests/test_ws_seq.py`
- FE：store 乱序丢弃 + 重连增量——`tests/ws-seq.test.ts`（jsdom 模拟）
- 回归：既有 1364 基线不回落

## 5. 回退

| 片 | 回退方式 |
|---|---|
| W1-1 | 删测试文件与 golden 目录 |
| W1-2 | `wrap_user_request` 调用点 revert（函数保留无害） |
| W1-3 | 前端忽略 seq 即回退（后端字段无害）；增量口无人调用即死代码，次批清理 |

## 6. 组内验收清单

- [ ] `pytest --regen-goldens` 命令存在且 README/CONV-03 有登记
- [ ] golden 漂移 CI 红（人为改一处 prompt 验证）
- [ ] 对抗注入样例全绿（转义后无标签逃逸）
- [ ] WS 乱序/重连回归绿；双标签页同会话无消息回退（手测）
- [ ] W0：`git tag topo-b1-start` + 行数基线登记完成
