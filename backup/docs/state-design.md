# 报告/分析功能状态管理设计

## 目标

全任务隔离、单一写点、组件只读 + dispatch。

## 仓库职责

```
analysisStore (不变)
  ├─ tasks[] / selectedTaskId / filter          ← 任务列表 CRUD
  ├─ loadTasks / createTask / stopTask / ...     ← 后端通信
  └─ subscribeToEvents()                        ← 后端进度事件
       ↓ taskId 关联

reportStore (重构 ← merge pipelineStore runtime + component local refs)
  ├─ Per-task state (keyed by taskId):
  │   ├─ pipelineRunning / pipelinePaused
  │   ├─ pipelineSteps / pipelineProgress
  │   ├─ communityRunning / communityPaused
  │   ├─ communities[] / llmResults / projectContext
  │   ├─ errorLogs
  │   └─ overallReport / communityResults (已有)
  │
  ├─ Actions (唯一写路径):
  │   ├─ runPipeline(taskId)           / stopPipeline(taskId)
  │   ├─ analyzeSelected(taskId, ...)   / stopAnalysis(taskId)
  │   ├─ toggleSelect(taskId, id)
  │   ├─ retryTask(taskId, communityId)
  │   ├─ loadCommunities(taskId, projectId)
  │   ├─ pushError(taskId, msg) / clearErrorLogs(taskId)
  │   └─ saveToDb(taskId) / restoreFromDb(taskId)
  │
  └─ IPC 封装方法 (getLevelCommunityDetail, saveCommunityResult, ... 已有)
```

## 数据流

```
┌───────────┐   dispatch action    ┌──────────────────────┐
│ Component │ ─────────────────►   │  reportStore action   │
│ (只读展示) │                     │  (唯一写入口)          │
│           │ ◄─────────────────  │  直接修改 task state   │
└───────────┘   reactive read      └──────────────────────┘
                                           │
                                    IPC 调用后端
                                           │
                                    community_llm_results
                                    / report_subdocs / ...
```

## 组件改造前后对照

### ReportGenerationPipeline

| 当前 (local ref) | 改造后 (store) |
|---|---|
| `rootTask` | `taskState.pipelineSteps` |
| `running` | `taskState.pipelineRunning` |
| `isPaused` | `taskState.pipelinePaused` |
| `overallProgress` | computed from steps |
| `stepOutputs` | `taskState.llmResults` (复用) |
| `errorLogs` | `taskState.errorLogs` |
| `syncStore()` → pipelineStore | ❌ 移除，store action 内直接写 |
| `onMounted` load from pipelineStore | `reportStore.restoreFromDb(taskId)` |

### CommunityAnalysisPipeline

| 当前 (local ref + pipelineStore) | 改造后 (store) |
|---|---|
| `allCommunities` / `llmResults` | `taskState.communities` / `taskState.llmResults` |
| `running` / `paused` | `taskState.communityRunning` / `taskState.communityPaused` |
| `projectContext` | `taskState.projectContext` |
| `loadError` / `runError` | ❌ 组件本地（纯展示状态） |
| `selectedEdgeType` / `selectedLevel` | ❌ 组件本地（视图偏好） |
| `searchQuery` / `currentPage` / `sortHistory` | ❌ 组件本地（视图偏好） |
| `saveState()` / `afterLoadMergePending()` / watcher / capStopSignals / triggerRef | ❌ **全部移除** |
| `analyzeSelected()` (async 循环) | `reportStore.analyzeSelected(taskId, modelId, batchSize)` |

### PipelineTaskTree

| 当前 | 改造后 |
|---|---|
| 通过 props 接收 node | 通过 props 接收 node (不变) |

### ReportHome

| 当前 | 改造后 |
|---|---|
| 少量 local ref (loading/search) | 不变（纯展示 + 编排） |

## 关键约束

1. **store 内不写组件 ref** — action 只依赖 `taskId` 参数，不依赖 `props`/`computed`
2. **store state 按 taskId 寻址** — `tasks.value[taskId].property`
3. **组件不写可变状态** — 所有 mutation 走 action
4. **移除全部跨实例同步机制** — store 恒存，无需 restore/watcher/moduleMap/triggerRef
5. **`pipelineStore` 中社区分析相关逻辑移除或简化** — `stepOutputs[CAP_STATE_KEY]` / `updateCommunityProgress` 不再需要
