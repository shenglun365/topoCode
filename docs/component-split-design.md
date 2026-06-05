# 大组件拆分完整设计方案

> 涉及: SubDocViewer.vue (1113行) | ReportHome.vue (977行) | ProjectCard.vue (859行) | RightPanel.vue (跨层)
> 日期: 2026-06-05

---

## 一、拆分目标

| 组件 | 当前行数 | 目标行数 | 策略 |
|------|----------|----------|------|
| `SubDocViewer.vue` | 1113 | ~350 | 按功能域拆为 3 子组件 + 1 编排父组件 |
| `ReportHome.vue` | 977 | ~350 | 按模板区块拆为 4 子组件 + 1 编排父组件 |
| `ProjectCard.vue` | 859 | ~380 | 拆出对话框 + 菜单, 父组件纯展示+事件 |
| `RightPanel.vue` | 249 | ~80 | 动态组件注册, 消除跨层 import |

总计减少: **2949 → ~1160 (~60%)**

---

## 二、SubDocViewer.vue 拆分方案

### 2.1 当前结构

| 区块 | 行数 | 占比 | 职责 |
|------|------|------|------|
| `<script setup>` | 1–550 | 49% | 状态 + 文档加载 + 再生 + 图表渲染 + 导航 |
| `<template>` | 551–742 | 17% | 工具栏 + 内容区 + 再生弹窗 |
| `<style>` | 743–1113 | 33% | 所有 CSS |

### 2.2 拆分子组件

#### 2.2.1 `SubDocContent.vue` (~300行)

**职责**: Markdown 渲染、Mermaid/PlantUML 图注入、内容点击导航、hash 滚动。

**Props**:

```typescript
interface SubDocContentProps {
  content: string                          // Markdown 原始内容
  taskId: string                           // 用于导航事件上下文
  projectId?: string                       // 同上
  loading: boolean                         // 父组件控制的加载状态
}
```

**Emits**:

```typescript
interface SubDocContentEmits {
  'navigate-community': [payload: {
    taskId: string
    communityId: string
    edgeType: string
  }]
  'open-child-analysis': [payload: {
    taskId: string
    parentLevel: string
    parentCommId: string
    edgeType: string
    projectId?: string
  }]
  'view-child-md': [payload: {
    taskId: string
    communityId: string
    level: string
    edgeType: string
    parentLevel: string
    parentCommId: string
    name: string
    summary: string
    mermaid?: string
    plantuml?: string
  }]
}
```

**迁移内容** (从 SubDocViewer.vue 移入):
- `renderedContent` computed (line 423–492) — Markdown → HTML 渲染
- `diagramBlocks` ref + `extractDiagrams()` + `renderAllDiagrams()` — 图表处理
- `ensureMermaid()` + `injectDiagram()` + `normalizeDiagramCode()` + `escapeHtml()` — 图表工具
- `onDocContentClick()` — 社区链接点击事件代理
- `scrollToHash()` + `onHashChange()` — TOC hash 导航
- `loading` ref (迁移到此组件, 显示 spinner)
- 模板 line 558–564 (loading) + line 607–633 (doc 元数据 + 内容 + ChildSection)

**子组件引用**: `<ChildSection>` 作为透传, 直接在此组件模板中使用。

---

#### 2.2.2 `SubDocRegenDialog.vue` (~180行)

**职责**: AI/手动再生弹窗 — 全文档再生 + Mermaid 再生 + PlantUML 再生。

**Props**:

```typescript
interface SubDocRegenDialogProps {
  visible: boolean
  regenerationType: 'community' | 'overall'
  taskId: string
  projectId: string
  existingMermaid: string               // 当前文档中的 mermaid 代码
  existingPlantuml: string              // 当前文档中的 plantuml 代码
}
```

**Emits**:

```typescript
interface SubDocRegenDialogEmits {
  'close': []
  'regenerated': [payload: {
    content: string                      // 再生后的完整 Markdown 内容
    mermaidCode?: string                 // 仅图表再生时
    plantumlCode?: string                // 仅图表再生时
    mode: 'full' | 'mermaid' | 'plantuml'
  }]
}
```

