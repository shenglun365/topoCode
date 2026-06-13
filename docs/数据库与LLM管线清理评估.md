# 数据库与 LLM 管线清理评估

> 生成日期: 2026-06-13
> 审计范围: SQLite 表结构、提示词模板、LLM 调用路径、Agent 数据模型
> 最后更新: 2026-06-13 执行完毕

---

## 执行完成总览

| # | 问题 | 原建议 | 最终执行 | 状态 |
|---|------|--------|---------|------|
| Q1 | `store/schema.py` DDL 重复 | 三步迁移删除 | ✅ 已执行：main_cli.py 改 import + 5 表合并 sqlite_ctx.py + schema.py 删除 + MultiDBManager 清理 | ✅ |
| Q2 | `agent_configs` 无 UI | 移除全链路 | ⚠️ 方向变更：保留+增强（放宽 type CHECK + agent_executions 表 + executeAgent RPC + 前端 IPC 全链路） | ✅ |
| Q3 | `ai_sessions` 孤数据 | 移除 ~400 行 | ✅ 已执行：DDL 保留移入 sqlite_ctx.py + ai_session_tracker.py 删除 + analysis_sessions preload 桥接 | ✅ |
| Q4 | 旧管线/Agent 提示词重叠 + Agent 日志缺失 | 合并+接入日志 | ✅ 已执行：4 个 Agent 模板 + 3 个 Tool 切 PromptManager + llm_adapter 审计日志 + explainCommunity 切模板 + 0-Token 图生成 RPC | ✅ |

---

## 一、现状总览

### 数据库分布

| 数据库文件 | 表数量 | 管理器 |
|-----------|--------|--------|
| `topoone.db` (main) | 18 | `sqlite_ctx.MultiDBManager` |
| `sessions.db` | 3 | `sqlite_ctx.MultiDBManager` |
| `knowledge.db` | 1 | `sqlite_ctx.MultiDBManager` |
| `project.db` (per-project) | 15 | `sqlite_ctx.MultiDBManager` + `store/schema.py` 并行 |

### 存量问题清单

| # | 问题 | 判定 | 状态 |
|---|------|------|------|
| Q1 | `store/schema.py` 表 DDL 重复 | 9 表重复定义，2 条初始化路径 | ✅ 已完成 |
| Q2 | `agent_configs` 表 | 前后端全链路实现但无 UI 组件 | ✅ 已增强 |
| Q3 | `ai_sessions` 系列表（3 表） | 写后即弃，无读取方 | ✅ 已完成 |
| Q4 | 旧管线 vs Agent 系统的 LLM 提示词路径 | 9 个旧模板，Agent 系统全内联硬编码 | ✅ 已完成 |

---

## 二、Q1: `store/schema.py` 表 DDL 重复 — 迁移计划

### 现状

`schema.py` 中 9 张表与 `sqlite_ctx.py` 重复定义：

| 数据库 | 重复的表 |
|--------|---------|
| Main DB | `analysis_tasks`, `analysis_task_runs`, `analysis_reports`, `task_config_history` |
| Project DB | `source_files`, `graph_node`, `graph_edge`, `graph_doc`, `community_hierarchy`, `community_llm_results` |

`schema.py` 独有（`sqlite_ctx.py` 中无）的 5 张表：

| 表 | 活跃调用者 |
|----|-----------|
| `ai_sessions` | `ai_session_tracker.py`（写入） |
| `ai_session_changes` | `ai_session_tracker.py`（写入） |
| `ai_session_issues` | `ai_session_tracker.py`（写入） |
| `cloud_api_config` | `core_service.py` |
| `agent_instructions` | `InstructionManager` |

### 调用路径

```
main_cli.py  ──→  store/connection.py（旧路径）
                    └── store/schema.py  init_main_schema / init_project_schema

主服务       ──→  sqlite_ctx.py（新路径）
                    └── MultiDBManager._init_main_tables / _init_project_tables
```

两条路径互相独立，各自维护 DDL。

### 三步迁移计划

