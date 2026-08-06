# 通用约定与持久化

> 本文件定义 architect 后端所有接口的**通用约定**与**持久化方案**。
> 与 `topoCode-architect/docs/backend-api.md`「通用约定」一节保持一致，并补充 architect 特有的落地细节。

---

## 1. 传输方式与协议

- **REST/JSON**(HTTP) 用于查询、状态读取与结构化落盘。
- **WebSocket** 用于服务端推流 / 长连接：
  - 单元测试执行流(`/api/architect/ws/unit-test`)——见 [api-unit-test.md](api-unit-test.md)
  - 知识库分析 agent 多轮对话(`/ws/kb-analysis`)——见 [api-knowledge-greenfield.md](api-knowledge-greenfield.md)
  - coding agent 会话(`/ws/coding-agent`)——见 [api-execution.md](api-execution.md)
- Markdown 散文字段(规约、摘要、`basicMd` 等)为 Opaque 字符串原样存储。

## 2. 统一响应包络

后端所有 REST 接口返回统一包络，前端 `api-client.ts` 解包后返回 typed 数据：

```jsonc
{
  "code": 0,            // 0=成功；非 0=业务错误码
  "message": "ok",
  "data": { /* 具体契约载荷 */ }
}
```

## 3. 错误码约定

- `0` 成功。
- `404` 资源未命中(该资源集合内不存在该 id)。
- `400` 且 `code` 非 0：业务失败，`message` 说明原因(缺关键信息、门槛未过、互斥冲突、
  基线不一致等)。领域文档给出具体失败语义。

## 4. ID 生成约定

后端负责 ID 生成，保证多端唯一且前缀与前端一致。**弃用时间戳式 `_id()`**，改为
按前缀单调递增序列；前缀与 `docs/backend-api.md §2.4` 一致：

| 资源 | 前缀 | 说明 |
| --- | --- | --- |
| 需求(提案/池) | `RQ-<n>`、`US-<n>` | 现有 mock 用 `RQ-1..3`；池内需求用 `US-*` |
| 设计方案(执行批次) | `plan-<n>` | |
| 任务方案树 | `tp-<n>` | |
| 执行任务 | `ex-<n>` | |
| agent 会话 | `sess-<n>` | |
| 追加需求 | `ap-<n>` | |
| 单元测试 | `ut-<n>` | 本计划新增 |
| 单元测试会话 | `uts-<n>` | 本计划新增 |
| 架构快照 | `snap-v0` / `snap-v1` | |

实现：`common.py` 维护 `{prefix: last_seq}`(可落 sqlite 一列或多端共享时用序列表)，
`_id("ex") → "ex-12"`。

## 5. 时间与版本

- 所有时间戳为**毫秒时间戳**(`number`)，对应前端 `Date.now()`。
- 架构模型版本：`v0`(基线) / `v1`(当前)。

## 6. WebSocket 通用框架

所有 architect WS 端点统一消息外壳：

- 客户端 → 服务端：`{ "type": "<action>", ...领域字段 }`，可选 `reqId` 做请求关联。
- 服务端 → 客户端：`{ "type": "<event>", ...领域字段 }`。
- 所有端点支持 `{ "type": "ping" }` → `{ "type": "pong" }`。

---

## 7. 持久化方案：独立 `architect.db`

### 7.1 决策

- **文件**：`{ARCH_DATA_DIR:-~/.topocode}/architect.db`(与 `knowledge.db`/`sessions.db` 同层)。
- **归属**：由**独立 architect 服务**(`plugins/architect`)经 `arch_routes/ctx.setup()` 打开
  SQLiteContext(label `architect`)并成为**唯一写入者**；reports 不再触碰它。
- **不并入** `topoone.db`(迁移隔离、生命周期独立、可单独重置演示数据)。
- **不随项目库**(workbench 状态是应用级状态，非某项目代码分析产物)。

### 7.2 依据(已核对代码)

- `MultiDBManager`(backend-core/sqlite_ctx.py:1113)本就是多文件模型：
  `register_db(label, path)`(write_queue.py:79)是「label→路径」懒连接映射，任意新文件可注册。
- 本地/分布式建表都走 `_write_queue.execute_sync("architect", DDL)`，与 knowledge/sessions 一致。
- 主库迁移 `_migrate_main_tables()` 已很长，混入 architect 表会互相拖累。

### 7.3 表结构

常量 `ARCHITECT_DB_TABLES_SQL`(阶段 0 实现)，13 张表：

| 表 | 用途 | 关键列 |
| --- | --- | --- |
| `arch_projects` | 绑定/绿色字段项目冗余 | id, name, mode, exec_root, kb_root, config(json), active |
| `arch_requirements` | 需求提案 + 池 | id, kind, tier, status, location, title, desc, priority, acceptance(json), analysis(json), trace_to(json), updated_at |
| `arch_plans` | 设计(执行批次)方案 | id, req_ids(json), title, approach, changes(json), impact(json), status, task_plan_id, base_commit, updated_at |
| `arch_task_trees` | 任务方案树(含历史) | id, plan_id, root(json), revision, history(json), updated_at |
| `arch_execution_tasks` | 执行任务实例 | id, plan_id, adapter, model, req_ids(json), connectivity, status, session_ids(json), base_commit, run_count, test_ids(json), amendments(json), stats(json), error, created/updated/ended |
| `arch_agent_sessions` | coding agent 会话 | id, task_id, adapter, status, keep_context, artifacts(json), test_result(json), stats(json), created/updated |
| `arch_agent_messages` | agent 会话消息 | id, session_id, role, time, content, tool(json) |
| `arch_unit_tests` | 单元测试用例 | id, name, levels(json), script_path, source, status, last_result(json), created/updated |
| `arch_unit_test_sessions` | 单测会话 | id, title, channel, adapter, test_ids(json), status, stats(json), created/updated |
| `arch_unit_test_messages` | 单测会话消息 | id, session_id, role, time, content, tool(json) |
| `arch_mcp_calls` | MCP 外部调用日志 | id, tool, input(json), output(json), status, time |
| `arch_interactions` | 协作交互记录 | id, prompt, status, answer, time |
| `arch_specs` | 架构规约 | version, overrides(json), explicit_rules(json), derived_rules(json), changelog(json) |

> 嵌套结构(`levels`、`test_ids`、`analysis`、`tool` 等)以 JSON 文本存列；扁平字段直接落列，
> 与前端 `types/index.ts` 形状一致。

### 7.4 接线点

1. `sqlite_ctx` 提供模块级 `init_architect_db(db)` / `architect_db_migrations(db)`
   (SQLiteContext 打开即建表+迁移)。
2. `arch_routes/ctx.setup(data_dir)` 打开 `architect.db` 并 `init_architect_db`；
   `store._db()` 只经 `ctx.db()`(独立服务)或 `ctx.default_db()`(嵌入式/测试)取连接。
3. `arch_routes/store.py` 统一经 `ctx` 读写，路由保持细薄。

### 7.5 项目根路径(arch_projects 自持)

architect 解耦后，`arch_projects` 为项目唯一事实源：直接存 `rootPath`(工作目录)；
KB 关联元数据(`kb_project_id`/`kb_source_dir`/`baseline_id`/`link_verified_at`)写同一行，
**不再**跨库从 `main_db.projects` 现读。关联前须过 `_same_repo_source` 校验(同一仓库源)。

### 7.6 写入归属

- 独立 architect 进程是 `architect.db` 唯一写入者(经 ctx 注入的 SQLiteContext)。
- 不再经 reports `write_queue`/`db_client`；reports 进程已摘除 architect 相关初始化。