**迁移内容** (从 SubDocViewer.vue 移入):
- 所有 `regen*` 状态 refs (line 63–69): `regenMode`, `regenSubMode`, `regenPrompt`, `regenManualCode`, `regenLoading`, `regenError`
- `canRegenerate` computed (line 71)
- `existingMermaid`/`existingPlantuml`/`existingDiagramCode` computed (line 73–89)
- `watch(regenSubMode)` (line 91–95)
- `submitRegen()` (line 112–210) — 核心再生逻辑, 包含 AI / manual / full / diagram 四条路径
- 模板 line 636–740 (regen 弹窗全部内容)

**与父组件的交互**:
- 父组件调用 `openRegenDialog(mode?)` → 设置 props + `visible=true`
- 子组件 emit `regenerated` → 父组件在 handler 中更新 `doc` 状态并关闭弹窗
- 子组件 emit `close` → 父组件 `showRegenDialog=false`

---

#### 2.2.3 `SubDocToolbar.vue` (~60行)

**职责**: 顶部工具栏 — 返回按钮、标题显示、刷新、浏览器打开、再生触发。

**Props**:

```typescript
interface SubDocToolbarProps {
  title: string
  canOpenInBrowser: boolean
  canRegenerate: boolean
  httpPort: number
  docId: string
}
```

**Emits**:

```typescript
interface SubDocToolbarEmits {
  'close': []
  'refresh': []
  'open-browser': [url: string]
  'open-regen-dialog': [mode?: 'full' | 'mermaid' | 'plantuml']
}
```

**迁移内容**:
- `canOpenInBrowser` computed (line 395) + `openInBrowser()` (line 397–420)
- `openRegenDialog()` (line 97–104) → 变为 emit
- 模板 line 567–605 (toolbar 部分)

---

#### 2.2.4 `SubDocViewer.vue` (父组件, ~350行)

**产后职责**: 编排 — props/emit 定义 + `loadDoc()` 数据加载 + 生命周期 + 子组件组装。

**保留内容**:
- Props: `subDocId`, `initialContent`, `initialTitle`, `taskId`, `parentLevel`, `parentCommId`, `parentEdgeType`, `projectId`, `regenerationType`
- Emits: `close`, `navigate-community`, `open-child-analysis`, `view-child-md` — **全部透传** 给 `SubDocContent`
- `loadDoc()` (line 335–392) — 从 DB/initialContent 加载文档, 调用 `extractDiagrams`
- `doc` ref, `httpPort` ref
- `showRegenDialog` ref (控制再生弹窗显隐)
- 生命周期: `onMounted(loadDoc)`, `watch(subDocId, loadDoc)`, `watch(loading, scrollToHash)`
- 模板: 简化为三子组件组装

**模板结构 (最终)**:

```html
<template>
  <SubDocToolbar
    :title="doc?.title ?? initialTitle ?? ''"
    :can-open-in-browser="!!doc"
    :can-regenerate="canRegenerate"
    :http-port="httpPort"
    :doc-id="doc?.id ?? ''"
    @close="emit('close')"
    @refresh="loadDoc"
    @open-regen-dialog="(mode) => openRegenDialog(mode)"
  />
  <SubDocContent
    :content="doc?.content ?? ''"
    :task-id="taskId ?? ''"
    :project-id="projectId"
    :loading="loading"
    @navigate-community="(p) => emit('navigate-community', p)"
    @open-child-analysis="(p) => emit('open-child-analysis', p)"
    @view-child-md="(p) => emit('view-child-md', p)"
  />
  <SubDocRegenDialog
    :visible="showRegenDialog"
    :regeneration-type="regenerationType ?? 'community'"
    :task-id="taskId ?? ''"
    :project-id="projectId ?? ''"
    :existing-mermaid="existingMermaid"
    :existing-plantuml="existingPlantuml"
    @close="showRegenDialog = false"
    @regenerated="handleRegenerated"
  />
</template>
```

**行数估算**: script ~200行 (loadDoc + lifecycle + handlers) + template ~30行 + style ~120行 = **~350行**。

---

## 三、ReportHome.vue 拆分方案

### 3.1 当前结构

| 区块 | 行数 | 职责 |
|------|------|------|
| `<script setup>` | 1–348 | 9 store imports + 8 refs + 10 computed + 10 functions + 2 watchers |
| `<template>` | 350–648 | 加载态 / 错误态 / 项目概要 / 任务概要 / 社区概要 / 操作区 / 弹窗 |
| `<style>` | 650–977 | CSS |

