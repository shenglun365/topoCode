# GUI 交互层设计方案 (v2 — 开发就绪版)

## 一、设计概述

基于需求文档，GUI 交互层采用 **Electron + Vue 3.5 + TypeScript + Element Plus + Tailwind CSS** 技术栈，负责界面渲染、文件管理、图表交互与动画控制面板。

本方案在 v1 基础上补充了：组件 API 规范、路由详细配置、数据流设计、状态机、核心用户旅程、开发阶段规划及测试策略。

---

## 二、模块划分与组件树

```
App.vue
├── AppShell.vue                    # 主框架 (持久布局)
│   ├── AppSidebar.vue              # 侧边导航 (5个一级菜单)
│   ├── AppHeader.vue               # 顶部工具栏
│   └── <router-view />             # 主内容区 (SPA 路由出口)
│
├── [Route: /home]  Home.vue
│   ├── ProjectImporter.vue         # 拖拽/点击导入区域
│   ├── ProjectList.vue             # 最近项目卡片列表
│   └── QuickStartGuide.vue         # 快速入门引导 (首次使用)
│
├── [Route: /analysis/:projectId]  Analysis.vue
│   ├── FileTree.vue                # 左侧文件树 (可折叠)
│   ├── AstPanel.vue                # AST 解析结果面板
│   ├── AiChatPanel.vue             # AI 对话面板 (流式渲染)
│   ├── CallChainView.vue           # 调用链关系图
│   ├── AnalysisTabs.vue            # 面板 Tab 切换容器
│   └── AnalysisToolbar.vue         # 分析工具栏 (运行/停止/刷新)
│
├── [Route: /knowledge/:projectId]  Knowledge.vue
│   ├── KnowledgeGraph.vue          # D3 知识图谱主画布
│   ├── KnowledgeNodeDetail.vue     # 节点详情侧边抽屉
│   ├── KnowledgeFilter.vue         # 节点类型/标签过滤器
│   └── KnowledgeTimeline.vue       # 架构演进时间线
│
├── [Route: /coder/:projectId?]  Coder.vue
│   ├── CodeEditor.vue              # 代码编辑器 (预留 Monaco Editor)
│   ├── AiAssistantPanel.vue        # AI 编程助手侧边栏
│   └── DiffViewer.vue              # Diff 对比视图
│
└── [Route: /user]  User.vue
    ├── AiModelConfig.vue           # AI 模型配置
    ├── GeneralSettings.vue         # 通用设置 (主题/语言/快捷键)
    ├── PluginManager.vue           # 插件管理
    └── AboutPanel.vue              # 关于信息
```

---

## 三、路由配置

```typescript
// src/router/index.ts
import { createRouter, createWebHashHistory } from 'vue-router'
import type { RouteRecordRaw } from 'vue-router'

const routes: RouteRecordRaw[] = [
  {
    path: '/',
    redirect: '/home'
  },
  {
    path: '/home',
    name: 'Home',
    component: () => import('@/views/Home.vue'),
    meta: { title: '首页', icon: 'HomeFilled', sidebar: true }
  },
  {
    path: '/analysis/:projectId',
    name: 'Analysis',
    component: () => import('@/views/Analysis.vue'),
    meta: { title: '代码分析', icon: 'DataAnalysis', sidebar: true },
    props: true
  },
  {
    path: '/knowledge/:projectId',
    name: 'Knowledge',
    component: () => import('@/views/Knowledge.vue'),
    meta: { title: '知识库', icon: 'Collection', sidebar: true },
    props: true
  },
  {
    path: '/coder/:projectId?',
    name: 'Coder',
    component: () => import('@/views/Coder.vue'),
    meta: { title: 'AI 编程助手', icon: 'Edit', sidebar: true },
    props: true
  },
  {
    path: '/user',
    name: 'User',
    component: () => import('@/views/User.vue'),
    meta: { title: '用户设置', icon: 'Setting', sidebar: true }
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/NotFound.vue'),
    meta: { title: '404', sidebar: false }
  }
]

const router = createRouter({
  history: createWebHashHistory(),  // Electron 推荐 hash 模式
  routes
})

// 全局前置守卫：无项目时限制访问
router.beforeEach((to, from, next) => {
  const projectStore = useProjectStore()
  if (to.meta.requiresProject && !projectStore.activeProjectId) {
    next('/home')
  } else {
    next()
  }
})

export default router
```

### 路由 Meta 扩展类型

```typescript
declare module 'vue-router' {
  interface RouteMeta {
    title: string
    icon?: string              // Element Plus 图标名称
    sidebar?: boolean          // 是否在侧边栏显示
    requiresProject?: boolean  // 是否需要已打开项目
  }
}
```

---

## 四、Pinia Store 详细设计

### 4.1 projectStore