| 步骤 | 操作 | 风险 | 工作量 |
|------|------|------|--------|
| **1** | `main_cli.py` 中将 `from store.connection import SQLiteContext` 改为 `from sqlite_ctx import SQLiteContext`，两个 `SQLiteContext` 接口兼容（`.execute()`/`.fetchone()`/`.fetchall()`/`.commit()`），CLI 路径只读，无行为变化 | 低 | 5 分钟 |
| **2** | 将 `schema.py` 独有的 5 表 DDL（ai_sessions 系列 + cloud_api_config + agent_instructions）合并到 `sqlite_ctx.py` 的 `PROJECT_DB_TABLES_SQL` 中。**先决条件**：确认 `AISessionTracker` 的初始化入口是从 `MultiDBManager.get_project_db()` 获取连接还是独立创建 `SQLiteContext` | 中 | 30 分钟 |
| **3** | 删除 `store/schema.py`，清理 `store/__init__.py` 中的导出引用 | 低 | 5 分钟 |

### 待决策

- 步骤 2 完成后，`AISessionTracker` 使用的 3 张表是否还需要？（见 Q3）
- 如果 Q3 结论是移除 `ai_sessions` 系列，则步骤 2 只需移入 `cloud_api_config` + `agent_instructions` 两张表

---

## 三、Q2: `agent_configs` 表 — 需求评估

### 现状

| 层 | 实现状态 | 文件 |
|----|---------|------|
| DB Schema | ✅ | `sqlite_ctx.py:243-257` |
| 后端 RPC (5 方法) | ✅ | `core_service.py:1202-1261` |
| 类型定义 | ✅ | `src/types/ipc.ts:350-358` |
| IPC 桥接 | ✅ | `preload.ts:304-312` |
| 服务层 | ✅ | `src/services/ipc.ts:435-448` |
| Pinia Store | ✅ | `agent-usage-store.ts:12-41` |
| i18n (中英) | ✅ | `settings.ts` — 两部分完整 |
| **Vue UI 组件** | ❌ **不存在** | `UserPage.vue` 设置页 6 Tab 中无 Agent Tab |

### 功能说明

`agent_configs` 表用于管理用户安装的外部 CLI Agent 工具（qwen-code、cline、opencode、custom）。schema 字段：

```sql
agent_configs (
    id, name, type, path, args, env, status, version,
    is_default, timeout, extra_config, created_at, updated_at
)
```

### 判定

**非当前有效需求范围。** 这是一个前后端全链路已实现但从未暴露 UI 的遗留功能。设计文档标记为 P5（最低优先级）。

### 清理代价预估

| 需移除 | 文件 | 预估行数 |
|--------|------|---------|
| 5 个 RPC 方法 | `core_service.py` | ~60 行 |
| DDL | `sqlite_ctx.py` | ~15 行 |
| 类型 + IPC 接口 | `ipc.ts` | ~30 行 |
| IPC 桥接 | `preload.ts` | ~10 行 |
| 服务层 | `src/services/ipc.ts` | ~15 行 |
| Pinia Store | `agent-usage-store.ts` | ~40 行 |
| i18n | `settings.ts` × 2 | ~30 行 |

**总计: ~200 行**

### 待决策

- 是否有计划集成外部 CLI Agent？如无，是否清理全部关联代码？
- 如果保留（未来可能启用），仅需补充 UI 组件

---

## 四、Q3: `ai_sessions` 系列表 — 多个 Session 管理表并存

### 三套 Session 表全景

| 表 | 数据库 | 内容 | 子表 | 读取方 | 写入方 | 前端连接 |
|----|--------|------|------|--------|--------|---------|
| `llm_sessions` | `sessions.db` | LLM 聊天会话 | `llm_messages` (role/content) | `LLMService` 6 处查询 | `LLMService` 7 处写入 | ✅ `chat.ts` → `CoderPage.vue` |
| `analysis_sessions` | `sessions.db` | 分析任务↔llm_sessions 关联表 | 无 | `LLMService.list_analysis_sessions()` | `LLMService` 2 处写入 | ❌ 类型已定义，preload 未暴露 |
| `ai_sessions` | `topoone.db` | 编码 Agent 文件快照 + 变更追踪 | `ai_session_changes`, `ai_session_issues` | **无** | `AISessionTracker` 4 处写入 | ❌ `SessionPanel.vue` TODO 从未实现 |

