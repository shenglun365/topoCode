# TopoCode-UI 架构质量评估报告 v2

> 分析日期: 2026-06-05 | 范围: 全项目 | 对比基线: v1 报告 (2026-06-03)

---

## 一、重构成果评估

### 1.1 已解决问题 (v1 → v2)

| # | v1 问题 | 状态 | 说明 |
|---|---------|------|------|
| 1 | `report.ts` Store 1284行 | ✅ 已拆分 | 拆为 `report-store`(96) + `community-store`(519) + `pipeline-store`(186) + `model-store`(137) |
| 2 | `settings.ts` 职责过多 349行 | ✅ 已拆分 | 拆为 `settings-store`(107) + `model-store`(137)，原文件为兼容性 wrapper |
| 3 | `main.js` 安全隐患 | ✅ 已删除 | `nodeIntegration: true` 文件不存在于项目中 |
| 4 | `backup/` 在 `src/` 下 | ✅ 已迁移 | 移至项目根目录，与源码分离 |
| 5 | `render-worker-bundled.js` 180K行在 src | ✅ 已迁移 | 移至 `build/` 目录 |
| 6 | AI 聊天无共享 | ✅ 已解决 | 新增 `useChatSession.ts` composable，`AIAssistantPanel` 从366→242行 |
| 7 | `ipc.ts` 服务单体 485行 | ✅ 已拆分 | 拆为 7 个独立子服务 + 144行编排层 |
| 8 | 重复工具函数 | ✅ 已解决 | 新增 `statusBadge.ts`, `time.ts`, `fileColors.ts` |
| 9 | 无 Plugin 系统 | ✅ 已实现 | `plugins/` 目录 + `plugin-store.ts` + `PluginManager.vue` |
| 10 | 无自动更新 | ✅ 已实现 | `electron-updater` + `updater.ts` |

### 1.2 架构演进对比

| 指标 | v1 | v2 | 变化 |
|------|----|----|------|
| Pinia Stores | 13 (1个超大) | 17 + 2 wrapper | Store 职责更清晰 |
| 最大 Store | 1284行 (report.ts) | 519行 (community-store.ts) | **-60%** |
| 服务层文件 | 2 | 9 (ipc.ts + 7子服务 + render-manager) | 领域拆分 |
| 共享工具 | 0 (嵌入组件) | 4 (time, statusBadge, fileColors, logger) | 消除重复 |
| Composables | 6 | 8 (新增 useChatSession, useDiagramRenderer) | 逻辑复用 |
| Plugin 系统 | 无 | 完整 (加载/安装/卸载) | 可扩展架构 |
| `any` 类型 | 290 | ~392 (含新增 window-api.ts 70处) | 因新增类型文件上升 |
| `console.*` | 172 | 110 | **-36%** |
| `main.js` | 存在 (安全隐患) | 已删除 | 安全加固 |

---

## 二、当前架构总览

```
                         ┌──────────────────────────┐
                         │    Electron Main Process │
                         │  main.ts / preload.ts    │
                         │  zmq-router / python-bridge│
                         │  window-manager / updater │
                         └──────────┬───────────────┘
                                    │ ZMQ (tcp://127.0.0.1:5671/5680)
                         ┌──────────▼───────────────┐
                         │    Python Backend (Core)  │
                         │  backend-core/main.py     │
                         │  zmq_server.py / core_    │
                         │  service.py / llm_service │
                         │  plugin_manager.py        │
                         │  ┌──────────────────────┐ │
                         │  │ 6 Plugins            │ │
                         │  │ parsers/community/    │ │
                         │  │ reports/ollama/       │ │
                         │  │ openai/lm-studio      │ │
                         │  └──────────────────────┘ │
                         └───────────────────────────┘

    ┌──────────────────────────────────────────────────────┐
    │                    Renderer (Vue 3)                   │
    │                                                      │
    │  ┌─────────┐  ┌──────────┐  ┌───────────────────┐   │
    │  │  Pages  │  │Components│  │  Stores (17+2w)   │   │
    │  │  6 pages│  │ 60 .vue  │  │  ┌──────┐┌──────┐ │   │
    │  │         │  │ 13 dirs  │  │  │project││comm- │ │   │
    │  └─────────┘  └──────────┘  │  │  un.  │└──────┘ │   │
    │                             │  └──────┘         │   │
    │  ┌─────────┐  ┌──────────┐  └───────────────────┘   │
    │  │Services │  │Composable│                           │
    │  │ 9 files │  │ 8 files  │  ┌───────────────────┐   │
    │  └─────────┘  └──────────┘  │    Types (4 files) │   │
    │                             │  ipc / index /     │   │
    │  ┌─────────┐  ┌──────────┐  │  window-api / zmq  │   │
    │  │ Utils   │  │   i18n   │  └───────────────────┘   │
    │  │ 5 files │  │ 2 locales│                           │
    │  └─────────┘  └──────────┘                           │
    └──────────────────────────────────────────────────────┘
```