```typescript
// src/stores/project-store.ts
interface ProjectInfo {
  id: string                // uuid
  name: string              // 项目名称
  path: string              // 本地绝对路径
  language: string          // 主语言标识: 'python'|'javascript'|'java'|'go'|...
  languages: string[]       // 多语言列表
  lastOpened: number        // 最后打开时间戳
  fileCount: number         // 文件总数
  size: number              // 项目大小(bytes)
}

interface ScanProgress {
  stage: 'scanning' | 'indexing' | 'done' | 'error'
  current: number
  total: number
  message: string
}

interface ProjectStoreState {
  activeProjectId: string | null
  projects: ProjectInfo[]             // 最近项目列表
  fileTree: FileNode[]                // 当前项目文件树
  scanProgress: ScanProgress | null
}

// Actions
interface ProjectStoreActions {
  openProject(): Promise<void>           // 触发 dialog:open-project IPC
  loadProject(projectId: string): Promise<void>
  closeProject(): void
  removeFromHistory(projectId: string): void
  refreshFileTree(): Promise<void>
  selectFile(filePath: string): Promise<string>  // 读取文件内容
}
```

### 4.2 analysisStore

```typescript
// src/stores/analysis-store.ts
interface AstNode {
  type: string              // 节点类型: 'function'|'class'|'import'|'variable'
  name: string              // 标识符
  location: { file: string; line: number; column: number }
  children: AstNode[]
  meta: Record<string, any>
}

interface CallEdge {
  from: string              // 调用方标识符
  to: string                // 被调用方标识符
  file: string
  line: number
}

interface AiChatMessage {
  id: string
  role: 'user' | 'assistant' | 'system'
  content: string
  timestamp: number
  streaming?: boolean       // 是否正在流式输出
  referencedFiles?: string[] // 引用的文件路径
}

interface AnalysisStoreState {
  analysisRunning: boolean
  astResult: AstNode | null
  callGraph: { nodes: string[]; edges: CallEdge[] }
  chatHistory: AiChatMessage[]
  currentQuery: string
  streamingActive: boolean
}

// Actions
interface AnalysisStoreActions {
  startAnalysis(projectId: string): Promise<void>
  stopAnalysis(): void
  askQuestion(question: string, fileContext?: string[]): Promise<void>
  clearChat(): void
}
```

### 4.3 visualizationStore

```typescript
// src/stores/visualization-store.ts
type ChartType = 'mermaid' | 'plantuml' | 'd3-animation'

interface ChartConfig {
  id: string
  type: ChartType
  title: string
  code: string              // Mermaid 代码 或 PlantUML 源码 或动画脚本
  rendered: boolean
  exportFormat: 'png' | 'svg' | 'pdf'
}

interface CanvasState {
  zoom: number              // 缩放比例 (0.1 ~ 5.0)
  panX: number
  panY: number
  selectedNodes: string[]
}

interface AnimationFrame {
  id: string
  timestamp: number
  data: any                 // D3 动画帧数据
}

interface VisualizationStoreState {
  charts: ChartConfig[]
  activeChartId: string | null
  canvas: CanvasState
  animation: {
    playing: boolean
    currentFrame: number
    totalFrames: number
    speed: number           // 播放速率 0.25x ~ 4x
    frames: AnimationFrame[]
  }
}
```

### 4.4 pluginStore

```typescript
// src/stores/plugin-store.ts
interface PluginInfo {
  id: string
  name: string              // 如 "Python AST 解析器"
  language: string          // 对应语言
  version: string
  enabled: boolean
  status: 'loaded' | 'loading' | 'error' | 'not-installed'
  errorMessage?: string
}

interface PluginStoreState {
  plugins: PluginInfo[]
  installProgress: Record<string, number>  // pluginId -> progress%
}
```

### 4.5 settingsStore

```typescript
// src/stores/settings-store.ts
type AiProvider = 'ollama' | 'lm-studio' | 'openai' | 'deepseek'

interface AiModelConfig {
  provider: AiProvider
  baseUrl: string           // API 端点
  modelName: string         // 模型名称
  apiKey: string            // 加密存储引用 (不存明文)
  temperature: number       // 0.0 ~ 2.0
  maxTokens: number
}

interface GeneralSettings {
  theme: 'light' | 'dark' | 'system'
  language: 'zh-CN' | 'en-US'
  fontSize: number          // 代码字体大小
  autoSaveInterval: number  // 自动保存间隔(秒)
}

interface SettingsStoreState {
  aiConfigs: AiModelConfig[]
  activeAiConfigId: string
  general: GeneralSettings
  privacy: {
    localOnly: boolean      // 仅使用本地模型
    telemetry: boolean      // 匿名使用数据 (默认关闭)
  }
}
```

### 4.6 持久化策略

- **localStorage** (via pinia-plugin-persistedstate):
  - `settingsStore.general` — 主题、语言等无敏感数据
  - `projectStore.projects` — 最近打开项目历史 (仅路径，不含代码)
  - `pluginStore.plugins` — 插件启用状态
- **electron.safeStorage** (加密存储):
  - `settingsStore.aiConfigs[].apiKey` — API Key 密文