### `llm_sessions` — 当前主力

| IPC 方法 | 后端 | 前端调用者 |
|----------|------|-----------|
| `session.list` | `llm_service.py:889` | `chat.ts` → `CoderPage.vue` |
| `session.create` | `llm_service.py:901` | `chat.ts` |
| `session.delete` | `llm_service.py:914` | `chat.ts` |
| `session.clearAll` | `llm_service.py:918` | `chat.ts` |
| `session.getMessages` | `llm_service.py:922` | `chat.ts` |
| `session.addMessage` | `llm_service.py:933` | `chat.ts` |
| `session.deleteMessage` | `llm_service.py:947` | `chat.ts` |
| `session.updateMeta` | `llm_service.py:951` | `chat.ts` |

### `analysis_sessions` — 后端就绪，前端未连接

| IPC 方法 | 后端 | 前端调用者 |
|----------|------|-----------|
| `analysisSession.list` | `llm_service.py:1027` | 无 |
| `analysisSession.create` | `llm_service.py:1055` | 无 |
| `analysisSession.delete` | `llm_service.py:1084` | 无 |

preload.ts 未暴露 `analysisSession.*`，前端 `ipc.ts` 类型已定义但无人呼叫。

### `ai_sessions` — 孤数据（写后即弃）

| 写入操作 | 位置 |
|---------|------|
| `INSERT INTO ai_sessions` | `ai_session_tracker.py:85` |
| `UPDATE ai_sessions SET ended_at=..., status='completed'` | `ai_session_tracker.py:114` |
| `INSERT INTO ai_session_changes` | `ai_session_tracker.py:313` |
| `INSERT INTO ai_session_issues` | `ai_session_tracker.py:325` |

**无 SELECT 查询。无 IPC 方法。无前端消费。**

### 不推荐整合的理由

| 对比 | `ai_sessions` (编码追踪) | `llm_sessions` (对话记录) |
|------|--------------------------|--------------------------|
| 内容 | 文件快照 + 变更列 + 质量评分 | role/content 消息序列 |
| 子表 | `ai_session_changes`, `ai_session_issues` | `llm_messages` |
| 生命周期 | start() → agent 执行 → stop() | create() → 多轮对话 → delete() |
| 数据库 | `topoone.db` | `sessions.db` |
| Schema 列数 | 10 (含 file_snapshot, quality_score) | 7 (含 module_type, metadata) |

不同数据库+不同 Schema+不同生命周期 → 保持分离

### 纯化建议

- **`ai_sessions` 系列 3 表**: 如果编码 Agent 追踪功能无需求，移除 `ai_sessions` + `ai_session_changes` + `ai_session_issues` + `ai_session_tracker.py`（~400 行）
- **`analysis_sessions`**: 需要前端补全 `SessionPanel.vue` 的 TODO 连接，或移除此表
- **`llm_sessions`**: 保持不变，当前主力

### 待决策

1. 编码 Agent 追踪（`AISessionTracker`）是否需要保留？
2. `analysis_sessions` 的前端连接是否需要补全？

---

## 五、Q4: 旧管线 PromptManager 调用路径 vs Agent 系统

### 架构对比

| 路径 | 提示词来源 | LLM 调用方式 |
|------|-----------|-------------|
| **旧管线** | `PromptManager.render(templateId)` → 从 `llm_prompt_templates` 表解析 | `llm.chat({templateId, ...})` → `streaming_chat()` |
| **Agent 系统** | 各 Tool 类内联硬编码 | `service.streaming_chat()` 直接调用 |

### 活跃的旧管线模板（9 个）

