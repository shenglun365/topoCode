# TopoCode-UI 重构完成度审计报告

> 审计日期: 2026-06-05 | 基线: `docs/refactoring-plan-v3.md` (8项决策版) | 审计范围: 全项目

---

## 一、逐 Phase 评估

### Phase 0: 测试基础设施 (目标 1天) —— 完成度 70%

| 任务 | 状态 | 证据 |
|------|------|------|
| T1 vue-tsc 修复 | ⚠️ | `vue-tsc@1.8.27` 与 `typescript@5.9.3` 版本不兼容, `npm run type-check` 可能崩溃 |
| T2 vitest 配置 | ✅ | `vitest.config.ts` 存在, 7 个 `.test.ts` 文件 |
| T3 工具函数测试 | ✅ | `tests/unit/utils/` 含 fileColors/time/logger/statusBadge 4 组测试 |
| T4 composable 测试 | ❌ | 无 composable 测试文件 |
| T5 pytest 配置 | ❌ | 无 `pytest.ini` / `pyproject.toml` / `setup.cfg` |
| T6 数据模型测试 | ✅ | `backend-core/tests/` 含 12 个 test_*.py (change_model, diff_engine, snapshot_store 等) |
| T7 CI 集成 | ❌ | 无 `.github/workflows/`, 无任何 CI 配置文件 |

**关键遗漏**: pytest 配置文件缺失导致 `pytest backend-core/tests/` 无法通过标准方式运行。

---

### Phase 1: P0修复 + 后端清理 (目标 3天) —— 完成度 90%

| 任务 | 状态 | 证据 |
|------|------|------|
| P0-3 PlantUML IPC 路径 | ✅ | `usePlantUmlRender.ts:33` → `api.render.renderPlantuml` |
| P0-2 类型统一 | ✅ | `KnowledgeDoc` 两个文件均使用 `tags`, 字段完全一致 |
| P0-4 死代码回调数组 | ✅ | `taskProgressCbs`/`backendStatusCbs` 已删除 |
| P1-1 死导入移除 | ✅ | `project.ts` 中 `useSettingsStore` 导入已移除 |
| B1 backend/ 删除 | ✅ | 目录不存在, 仅 `backend-core/` 保留 |
| B2 backup/ 删除 | ✅ | 目录不存在 |
| B3 tmp-module-build/ | ✅ | 目录不存在 |

**剩余问题**: `console.log/error` 从 110 → 86 (-22%), 但仍未达预期 (<30)。`CommunityAnalysisPipeline.vue` (14处) 和 `OnboardingTour.vue` (8处) 是主要残留。

---

### Phase 2: Tree-sitter Query + Symbol 模型 (目标 6天) —— 完成度 85%

