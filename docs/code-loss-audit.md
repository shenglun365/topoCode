# TopoCode-UI 代码丢失审计报告

> 审计日期: 2026-06-05 | 触发原因: 其他会话误操作导致部分修改进度丢失 | 仅分析, 不修改

---

## 一、执行摘要

**丢失范围**: 主要集中在前端 Store 拆分的消费者更新。组件拆分文件 (SubDocContent, CommunitySection 等) 本体存在，但父组件 (SubDocViewer, ReportHome) 的部分精简被回退。

**总 type-check 错误数: 450** (正常应为 ~13)。

---

## 二、严重问题 (CRITICAL — 4项)

### C1: `src/stores/settings.ts` 未删除 — Store ID 冲突

**文件**: `src/stores/settings.ts` (349行)

该文件是 H4 拆分前的老版本 `useSettingsStore`，包含 `models`/`agents`/`skills`/`bindings`/`usageStats` 全部状态和操作。Pinia store ID 为 `'settings'`。

而 `src/stores/settings-store.ts` (107行) 是拆分后的新版，仅含 UI 偏好 (locale/fontSize/restartBackend 等)，Pinia store ID 也是 `'settings'`。

**两个文件共享同一个 Pinia ID `'settings'`，运行时其中一个会静默覆盖另一个。** 根据文件加载顺序，老文件 (349行) 先被 import 并注册 `'settings'` store，新文件后注册时 Pinia 会报 warning 但仍使用第一个。

**影响**: 所有消费 `useSettingsStore` 的代码可能拿到错误的 store 实例。

---

### C2: 11 个消费者的 Store 引用回归

**H4 拆分完成时**，以下文件已从 `settingsStore.models` 改为 `modelConfigStore.models`:

| 文件 | 当前状态 | 问题 |
|------|----------|------|
| `src/App.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models` 不存在 |
| `src/pages/UserPage.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models.length` 不存在 |
| `src/components/shell/StatusBar.vue` | `useSettingsStore` from `settings-store` | `settings.models` 不存在 |
| `src/components/settings/ModelConfig.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models/addModel/updateModel/removeModel/testModel/loadUsageStats` 全部不存在 |
| `src/components/settings/UsageStatsPanel.vue` | mixed: `useAgentUsageStore` + `useSettingsStore` | `settingsStore.deleteUsageStat` 等不存在 |
| `src/stores/chat.ts` | `useSettingsStore` from `settings-store` | `settingsStore.models` 不存在 |
| `src/components/report/ReportHome.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models` 不存在 |
| `src/components/report/ReportAIPanel.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models` 不存在 |
| `src/components/report/ReportGenerationPipeline.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models/testModel` 不存在 |
| `src/components/report/ReportTaskListPanel.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models/testModel` 不存在 |
| `src/components/report/ChildAnalysisPanel.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models` 不存在 |
| `src/components/report/CommunityAnalysisPipeline.vue` | `useSettingsStore` from `settings-store` | `settingsStore.models` 不存在 |

**这 12 个文件** 的 store 引用全部回退到了拆分前的状态。`modelConfigStore` 和 `useModelConfigStore` 的 import 全部丢失。

---

### C3: `src/stores/report-store.ts` IPC 迁移回退

**预期状态**: `listCommunityResults`、`getCascadeLevels`、`saveCommunityResult` 应从 `report-store.ts` 移除 (H5 修复)。

**当前状态**: 这三个函数存在于 `report-store.ts:82-99`，且同时存在于 `community-store.ts:82-90`——形成**双份重复**。

---

### C4: SubDocViewer.vue 拆分回退

**文件**: `src/components/report/SubDocViewer.vue` (975行)

**预期**: ~613行 (SubDocContent + SubDocToolbar + SubDocRegenDialog 已抽出)

**当前**: 975行。包含以下本应已迁移到 `SubDocContent.vue` 的代码:
- `diagramBlocks` ref (line 94)
- `ensureMermaid()` 函数
- `injectDiagram()` 函数
- `normalizeDiagramCode()` 函数
- `renderAllDiagrams()` 函数
- `extractDiagrams()` 函数
- `renderedContent` computed (含完整的 Markdown→HTML 渲染逻辑)
- `onDocContentClick()` 函数
- `scrollToHash()` + `onHashChange()` 函数