| 模板 ID | 调用者（文件:行） | 功能 | Agent 等价物 |
|---------|-------------------|------|-------------|
| `community_analyze` | `community-store.ts:481,539,596`<br>`child-analysis-store.ts:75,112`<br>`SubDocRegenDialog.vue:89`<br>`SubDocViewer.vue:129` | 社区 LLM 分析（名称+摘要+图） | `_AnalyzeCommunityTool` |
| `community_name` | `llmClient.ts:205` | 社区结构化命名 | `_AnalyzeCommunityTool` |
| `diagram_regenerate_mermaid` | `report-store.ts:86` | 用户手动重提 Mermaid 图 | `_GenerateDiagramTool`（0-Token 模板） |
| `diagram_regenerate_plantuml` | `report-store.ts:86` | 用户手动重提 PlantUML 图 | 同上 |
| `regenerate_community_doc` | `report-store.ts:166` | 完整社区文档重新生成 | 无直接等价物 |
| `regenerate_overall_doc` | `report-store.ts:264` | 整体架构文档重新生成 | `_GenerateOverviewTool` |
| `source_explain` | `llmClient.ts:116` | 源码符号功能解释 | **无 Agent 等价物** |
| `edge_explain` | `llmClient.ts:140` | 边关系解释 | **无 Agent 等价物** |
| `src_to_pseudocode` | `llmClient.ts:187` | 源码→伪码翻译 | **无 Agent 等价物** |

### 功能重叠分析

| 旧模板 | Agent 系统覆盖 | 重叠类型 |
|--------|---------------|---------|
| `community_analyze` + `community_name` | `_AnalyzeCommunityTool`（内联提示） | **功能重叠** — 同一个"分析社区"操作，两套提示词 |
| `diagram_regenerate_mermaid/plantuml` | `_GenerateDiagramTool`（0 Token 模板） | **架构重叠** — 旧管线用 LLM 生成图，Agent 系统用模板 |
| `regenerate_overall_doc` | `_GenerateOverviewTool` | **功能重叠** — 同一份"架构概览" |
| `regenerate_community_doc` | 无 | 独立需求 |
| `source_explain` / `edge_explain` / `src_to_pseudocode` | 无 | **独立需求** — Agent 系统不覆盖 |

### Agent 系统的提示词缺失

| 缺失 | Agent 系统现状 | 影响 |
|------|--------------|------|
| Agent LLM 调用不经过 `PromptManager` | 硬编码内联提示词 | 用户无法自定义 Agent 提示词 |
| Agent LLM 调用不记录 `llm_call_logs` | `BudgetTracker` 仅内存计数 | 无调用日志，不可审计 |
| Agent LLM 调用不经过 `InstructionManager` | `agent_instructions` 被忽略 | 用户自定义指令对 Agent 无效 |
| Agent LLM 调用不跟踪 `model_daily_usage` | `BudgetTracker` 仅内存 | 无用量限制 |

### 待决策

1. 哪些旧模板需保留？`source_explain`/`edge_explain`/`src_to_pseudocode` 无 Agent 等价物，是否保留独立？
2. `community_analyze` + `community_name` 是否从旧管线迁移到 Agent 系统？
3. `diagram_regenerate_mermaid/plantuml` 图表再生成为什么还走 LLM 而非 0-Token 模板？
4. Agent 系统的提示词是否应接入 `PromptManager`（用户可配置化）？
5. Agent 系统的 LLM 调用是否应补入 `llm_call_logs` + `model_daily_usage`？

---

## 六、综合处理优先级