- **不持久化** (内存态 / Session 级):
  - `analysisStore` — AST 结果、AI 对话、调用链
  - `visualizationStore` — 图表配置、动画状态

---

## 五、组件 API 规范

### 5.1 主框架组件

#### AppShell.vue
```
功能: 全局响应式布局容器，管理侧边栏折叠/展开
状态:
  - sidebarCollapsed: boolean  (默认 false)

Slots:
  - #sidebar  →  AppSidebar.vue
  - #header   →  AppHeader.vue
  - #default  →  <router-view />
```

#### AppSidebar.vue
```
Props:
  - collapsed: boolean          # 折叠状态
  - menuItems: MenuItem[]       # 菜单项列表

Emits:
  - @toggle-collapse
  - @navigate(routeName: string)

MenuItem 类型:
  { routeName: string; title: string; icon: string; badge?: number }
```

#### AppHeader.vue
```
Props:
  - title: string               # 当前页面标题
  - showProjectSwitcher: boolean

Emits:
  - @open-project
  - @toggle-theme

Slots:
  - #actions                    # 右侧操作按钮区
```

### 5.2 项目导入组件

#### ProjectImporter.vue
```
功能: 拖拽导入 + 点击导入 + 文件夹选择
状态机:
  IDLE → DRAGGING → VALIDATING → SCANNING → DONE
                                   ↳ ERROR (显示重试)

Props: 无 (自包含)

Emits:
  - @project-opened(projectInfo: ProjectInfo)

UI 状态:
  - IDLE: 显示导入引导卡片 (虚线边框 + 图标 + 文案)
  - DRAGGING: 边框高亮 + "松手导入" 提示
  - VALIDATING: 加载中动画
  - SCANNING: 进度条 + 文件统计实时更新
  - DONE: 跳转到分析页
  - ERROR: 错误信息 + 重试按钮
```

#### ProjectList.vue
```
功能: 最近项目卡片网格列表
Props:
  - projects: ProjectInfo[]
  - loading: boolean

Emits:
  - @select(projectId: string)
  - @remove(projectId: string)
  - @open-new

空状态: 显示 "暂无项目，请导入源码仓库开始分析"
```

### 5.3 分析视图组件

#### FileTree.vue
```
功能: 虚拟滚动文件树，支持搜索过滤 / 右键菜单
Props:
  - tree: FileNode[]            # 文件树数据
  - activeFile: string | null   # 当前选中文件路径

Emits:
  - @file-select(filePath: string)
  - @file-open(filePath: string)       # 双击/回车打开

内部状态:
  - filterQuery: string                # 搜索过滤
  - expandedDirs: Set<string>          # 展开的目录集合
  - collapsed: boolean                 # 整体折叠

性能: 使用 @tanstack/vue-virtual 渲染 >1000 节点
```

#### AstPanel.vue
```
功能: AST 解析结果树状展示 + 节点点击高亮源码
Props:
  - ast: AstNode | null
  - loading: boolean

Emits:
  - @node-click(node: AstNode)         # 点击节点，联动源码定位

UI 状态:
  - loading:  骨架屏
  - null:     "未开始分析，点击运行按钮开始"
  - empty:    "当前文件无 AST 数据" (JSON/YAML 等非代码文件)
  - data:     树状结构渲染
```

#### AiChatPanel.vue
```
功能: AI 对话面板，支持 Markdown 渲染 + 流式输出 + 代码高亮
Props:
  - messages: AiChatMessage[]
  - streaming: boolean
  - projectId: string

Emits:
  - @send(message: string, fileContext?: string[])

内部依赖:
  - marked + highlight.js 进行 Markdown → HTML 渲染
  - useStreaming() composable 处理 SSE/WebSocket 流

UI 特性:
  - 自动滚到底部 (仅当用户在底部时)
  - "停止生成" 按钮 (流式输出中可见)
  - 消息引用文件标签 (可点击跳转)
  - 空状态: "👋 你好，我可以帮你分析项目架构...\n试试: '请分析该项目的鉴权流程'"
```

#### CallChainView.vue
```
功能: D3 力导向图展示函数调用关系
Props:
  - nodes: string[]
  - edges: CallEdge[]
  - loading: boolean

Emits:
  - @node-click(nodeId: string)

交互:
  - 节点拖拽
  - 滚轮缩放
  - 悬停高亮相邻边
  - 双击节点展开/折叠子调用
```

### 5.4 可视化组件

#### MermaidRenderer.vue
```
功能: 接收 Mermaid 代码并实时渲染为 SVG
Props:
  - code: string
  - zoom: number

Emits:
  - @render-error(error: Error)
  - @rendered(svgElement: SVGElement)

内部:
  - 使用 mermaid.run() 异步渲染
  - 渲染错误时降级显示错误信息 + 源码
```