### 3.2 拆分子组件

#### 3.2.1 `ProjectSummaryCard.vue` (~80行)

**Props**:

```typescript
interface ProjectSummaryCardProps {
  projectName: string
  language: string
  fileCount: number
  rootPath: string
}
```

**迁移内容**: 模板 line 380–406 (项目概要 4 卡片), 几乎 0 逻辑依赖——纯展示组件。

---

#### 3.2.2 `TaskSummaryCard.vue` (~120行)

**Props**:

```typescript
interface TaskSummaryCardProps {
  taskName: string
  taskType: string
  taskStatus: string
  createdAt: string
  scopes: string[]
  extensions: string[]
  excludeDirs: string[]
}
```

**迁移内容**: 模板 line 409–471 (任务概要 + 文件分布/范围标签), `getStatusBadge`/`getStatusText` 样式计算。

---

#### 3.2.3 `CommunitySection.vue` (~250行)

**职责**: 社区概要——边类型切换、统计栏、搜索、网格、分页。这是最大的提取块。

**Props**:

```typescript
interface CommunitySectionProps {
  communities: CommunityItem[]            // L0 社区列表 (已过滤 edgeType)
  edgeType: 'INCLUDE' | 'CALL'
  searchQuery: string
  currentPage: number
  pageSize: number                       // 默认 100
}
```

**Emits**:

```typescript
interface CommunitySectionEmits {
  'update:edgeType': [type: 'INCLUDE' | 'CALL']
  'update:searchQuery': [query: string]
  'update:currentPage': [page: number]
  'select-community': [item: CommunityItem]
}
```

**迁移内容**:
- `commStats` computed (line 79–90)
- `communityItems` computed (line 92–100)
- `communityTotalPages` + `pagedCommunityItems` computed (line 102–106)
- `watch(communitySearch)` (line 108) → 移入组件内部
- `truncatePath` / `formatCommId` / `commName` utilities (line 112–128)
- 模板 line 473–564 (社区概要全部内容: edge toggle + stats + search + grid + pagination)

---

#### 3.2.4 `ActionsBar.vue` (~80行)

**Props**:

```typescript
interface ActionsBarProps {
  hasModel: boolean
  communityAnalysisProgress: number       // 0-100
  hasArchitectureReport: boolean
}
```

**Emits**:

```typescript
interface ActionsBarEmits {
  'open-task-list': []
  'open-community-analysis': []
  'open-overall-architecture': []
}
```

**迁移内容**: 模板 line 567–613 (LLM 警告 + 3 个操作按钮)。父组件的 `openTaskList`/`openCommunityAnalysis`/`openOverallArchitecture` 函数保留, 子组件通过 emit 触发。

---

#### 3.2.5 `ReportHome.vue` (父组件, ~350行)

**产后职责**: 数据加载编排 + 子组件组装 + `ReportGenerationPipeline` 管理。

**模板结构 (最终)**:

```html
<template>
  <div v-if="loading" class="loading-state"><!-- spinner --></div>
  <div v-else-if="loadError" class="load-error"><!-- retry --></div>
  <div v-else class="report-home-scroll">
    <ProjectSummaryCard
      :project-name="project?.name ?? '-'"
      :language="project?.language ?? '-'"
      :file-count="project?.fileCount ?? 0"
      :root-path="project?.rootPath ?? '-'"
    />
    <TaskSummaryCard
      :task-name="task?.name ?? ''"
      :task-type="task?.type ?? ''"
      :task-status="task?.status ?? ''"
      :created-at="task?.createdAt ?? ''"
      :scopes="task?.scopes ?? []"
      :extensions="task?.extensions ?? []"
      :exclude-dirs="task?.excludeDirs ?? []"
    />
    <CommunitySection
      v-if="runtimeCommunities.length > 0"
      :communities="runtimeCommunities"
      :edge-type="commEdgeType"
      :search-query="communitySearch"
      :current-page="communityPage"
      :page-size="communityPageSize"
      @update:edge-type="commEdgeType = $event"
      @update:search-query="communitySearch = $event"
      @update:current-page="communityPage = $event"
      @select-community="openCommunityDoc"
    />
    <ActionsBar
      :has-model="hasModel"
      :community-analysis-progress="communityAnalysisProgress"
      :has-architecture-report="hasArchitectureReport"
      @open-task-list="openTaskList"
      @open-community-analysis="openCommunityAnalysis"
      @open-overall-architecture="openOverallArchitecture"
    />
    <ReportGenerationPipeline
      :task-id="taskId"
      :project-id="projectId"
      @generated="handleReportGenerated"
      @view-community-md="(p) => emit('open-md', p)"
    />
    <NoReportDialog v-if="showNoReportDialog" @close="showNoReportDialog = false" />
  </div>
</template>
```

