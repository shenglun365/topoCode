# TopoCode-UI 重构审计报告 v2

> 审计日期: 2026-06-05 | 对比基线: `refactoring-audit-report.md` (v1) | 审计范围: 全项目

---

## 一、总体评估: 完成度 v1 62% → v2 78%

| 维 度 | v1 | v2 | Δ |
|--------|----|----|---|
| Phase 0 测试基础设施 | 70% | 85% | +15 |
| Phase 1 P0修复+清理 | 90% | 95% | +5 |
| Phase 2 Query引擎 | 85% | 90% | +5 |
| Phase 3 Stack Graphs | 75% | 80% | +5 |
| Phase 4 前端债务 | 5% | 35% | +30 |
| Phase 5 MCP Server | 60% | 80% | +20 |
| Phase 6 Skills | 70% | 85% | +15 |
| Phase 7 变更感知 | 75% | 85% | +10 |
| **综合** | **62%** | **78%** | **+16** |

---

## 二、上次审计 P0 问题修复情况

### P0-1: 双管线并存 — 未完全解决，但已有控制开关

**当前状态**: `analyst_runner.py:27` 中 `USE_NEW_PARSER = True` 使新管线为默认路径。旧 DFS 代码 (`parser.py` 548行) 保留在每个 `else` 分支中但默认不执行。

| 维度 | v1 | v2 |
|------|----|----|
| 旧管线执行 | 可能同时运行 | 仅在 `USE_NEW_PARSER = False` 时 |
| `extract_node_info()` | 活跃调用 | 保留但不触发 (默认) |
| 数据竞争风险 | 高 | 低 (受开关控制) |

**评级**: B (从 D 提升)。旧代码仍存在但默认不执行。

---

### P0-2: Phase 4 进展 — 从 5% → 35%

| 提升项 | v1 | v2 |
|--------|----|----|
| `community-store.ts` | 519行 | **387行 (-25%)** |
| `useSearchFilter` composable | 不存在 | **31行** ✅ |
| `usePolling` composable | 不存在 | **36行** ✅ |
| `flattenTree.ts` | 不存在 | **37行** ✅ |
| `community.ts` (fmtCommId) | 不存在 | **22行** ✅ |
| `RightPanel.vue` 行数 | ~800+ | **249行** ✅ |
| `RightPanel.vue` 跨层依赖 | 存在 | **已清理** ✅ |
| Wrapper 文件 | `report.ts` + `settings.ts` | **已删除** ✅ |
| 空目录 (4个) | 存在 | **已删除** ✅ |
| `statusBadge.ts` 被导入 | 0 个组件 | **3 个组件** ✅ |
| `any` 类型 | 539 | **329 (-39%)** |
| `console.*` | 86 | **24 (-72%)** |
| 空 catch 块 | 6 | **3 (-50%)** |

**仍 未完成**:

| 项目 | 当前状态 |
|------|----------|
| `model-store.ts` 拆分 | 137行, 5实体混合 (未变) |
| `report-store.ts` IPC 迁移 | `listCommunityResults`/`getCascadeLevels`/`saveCommunityResult` 仍在 report-store |
| `project.ts` 导入工作流拆分 | `importProject` 仍在 project.ts, 且存在重复 import (line 10/16) |
| `theme.ts` DOM 迁移 | `document.documentElement` + `localStorage` 仍在 store 内 |
| `debug.ts` 副作用延迟 | `addLogHandler` 仍在 store 初始化时执行 |
| `SubDocViewer.vue` | **1112行 (+152)** |
| `ModelConfig.vue` | **1200行 (+292)** |
| `ReportHome.vue` | 977行 (几乎未变) |
| `ProjectCard.vue` | 859行 (未变) |
| Post-process 逻辑 | 缺失 (仅 `result_compressor.py` 有函数, skill_executor 未集成) |

**评级**: C+ (从 F 提升, 但核心拆分未执行)

---

### P0-3: MCP Server ZMQ — 部分实现

**当前状态**: ZMQ 客户端代码已实现 (`zmq_client.py`), 但 `__main__.py` 默认使用直接库调用 (port=0)。ZMQ 通过 `--zmq-dealer-port > 0` 参数可选启用。

**评级**: B (从 C 提升, ZMQ 可用但非默认)

---

### P0-4: 快照挂载 — 部分实现

**当前状态**: `SnapshotStore` 在 `analyst_runner.py:561` 中实例化用于分析管线, 但在 MCP Server 的 `__main__.py` 中未传入 `ToolDispatcher`。MCP 变更 Tool 调用时会返回错误 "Change tracking requires SnapshotStore"。