#### PlantUmlRenderer.vue
```
功能: 通过 plantuml-encoder 编码后请求远程/本地 PlantUML 服务
Props:
  - code: string
  - serverUrl: string        # PlantUML 服务器地址 (默认本地)

Emits:
  - @render-error(error: Error)

内部:
  - deflate + base64 编码
  - 生成 <img> 标签加载
```

#### D3AnimationCanvas.vue
```
功能: D3 动画画布，支持数据流模拟、模块交互演示
Props:
  - animationData: AnimationFrame[]
  - playing: boolean
  - speed: number
  - currentFrame: number

Emits:
  - @frame-change(frameIndex: number)
  - @play-state-change(playing: boolean)
  - @node-select(nodeId: string)

交互:
  - 画布缩放/平移 (d3.zoom)
  - 节点拖拽 (d3.drag)
  - 动画播放控制 (播放/暂停/快进/快退/速度调节)
```

#### ChartExporter.vue
```
功能: 通用图表导出工具
Props:
  - targetSelector: string    # CSS 选择器指向要导出的 DOM 元素
  - title: string

Emits:
  - @export-start
  - @export-done(path: string)

支持格式: PNG / SVG / PDF
```

### 5.5 插件管理组件

#### PluginManager.vue
```
功能: 插件列表 + 开关控制 + 安装进度
Props: 无 (使用 pluginStore)

内部状态:
  - 每个 PluginInfo 渲染为一行:
    [图标] 插件名 v版本  [启用开关] [状态标签] [安装/卸载按钮]

状态标签:
  - loaded:     绿色 "已加载"
  - loading:    蓝色加载图标
  - error:      红色 "错误" + Tooltip 显示错误详情
  - not-installed: 灰色 "未安装"
```

### 5.6 设置组件

#### AiModelConfig.vue
```
功能: AI 模型配置表单
Props:
  - config: AiModelConfig
  - index: number

Emits:
  - @update(config: AiModelConfig)
  - @delete(index: number)
  - @test-connection(config: AiModelConfig)

表单字段:
  - provider:  下拉选择 (Ollama / LM-Studio / OpenAI / DeepSeek)
  - baseUrl:   文本输入 (provider 为 Ollama/LM-Studio 时显示)
  - modelName: 文本输入
  - apiKey:    密码输入 (provider 为 OpenAI/DeepSeek 时显示)
  - temperature: 滑块 0.0~2.0
  - maxTokens:  数字输入

测试连接:
  - 点击 "测试连接" → loading → success/error 反馈
```

#### GeneralSettings.vue
```
功能: 通用设置表单
包含:
  - 主题切换 (light / dark / system)
  - 语言切换
  - 代码字体大小设置
  - 快捷键查看/自定义
```

---

## 六、Composables 设计

### 6.1 useIpc.ts
```typescript
// Electron IPC 通信封装
export function useIpc() {
  // 渲染进程 → 主进程 (invoke/handle 模式)
  async function invoke<T>(channel: string, ...args: any[]): Promise<T>

  // 主进程 → 渲染进程 (on/off 事件监听)
  function on<T>(channel: string, callback: (data: T) => void): void
  function off<T>(channel: string, callback: (data: T) => void): void

  return { invoke, on, off }
}
```

### 6.2 useStreaming.ts
```typescript
// AI 流式输出处理
export function useStreaming() {
  const buffer = ref('')          // 当前累积的流式文本
  const isStreaming = ref(false)

  async function startStream(url: string, payload: any): Promise<void>
  function stopStream(): void

  // 内部逻辑:
  // 1. 通过 socket.io-client 连接 WebSocket
  // 2. 接收 'ai:stream-chunk' 事件，增量更新 buffer
  // 3. 接收 'ai:stream-done' 事件，标记完成
  // 4. 支持 abort/cancel

  return { buffer, isStreaming, startStream, stopStream }
}
```

### 6.3 useFileWatch.ts
```typescript
// 文件监听
export function useFileWatch(projectPath: string) {
  const changedFiles = ref<string[]>([])

  // 通过 IPC 通知主进程开启 fs.watch
  // 主进程检测到变更后发送 'file:change' 事件
  // 渲染进程接收事件并更新 changedFiles

  function startWatch(): void
  function stopWatch(): void
  function clearChanges(): void

  return { changedFiles, startWatch, stopWatch, clearChanges }
}
```

---

## 七、数据流设计

### 7.1 项目导入完整流程

```
用户点击导入
    │
    ▼
ProjectImporter.vue
    │ emit @open-project
    ▼
useIpc().invoke('dialog:open-project')
    │
    ▼
Electron 主进程 ── dialog.showOpenDialog() ──→ 选择文件夹
    │
    ▼ (文件夹路径)
主进程 project-service.js
    │ 扫描目录, 识别语言, 统计文件
    │ 通过 webContents.send('project:scan-progress', progress)
    ▼
渲染进程 projectStore.scanProgress 更新
    │
    ▼ (扫描完成)
projectStore.projects.push(newProjectInfo)
    │
    ▼
router.push('/analysis/' + projectId)
```