| 优先级 | 问题 | 建议 | 预估行数 | 实际状态 |
|--------|------|------|---------|---------|
| **P0** | Q1: `store/schema.py` DDL 重复 | 执行三步迁移 | ~200 删除 | ✅ 完成（steps 1-3 all done） |
| **P0** | Q3: `ai_sessions` 孤数据 | 如果无需求则移除 | ~400 删除 | ✅ 完成（DDL 保留，.py 删除） |
| **P1** | Q2: `agent_configs` 无 UI | 移除全链路 | ~200 删除 | ⚠️ 方向变更（保留+增强） |
| **P1** | Q3: `analysis_sessions` 无前端连接 | 补全或移除 | 待定 | ✅ 完成（preload 桥接 added） |
| **P2** | Q4: 旧管线/Agent 提示词重叠 | 合并到 Agent 系统统一管理 | 架构调整 | ✅ 完成（4 模板 + 3 Tool 切换） |
| **P2** | Q4: Agent 系统日志缺失 | 接入 `llm_call_logs` + `model_daily_usage` | ~80 新增 | ✅ 完成（llm_adapter.py） |

---

## 附录

### A. 已完成的清理（本轮对话中）

| 已移除 | 文件 | 行数 |
|--------|------|------|
| `_find_target_for_import()` | `analyst_runner.py` | ~48 |
| `USE_NEW_PARSER = True` | `analyst_runner.py` | 3 |
| `pipeline-store.ts` | `src/stores/` | 21 |
| `PipelineTaskTree.vue` | `src/components/report/` | 226 |
| `PipelineTaskNode/State/ControlFunctions/Data/Response` 类型 | `src/types/ipc.ts` | ~45 |
| `savePipelineState/loadPipelineState` 全链路 (后端+前端+IPC) | 7 文件 | ~150 |
| `hybrid_resolver.py` + 测试 | `backend-core/` | ~200 |
| `bidirectional_analyzer.py` | `backend-core/` | ~280 |
| `diagram_orchestrator.py` | `backend-core/` | ~370 |
| `analysis_tasks.agent_id` 字段 | `sqlite_ctx.py` + `schema.py` | 2 |
| 22 个未引用提示词模板 | `prompt_templates.json` | ~300 |

### B. `_do_parse()` 重构后架构

```
_do_parse (30行编排器)
  ├── _load_task_context() ── 加载任务配置/Store/Emitter
  ├── _step1_parse_ast(ctx) ── AST解析+符号提取 (5→65%)
  ├── _step2_resolve_references(ctx) ── 跨文件引用解析 (65→72%)
  ├── _step3_extract_imports(ctx) ── 文件依赖提取 (72→74%)
  ├── _step4_synthesize_frameworks(ctx) ── 框架感知+动态合成 (74→77%)
  ├── _step5_detect_communities(ctx) ── Louvain社区分析 (77→99%)
  └── _step6_generate_summary(ctx) ── 结果汇总+报告写入 (99→100%)
```

---

## C. Q4 执行细节（2026-06-13 追加）

### 新增 Agent 提示词模板

| 模板 ID | 用于 | 来源 |
|---------|------|------|
| `agent_analyze_community` | `_AnalyzeCommunityTool` | arch_analyst.py:37-40 硬编码 → 模板化 |
| `agent_generate_overview` | `_GenerateOverviewTool` | arch_analyst.py:130-141 硬编码 → 模板化 |
| `agent_summarize_changes` | `_SummarizeTool` | arch_sentinel.py:156-167 硬编码 → 模板化 |
| `agent_explain_community` | `explainCommunity()` | llmClient.ts:163-171 硬编码 → 模板化 |

### render_prompt 注入链

```
router.py (PromptManager → _render lambda)
  → tool_factory.py (build_analyst_tools / build_sentinel_tools)
    → ArchAnalystWorkflow tools (_AnalyzeCommunityTool, _GenerateOverviewTool)
    → ArchSentinelWorkflow tools (_SummarizeTool)
```

每个 Tool 保持 `else` 兜底（render_prompt=None 时回退到硬编码），确保向后兼容。

### Agent LLM 审计日志

`llm_adapter.py` — 每次 `streaming_chat()` 成功后：
- `LLMService._save_call_log()` → `llm_call_logs`（含 template_id="agent_direct"、estimated=True）
- `LLMService._record_usage()` → `model_daily_usage`
- 失败时同样记录 error 状态日志

### 0-Token 图生成 RPC