**评级**: C (从 F 提升, 后端可存快照但 MCP 不可访问)

---

### P0-5: vue-tsc 版本 — 已解决 ✅

`vue-tsc: 2.2.12` (从 1.8.27), 与 `typescript: 5.9.3` 兼容。

**评级**: A

---

### P0-6: CI 配置 — 存在但有缺陷

CI 文件存在 (`.github/workflows/ci.yml`, 58行), 但 `vue-tsc`/`eslint`/`pytest` 步骤使用 `|| true` 静默忽略所有失败。

**评级**: C (从 F 提升, 但 `|| true` 使门禁形同虚设)

---

## 三、上次审计 P1 问题修复情况 (全部完成 ✅)

| # | 问题 | v1 | v2 |
|---|------|----|----|
| P1-1 | 兼容性 wrapper | 存在 (`report.ts`/`settings.ts`) | ✅ 已删除 |
| P1-2 | 空目录 (4个) | `handlers/`/`repositories/`/`services/`/`main/` | ✅ 已删除 |
| P1-3 | `statusBadge.ts` 被 0 个组件导入 | 7 组件各自实现 | ✅ 3 个组件导入 |
| P1-4 | `snapshot_symbols` 表 | JSON blob | ✅ 标准化表 + 索引 |
| P1-5 | NetworkX 图融合 | 未实现 | ✅ `symbol_graph.py` 引入 `networkx` |
| P1-6 | `result_compressor.py` | 不存在 | ✅ 83行 |
| P1-7 | MCP 文件 (3个) | 不存在 | ✅ 全部存在 |

---

## 四、上次审计 P2 问题修复情况 (5/8 完成)

| # | 问题 | v1 | v2 |
|---|------|----|----|
| P2-1 | console.log/error | 86 | ✅ **24** |
| P2-2 | `any` 类型 | 539 | ⚠️ **329** (-39%, 仍未达标) |
| P2-3 | 空 catch 块 | 6 | ⚠️ **3** (UserPage:47, StatusBar:29, TemplateManager:174) |
| P2-4 | Pixi ticker 泄漏 | 存在 | ✅ 已修复 (`_tickers` 追踪 + `destroy` 清理) |
| P2-5 | relayout hack | 存在 | ✅ 已消除 |
| P2-6 | Post-process 逻辑 | 缺失 | ⚠️ `result_compressor.py` 有函数但 `skill_executor` 未集成 |
| P2-7 | version_store 并发控制 | 无 | ⚠️ 未评估变化 (需确认) |
| P2-8 | pytest.ini | 缺失 | ✅ 存在 (9行), `pyproject.toml` 仍缺失 |

---

## 五、各文件行数变化总览

### 正面变化 (缩小/删除)

| 文件 | v1 | v2 | Δ |
|------|----|----|---|
| `community-store.ts` | 519 | 387 | -132 |
| `RightPanel.vue` | ~800 | 249 | -550 |
| `report.ts` (wrapper) | 16 | **删除** | -16 |
| `settings.ts` (wrapper) | 10 | **删除** | -10 |
| `handlers/` `repositories/` `services/` `main/` | 4 空目录 | **删除** | -4 目录 |

### 负面变化 (增大)

| 文件 | v1 | v2 | Δ | 原因 |
|------|----|----|---|------|
| `SubDocViewer.vue` | 960 | **1112** | +152 | 未拆分, 功能累加 |
| `ModelConfig.vue` | 908 | **1200** | +292 | 未拆分, 功能累加 |

### 新增文件

| 文件 | 行数 | 用途 |
|------|------|------|
| `useSearchFilter.ts` | 31 | 搜索过滤 composable |
| `usePolling.ts` | 36 | 轮询 composable |
| `flattenTree.ts` | 37 | 树扁平化工具 |
| `community.ts` | 22 | 社区ID格式化 |
| `result_compressor.py` | 83 | 结果压缩 |
| `zmq_client.py` | ~80 | MCP ZMQ 客户端 |
| `pytest.ini` | 9 | Python 测试配置 |
| `.github/workflows/ci.yml` | 58 | CI 配置 |
| `electron/mcp-manager.ts` | 116 | MCP 子进程管理 |
| `MCPSettings.vue` | 179 | MCP 控制面板 |
| `mcp-store.ts` | 49 | MCP 状态管理 |
| `symbol_graph.py` | ~80 | NetworkX 图融合 |

---

## 六、当前问题清单 (按严重度)

### 🔴 仍阻塞 (2项)