### 7.2 AI 分析流程

```
AiChatPanel.vue ──emit @send(question)──→ analysisStore.askQuestion()
    │
    ▼
useIpc().invoke('analysis:start', { projectId, question, fileContext })
    │
    ▼
Electron 主进程 python-bridge.js
    │ HTTP POST → Python 后端 /api/analyze
    ▼
Python 后端
    │ 1. 构建 Prompt + 代码上下文
    │ 2. 调用 AI 模型 (Ollama / OpenAI / ...)
    │ 3. 流式响应 → WebSocket
    ▼
Electron 主进程 ←── WebSocket ←── Python 后端
    │ webContents.send('ai:stream-chunk', chunk)
    ▼
渲染进程 useStreaming().buffer 更新
    │
    ▼
AiChatPanel.vue 实时渲染 Markdown
    │
    ▼ (流结束)
analysisStore.messages[last].streaming = false
```

### 7.3 可视化渲染流程

```
分析结果 (AST / AI) 
    │
    ▼
visualizationStore 生成图表代码
    │
    ├── MermaidRenderer    ← code(mermaid语法)
    │       └── mermaid.run() → SVG DOM
    │
    ├── PlantUmlRenderer   ← code(plantuml语法)
    │       └── plantuml-encoder → <img src="...">
    │
    └── D3AnimationCanvas  ← animationData
            └── D3.js enter/update/exit → SVG animation
```

---

## 八、Electron IPC 协议完整清单

### 8.1 渲染进程 → 主进程 (invoke/handle)

| Channel | 请求参数 | 返回类型 |
|---|---|---|
| `dialog:open-project` | — | `ProjectInfo \| null` |
| `dialog:select-file` | `{ filters?: FileFilter[] }` | `string \| null` |
| `dialog:save-file` | `{ defaultName: string; filters?: FileFilter[] }` | `string \| null` |
| `fs:read-directory` | `{ path: string; recursive?: boolean }` | `FileNode[]` |
| `fs:read-file` | `{ path: string; encoding?: string }` | `string` |
| `analysis:start` | `{ projectId: string; question?: string; fileContext?: string[] }` | `{ taskId: string }` |
| `analysis:stop` | `{ taskId: string }` | `void` |
| `plugin:toggle` | `{ pluginId: string; enabled: boolean }` | `void` |
| `plugin:install` | `{ pluginId: string }` | `void` |
| `python:get-status` | — | `{ running: boolean; port: number; version: string }` |
| `python:restart` | — | `void` |
| `settings:set-ai-config` | `{ config: AiModelConfig }` | `void` |
| `settings:test-connection` | `{ config: AiModelConfig }` | `{ success: boolean; latency: number; error?: string }` |
| `storage:encrypt` | `{ plaintext: string }` | `string` (密文) |
| `storage:decrypt` | `{ encrypted: string }` | `string` (明文) |
| `export:chart` | `{ selector: string; format: string; path: string }` | `void` |

### 8.2 主进程 → 渲染进程 (webContents.send)

| Channel | 数据 |
|---|---|
| `project:scan-progress` | `ScanProgress` |
| `project:scan-complete` | `ProjectInfo` |
| `ai:stream-chunk` | `{ taskId: string; chunk: string; done: boolean }` |
| `plugin:status-change` | `{ pluginId: string; status: PluginStatus }` |
| `file:change` | `{ path: string; event: 'add' \| 'change' \| 'unlink' }` |

---

## 九、Python 后端通信方案

```
┌────────────────────┐       HTTP (localhost:PORT)       ┌────────────────────┐
│   Electron 主进程   │ ◄───────────────────────────────► │  Python 后端        │
│   python-bridge.js  │                                   │  (FastAPI)          │
│                    │       WebSocket                  │                    │
│                    │ ◄───────────────────────────────► │  /ws/stream        │
└────────────────────┘                                   └────────────────────┘
```

### HTTP API 端点

| Method | Path | 用途 |
|---|---|---|
| `GET` | `/health` | 健康检查 |
| `POST` | `/api/ast/parse` | AST 解析 |
| `POST` | `/api/ast/call-graph` | 调用链分析 |
| `POST` | `/api/ai/analyze` | AI 分析 (阻塞) |
| `POST` | `/api/ai/chat` | AI 对话 (返回 taskId) |
| `DELETE` | `/api/ai/chat/:taskId` | 取消 AI 任务 |

### WebSocket 事件

| 事件 | 方向 | 数据 |
|---|---|---|
| `stream:chunk` | Server → Client | `{ taskId, delta, index }` |
| `stream:done` | Server → Client | `{ taskId, fullText }` |
| `stream:error` | Server → Client | `{ taskId, error }` |
| `stream:cancel` | Client → Server | `{ taskId }` |
| `progress:update` | Server → Client | `{ stage, percent, message }` |

### 启动策略