---

## 三、现存问题（按严重程度）

### 🔴 P0 - 严重

#### P0-1 `community-store.ts` 仍严重超重 (519行)

虽已从 `report.ts` 拆分，但 30 个 actions 涵盖三层职责：顶层社区分析 + 子社区分析 + 选择/同步管理。`analyzeSelected` 与 `analyzeChildSelected` 存在 ~30 行重复批处理逻辑，`retryTask` 与 `retryChildTask` 存在 ~15 行重复。

**涉及文件**: `src/stores/community-store.ts`

**建议**: 拆分为 `community-analysis-store` + `child-analysis-store`，提取共享批处理 composable。

---

#### P0-2 `types/index.ts` 与 `types/ipc.ts` 类型不一致 (严重级别)

两个文件的 `KnowledgeDoc` 字段名完全不同：`index.ts` 用 `dimensions` (子字段 `techstack`/`attribute`)，`ipc.ts` 用 `tags` (子字段 `techStack`/`purpose`)。`AnalysisTask.status` 在 `index.ts` 缺少 `'modified'` 和 `'cancelled'`。`ModelConfig.type` 在两个文件中语义不同（provider名 vs deployment类型）。

**涉及文件**: `src/types/index.ts:97-113`, `src/types/ipc.ts:349-367`

**建议**: 以 `ipc.ts` 为唯一来源，`index.ts` 仅保留纯前端特有类型，通过 `Pick/Omit` 派生。

---

#### P0-3 `usePlantUmlRender.ts` 调用错误的 IPC 路径

第33行调用 `window.api.backend.renderPlantuml`，但 `window-api.ts` 中 `renderPlantuml` 实际在 `api.render` 命名空间下。在 Electron 环境中 PlantUML 渲染会静默失败。

**涉及文件**: `src/composables/usePlantUmlRender.ts:33`

**建议**: 改为 `window.api.render.renderPlantuml`，与 `useDiagramRenderer.ts` 保持一致。

---

#### P0-4 Event 回调 fallback 数组从未被消费

`analysis-service.ts` 和 `backend-service.ts` 中的 `taskProgressCbs`/`backendStatusCbs` 在 `window.api` 缺少对应方法时仅 push 回调到数组，但数组从未被遍历触发——所有回调静默丢失。

**涉及文件**: `src/services/ipc/analysis-service.ts`, `src/services/ipc/backend-service.ts`

**建议**: 移除死代码，或实现真正的 fallback 轮询机制。

---

### 🟠 P1 - 高

#### P1-1 `project.ts` 仍是 God Store (480行)

25 个 actions、6 个外部 store 依赖，混合了项目 CRUD + tab 管理（10个透传方法）+ 导入工作流 + 缓存清理。`useSettingsStore` 被导入但从未使用（死导入）。

**涉及文件**: `src/stores/project.ts:14`

**建议**: 将 tab 管理方法移至组件层直接调用 `funcGroup`，清理死导入，拆分导入工作流到 `import-store`。

---

#### P1-2 大型组件未分解 (26个超400行)

| 组件 | 行数 | 核心问题 |
|------|------|----------|
| `SubDocViewer.vue` | 960 | 自实现 Markdown 渲染器 + 图再生 + 文档CRUD |
| `ReportHome.vue` | 981 | 数据加载 + 社区搜索 + 分页 + Markdown 附录生成 |
| `ModelConfig.vue` | 908 | 模型CRUD + 用量限制 + 统计面板 |
| `ProjectCard.vue` | 859 | 上下文菜单 + 分组编辑 + 路径变更 + 删除确认 |