| # | 问题 | 详情 |
|---|------|------|
| B1 | CI 使用 `|| true` 静默忽略所有质量门禁 | `vue-tsc`/`eslint`/`pytest` 失败不会阻止合并 |
| B2 | MCP 变更 Tool 运行时返回错误 | `__main__.py` 未传入 `SnapshotStore`, `get_changes`/`evaluate_change` 等无法工作 |

### 🟠 高优先级 (5项)

| # | 问题 | 详情 |
|---|------|------|
| H1 | `project.ts` 存在重复 import | `useAnalysisStore` 在第 10 行和第 16 行各导入一次 |
| H2 | `theme.ts` DOM 操作仍在 store 中 | `document.documentElement.setAttribute` 等 4 处 |
| H3 | `debug.ts` 副作用未延迟 | `addLogHandler` 在 store 初始化时执行 |
| H4 | `model-store.ts` 5 实体混合 | Models/Agents/Skills/Bindings/UsageStats 同在一文件 |
| H5 | `report-store.ts` 仍含 analysis IPC | `listCommunityResults`/`getCascadeLevels`/`saveCommunityResult` |

### 🟡 中优先级 (5项)

| # | 问题 | 详情 |
|---|------|------|
| M1 | `SubDocViewer.vue` 继续膨胀 (1112行) | 自定义 Markdown 渲染 + 图再生 + 文档CRUD |
| M2 | `ModelConfig.vue` 继续膨胀 (1200行) | 模型CRUD + 用量统计 + 用量限制 |
| M3 | `any` 类型 329 处 | 目标 ≤200 |
| M4 | 3 个空 catch 块 | `UserPage:47`, `StatusBar:29`, `TemplateManager:174` |
| M5 | `skill_executor.py` 未集成 `result_compressor` | Post-process 逻辑可调用但未在 Skill 步骤中使用 |

### 🟢 低优先级 (2项)

| # | 问题 |
|---|------|
| L1 | `pyproject.toml` 仍缺失 (pytest.ini 已存在, 可接受) |
| L2 | CI 中后端测试目录重复执行两次 (ci.yml:55,58) |

---

## 七、架构整洁度评估

| 维度 | v1 | v2 | 评语 |
|------|----|----|------|
| 兼容性补丁 | D (2个wrapper) | **A** (已删除) | Clean |
| 空目录 | D (4个) | **A** (0个) | Clean |
| 双管线 | D (同时运行) | **B** (开关控制) | 旧代码仍存在但默认不执行 |
| Store 大小 | C (519行 max) | **B** (387行 max) | 改善但核心拆分未完成 |
| 组件大小 | C (981行 max) | **C** (1200行 max) | 恶化 (2组件膨胀) |
| 代码重复 | D (7组件重复) | **B** (3组件统一) | statusBadge 已统一, useSearchFilter/usePolling 已提取 |
| 类型安全 | D (539 any) | **C** (329 any) | 改善但 window-api.ts 仍是主要来源 |
| 测试覆盖 | D (0前端测试) | **B** (7前端+12后端) | 显著改善 |
| CI/CD | F (无) | **C** (有但 `\|\| true`) | 存在但门禁虚设 |

---

## 八、结论与建议

**v1 → v2 提升 +16 个百分点 (62%→78%)**。本轮修复集中在清理性工作: 删除 wrapper/空目录、新增 composables/utils、修复已知 bug (ticker泄漏/null-toggle)、建立 CI/CD。但**核心架构拆分 (Phase 4) 仍未执行**。

### 立即行动 (1天)

1. B1: 移除 CI 中的 `|| true`, 使 `vue-tsc`/`eslint`/`pytest` 失败能阻止合并
2. B2: 在 `__main__.py` 中传入 `SnapshotStore` 给 `ToolDispatcher`
3. H1: 删除 `project.ts` 中的重复 import

### 短期行动 (3-5天)

4. H2/H3: 将 `theme.ts` DOM 操作移至 `useThemeEngine` composable; `debug.ts` 副作用延迟到 `onMounted`
5. H4: 拆分 `model-store.ts` 为 2 个 store (model-config + agent-usage)
6. H5: 将 `report-store.ts` 中 3 个 analysis IPC 迁移到 `community-store`
7. M1/M2: 拆分 `SubDocViewer.vue` (抽出 useMarkdownRenderer + DiagramsPanel), `ModelConfig.vue` (抽出 UsageStatsPanel)

### 中期行动 (3-5天)

8. M5: `skill_executor.py` 集成 `result_compressor.py` 的 `limit_top_5`/`filter_by_range`
9. M3: 逐步替换 `window-api.ts` 中的 `any` 为具体类型
10. 删除旧 DFS 代码 (parser.py 的 else 分支) 当新管线稳定运行足够时间后