- 主进程启动时 spawn Python FastAPI 子进程，随机端口
- 主进程等待 `/health` 返回 200 后通知渲染进程
- 主进程退出时 kill Python 子进程

---

## 十、关键用户旅程

### 10.1 首次使用 → 首次分析

```
1. 用户启动应用
2. 进入 /home，看到 QuickStartGuide + 空白导入区域
3. 点击 "导入项目" → 系统弹出文件夹选择对话框
4. 用户选择项目文件夹 → 显示扫描进度条
5. 扫描完成 → 自动跳转到 /analysis/{id}
6. 左侧显示文件树，右侧显示分析引导
7. 用户点击文件树中的一个 .py 文件
8. AST 面板加载该文件的语法树
9. 用户在 AI 聊天面板输入: "请分析该项目的鉴权流程"
10. AI 流式返回分析结果 (Markdown 渲染)
11. 用户点击 "生成调用链图" → CallChainView 展示力导向图
```

### 10.2 可视化图表导出

```
1. 用户在 Analysis 页查看 AI 生成的架构图
2. 点击图表右上角 "导出" 按钮
3. 弹出格式选择下拉: PNG / SVG / PDF
4. 选择 PNG → 系统弹出保存对话框
5. 用户选择保存路径 → 导出完成提示 "图表已导出至 ..."
```

### 10.3 插件管理

```
1. 用户进入 /user → 切换到 "插件管理" Tab
2. 看到已安装插件列表 (Python AST、JavaScript AST)
3. 发现 Java AST 显示 "未安装"
4. 点击 "安装" → 显示安装进度
5. 安装完成 → 自动启用
6. 下次分析 Java 项目时自动加载该插件
```

### 10.4 模型切换

```
1. 用户进入 /user → AI 模型配置
2. 当前使用的配置: "Ollama - qwen2.5-coder:7b"
3. 用户点击 "添加配置" → 选择 "OpenAI"
4. 填入 API Key 和模型名 "gpt-4o"
5. 点击 "测试连接" → 显示延迟 320ms ✅
6. 点击 "设为默认"
7. 下次 AI 分析使用新模型
```

---

## 十一、开发阶段规划

### Phase 1: 基础设施搭建 (Foundation)
**目标**: 可启动的 Electron + Vue + Vite + Tailwind 骨架

| 任务 | 产物 |
|---|---|
| 1.1 创建 `vite.config.ts` + `tsconfig.json` + `tailwind.config.js` + `postcss.config.js` | 构建配置就绪 |
| 1.2 创建 `electron/main.js` (从根目录迁移) + `electron/preload.js` | Electron 主进程基本可运行 |
| 1.3 创建 `src/App.vue` + `src/router/` + `src/styles/` | Vue 路由骨架 |
| 1.4 创建 `src/components/shell/` (AppShell, AppSidebar, AppHeader) | 主框架布局可用 |
| 1.5 创建 5 个占位视图 (`Home.vue`, `Analysis.vue`, 等) | 路由跳转验证通过 |

**验收**: `npm run dev` 成功启动，5 个页签切换正常，暗/亮主题切换正常。

### Phase 2: 项目导入模块 (Project Import)
**目标**: 导入本地代码仓库并持久化历史

| 任务 | 产物 |
|---|---|
| 2.1 实现 `electron/services/project-service.js` | 文件扫描、语言识别 |
| 2.2 实现 IPC 通道 `dialog:open-project`, `fs:read-directory` | 主进程文件操作能力 |
| 2.3 创建 `src/stores/project-store.ts` | Pinia 状态管理 |
| 2.4 创建 `src/components/project/ProjectImporter.vue` | 拖拽/点击导入 UI |
| 2.5 创建 `src/components/project/ProjectList.vue` | 最近项目列表 |
| 2.6 实现 `src/views/Home.vue` 完整首页 | 首页完整可用 |

**验收**: 可导入项目，扫描进度显示正常，最近项目列表持久化。

### Phase 3: 代码分析视图 (Analysis View)
**目标**: 文件树 + AST 面板 + AI 对话面板

| 任务 | 产物 |
|---|---|
| 3.1 创建 `src/components/analysis/FileTree.vue` (含虚拟滚动) | 文件树组件 |
| 3.2 创建 `src/components/analysis/AstPanel.vue` | AST 面板组件 |
| 3.3 实现 IPC `fs:read-file` + `analysis:start`/`stop` | 分析通道 |
| 3.4 创建 `electron/services/python-bridge.js` | Python 通信桥 |
| 3.5 创建 `src/composables/useIpc.ts` + `useStreaming.ts` | IPC/流式处理封装 |
| 3.6 创建 `src/stores/analysis-store.ts` | 分析状态管理 |
| 3.7 创建 `src/components/analysis/AiChatPanel.vue` | AI 对话面板 |
| 3.8 创建 `src/views/Analysis.vue` 完整页面 | 分析页完整可用 |

**验收**: 可浏览文件树，查看 AST 结果，向 AI 提问并获得流式响应。