**建议**: `SubDocViewer` 提取 `useMarkdownRenderer` composable + `DocRegenerationPanel`；`ReportHome` 拆分为 `ReportSummaryCard` + `CommunityGrid`。

---

#### P1-3 多处重复逻辑未消除

| 重复模式 | 出现次数 | 推荐方案 |
|----------|----------|----------|
| 状态徽章映射 (`getStatusBadge`/`statusColor`) | 8 处 | 统一使用已有的 `statusBadge.ts` |
| 社区ID格式化 (`fmtCommId`) | 4 处 | 提取到 `utils/community.ts` |
| 树扁平化递归 | 4 处 | 创建通用 `flattenTree(nodes, key)` |
| 搜索过滤 (`computed` + `toLowerCase`) | 7+ 处 | 创建 `useSearchFilter` composable |
| 轮询 `setInterval` 模式 | 3 处 | 创建 `usePolling` composable |

**涉及文件**: `ModelConfig.vue`, `ProjectCard.vue`, `TaskDetailDialog.vue`, `TaskListPanel.vue`, `KnowledgeDocCard.vue`, `ChildAnalysisPanel.vue`, `ReportHome.vue`, `CommunityAnalysisPipeline.vue`, 等

---

#### P1-4 `model-store.ts` 多实体混合 (137行)

管理 5 种不同实体：Models, Agents, Skills, Bindings, UsageStats。Agent 和 Skill 的 CRUD 逻辑与 Model 无关，应独立管理。

**涉及文件**: `src/stores/model-store.ts`

**建议**: 拆分为 `model-config-store` + `agent-store` + `usage-stats-store`。

---

#### P1-5 `report-store.ts` 越界包含 analysis IPC

其 16 个 action 中包含 `listCommunityResults`、`getCascadeLevels`、`saveCommunityResult` 等社区分析相关调用，这些应属于 `community-store`。

**涉及文件**: `src/stores/report-store.ts`

**建议**: 将分析相关 IPC 调用迁移到 `community-store`。

---

#### P1-6 `shell/RightPanel.vue` 跨层依赖 report 组件

直接 import `CodeIndexPanel` 和 `ReportTaskListPanel`——shell 层不应依赖 feature 层组件。

**涉及文件**: `src/components/shell/RightPanel.vue`

**建议**: 使用动态组件注册或 composable 解析，由页面级组件注入右面板内容。

---

#### P1-7 两个 Python 后端目录并存

`backend/` (472 blocks, 旧版) 和 `backend-core/` (436 blocks, 新版) 同时存在。`backend/` 包含内联的 community_analysis/parsers/web_server（已迁移到 plugins），容易引起混淆和维护错误。

**涉及目录**: `backend/`, `backend-core/`

**建议**: 删除或归档 `backend/`，保留 `backend-core/` 为唯一后端源码。

---

#### P1-8 `window-manager.ts` 过度设计 + `updater.ts` 存根

`WindowManager` 维护 `Map<number, BrowserWindow>` 和 `broadcast()` 等多窗口 API，但实际 `MAX_WINDOWS=1`。`updater.ts` 的 `getUpdateStatus()` 始终返回 `{status:'checking'}` 硬编码。

**涉及文件**: `electron/window-manager.ts`, `electron/updater.ts`

**建议**: 简化 `WindowManager` 为单窗口；实现 `getUpdateStatus` 真实逻辑或标记为待实现。

---

### 🟡 P2 - 中

#### P2-1 `usePixiCanvas.ts` ticker 内存泄漏

`addFlowAnimation()` 中通过 `app.ticker.add()` 注册的回调从未被移除，组件卸载后持续运行。

**涉及文件**: `src/composables/usePixiCanvas.ts:193`

**建议**: 返回清理函数，在 `onUnmounted` 中调用。

---

#### P2-2 `knowledge-service.ts` JSON.parse 无防护

`adaptDoc()` 对 `d.tags` 直接调用 `JSON.parse`，若已是对象则抛出异常。

**涉及文件**: `src/services/ipc/knowledge-service.ts:10`