**保留函数**: `loadData`, `openCommunityDoc`, `handleCommunityMD`, `openTaskList`, `openCommunityAnalysis`, `openOverallArchitecture`, `handleReportGenerated`, `escapeTbl`, `buildCommunityAppendix`。

**行数估算**: ~350行。

---

## 四、ProjectCard.vue 拆分方案

### 4.1 当前结构

| 区块 | 行数 | 职责 |
|------|------|------|
| `<script setup>` | 1–320 | 状态 + 存储统计 + 菜单 + 编辑 + 路径变更 + 删除/清缓存 |
| `<template>` | 322–601 | 卡片 + 上下文菜单 + 删除确认 + 清缓存 + 编辑弹窗 + 路径确认 |
| `<script>` (options) | 603–619 | `languageBadge()` 独立函数 |
| `<style scoped>` | 621–745 | 卡片样式 + 编辑弹窗样式 |
| `<style>` (global) | 747–859 | 上下文菜单 + 全局样式 |

### 4.2 拆分子组件

#### 4.2.1 `EditProjectInfoDialog.vue` (~170行)

**Props**:

```typescript
interface EditProjectInfoDialogProps {
  visible: boolean
  projectName: string
  projectId: string
  currentGroupIds: string[]
}
```

**Emits**:

```typescript
interface EditProjectInfoDialogEmits {
  'close': []
  'confirm': [payload: { newName: string; newGroupIds: string[] }]
  'open-group-manager': []
}
```

**迁移内容**:
- `editNameInput` ref, `allGroups` ref + 加载逻辑, `selectedGroupIds` ref
- `flattenGroups()` (line 179–188)
- `toggleGroupSelect()` (line 190–197)
- `handleOpenGroupManagerFromDialog()` → 改为 emit `open-group-manager`
- 模板 line 536–589 (编辑弹窗全部: name input + group tree checklist)
- CSS line 661–744 (`.edit-info-dialog` 相关样式)

**在父组件中保留**: 确认后的 IPC 持久化逻辑 (`ipc.group.addProject`/`removeProject`/`projectStore.updateProjectMeta`/`projectStore.loadProjects`), 在 `@confirm` handler 中执行。

---

#### 4.2.2 `ProjectContextMenu.vue` (~110行)

**Props**:

```typescript
interface ProjectContextMenuProps {
  visible: boolean
  position: { x: number; y: number }
  isFavorited: boolean
  isPinned: boolean
  isSample: boolean
}
```

**Emits**:

```typescript
interface ProjectContextMenuEmits {
  'close': []
  'toggle-favorite': []
  'toggle-pinned': []
  'edit-info': []
  'change-path': []
  'check-changes': []
  'clear-cache': []
  'delete': []
}
```

**迁移内容**:
- `menuVisible` ref, `menuPosition` ref
- `showMenu(e)` 定位计算逻辑 (line 110–131)
- `hideMenu()` (line 133–135)
- 模板 line 441–518 (上下文菜单全部: 收藏/置顶/编辑/改路径/检查/清缓存/删除 + backdrop)
- CSS line 748–806 (上下文菜单全局样式)

---

#### 4.2.3 共享工具函数提取

**`formatTime` → `src/utils/time.ts`** (新增函数):

```typescript
// 追加到现有 utils/time.ts
export function formatRelativeTime(dateStr: string | null): string { ... }
```

迁移自 ProjectCard.vue line 95–107。`ChatMessage.vue` 和 `KnowledgeDocCard.vue` 后续可统一使用。

**`getStatusBadge` / `getStatusText`**: 
ProjectCard 的 `synced/syncing/error` 状态不同于 `statusBadge.ts` 中的 task/backend 状态, 但模式相同。建议在 `statusBadge.ts` 中追加:

