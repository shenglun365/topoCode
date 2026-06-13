# Agent 相关能力代码位置总览

> 本文档全面梳理 TopoCode 项目中与 Agent 能力相关的代码位置，包括 Harness、Skill、Tool、提示词约束、安全沙箱、运行时循环等所有模块。

---

## 目录

1. [Harness — RouterHarness](#1-harness--routerharness)
2. [Skill — 多步工具编排](#2-skill--多步工具编排)
3. [Tool — 三层工具系统](#3-tool--三层工具系统)
4. [Agent Workflow 系统](#4-agent-workflow-系统)
5. [提示词约束信息位置](#5-提示词约束信息位置)
6. [安全沙箱约束](#6-安全沙箱约束)
7. [MCP Server 桥接层](#7-mcp-server-桥接层)
8. [前端相关代码](#8-前端相关代码)
9. [SQLite 中的提示词/约束存储](#9-sqlite-中的提示词约束存储)

---

## 1. Harness — RouterHarness

| 位置 | 作用 |
|---|---|
| `backend-core/agent_workflow/router.py:39` | `RouterHarness` 类 — 将 action 字符串路由到 Workflow+Tool 组合 |
| `backend-core/agent_workflow/router.py:228` | `create_default_router()` — 注册默认路由 |
| `backend-core/task_manager.py:2095,2185` | 被 `task_manager.py` 调用以启动/停止架构追踪 |

**核心逻辑**：`dispatch(action, task_id, context)` 通过 `RouteEntry` 查找注册的 `workflow_class`、`tool_builder`、`sandbox_builder`，实例化后交给 `AgentTaskManager.enqueue()`。

**默认路由**：
- `"analyze"` → `ArchAnalystWorkflow`（LLM 分析 + 图表 + 概览）
- `"track_start"` → `ArchSentinelWorkflow`（快照录制）
- `"track_stop"` → `ArchSentinelWorkflow`（差异 + 摘要 + 持久化）

**路由类定义**：

| 类 | 文件行 | 用途 |
|---|---|---|
| `RouteEntry` | `router.py:25` | 单条路由定义（workflow_class / tool_builder / sandbox_builder / context_transformer） |
| `RouterHarness` | `router.py:39` | Harness 主体：注册 action、dispatch、NL 路由 |
| `create_default_router()` | `router.py:228` | 工厂函数 |

---

## 2. Skill — 多步工具编排

| 位置 | 作用 |
|---|---|
| `backend-core/mcp_server/skill_executor.py:39` | `SkillExecutor` 类 — 注册 Skill、执行多步流水线、结果合并 |
| `backend-core/mcp_server/skills.py` | `register_core_skills()` — 注册 13 个内置 Skill |
| `backend-core/mcp_server/__init__.py` | 导出 `SkillExecutor`, `SkillDefinition`, `SkillStepDef` |
| `backend-core/tests/test_skill_executor.py` | 单元测试 |

**关键数据类型**：

| 类 | 文件行 | 用途 |
|---|---|---|
| `SkillStepDef` | `skill_executor.py:22` | 单步定义：`name`, `fn`, `post_process` |
| `SkillDefinition` | `skill_executor.py:29` | 完整 Skill 定义：`name`, `description`, `steps`, `input_schema`, `max_tokens`, `timeout_ms` |
| `SkillExecutor` | `skill_executor.py:39` | 注册 Skill、执行多步流水线、上下文传递、Token 预算控制、结果合并 |

**内置 Skill 完整列表**：

| 分类 | Skill 名称 | 步骤 |
|---|---|---|
| 文档生成 | `skill_generate_arch_overview` | get_communities → get_overview |
| 文档生成 | `skill_analyze_community` | get_community_detail |
| 图表 | `skill_fix_mermaid` | 直接调用 |
| 图表 | `skill_fix_plantuml` | 直接调用 |
| 图表 | `skill_fix_diagram` | validate → auto-fix |
| 架构学习 | `skill_explain_arch_pattern` | get_community_detail → get_overview |
| 架构学习 | `skill_compare_arch` | get_diff |
| 架构学习 | `skill_recommend_refactor` | quality_inspect |
| 架构学习 | `skill_validate_arch_impact` | 无（占位） |
| 架构学习 | `skill_detect_arch_drift` | get_diff |
| 批量编排 | `skill_batch_analyze_communities` | get_communities |
| 会话追踪 | `skill_track_ai_session` | get_diff → get_session_summary |
| 会话追踪 | `skill_audit_changes` | quality_inspect |

---

## 3. Tool — 三层工具系统

### 3A. Agent 工作流层（AgentTool）

| 位置 | 作用 |
|---|---|
| `backend-core/agent_workflow/tools.py:32` | `AgentTool` ABC — 所有工具的基类，定义 `execute()`, `to_schema()` |
| `backend-core/agent_workflow/tools.py:54` | `ToolRegistry` — 白名单注册器 |
| `backend-core/agent_workflow/tool_factory.py` | `build_analyst_tools()` / `build_sentinel_tools()` — 工厂函数 |

**AgentTool 实现**：

| 类 | 文件 | 用途 |
|---|---|---|
| `_AnalyzeCommunityTool` | `workflows/arch_analyst.py` | LLM 为社区生成名称+摘要 |
| `_GenerateDiagramTool` | `workflows/arch_analyst.py` | 模板化 Mermaid/PlantUML 生成 |
| `_GenerateOverviewTool` | `workflows/arch_analyst.py` | LLM 生成立体架构概览 |
| `_SaveResultsTool` | `workflows/arch_analyst.py` | 持久化分析结果 |
| `_SnapshotTool` | `workflows/arch_sentinel.py` | 录制架构快照到 JSONL |
| `_DiffTool` | `workflows/arch_sentinel.py` | 比较两个版本社区数据 |
| `_SummarizeTool` | `workflows/arch_sentinel.py` | LLM 生成可读变更摘要 |
| `_SaveDeltaTool` | `workflows/arch_sentinel.py` | 持久化变更到 JSONL |

### 3B. LLM Tools Calling 层

| 位置 | 内容 |
|---|---|
| `backend-core/tools_executor.py` | `ToolExecutor` — 7 个 OpenAI 格式 function-calling tool |

**7 个工具**：`get_file_content`, `get_symbol_detail`, `get_community_subgraph`, `get_edge_detail`, `search_symbols`, `get_call_chain`, `get_ast_node`

### 3C. MCP Tool 层

| 位置 | 作用 |
|---|---|
| `backend-core/mcp_server/tools.py` | `ToolDefinition` 数据类 + `CORE_TOOLS` 列表 |
| `backend-core/mcp_server/dispatcher.py:17` | `ToolDispatcher` — 分发 `tools/call` 到 6 个 handler |

**6 个 MCP 架构认知工具**：

| 工具名 | Handler | 用途 |
|---|---|---|
| `topocode_community` | `_handle_community()` | 列出社区（按层级过滤） |
| `topocode_community_detail` | `_handle_community_detail()` | 社区详情（name/what/how/why/hubs） |
| `topocode_architecture_overview` | `_handle_arch_overview()` | 整体架构概览 |
| `topocode_diff` | `_handle_diff()` | 变更差异分析 |
| `topocode_session_summary` | `_handle_session_summary()` | 会话摘要 |
| `topocode_quality_inspect` | `_handle_quality_inspect()` | 质量检查（大社区/孤立社区） |

---

## 4. Agent Workflow 系统

### 目录结构

```
backend-core/agent_workflow/
├── __init__.py          — 导出 17 个公开符号
├── tools.py             — AgentTool ABC, ToolRegistry, ToolResult
├── runtime.py           — AgentRuntime 核心循环
├── memory.py            — AgentMemory 上下文窗口
├── sandbox.py           — AgentSandbox 安全沙箱
├── router.py            — RouterHarness 路由调度
├── agent_queue.py       — AgentTaskManager 任务队列
├── jsonl_store.py       — JSONL 持久化
├── llm_adapter.py       — LLMService 包装
├── workflows/
│   ├── base.py          — AgentWorkflow ABC + AgentStep + WorkflowResult
│   ├── arch_analyst.py  — ArchAnalystWorkflow（分析）
│   └── arch_sentinel.py — ArchSentinelWorkflow（追踪）
└── cloud/
    ├── __init__.py
    ├── schema.py         — 匿名化数据结构
    ├── client.py         — 云 API 客户端（存根）
    └── anonymize.py      — 数据匿名化
```

### 执行流程

```
User action (string) or NL
    → RouterHarness.dispatch(action, task_id, context)
        → RouteEntry 查找
        → tool_builder(context) → ToolRegistry
        → sandbox_builder(project_root) → AgentSandbox
        → workflow_class() → AgentWorkflow 实例
        → AgentTaskManager.enqueue() → 后台线程
```

### 运行时循环（`runtime.py:69` `AgentRuntime.run()`）

1. **Plan**: `workflow.plan(context)` → `List[AgentStep]`
2. **Execute**: 对每步查找 tool，执行（最多重试 2 次），应用沙箱约束
3. **Observe**: 收集结果 → `AgentMemory` → `BudgetTracker` → 进度回调
4. **Finalize**: `workflow.finalize(results)` → `WorkflowResult`

### 任务队列（`agent_queue.py`）

| 组件 | 说明 |
|---|---|
| `AgentTaskManager` | 线程池（默认 max 3 并发） |
| `enqueue()` | 启动守护线程，立即返回 `agent_id` |
| 支持操作 | 进度查询 (`get_progress`)、取消 (`cancel`)、崩溃恢复持久化 |
| 任务状态 | QUEUED → RUNNING → COMPLETED/PARTIAL/FAILED/CANCELLED |

---

## 5. 提示词约束信息位置

### 5A. Prompt 模板管理器

| 位置 | 作用 |
|---|---|
| `backend-core/prompt_manager.py:42` | `PromptManager` — 模板 CRUD + 渲染 + 数据库持久化 |
| `backend-core/prompt_manager.py:412` | `render()` — 填充变量 → 返回 `{messages, mode, tools, outputSchema}` |
| `backend-core/prompt_manager.py:263` | `create_template()` — 创建自定义模板 |
| `backend-core/prompt_manager.py:363` | `restore_defaults()` — 从 JSON 恢复默认 |

**三种模式**：
- `chat` — 对话模式（完整文本流式输出）
- `tools` — Tools Calling 模式（模型按需调用工具）
- `structured` — 结构化输出模式（JSON Schema 校验）

### 5B. 内置提示词模板（JSON 配置文件）

**文件**：`backend-core/config/prompt_templates.json`（459 行，35 个模板）

每个模板包含：
- `system_prompt` — 角色设定 + 行为约束
- `user_prompt_template` — 带 `{variable}` 占位符
- `output_schema_json` — 结构化模式的 JSON Schema
- `tools_json` — tools 模式的可用工具列表
- `variables_json` — 变量声明
- `locale` — zh-CN / en-US

**模板类别概览**：

| 分类 | 模板 ID 示例 | 模式 |
|---|---|---|
| 源码分析 | `func_summary`, `source_explain`, `source_pseudocode` | chat |
| 架构分析 | `arch_analysis` | tools |
| AI 对话 | `agent_chat` | chat |
| 组件命名 | `community_name` | structured |
| 组件分析 | `community_analyze` | structured |
| 报告流水线 | `report_overall_architecture`, `report_project_summary`, `report_core_modules` | chat |
| 图表修复 | `diagram_regenerate_mermaid`, `diagram_regenerate_plantuml`, `regenerate_diagram` | structured |

### 5C. InstructionManager（运行时指令注入）

| 位置 | 作用 |
|---|---|
| `backend-core/instruction_manager.py:21` | `InstructionManager` — 向 system prompt 注入自定义指令 |
| `instruction_manager.py:12` | 默认指令：`"你是一个以人为本的架构认知助手。输出应简洁、结构化，先给结论再给依据。"` |
| `instruction_manager.py:64` | `inject()` — 深拷贝 messages，注入指令 |

**优先级**：
| 优先级 | 行为 |
|---|---|
| `prepend` | 前置追加到 system prompt |
| `append` | 后置追加到 system prompt |
| `replace` | 完全替换 system prompt |

**作用域**：`all` / `report` / `chat` / `diagram`

### 5D. Server Instructions（MCP 行为指南）

| 位置 | 作用 |
|---|---|
| `backend-core/mcp_server/server_instructions.py:12` | `EXTERNAL_AGENT_INSTRUCTIONS` — 给外部 Agent（Claude/Codex） |
| `backend-core/mcp_server/server_instructions.py:51` | `INTERNAL_AGENT_INSTRUCTIONS` — 内置 Agent 的 System Prompt |

**核心原则**：
1. **输出抽象，而非枚举** — BAD: "12 个节点、45 条边" / GOOD: "auth 是业务层的中心子系统"
2. **渐进披露** — 先给框架，人追问时再展开
3. **教人，而非替代人** — 解释"为什么"，决策权在人手里

---

## 6. 安全沙箱约束

| 组件 | 文件 | 约束 |
|---|---|---|
| `PathSandbox` | `sandbox.py:17` | 读限项目根目录，写限 `.topocode/` |
| `ContentGuard` | `sandbox.py:54` | 过滤 shell 命令、URL、代码块、危险命令 |
| `RateLimiter` | `sandbox.py:86` | 最大并发 3，最小间隔 200ms，每秒最多 1 次 |
| `BudgetTracker` | `sandbox.py:123` | Token 预算最大 50000，超时 300 秒 |
| `AgentSandbox` | `sandbox.py:184` | 以上四者的统一入口 |

**PathSandbox 规则**：
- `allow_read(path)` — 文件路径必须以 `project_root` 开头
- `allow_write(path)` — 文件路径必须以 `project_root/.topocode/` 开头

**ContentGuard 过滤规则**：
```
- ```bash/sh/zsh/shell 代码块
- ```python/js/javascript 代码块
- 行内 `code`
- URL (https?://...)
- sudo / chmod / chown / rm -rf / mkfs / dd if=
- <?php ... ?> / <script ... </script>
```

---

## 7. MCP Server 桥接层

### 目录结构

```
backend-core/mcp_server/
├── __init__.py            — 导出 MCPServer, ToolDispatcher, CORE_TOOLS, SkillExecutor
├── __main__.py            — 入口: python -m backend-core.mcp_server
├── server.py              — MCPServer: JSON-RPC 2.0 over stdio
├── dispatcher.py          — ToolDispatcher: 6 个架构认知工具
├── tools.py               — ToolDefinition + CORE_TOOLS
├── skills.py              — register_core_skills() — 13 个 Skill
├── skill_executor.py      — SkillExecutor — 多步编排
├── backend_bridge.py      — ZMQ 桥接
├── zmq_client.py          — 异步 ZMQ DEALER 客户端
├── path_validator.py      — 目录穿越防护
├── result_compressor.py   — Token 预算压缩
└── server_instructions.py — 外部/内置 Agent 行为指南
```

### 通信模式

```
外部 Agent (Claude/Codex)
    ↓ stdio JSON-RPC 2.0
MCPServer (server.py)
    ├── Direct 模式: ToolDispatcher 直接调用
    └── ZMQ 模式: BackendBridge → ZMQServer → ToolDispatcher
```

### MCP Capabilities

- 协议: `2024-11-05`
- Server: `topocode-mcp` v0.2.0
- Features: `tools/list`, `tools/call`, `prompts/list`, `prompts/get`

---

## 8. 前端相关代码

### 类型定义

| 文件 | 类型/接口 | 用途 |
|---|---|---|
| `src/types/ipc.ts:382` | `AgentConfigItem` | Agent 配置：`{id, name, path, args, status, version, isDefault}` |
| `src/types/ipc.ts:393` | `SkillConfigItem` | Skill 配置：`{id, name, description, enabled}` |
| `src/types/ipc.ts:814` | `AgentConfigDTO` | AgentConfigItem 别名 |
| `src/types/ipc.ts:815` | `SkillConfigDTO` | SkillConfigItem 别名 |
| `src/types/ipc.ts:769` | `UsageStatDTO` | 模型用量统计 |

### Pinia Stores

| 文件 | Store | 用途 |
|---|---|---|
| `src/stores/agent-usage-store.ts` | `useAgentUsageStore` | Agent/Skill CRUD + 用量统计 |
| `src/stores/mcp-store.ts` | `useMCPStore` | MCP 服务器状态 (stopped/starting/running/error) |
| `src/stores/community-store.ts` | `useCommunityStore` | Agent 任务追踪（`_pollAgentProgress()`） |

### 组件

| 文件 | 用途 |
|---|---|
| `src/components/report/ChatView.vue` | Agent 对话界面 |
| `src/components/report/AgentTaskList.vue` | Agent 任务列表面板 |
| `src/components/report/ReportTaskListPanel.vue` | 分析任务执行状态 |
| `src/components/settings/ModelConfig.vue` | 用量统计展示 |

### IPC 服务

| 方法 | 说明 |
|---|---|
| `settings.getAgents()` / `addAgent()` / `updateAgent()` / `removeAgent()` / `detectAgent()` | Agent CRUD |
| `settings.getSkills()` / `updateSkill()` | Skill CRUD |
| `analysis.startArchAnalysis()` | 启动架构分析 |
| `analysis.startArchTrack()` / `stopArchTrack()` | 启动/停止架构追踪 |
| `analysis.getAgentProgress()` | 查询 Agent 进度 |
| `analysis.cancelAgentTask()` | 取消 Agent 任务 |

---

## 9. SQLite 中的提示词/约束存储

### 数据库表总览

| 表名 | 文件:行 | 数据库 | 用途 |
|---|---|---|---|
| `llm_prompt_templates` | `sqlite_ctx.py:291` | main (topoone.db) | **35 条 LLM 提示词模板**（从 JSON 导入） |
| `context_store` | `sqlite_ctx.py:283` | main (topoone.db) | KV 配置（如 `default_template_locale`） |
| `app_config` | `sqlite_ctx.py:397` | main (topoone.db) | 系统级配置（如导入过滤） |
| `report_interaction_log` | `sqlite_ctx.py:337` | main (topoone.db) | 流水线交互日志（含 template_id） |
| `report_subdocs` | `sqlite_ctx.py:683` | project (project.db) | 报告子文档 + 流水线状态 (`__pipeline_state__`) |
| `project_config` | `sqlite_ctx.py:550` | project (project.db) | 项目级 KV 配置 |
| `model_configs` | `sqlite_ctx.py:225` | main (topoone.db) | LLM 模型配置 |
| `agent_instructions` (遗留) | `store/schema.py:353` | main (topoone.db) | **旧流水线产物**——表定义存在但新代码未使用 |

### 关键发现

1. **`llm_prompt_templates`** — 35 条模板全量在数据库中（来自 `prompt_templates.json`），包含 system_prompt、output_schema、tools 等约束
2. **`agent_instructions`** — 旧 schema 遗留表，`instruction_manager.py` 未实际查询此表（当前指令由内存 `DEFAULT_INSTRUCTIONS` 驱动）
3. **`context_store`** — `default_template_locale` 决定 PromptManager 返回哪个 locale 的模板
4. **流水线状态** — 以 `comm_id = '__pipeline_state__'` 的形式存储在 `report_subdocs` 中

---

## 架构总览图

```
┌──────────────────────────────────────────────────────────────┐
│                         Frontend (Vue 3)                      │
│  src/stores/agent-usage-store.ts                              │
│  src/components/report/{AgentTaskList,ChatView}.vue          │
│  src/services/ipc/settings-service.ts                        │
└──────────────┬───────────────────────────────────────────────┘
               │ ZeroMQ IPC (JSON-RPC)
               ▼
┌──────────────────────────────────────────────────────────────┐
│                      Backend Core                             │
│                                                               │
│  ┌──────────────────────────────────────────┐                │
│  │         RouterHarness (router.py)         │                │
│  │  action → RouteEntry → dispatch()         │                │
│  └────────────┬─────────────────────────────┘                │
│               │                                               │
│  ┌────────────▼─────────────────────────────┐                │
│  │     AgentTaskManager (agent_queue.py)     │                │
│  │  Thread pool (max 3), concurrency        │                │
│  └────────────┬─────────────────────────────┘                │
│               │                                               │
│  ┌────────────▼─────────────────────────────┐                │
│  │       AgentRuntime (runtime.py)           │                │
│  │  Plan → Execute → Observe → Finalize     │                │
│  │  With AgentSandbox constraints            │                │
│  └──┬──────────┬──────────┬─────────────────┘                │
│     │          │          │                                   │
│     ▼          ▼          ▼                                   │
│  ToolRegistry  AgentMem   AgentSandbox                        │
│  (tools.py)    (memory)   (sandbox.py)                        │
│                  │         ├─ PathSandbox                     │
│                  │         ├─ ContentGuard                   │
│                  │         ├─ RateLimiter                    │
│                  │         └─ BudgetTracker                  │
│                  ▼                                            │
│  AgentWorkflows                                              │
│  ├─ ArchAnalystWorkflow  (arch_analyst.py)                   │
│  └─ ArchSentinelWorkflow (arch_sentinel.py)                  │
│                                                               │
│  ┌──────────────────────────────────────────┐                │
│  │        MCP Server (mcp_server/)          │                │
│  │  JSON-RPC 2.0 over stdio                 │                │
│  │  ├─ MCPServer: tools/list, tools/call    │                │
│  │  │             prompts/list, prompts/get │                │
│  │  ├─ ToolDispatcher: 6 个架构认知工具     │                │
│  │  ├─ SkillExecutor: 13 个多步 Skill      │                │
│  │  └─ BackendBridge → ZMQ 转发            │                │
│  └──────────────────────────────────────────┘                │
│                                                               │
│  ┌──────────────────────────────────────────┐                │
│  │  Tools Executor (tools_executor.py)       │                │
│  │  7 function-calling tools (LLM 模式)     │                │
│  └──────────────────────────────────────────┘                │
│                                                               │
│  ┌──────────────────────────────────────────┐                │
│  │  PromptManager + InstructionManager      │                │
│  │  prompt_templates.json (35 个模板)       │                │
│  │  Server Instructions (外部+内置 Agent)   │                │
│  │  SQLite: llm_prompt_templates (35 条)   │                │
│  │          context_store (locale 配置)     │                │
│  └──────────────────────────────────────────┘                │
└──────────────────────────────────────────────────────────────┘
```