`core_service.py:2636` — `report.renderDiagram`（API-114）
- 从 `graph_doc` + `graph_edge` 查询社区结构
- 调用 `_build_mermaid()` / `_build_plantuml()` 返回图代码
- 保留 `diagram_regenerate_mermaid/plantuml` 模板用于用户 LLM 驱动的图修改

---

## D. 遗留项（有意推迟）

| # | 问题 | 原因 | 优先级 |
|---|------|------|--------|
| D1 | Agent 系统忽略 `agent_instructions` | `InstructionManager` 不传 store，暂不影响 | P3 |
| D2 | `cloud_api.py` 纯 stub | 云端功能未实施 | P4 |
| D3 | `agent_configs` 无 Vue UI 组件 | 外部 Agent 执行先走 API/MCP，UI 后续 | P2 |
| D4 | `_ExplainSymbolTool` / `_ExplainEdgeTool` 未创建 | 当前迭代预算用尽，`source_explain`/`edge_explain`/`src_to_pseudocode` 保留在旧管线 llm.chat() 路径（受益于 D3 审计） | P3 |
| D5 | `analysis_sessions` 前端消费 | preload 已桥接，无需 UI（由外部 Agent/MCP 以 API 形式调用） | P3 |

---

## E. 所有改动文件清单

### 已删除（8 文件）

| 文件 | 行数 |
|------|------|
| `backend-core/store/schema.py` | 435 |
| `backend-core/ai_session_tracker.py` | ~355 |
| `backend-core/hybrid_resolver.py` | ~80 |
| `backend-core/bidirectional_analyzer.py` | ~280 |
| `backend-core/diagram_orchestrator.py` | ~370 |
| `backend-core/tests/test_hybrid_resolver.py` | ~50 |
| `src/stores/pipeline-store.ts` | 21 |
| `src/components/report/PipelineTaskTree.vue` | 226 |

### 已修改（15 文件）

| 文件 | 改动类型 |
|------|---------|
| `backend-core/analyst_runner.py` | `_do_parse()` 拆分为 6 步函数 |
| `backend-core/sqlite_ctx.py` | 合并 5 表 DDL + agent_configs type 放宽 + agent_executions 新增 |
| `backend-core/store/connection.py` | 删除死 MultiDBManager + 清理 imports |
| `backend-core/store/__init__.py` | 移除 MultiDBManager 导出 |
| `backend-core/main_cli.py` | import 从 store.connection 切换 sqlite_ctx |
| `backend-core/core_service.py` | executeAgent + renderDiagram + 4 个 agent 执行 RPC |
| `backend-core/task_manager.py` | _build_agent_tools 死代码修正 |
| `backend-core/rpc_ids.py` | 删除 API-108/109 + 新增 API-110~114 |
| `backend-core/mcp_server/dispatcher.py` | 注释修正（ai_session_tracker 引用） |
| `backend-core/config/prompt_templates.json` | +4 Agent 模板 |
| `backend-core/agent_workflow/tool_factory.py` | render_prompt 参数注入 |
| `backend-core/agent_workflow/router.py` | render_prompt 创建 + 传入 |
| `backend-core/agent_workflow/llm_adapter.py` | 审计日志 + 用量追踪 |
| `backend-core/agent_workflow/workflows/arch_analyst.py` | 2 个 Tool 切 PromptManager |
| `backend-core/agent_workflow/workflows/arch_sentinel.py` | 1 个 Tool 切 PromptManager |
| `electron/preload.ts` | analysisSession + renderDiagram 桥接 |
| `src/services/llmClient.ts` | explainCommunity 切模板 |
| `src/services/ipc/settings-service.ts` | 4 个 Agent 执行方法 |
| `src/services/ipc.ts` | Agent 执行 + addAgent type 参数 |
| `src/types/ipc.ts` | AgentExecution 类型 + 删除 Pipeline 类型 + 新 RPC 类型 |
| `src/stores/project.ts` | 移除 pipelineStore 引用 |