### Phase 4: 可视化渲染 (Visualization)
**目标**: Mermaid/PlantUML 渲染 + D3 动画引擎基础

| 任务 | 产物 |
|---|---|
| 4.1 创建 `src/components/visualization/MermaidRenderer.vue` | Mermaid 渲染 |
| 4.2 创建 `src/components/visualization/PlantUmlRenderer.vue` | PlantUML 渲染 |
| 4.3 创建 `packages/animation-engine/` 子包 (D3 引擎) | 动画引擎 |
| 4.4 创建 `src/components/visualization/D3AnimationCanvas.vue` | D3 画布 |
| 4.5 创建 `src/components/visualization/ChartExporter.vue` | 图表导出 |
| 4.6 创建 `src/stores/visualization-store.ts` | 可视化状态管理 |
| 4.7 创建 `src/components/analysis/CallChainView.vue` | 调用链力导向图 |

**验收**: Mermaid/PlantUML 代码正确渲染，D3 画布可缩放平移，可导出 PNG。

### Phase 5: 设置与插件管理 (Settings & Plugins)
**目标**: AI 模型配置、通用设置、插件管理

| 任务 | 产物 |
|---|---|
| 5.1 创建 `src/stores/settings-store.ts` | 设置状态管理 (含持久化) |
| 5.2 创建 `src/components/settings/AiModelConfig.vue` | AI 模型配置表单 |
| 5.3 创建 `src/components/settings/GeneralSettings.vue` | 通用设置表单 |
| 5.4 创建 `src/stores/plugin-store.ts` | 插件状态管理 |
| 5.5 创建 `src/components/plugins/PluginManager.vue` | 插件管理面板 |
| 5.6 创建 `src/views/User.vue` 完整设置页 | 设置页完整可用 |

**验收**: 可配置多模型并切换，连接测试可用，插件启用/禁用生效。

### Phase 6: Coder 与 Knowledge 视图 (增强功能)
**目标**: AI 编程助手 + 知识库视图

| 任务 | 产物 |
|---|---|
| 6.1 创建 `src/views/Coder.vue` + 子组件 | AI 编程助手页 |
| 6.2 创建 `src/views/Knowledge.vue` + 子组件 | 知识库页 |

### Phase 7: 安全加固与打包
**目标**: 安全措施 + 跨平台打包

| 任务 |
|---|
| 7.1 实现 safeStorage API Key 加密 |
| 7.2 配置 CSP 策略 |
| 7.3 文件系统访问白名单 |
| 7.4 electron-builder 配置调优 |
| 7.5 多平台构建测试 |

---

## 十二、实现优先级矩阵

```
                  高影响
                    │
    Phase 1        │   Phase 3, Phase 4
    (基础骨架)     │   (分析 + 可视化)
                    │
  ─────────────────┼──────────────────
                    │
    Phase 5        │   Phase 6, Phase 7
    (设置+插件)    │   (增强 + 打包)
                    │
                  低影响

  低紧迫 ────────────────────── 高紧迫
```

**推荐实施顺序**: Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 7 → Phase 6

---

## 十三、配置文件创建清单 (Phase 1 详细)

Phase 1 需要创建以下配置文件：

| 文件 | 类型 | 说明 |
|---|---|---|
| `tsconfig.json` | TypeScript 配置 | 路径别名 `@/` → `src/` |
| `vite.config.ts` | Vite 构建配置 | Vue 插件 + Electron 外部化 |
| `tailwind.config.js` | Tailwind 配置 | 内容路径 + 主题扩展 |
| `postcss.config.js` | PostCSS 配置 | Tailwind + Autoprefixer |
| `src/env.d.ts` | 类型声明 | `.vue` 文件模块声明 |
| `.gitignore` | Git 忽略 | node_modules, dist, .env 等 |
| `electron/main.js` | 迁移 + 重写 | 从根目录迁入 /electron |
| `electron/preload.js` | 预加载脚本 | contextBridge 暴露 IPC API |
| `src/main.ts` | Vue 入口 | createApp + Router + Pinia + ElementPlus |

---

## 十四、测试策略

### 14.1 单元测试

| 测试对象 | 框架 | 覆盖要点 |
|---|---|---|
| Pinia Stores | Vitest | Action 调用链、状态变更正确性 |
| Composables | Vitest + @vue/test-utils | IPC mock、流式数据模拟 |
| 工具函数 | Vitest | 语言识别、路径解析、Mermaid 代码生成 |

### 14.2 组件测试

| 测试对象 | 覆盖要点 |
|---|---|
| ProjectImporter | 拖拽事件、文件夹选择、进度展示、错误状态 |
| FileTree | 虚拟滚动行数、过滤筛选、展开折叠 |
| AiChatPanel | 消息渲染、流式追加、Markdown 转换、空状态 |
| MermaidRenderer | 代码→SVG 渲染、错误降级 |

### 14.3 E2E 测试 (Playwright + Electron)