**建议**: 添加 `typeof d.tags === 'string'` 检查。

---

#### P2-3 空 catch 块增多 (16处)

`settings-store.ts` 贡献了 5 个空 catch（localStorage 读取），`AppShell.vue` 和 `TopBar.vue` 各 2 个。所有失败静默丢弃。

**涉及文件**: `settings-store.ts`, `AppShell.vue`, `TopBar.vue`, `StatusBar.vue`, 等

**建议**: 至少添加 `console.warn`，关键路径使用用户可见提示。

---

#### P2-4 `theme.ts` DOM 操作在 store 中

`applyThemeById()` 直接操作 `document.documentElement.style` 和 `localStorage`——破坏 SSR 兼容性和 Vue 响应式模型。`watch(theme, applyTheme)` 导致 `applyTheme` 可能被重复调用。

**涉及文件**: `src/stores/theme.ts:274-309,323`

**建议**: 将 DOM 操作移至 `App.vue` 的 `watch` 或专用 composable。

---

#### P2-5 `useD3Graph` / `useMermaidRender` 脆弱的重布局

通过先后设 `null` 再恢复原值触发 watcher——依赖 Vue 的异步调度时序。

**涉及文件**: `src/composables/useD3Graph.ts:72-77`, `src/composables/useMermaidRender.ts:58-65`

**建议**: 使用显式版本号 `ref` 或 `trigger` 函数。

---

#### P2-6 `debug.ts` 模块级副作用

在 `defineStore` 外部调用 `addLogHandler()` 注册全局日志处理器，在 SSR 或测试环境下可能导致意外行为。

**涉及文件**: `src/stores/debug.ts:26-33`

**建议**: 移至 store 的初始化 action 中延迟执行。

---

#### P2-7 硬编码 URL 仍存在 13 处

ModelFormDialog 中 Ollama/OpenAI/LM Studio 等提供商 URL 硬编码，PlantUML 仍用 `http://`。

**涉及文件**: `ModelFormDialog.vue`, `usePlantUmlRender.ts`, `exportHTML.ts`, 等

**建议**: 提取到环境变量或配置常量文件。

---

#### P2-8 `window-api.ts` 中 70 处 `any`

新增的 `window-api.ts` 几乎所有方法返回 `Promise<any>`，完全丧失类型安全。

**涉及文件**: `src/types/window-api.ts`

**建议**: 逐步用 `IPCAPI` 中的具体类型替换。

---

### 🟢 P3 - 低

| # | 问题 | 位置 |
|---|------|------|
| P3-1 | `llmClient.ts` 紧耦合 Pinia (`useSettingsStore`) | `src/services/llmClient.ts` |
| P3-2 | `render-manager.ts` 进度广播到错误任务 | `src/services/render-manager.ts:77` |
| P3-3 | `usePlantUmlRender.ts` `deflateManual` 为存根 | `src/composables/usePlantUmlRender.ts:103` |
| P3-4 | `useComponentId.ts` debug 模式非响应式 | `src/composables/useComponentId.ts` |
| P3-5 | `onboarding.ts` 硬编码 CSS 选择器 | `src/stores/onboarding.ts` |
| P3-6 | `python-bridge.ts` 子进程无心跳监控 | `electron/python-bridge.ts` |
| P3-7 | ZMQ 监听器异常后静默停止 | `electron/zmq-router.ts` |
| P3-8 | `python-bridge.ts` `checkAndKillPortOccupant` 忙等300ms | `electron/python-bridge.ts:332` |
| P3-9 | mock.ts 包含真实文件路径 | `src/utils/mock.ts` |

---

## 四、架构质量评分