| 任务 | 状态 | 证据 |
|------|------|------|
| `.scm` Query 文件 | ✅ | 30 个文件, 覆盖 10 种语言 (C/C++/C#/Go/Java/JS/Python/Rust/Swift/TS) |
| `query_loader.py` | ✅ | 121 行, `QueryLoader` + `QuerySet` + `run_query()` |
| `symbol_model.py` | ✅ | 126 行, `Symbol`/`Reference`/`FileSymbolTable` + 5 个枚举 |
| `binder.py` | ✅ | 213 行, `SimpleBinder` + 作用域链 + 跨文件导入解析 |
| `parse_with_queries.py` (新管线) | ✅ | 482 行, 完整可用的 Query 驱动解析管线 |
| `extract_node_info()` 迁移 | ❌ | **`parser.py` 的 DFS 遍历未迁移**, `extract_call_graph.py` 和 `extract_global_symbols.py` 中有注释标注"新 pipeline 已处理"但旧代码路径仍在运行 |

**架构债务**: `parser.py` (548行, 旧 DFS) 和 `parse_with_queries.py` (482行, 新 Query) **两个管线并存**。`file_visitor.py` 使用新管线 (`_build_symbol_table`/`_persist_table`), 但 `extract_call_graph.py` 和 `extract_global_symbols.py` 中的注释暗示旧管线仍在被调用——形成"新代码写数据, 旧代码读数据"的脆弱耦合。

---

### Phase 3: Stack Graphs + HybridResolver (目标 3.5天) —— 完成度 75%

| 任务 | 状态 | 证据 |
|------|------|------|
| `stack_graphs_service.py` | ✅ | 200 行, `shutil.which` 检测 + 优雅降级 |
| `hybrid_resolver.py` | ✅ | 113 行, Tier1(SimpleBinder) → Tier2(StackGraphs) 两级路由 |
| 融合 NetworkX 图 | ❌ | **未实现**。`HybridResolver.resolve()` 返回单个结果, 不构建合并图 |

---

### Phase 4: 前端架构债务清理 (目标 7.5天) —— 完成度 5%

| 任务 | 状态 |
|------|------|
| ✅ `project.ts` tab 方法 `@deprecated` 标注 | **唯一完成项** |
| ❌ `community-store.ts` 拆分 (519行) | 未拆分 |
| ❌ `model-store.ts` 拆分 (137行, 5 实体) | 未拆分 |
| ❌ `report-store.ts` IPC 迁移 (4 个 analysis IPC) | 未迁移 |
| ❌ `project.ts` 导入工作流拆分 | 未拆分 (`importProject` 仍在 project.ts) |
| ❌ `theme.ts` DOM 操作迁移 | 未迁移 (4 处 `document.documentElement` + `localStorage`) |
| ❌ `debug.ts` 副作用延迟 | 未延迟 (`addLogHandler` 在模块顶级执行) |
| ❌ `useSearchFilter` composable | 不存在 |
| ❌ `usePolling` composable | 不存在 |
| ❌ `utils/flattenTree.ts` | 不存在 |
| ❌ `utils/community.ts` (fmtCommId) | 不存在 |
| ❌ 状态徽章统一 (7文件12重复) | `statusBadge.ts` 存在但**被 0 个 .vue 文件导入** |
| ❌ `SubDocViewer.vue` 拆分 (960行) | 未拆分 |
| ❌ `ReportHome.vue` 拆分 (981行) | 未拆分 |
| ❌ `ModelConfig.vue` 拆分 (908行) | 未拆分 |
| ❌ `ProjectCard.vue` 拆分 (859行) | 未拆分 |
| ❌ `shell/RightPanel.vue` 跨层解耦 | 未解耦 (直接访问 `projectStore.activeTab?.kind`) |
| ❌ 空 catch 块填充 | 6 个空 catch 块留存 |
| ❌ `any` 类型替换 | **539 处** (`window-api.ts` 独占 129) |
| ❌ `window-api.ts` 类型补齐 | `IpcCall = (...args: any[]) => Promise<any>` 未改动 |
| ❌ `usePixiCanvas.ts` ticker 泄漏 | 未修复 |
| ❌ `useD3Graph`/`useMermaidRender` 重布局 hack | 未修复 |

**Phase 4 是最大的失败点**。21 项任务仅完成 1 项。主要原因可能是后端 Phase 2/3/5/6/7 耗费了大量精力, 前端债务清理被推迟。

---

### Phase 5: MCP Server (目标 5天) —— 完成度 60%

| 任务 | 状态 | 证据 |
|------|------|------|
| `backend-core/mcp_server/` 目录 | ✅ | 8 个文件, 1197 行 |
| `server.py` (MCPServer) | ✅ | 139 行, stdio JSON-RPC |
| `tools.py` (11 Tool) | ✅ | 全部 11 个 Tool 已定义 |
| `dispatcher.py` (ToolDispatcher) | ✅ | 442 行, 全部 11 个 Handler |
| ZMQ 通信 | ❌ | `__main__.py` 使用 `port=0 = direct library calls`, **决策2(独立+ZMQ)未实施** |
| `electron/mcp-manager.ts` | ❌ | 文件不存在 |
| `MCPSettings.vue` | ❌ | 文件不存在 |
| `mcp-store.ts` | ❌ | 文件不存在 |

**关键偏离**: 决策2 明确要求 MCP Server 通过 ZMQ 独立进程通信, 但当前 `__main__.py` 使用直接库调用 (`port=0`), 违背了架构决策。

---

### Phase 6: Skills (目标 4天) —— 完成度 70%

| 任务 | 状态 | 证据 |
|------|------|------|
| `skills.py` (Skill 定义) | ✅ | 7 个 Skill (含 assess_merge_impact + review_refactoring) |
| `skill_executor.py` (SkillExecutor) | ✅ | 87 行, Token Budget 控制 |
| `result_compressor.py` | ❌ | 文件不存在 |
| Post-process 逻辑 | ❌ | `limit_top_5`/`filter_by_range`/`invoke_llm_doc_gen` 未实现 |
| 路径安全校验 | ✅ | `path_validator.py` 40 行 |

---

### Phase 7: 变更感知 (目标 5天) —— 完成度 75%

| 任务 | 状态 | 证据 |
|------|------|------|
| `change_tracker/` 目录 | ✅ | 6 个文件, 625 行 |
| `change_model.py` | ✅ | 4 个核心类 (Snapshot/ChangeReport/SymbolChange/Summary) |
| `snapshot_store.py` | ⚠️ | 实现存在但符号存为 JSON blob, 未使用标准化的 `snapshot_symbols` 表 |
| `diff_engine.py` | ✅ | 192 行, 四维 diff |
| `git_adapter.py` | ✅ | 108 行 |
| `impact_analyzer.py` | ✅ | 76 行 |
| 前端 7 个变更组件 | ✅ | `ChangeTimeline`/`ChangeImpactGraph`/`ChangeDashboard` 等全部存在 |
| `change-store.ts` | ✅ | 175 行 |
| 生产环境 wiring | ❌ | `SnapshotStore` 未在 `__main__.py` 中实例化, 快照不会自动生成 |

---

## 二、逐 Phase 评分汇总

| Phase | 完成度 | 评分 | 评语 |
|-------|--------|------|------|
| Phase 0 | 70% | C+ | 测试框架存在但缺 pytest 配置和 CI, vue-tsc 版本不兼容 |
| Phase 1 | 90% | A- | P0 全部清零, console.log 残留 86 处 |
| Phase 2 | 85% | B+ | Query 管线完整但旧 parser.py 未迁移, 双管线共存 |
| Phase 3 | 75% | B | HybridResolver 两级路由正确但 NetworkX 图融合未实现 |
| Phase 4 | **5%** | **F** | 21 项仅完成 1 项, 前端债务完全未清 |
| Phase 5 | 60% | C | 核心代码存在但 ZMQ 通信偏离决策, Electron 集成缺失 |
| Phase 6 | 70% | B- | Skills 框架完整但后处理逻辑和压缩器缺失 |
| Phase 7 | 75% | B | 后端模型完整, 前端组件完整, 但生产环境 wiring 缺失 |
| **综合** | **~62%** | **C+** | 后端管线升级成功 (Phase 2/3), MCP/变更框架可运行 (Phase 5/6/7), 但 Phase 4 (前端债务) 完全未执行 |

---

## 三、架构整洁度审计

### 3.1 兼容性补丁/Wrapper

| 文件 | 行数 | 性质 | 建议 |
|------|------|------|------|
| `src/stores/report.ts` | 16 | 向后兼容 re-export wrapper (report-store → useReportStore) | **删除**。Phase 3 拆分已完成, 无组件仍依赖此 wrapper |
| `src/stores/settings.ts` | 10 | 向后兼容 re-export wrapper (settings-store → useSettingsStore) | **删除**。同上 |

两个文件标记为 "Phase 3 backward-compat wrapper", 违反了"无兼容性补丁"的整洁度要求。

### 3.2 死代码/未使用代码

| 位置 | 问题 |
|------|------|
| `src/utils/statusBadge.ts` (50行) | **被 0 个 .vue 文件导入**。7 个组件各自重新实现了相同的状态映射逻辑 |
| `src/main/` | **空目录** (0 个文件) |
| `backend-core/handlers/` | **空目录** |
| `backend-core/repositories/` | **空目录** |
| `backend-core/services/` | **空目录** |
| `parser.py` 中的 `extract_node_info()` | 与新管线 `parse_with_queries.py` 功能重复, 但仍在被调用 |

### 3.3 双管线架构 (最大架构债务)

```
旧管线: parser.py → extract_node_info() [DFS]
                     → extract_global_symbols() [已标注"新管线已处理"]
                     → extract_call_graph()     [已标注"新管线已处理"]
                     
新管线: file_visitor.py → parse_with_queries.py [Query引擎]
                        → _build_symbol_table()
                        → _persist_table()
```

`extract_global_symbols.py:250` 和 `extract_call_graph.py:368` 明确注释"新 pipeline 已将数据写入", 但这些函数仍在被调用——运行时会先执行新管线写入, 再执行旧管线重复处理。这构成了 **"双写"风险**: 同一符号被两个管线以不同格式写入 `graph_node` 表, 可能导致数据不一致。

---

## 四、完整度审计

### 4.1 计划偏离项

| 决策编号 | 决策内容 | 实际实施 | 偏差 |
|----------|----------|----------|------|
| 决策 2 | MCP Server 通过 ZMQ 独立进程 | `__main__.py` 使用直接库调用 (port=0) | **严重偏离** |
| 决策 4 | `snapshot_symbols` 独立标准化表 | 符号存为 JSON blob 在 `snapshots` 表内 | **偏离** |
| 决策 5 | `extract_node_info()` 迁移到 Query 引擎 | 旧 `parser.py` 未迁移, 新管线作为独立路径 | **未完成** |

### 4.2 遗漏项清单

| 类别 | 遗漏项 | 影响 |
|------|--------|------|
| 测试 | 无 `pytest.ini`/`pyproject.toml` | Python 测试不可标准运行 |
| 测试 | vue-tsc@1.8.27 vs typescript@5.9.3 | `npm run type-check` 崩溃 |
| 测试 | 无 CI 配置 | 无自动化质量门禁 |
| MCP | `electron/mcp-manager.ts` 缺失 | Electron 无法管理 MCP Server 生命周期 |
| MCP | `MCPSettings.vue` 缺失 | 用户无法在 UI 中控制 MCP Server |
| MCP | `mcp-store.ts` 缺失 | 前端无法跟踪 MCP Server 状态 |
| Skills | `result_compressor.py` 缺失 | 大量结果可能超出 Agent token 限制 |
| Skills | Post-process 逻辑缺失 | 引用截断/范围过滤/LLM文档生成不可用 |
| 变更 | `SnapshotStore` 未挂载到生产流程 | 快照永远不会自动生成 |
| 变更 | ZMQ 通信未实现 | MCP Server 与主后端解耦未达成 |
| 前端 | 21 项 Phase 4 任务未完成 | Store/组件/composable 债务完全保留 |

---

## 五、健壮性审计

### 5.1 错误处理

| 文件 | 问题 | 风险级别 |
|------|------|----------|
| `src/components/shell/AppShell.vue:44,50` | 空 catch 块吞掉后端健康检查错误 | 中 |
| `src/components/shell/StatusBar.vue:30` | 空 catch 块吞掉模型状态错误 | 低 |
| `src/components/shell/TopBar.vue:43,54` | 空 catch 块吞掉窗口控制错误 | 低 |
| `src/pages/UserPage.vue:60` | 空 catch 块吞掉页面切换错误 | 低 |
| `src/components/project/HomeTabBar.vue:117` | 空 catch 块吞掉 tab 拖拽错误 | 低 |
| `src/components/settings/TemplateManager.vue:174` | 空 catch 块吞掉模板恢复错误 | 低 |
| `version_store.py` | `save_snapshot()` 中的 JSON 序列化无异常处理 | 中 |
| `version_store.py` | 无并发控制——多线程分析可能同时写 DB | 高 |

### 5.2 安全

| 检查项 | 状态 |
|--------|------|
| Electron `nodeIntegration` | `false` (正确) |
| Preload `contextIsolation` | `true` (正确) |
| `env:get` 白名单 | 仅 3 个变量 (正确) |
| `fs:add-allowed-dir` 路径遍历 | `path.relative()` 检查 (正确) |
| `shell:open-external` URL 验证 | `http:`/`https:` 白名单 (正确) |
| MCP Server `path_validator.py` | 路径遍历防护 (正确) |
| MCP Server 文件内容暴露 | 仅返回符号元数据, 不返回完整文件 (正确) |

安全层面**无明显问题**。

### 5.3 可扩展性

| 能力 | 状态 |
|------|------|
| Plugin 系统 (parsers/community/reports/llm-providers) | ✅ 完整 |
| `.scm` Query 文件扩展 (新语言) | ✅ 只需添加 queries/{lang}/ 目录 |
| MCP Tool 扩展 (新增 Tool) | ✅ `CORE_TOOLS` 列表追加 + Handler |
| Skill 扩展 (新增 Skill) | ✅ `SkillRegistry` 注册 |
| 变更分析扩展 (新增 diff 维度) | ✅ `DiffEngine` 新方法 |

可扩展性架构**设计正确**。

### 5.4 稳定性风险

| 风险 | 严重度 |
|------|--------|
| **双管线数据竞争**: `parser.py` (DFS) 与 `parse_with_queries.py` (Query) 并发写入 `graph_node` 表 | 高 |
| **MCP Server 耦合**: 直接库调用而非 ZMQ, MCP Server 崩溃会带走主后端 | 中 |
| **变更快照未 wiring**: 所有变更分析代码可运行但**永远不会被触发** | 高 |
| **vue-tsc 崩溃**: 类型检查不可用, 重构回归风险增大 | 中 |

---

## 六、问题清单 (按严重度排序)

### 🔴 P0 — 阻塞问题

| # | 问题 | 位置 | 修复建议 |
|---|------|------|----------|
| P0-1 | **双管线并存** — `parser.py` DFS 和 `parse_with_queries.py` Query 同时写入 `graph_node` | `plugins/parsers/parsers/parser.py`, `parse_with_queries.py` | 删除 `parser.py` 中 Step 2-4 部分, 仅保留 Query 管线作为唯一路径 |
| P0-2 | **Phase 4 完全未执行** — 21 项前端债务 retained | `stores/`, `components/`, `composables/` | 需单独排期执行 Phase 4 |
| P0-3 | **MCP Server 偏离架构决策** — 直接库调用而非 ZMQ | `backend-core/mcp_server/__main__.py:38` | 实现 ZMQ DEALER 连接, 改为独立进程通信 |
| P0-4 | **变更快照未挂载生产** — `SnapshotStore` 不自动触发 | `backend-core/mcp_server/__main__.py` | 在分析完成回调中加入 `snapshot_store.save()` |
| P0-5 | **vue-tsc 版本不兼容** | `package.json:91` | 升级 `vue-tsc` 到 `^2.0` 或降级 `typescript` |
| P0-6 | **无 CI 配置** | 项目根 | 创建 `.github/workflows/ci.yml` |

### 🟠 P1 — 高优先级

| # | 问题 | 位置 |
|---|------|------|
| P1-1 | 兼容性 wrapper 未删除 (`report.ts`/`settings.ts`) | `src/stores/report.ts`, `src/stores/settings.ts` |
| P1-2 | 4 个空目录 (`handlers/`/`repositories/`/`services/`/`main/`) | `backend-core/`, `src/` |
| P1-3 | `statusBadge.ts` 被 0 个组件导入, 7 组件重复实现 | 7 个 .vue 文件 |
| P1-4 | `snapshot_symbols` 标准化表未实现 (符号存 JSON blob) | `backend-core/change_tracker/snapshot_store.py` |
| P1-5 | NetworkX 图融合未实现 | Phase 3 计划 |
| P1-6 | `result_compressor.py` 缺失 | Phase 6 计划 |
| P1-7 | electron `mcp-manager.ts` + `MCPSettings.vue` + `mcp-store.ts` 缺失 | `electron/`, `src/` |

### 🟡 P2 — 中优先级

| # | 问题 | 位置 |
|---|------|------|
| P2-1 | 86 处 `console.log/error` 残留 | 主要 `CommunityAnalysisPipeline.vue`(14) + `OnboardingTour.vue`(8) |
| P2-2 | 539 处 `any` 类型 (`window-api.ts` 129) | `src/` |
| P2-3 | 6 个空 catch 块 | `AppShell.vue`, `StatusBar.vue` 等 |
| P2-4 | `usePixiCanvas.ts` ticker 泄漏 | `src/composables/usePixiCanvas.ts` |
| P2-5 | `useD3Graph`/`useMermaidRender` 重布局 hack | `src/composables/` |
| P2-6 | Post-process 逻辑未实现 | `backend-core/mcp_server/skill_executor.py` |
| P2-7 | `version_store.py` 无并发控制 | `backend-core/change_tracker/snapshot_store.py` |
| P2-8 | 无 `pytest.ini` | `backend-core/` |

---

## 七、建议优先修复顺序

```
第一优先级 (阻塞, 1-2天):
  1. P0-1 删除旧 parser.py 的 Step 2-4, 统一为 Query 管线
  2. P0-3 MCP Server 改为 ZMQ 连接 (实现决策2)
  3. P0-4 挂载 SnapshotStore 到分析完成回调
  4. P0-5 升级 vue-tsc

第二优先级 (架构整洁, 2-3天):
  5. P1-1 删除 wrapper 文件, 更新所有导入路径
  6. P1-2 删除 4 个空目录
  7. P1-3 7 组件统一使用 statusBadge.ts
  8. P0-6 添加 CI 配置

第三优先级 (Phase 4 前端债务, 7-8天):
  9. Store 拆分 (community-store, model-store, report-store, project.ts)
  10. Composable 提取 (useSearchFilter, usePolling, flattenTree, community)
  11. 大组件拆分 (SubDocViewer, ReportHome, ModelConfig, ProjectCard)

第四优先级 (完善, 3-5天):
  12. P1-4 实现 snapshot_symbols 标准化表
  13. P1-6 实现 result_compressor.py
  14. P1-7 实现 electron MCP 管理层 + 前端 UI
  15. P1-5 NetworkX 图融合
  16. P2-(1-8) 各项代码质量修复

总工时: ~12-18 天
```

---

## 八、审计结论

**重构完成度 ~62%**。后端架构升级 (Phase 2/3) 和新增能力 (Phase 5/6/7) 执行质量较高, 架构设计正确。但存在三个严重问题:

1. **Phase 4 前端债务完全未清** (5%), 导致 `any` 泛滥 (539处)、组件巨型化 (4 个 850+ 行组件)、Store 臃肿等 v2 报告中的问题全部留存。

2. **双管线并存**是最大技术债务——`parser.py` 旧 DFS 和 `parse_with_queries.py` 新 Query 同时运行, 构成数据竞争风险。

3. **MCP Server 架构偏离决策**——直接库调用而非 ZMQ 独立进程, 违背了"解耦"和"可独立重启"的设计目标。

建议立即执行第一优先级修复 (1-2天), 随后单独为 Phase 4 排期一个迭代 (7-8天) 清偿前端债务。