| 场景 | 步骤 |
|---|---|
| 首次导入项目 | 启动 → 点击导入 → 选择文件夹 → 验证跳转分析页 |
| AI 对话 | 输入问题 → 等待流式响应 → 验证 Markdown 渲染 |
| 主题切换 | 点击主题按钮 → 验证 CSS 变量切换 → 持久化验证 |
| 图表导出 | 点击导出 → 选择 PNG → 验证文件生成 |

---

## 十五、目录结构 (完整最终版)

```
topoOne-ui/
├── electron/                     # Electron 主进程
│   ├── main.js                   # 主进程入口 (窗口管理)
│   ├── preload.js                # 预加载脚本 (contextBridge)
│   └── services/
│       ├── project-service.js    # 项目文件扫描、语言识别
│       ├── plugin-service.js     # 插件加载、状态管理
│       └── python-bridge.js      # Python 子进程管理与 HTTP/WS 转发
├── src/
│   ├── main.ts                   # Vue 应用入口
│   ├── App.vue                   # 根组件
│   ├── env.d.ts                  # 全局类型声明
│   ├── router/
│   │   └── index.ts              # 路由配置
│   ├── stores/
│   │   ├── project-store.ts
│   │   ├── analysis-store.ts
│   │   ├── visualization-store.ts
│   │   ├── plugin-store.ts
│   │   └── settings-store.ts
│   ├── composables/
│   │   ├── useIpc.ts
│   │   ├── useStreaming.ts
│   │   └── useFileWatch.ts
│   ├── views/
│   │   ├── Home.vue
│   │   ├── Analysis.vue
│   │   ├── Knowledge.vue
│   │   ├── Coder.vue
│   │   ├── User.vue
│   │   └── NotFound.vue
│   ├── components/
│   │   ├── shell/
│   │   │   ├── AppShell.vue
│   │   │   ├── AppSidebar.vue
│   │   │   └── AppHeader.vue
│   │   ├── project/
│   │   │   ├── ProjectImporter.vue
│   │   │   └── ProjectList.vue
│   │   ├── analysis/
│   │   │   ├── FileTree.vue
│   │   │   ├── AstPanel.vue
│   │   │   ├── AiChatPanel.vue
│   │   │   ├── CallChainView.vue
│   │   │   ├── AnalysisTabs.vue
│   │   │   └── AnalysisToolbar.vue
│   │   ├── visualization/
│   │   │   ├── MermaidRenderer.vue
│   │   │   ├── PlantUmlRenderer.vue
│   │   │   ├── D3AnimationCanvas.vue
│   │   │   └── ChartExporter.vue
│   │   ├── plugins/
│   │   │   └── PluginManager.vue
│   │   └── settings/
│   │       ├── AiModelConfig.vue
│   │       └── GeneralSettings.vue
│   ├── styles/
│   │   ├── main.css              # Tailwind 入口
│   │   ├── variables.css         # CSS 变量 (主题色)
│   │   └── transitions.css       # 路由过渡动画
│   └── utils/
│       ├── constants.ts          # IPC 通道名常量
│       ├── types.ts              # 共享类型定义
│       └── format.ts             # 格式化工具函数
├── packages/
│   ├── animation-engine/         # D3 教学动画引擎 (独立子包)
│   └── compiler-service/         # 编译器服务 (独立子包)
├── docs/
│   ├── 需求文档.md
│   └── GUI交互层设计方案.md
├── index.html                    # Vite 入口 HTML
├── package.json
├── tsconfig.json
├── vite.config.ts
├── tailwind.config.js
├── postcss.config.js
├── .gitignore
└── .eslintrc.cjs
```

---

## 十六、与需求文档的对应关系

| 需求功能 | GUI 模块 | 核心组件 |
|---|---|---|
| 项目导入与语言识别 | Project Import (Phase 2) | ProjectImporter, ProjectList |
| AST 静态分析 | Analysis View (Phase 3) | FileTree, AstPanel |
| AI 语义分析 + 问答 | Analysis View (Phase 3) | AiChatPanel, useStreaming |
| 调用链/依赖图 | Analysis View (Phase 4) | CallChainView |
| 图表渲染 (Mermaid/PlantUML) | Visualization (Phase 4) | MermaidRenderer, PlantUmlRenderer |
| 教学动画演示 | Visualization (Phase 4) | D3AnimationCanvas |
| 图表导出 | Visualization (Phase 4) | ChartExporter |
| 插件化管理 | Plugin Manager (Phase 5) | PluginManager |
| AI 模型配置与切换 | Settings (Phase 5) | AiModelConfig |
| 本地模型隐私保障 | Settings + Electron (Phase 5,7) | safeStorage + CSP |
| 流式输出性能 | Composables (Phase 3) | useStreaming, WebSocket |
| 知识库 | Knowledge (Phase 6) | KnowledgeGraph |
| AI 编程助手 | Coder (Phase 6) | CodeEditor, AiAssistantPanel |
