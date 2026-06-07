# TopoOne 系统架构概览

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                      Electron Shell                                 │
│  ┌──────────────┐  ┌────────────────┐  ┌────────────────────────┐  │
│  │  main.ts      │  │  zmq-router.ts │  │  python-bridge.ts     │  │
│  │  IPC 路由     │──│ ZMQ DEALER+SUB │──│ 管理 Python 子进程     │  │
│  │  窗口管理     │  │ RPC + 事件订阅  │  │                        │  │
│  └──────┬───────┘  └────────────────┘  └───────────┬────────────┘  │
│         │                                           │               │
│  ┌──────┴───────┐                                   │               │
│  │  preload.ts  │  contextBridge → window.api.*     │               │
│  └──────┬───────┘                                   │               │
└─────────┼───────────────────────────────────────────┼───────────────┘
          │ tcp://127.0.0.1:5671/5680                 │
┌─────────┴───────────────────────────────────────────┴───────────────┐
│               Vue 3 Frontend                                        │
│                                                                     │
│  Pages (6) ─── Components (15 groups) ─── Pinia Stores (22)        │
│                                                  │                  │
│                                        IPC Service (ipc.ts)         │
│                                          camelCase 适配层            │
└─────────────────────────────────────────────────────────────────────┘
│
│ ZMQ Protocol ─── ROUTER/DEALER (RPC) + PUB/SUB (Events)
│
┌─────────────────────────────────────────────────────────────────────┐
│               Python Backend                                        │
│                                                                     │
│  ZMQServer — @server.register("domain.method") — 100+ APIs         │
│                                                                     │
│  ├─ project.*      core_service.py   项目管理/分组/文件树            │
│  ├─ analysis.*     task_manager.py   任务 CRUD/社区/图查询           │
│  ├─ report.*       task_manager.py   子文档/概要/流水线状态          │
│  ├─ llm.chat       llm_service.py    LLM 网关/流式/结构化输出        │
│  ├─ session.*      llm_service.py    对话会话 CRUD                  │
│  ├─ knowledge.*    core_service.py   知识库文档                     │
│  ├─ settings.*     core_service.py   模型/代理/技能配置              │
│  └─ backend.*      core_service.py   后端生命周期/健康检查            │
│                                                                     │
│  执行引擎:                                                          │
│    analyst_runner.py   — 6 步流水线: AST→符号→调用图→依赖图→社区→汇总 │
│    prompt_manager.py   — 模板渲染 (chat/tools/structured)            │
│    tools_executor.py   — LLM 工具调用                               │
│    hybrid_resolver.py  — 符号解析 (SimpleBinder + StackGraphs)       │
│                                                                     │
│  数据库:                                                            │
│    topoone.db      — 项目/任务/模型/模板/配置                       │
│    knowledge.db    — 知识库文档                                     │
│    sessions.db     — LLM 会话/消息                                  │
│    {project}.db    — 源码/AST/图/社区/AI 结果/报告子文档             │
│                                                                     │
│  LLM Providers: ollama.py / openai_compat.py                        │
│  MCP Server:    backend_bridge.py (40+ API 暴露为 MCP 工具)          │
│  Change Tracker: git_adapter / diff_engine / snapshot_store          │
└─────────────────────────────────────────────────────────────────────┘
```

## 数据流

### RPC 调用 (同步)
```
Vue 组件 → Pinia Store → ipc.ts → preload.ts (ipcRenderer.invoke)
  → Electron main (ipcMain.handle) → zmq-router.ts (DEALER)
  → Python ZMQServer → 注册方法 → SQLite/LLM → 返回
```

### 事件推送 (异步)
```
Python → ZMQ PUB → Electron SUB → broadcast('event:xxx')
  → preload.ts 监听 → Pinia callback → Vue 响应式更新
```

## 前端结构

| 层 | 文件 | 职责 |
|---|---|---|
| Pages (6) | `src/pages/` | Home / Code / Analysis / Knowledge / Coder / User |
| Components | `src/components/` | shell/project/analysis/report/visualization/coder/... |
| Stores (22) | `src/stores/` | project/analysis/report/community/pipeline/chat/... |
| IPC Service | `src/services/ipc.ts` | 统一封装 window.api, camelCase 适配 |
| Router | `src/router/` | Hash 路由, 5 主页面 |
| i18n | `src/i18n/` | zh-CN / en-US |

## 数据库表

### 主库 (topoone.db)
- `projects` — 项目元数据
- `analysis_tasks` — 分析任务配置
- `analysis_task_runs` — 运行历史
- `analysis_reports` — 分析结果汇总
- `model_configs` — LLM 模型配置
- `llm_prompt_templates` — 提示词模板
- `project_groups` — 项目分组层级
- `task_model_bindings` — 任务类型→模型绑定

### 项目库 ({project_id}.db)
- `source_files` — 源码文件
- `base_node` — AST 节点
- `graph_node` — 符号/调用/依赖边
- `graph_doc` — 社区聚类结果
- `community_hierarchy` — 社区层级
- `community_llm_results` — AI 命名/摘要/图表
- `report_subdocs` — 报告子文档
- `file_summaries` — 文件摘要缓存

## 报告生成流水线

| 步骤 | 权重 | 说明 |
|------|------|------|
| validation | 5% | 模型连接验证 |
| project_summary | 20% | 项目概要 (README + 依赖) |
| community_analysis | 50% | L0 组件 AI 分析 (命名/摘要/图表) |
| overall_architecture | 25% | 整体架构文档生成 |

所有步骤状态通过 `savePipelineState` 持久化到 `report_subdocs`，重启后可恢复。