| 维度 | v1 评分 | v2 评分 | 变化 | 说明 |
|------|---------|---------|------|------|
| **Store 架构** | C (45) | B (72) | +27 | report/settings 拆分成功，但 community-store 和 project 仍可优化 |
| **组件结构** | C (48) | C+ (52) | +4 | 新增 composable 复用，但大型组件未拆分 |
| **服务层** | D (35) | B (70) | +35 | IPC 服务拆分+子服务化，领域边界清晰 |
| **类型系统** | D (30) | C (45) | +15 | 新增 window-api.ts 定义，但 index/ipc 不一致未解决 |
| **Electron 安全** | C (55) | B (75) | +20 | main.js 删除，preload 增强，env 白名单 |
| **代码质量** | C (50) | B (65) | +15 | console 减少36%，工具函数提取，但 any 仍多 |
| **后端架构** | C (50) | B+ (78) | +28 | Plugin 系统 + Module 系统，关注点分离 |
| **可扩展性** | D (30) | B (72) | +42 | Plugin/Module 系统 + electron-updater |
| **综合评分** | **C (43)** | **B (66)** | **+23** | 重构效果显著，仍有余地 |

---

## 五、改进路线图

### 第一阶段 (立即修复)

| 优先级 | 任务 | 预估工时 |
|--------|------|----------|
| 🔴 | 修复 `usePlantUmlRender.ts` IPC 路径 | 0.5h |
| 🔴 | 统一 `KnowledgeDoc` 类型定义 | 1h |
| 🔴 | 清理 `analysis-service`/`backend-service` 死代码 | 0.5h |
| 🔴 | 移除 `project.ts` 死导入 (`useSettingsStore`) | 0.1h |
| 🟠 | 删除或归档 `backend/` 旧目录 | 0.2h |

### 第二阶段 (短期优化)

| 优先级 | 任务 | 预估工时 |
|--------|------|----------|
| 🟠 | 拆分 `community-store.ts` (519→2个store) | 4h |
| 🟠 | 提取 `useSearchFilter` composable (消除7+处重复) | 2h |
| 🟠 | 提取 `usePolling` composable (消除3处重复) | 1h |
| 🟠 | 统一使用 `statusBadge.ts` 替换8处重复 | 2h |
| 🟠 | 提取通用 `flattenTree` 工具函数 | 1h |
| 🟠 | 填充16个空 catch 块 | 1h |
| 🟠 | 简化 `WindowManager` (单窗口优化) | 2h |

### 第三阶段 (中期重构)

| 优先级 | 任务 | 预估工时 |
|--------|------|----------|
| 🟡 | 拆分 `SubDocViewer.vue` (960行→多个子组件) | 6h |
| 🟡 | 拆分 `ReportHome.vue` (981行) | 4h |
| 🟡 | 拆分 `ModelConfig.vue` (908行) | 4h |
| 🟡 | 拆分 `project.ts` tab 管理到组件层 | 3h |
| 🟡 | 拆分 `model-store.ts` (models/agents/usage) | 2h |
| 🟡 | 解耦 `shell/RightPanel.vue` 跨层依赖 | 2h |
| 🟡 | 迁移 `theme.ts` DOM 操作到 composable | 2h |
| 🟡 | `window-api.ts` 类型补齐 (替换 any) | 4h |

### 第四阶段 (长期演进)

| 任务 | 预估工时 |
|------|----------|
| Vue Router 添加懒加载错误边界 | 1h |
| 补充单元测试 (当前 0 个 store/composable 测试) | 持续 |
| i18n 文件按模块拆分 (~1500行/文件) | 3h |
| 后端 ZMQ 添加认证机制 | 4h |
| `python-bridge.ts` 子进程添加心跳监控 | 3h |
| 移除 `backup/` 或归档到独立仓库 | 1h |

---

## 六、项目元数据

| 指标 | v1 | v2 |
|------|----|----|
| 总源文件 (.ts/.vue) | ~152 | ~180 |
| Pinia Stores | 13 | 17 + 2 wrapper |
| 组件文件 | 65 | 60 |
| 最大组件行数 | 1200 | 981 |
| 服务层文件 | 2 | 9 |
| Composables | 6 | 8 |
| `any` 类型使用 | 290 | ~392 |
| `console.*` 调用 | 172 | 110 |
| 空 catch 块 | 8 | 16 |
| 硬编码 URL | 15 | 13 |
| ESLint-disable | 0 | 0 |
| `main.js` | 存在(风险) | 已删除 |
| `backup/` 位置 | `src/backup/` | 项目根 |
| Plugin 系统 | 无 | 6个plugin + manager |
| 后端目录 | 1个(`backend/`) | 2个(`backend/` + `backend-core/`) |