```typescript
// 追加到 statusBadge.ts
const PROJECT_STATUS_BADGE: Record<string, string> = {
  synced: 'badge-green',
  syncing: 'badge-yellow',
  error: 'badge-red',
}
const PROJECT_STATUS_LABEL: Record<string, string> = {
  synced: 'project.synced',
  syncing: 'project.syncing',
  error: 'common.error',
}
export function getProjectStatusBadge(status: string): string { ... }
export function getProjectStatusLabel(status: string): string { ... }
```

**`languageBadge` → 使用 `utils/mock.ts` 导出** 或 创建 `utils/languageBadge.ts`:
删除 ProjectCard.vue 的 Options API `<script>` 块 (line 603–619), 改为 import。

---

#### 4.2.4 `ProjectCard.vue` (父组件, ~380行)

**产后职责**: 卡片展示 + 事件编排 (调用子组件对话框, 处理 IPC 持久化)。

**保留内容**:
- Props: `project: Project` + emit: `select`
- Storage stats: `loadStorageStats()` + `formatBytes()`
- 所有事件处理函数: `toggleFavorite`, `togglePinned`, `handleChangePath`, `confirmPathChange`, `handleCheckChanges`, `handleDelete`, `confirmDelete`, `handleClearCache`, `onClearCacheDone`
- `confirmEditInfo()` → 改为接收 `EditProjectInfoDialog` 的 `@confirm` payload
- 模板: 卡片核心布局 (line 322–439) + 子组件引用

**模板结构 (最终)**:

```html
<template>
  <div class="project-card" @click="emit('select', project)" @contextmenu.prevent="showEditMenu">
    <!-- 卡片内容: header, path, stats, progress, status — 约 118 行 -->
    ...
  </div>

  <ProjectContextMenu
    :visible="menuVisible"
    :position="menuPosition"
    :is-favorited="!!project.favorite"
    :is-pinned="!!project.pinned"
    :is-sample="isSample"
    @close="hideMenu"
    @toggle-favorite="toggleFavorite"
    @toggle-pinned="togglePinned"
    @edit-info="startEditInfo"
    @change-path="handleChangePath"
    @check-changes="handleCheckChanges"
    @clear-cache="handleClearCache"
    @delete="handleDelete"
  />

  <EditProjectInfoDialog
    :visible="showEditDialog"
    :project-name="project.name"
    :project-id="project.id"
    :current-group-ids="project.groups ?? []"
    @close="showEditDialog = false"
    @confirm="confirmEditInfo"
    @open-group-manager="handleOpenGroupManager"
  />

  <ConfirmDialog v-model:visible="showDeleteConfirm" ... />
  <ConfirmDialog v-model:visible="showPathConfirm" ... />
  <ClearCacheDialog v-if="showClearCacheDialog" ... />
</template>
```

---

## 五、RightPanel.vue 跨层解耦

### 5.1 当前问题

```typescript
// RightPanel.vue:8-11 — shell 层直接 import feature 层
import DebugPanel from '@/components/debug/DebugPanel.vue'
import CodeIndexPanel from '@/components/report/CodeIndexPanel.vue'
import AIAssistantPanel from '@/components/ai/AIAssistantPanel.vue'
import ReportTaskListPanel from '@/components/report/ReportTaskListPanel.vue'
```

### 5.2 解决方案: 动态组件注册表

```typescript
// src/components/shell/rightPanelRegistry.ts
import { defineAsyncComponent, type Component } from 'vue'

export const RIGHT_PANEL_COMPONENTS: Record<string, Component> = {
  debug:    defineAsyncComponent(() => import('@/components/debug/DebugPanel.vue')),
  codeIndex: defineAsyncComponent(() => import('@/components/report/CodeIndexPanel.vue')),
  ai:       defineAsyncComponent(() => import('@/components/ai/AIAssistantPanel.vue')),
  taskList: defineAsyncComponent(() => import('@/components/report/ReportTaskListPanel.vue')),
}
```

```html
<!-- RightPanel.vue 模板 -->
<component :is="activeComponent" v-bind="activeComponentProps" />
```