**`SubDocContent.vue` 本体完好 (253行)**，但父组件 `SubDocViewer.vue` 保留了这些代码的副本——形成了双份。

---

## 三、高优先级 (HIGH — 2项)

### H1: ReportHome.vue 社区逻辑重复

**文件**: `src/components/report/ReportHome.vue` (962行)

**预期**: ~728行，社区部分使用 `<CommunitySection>` 组件

**当前**: 962行。包含内联的社区网格渲染、社区统计、分页逻辑。`CommunitySection.vue` 本体完好 (177行)，但父组件 `ReportHome.vue` **未使用它**——形成重复。

具体重复内容:
- `commStats` computed
- `communityItems` computed  
- `communityTotalPages` computed
- `pagedCommunityItems` computed
- `commName` function
- `watch(communitySearch)`
- 模板中 ~90行社区 section HTML

---

### H2: RightPanel.vue 注册表未生效

**文件**: `src/components/shell/RightPanel.vue` (273行，比拆分前 249 行还多了 24 行)

**`rightPanelRegistry.ts` 存在 (8行)但未被使用**。RightPanel.vue 仍然直接 import feature 层组件:

```typescript
import DebugPanel from '@/components/debug/DebugPanel.vue'
import CodeIndexPanel from '@/components/report/CodeIndexPanel.vue'
import AIAssistantPanel from '@/components/ai/AIAssistantPanel.vue'
import ReportTaskListPanel from '@/components/report/ReportTaskListPanel.vue'
```

---

## 四、中优先级 (MEDIUM — 2项)

### M1: debug.ts 缺少模块级 `_handlerRegistered` 守卫

**文件**: `src/stores/debug.ts` (76行)

**已丢失**: H3 修复中移出的模块级 `_handlerRegistered` 变量。当前 `addLogHandler()` 在 store 体内 `defineStore` 回调中直接调用 (line 26)，无重复注册守卫。

---

### M2: ProjectCard.vue 本地 `languageBadge` 重复

**文件**: `src/components/project/ProjectCard.vue` (862行)

`src/utils/languageBadge.ts` 存在 (16行)，但 `ProjectCard.vue` 的 Options API `<script>` 块 (lines 607-621) 定义了**本地副本** `languageBadge()`，未使用共享工具。

---

## 五、低优先级 (LOW — 1项)

### L1: 子组件文件略有膨胀

| 文件 | 预期行数 | 当前行数 | 偏差 |
|------|----------|----------|------|
| `SubDocRegenDialog.vue` | ~200 | 256 | +56 |
| `CommunitySection.vue` | ~159 | 177 | +18 |
| `SubDocToolbar.vue` | ~56 | 70 | +14 |
| `SubDocContent.vue` | ~243 | 253 | +10 |
| `EditProjectInfoDialog.vue` | ~98 | 136 | +38 |
| `ProjectContextMenu.vue` | ~99 | 126 | +27 |

这可能是误操作前有额外的功能补充，或是在回退过程中混入了代码。偏差不大且文件功能正常，优先级低。

---

## 六、完整状态代码清单

### 保存在的修改

| 文件/目录 | 状态 |
|-----------|------|
| `src/stores/model-config-store.ts` | ✅ 完好 (75行) |
| `src/stores/agent-usage-store.ts` | ✅ 完好 (77行) |
| `src/stores/model-store.ts` (wrapper) | ✅ 完好 (8行) |
| `src/stores/report.ts` (wrapper) | ✅ 已删除 |
| `src/components/report/SubDocContent.vue` | ✅ 完好 (253行) |
| `src/components/report/SubDocToolbar.vue` | ✅ 完好 (70行) |
| `src/components/report/SubDocRegenDialog.vue` | ✅ 完好 (256行) |
| `src/components/report/CommunitySection.vue` | ✅ 完好 (177行) |
| `src/components/home/ProjectSummaryCard.vue` | ✅ 完好 (48行) |
| `src/components/home/TaskSummaryCard.vue` | ✅ 完好 (80行) |
| `src/components/home/ActionsBar.vue` | ✅ 完好 (69行) |
| `src/components/project/ProjectContextMenu.vue` | ✅ 完好 (126行) |
| `src/components/project/EditProjectInfoDialog.vue` | ✅ 完好 (136行) |
| `src/components/shell/rightPanelRegistry.ts` | ✅ 完好 (8行) |
| `src/utils/statusBadge.ts` (with getProjectStatusLabelKey) | ✅ 完好 (84行) |
| `src/utils/languageBadge.ts` | ✅ 完好 (16行) |
| `src/utils/community.ts` | ✅ 完好 (22行) |
| `src/utils/flattenTree.ts` | ✅ 完好 (37行) |
| `.github/workflows/ci.yml` (no `\|\| true`) | ✅ 完好 (55行) |
| `backend-core/pytest.ini` | ✅ 完好 (9行) |
| `backend-core/handlers/`, `repositories/`, `services/` 空目录 | ✅ 已删除 |
| `src/main/` 空目录 | ✅ 已删除 |

### 丢失/回退的修改

| 文件 | 问题 |
|------|------|
| `src/stores/settings.ts` | **应删除但存在** (349行, store ID 冲突) |
| `src/App.vue` | `useModelConfigStore` import 丢失 |
| `src/pages/UserPage.vue` | `useModelConfigStore` import 丢失 |
| `src/components/shell/StatusBar.vue` | `useModelConfigStore` import 丢失 |
| `src/components/settings/ModelConfig.vue` | `useModelConfigStore` + `useAgentUsageStore` imports 丢失 |
| `src/components/settings/UsageStatsPanel.vue` | `useAgentUsageStore` 部分丢失 (deleteUsage* 仍用 settingsStore) |
| `src/stores/chat.ts` | `useModelConfigStore` import 丢失 |
| `src/components/report/ReportHome.vue` | `useModelConfigStore` import 丢失 + CommunitySection 未使用 |
| `src/components/report/ReportGenerationPipeline.vue` | `useModelConfigStore` import 丢失 |
| `src/components/report/ReportTaskListPanel.vue` | `useModelConfigStore` import 丢失 |
| `src/components/report/ChildAnalysisPanel.vue` | `useModelConfigStore` import 丢失 |
| `src/components/report/CommunityAnalysisPipeline.vue` | `useModelConfigStore` import 丢失 |
| `src/components/report/ReportAIPanel.vue` | `useModelConfigStore` import 丢失 |
| `src/stores/report-store.ts` | IPC 迁移回退 (3个函数回归) |
| `src/components/report/SubDocViewer.vue` | 拆分回退 (975行, 含内联图表/导航代码) |
| `src/components/report/ReportHome.vue` | 社区逻辑回退 (962行, CommunitySection 未使用) |
| `src/components/shell/RightPanel.vue` | 注册表未使用 (273行, 直接 import feature 组件) |
| `src/stores/debug.ts` | `_handlerRegistered` 模块级守卫丢失 |
| `src/components/project/ProjectCard.vue` | `languageBadge` 本地重复未消除 |

### 推断

误操作发生在 H3 (debug.ts) 和 H4 (model-store 拆分 + 消费者更新) 完成之后、但在 type-check 验证之后。具体丢失了:

1. **settings.ts 的删除操作** — 文件回退出现
2. **12 个消费者的 import 更新** — 全部回退到使用 `useSettingsStore` 访问模型数据
3. **部分父组件的精简** — SubDocViewer 和 ReportHome 的内联代码恢复
4. **debug.ts 的模块级守卫** — 回退到 store 体内注册

保存在的有: 所有新创建的文件 (model-config-store, agent-usage-store, 9 个子组件, 4 个工具文件, CI, pytest) 都完好。丢失的是"对现有文件的修改"——这符合 git 中"untracked 新文件保留, tracked 文件修改丢失"的典型误操作特征。