```typescript
// RightPanel.vue script
const activeComponent = computed(() => {
  const page = navigationStore.currentPage
  if (panelStore.debugMode) return RIGHT_PANEL_COMPONENTS.debug
  if (page === 'analysis') return RIGHT_PANEL_COMPONENTS.taskList
  if (page === 'code') return RIGHT_PANEL_COMPONENTS.codeIndex
  return RIGHT_PANEL_COMPONENTS.ai
})
```

**优势**: 
- shell 层不再直接 import feature 组件, 通过注册表间接引用
- 懒加载: `defineAsyncComponent` 按需加载
- 新增右侧面板组件只需在注册表中添加一行

**RightPanel.vue 产后**: ~80行 (249 → 80, 减少 68%)。

---

## 六、新增文件总览

```
src/components/report/
  SubDocContent.vue          (~300行) — Markdown渲染+图表+导航
  SubDocRegenDialog.vue      (~180行) — AI/手动再生弹窗
  SubDocToolbar.vue          (~60行)  — 顶部工具栏
  CommunitySection.vue       (~250行) — 社区概览+搜索+分页

src/components/
  home/
    ProjectSummaryCard.vue   (~80行)  — 项目概要卡片
    TaskSummaryCard.vue      (~120行) — 任务概要卡片
    ActionsBar.vue           (~80行)  — 操作按钮栏

src/components/project/
  EditProjectInfoDialog.vue  (~170行) — 编辑项目信息弹窗
  ProjectContextMenu.vue     (~110行) — 上下文菜单

src/components/shell/
  rightPanelRegistry.ts      (~15行)  — 动态组件注册表

src/utils/
  time.ts                    (追加 ~15行 formatRelativeTime)
  statusBadge.ts             (追加 ~12行 getProjectStatusBadge/getProjectStatusLabel)
  languageBadge.ts           (新增 ~20行, 从 ProjectCard.vue + mock.ts 合并)
```

**新增文件**: 13 个 | **总新增行数**: ~1500 (含从原文件迁移的代码)

---

## 七、实施顺序

| 顺序 | 任务 | 风险 | 预估工时 |
|------|------|------|----------|
| 1 | 提取公共工具函数 (`time.ts` + `statusBadge.ts` + `languageBadge.ts`) | 低 | 0.5h |
| 2 | 拆分 `ProjectContextMenu.vue` | 低 (自包含, 纯事件) | 1.5h |
| 3 | 拆分 `EditProjectInfoDialog.vue` | 中 (涉及 group 加载 + 复杂 emit payload) | 2h |
| 4 | 清理 `ProjectCard.vue` — 集成子组件, 删除 Options API script | 低 | 1h |
| 5 | 拆分 `ProjectSummaryCard.vue` + `TaskSummaryCard.vue` | 低 (纯展示) | 1h |
| 6 | 拆分 `ActionsBar.vue` | 低 (纯事件) | 1h |
| 7 | 拆分 `CommunitySection.vue` | 中 (含搜索/分页/网格 逻辑) | 2h |
| 8 | 清理 `ReportHome.vue` — 集成 4 子组件 | 低 | 1h |
| 9 | 拆分 `SubDocRegenDialog.vue` | 中 (再生逻辑复杂, 4条路径) | 2h |
| 10 | 拆分 `SubDocContent.vue` | 高 (Markdown渲染+图表+导航 紧密耦合) | 2.5h |
| 11 | 拆分 `SubDocToolbar.vue` | 低 (纯事件) | 0.5h |
| 12 | 清理 `SubDocViewer.vue` — 集成 3 子组件 | 低 | 1h |
| 13 | `rightPanelRegistry.ts` + 重构 `RightPanel.vue` | 低 | 1h |

**总计: ~17h (约 2.5 天)**

## 八、迁移策略

**每个组件拆分采用以下步骤, 确保每一步可单独提交且不破坏功能**:

1. **创建新文件** — 新建子组件, 复制要迁移的 template/script/style 代码
2. **调整接口** — 将直接引用的 `ref`/`computed`/`function` 改为 `props`/`emit`
3. **在父组件中引入** — 将原 template 区块替换为 `<NewComponent ... />`
4. **删除冗余代码** — 从父组件中删除已迁移的 ref/computed/function/style
5. **验证** — `npm run type-check` + `npm run dev` 手动确认交互正常

**回滚策略**: 每个子组件的 git commit 独立, 任一步骤发现问题时仅回滚该 commit。
