/** IPC 类型定义 - ZeroMQ 消息队列通讯协议 */

// ==================== ZeroMQ 消息格式 ====================

/** ZeroMQ 请求帧 */
export interface ZMQRequest {
  identity: string            // 后端标识 (core/agent-1/agent-N)
  requestId: string           // 唯一请求 ID
  method: string              // 方法名 (模块.操作)
  params: Record<string, any> // 参数
}

/** ZeroMQ 响应帧 */
export interface ZMQResponse<T = any> {
  requestId: string           // 对应请求 ID
  result: T | null            // 成功结果
  error: ZMQError | null      // 错误信息
}

/** ZeroMQ 错误 */
export interface ZMQError {
  code: number
  message: string
  data?: any
}

/** ZeroMQ 事件消息 */
export interface ZMQEvent {
  topic: string               // 主题 (task/project/backend)
  eventType: string           // 事件类型 (progress/complete/error)
  data: Record<string, any>   // 事件数据
  timestamp: number           // 时间戳
}

// ==================== 业务数据类型 ====================

/** 项目 */
export interface Project {
  id: string
  name: string
  path: string        // 兼容旧字段
  rootPath?: string   // 新字段：源码根目录
  language: string
  fileCount: number
  status: 'synced' | 'syncing' | 'error'
  needsResync?: number    // 路径变更标志
  hasFileChanges?: number // 内容变更标志
  isSample?: number       // 示例项目标志
  lastSync: string | null
  createdAt: string
  fileTree?: FileTreeNode[]
}

/** 文件树节点 */
export interface FileTreeNode {
  name: string
  type: 'file' | 'directory'
  language?: string
  size?: number
  children?: FileTreeNode[]
}

/** 分析任务 */
export interface AnalysisTask {
  id: string
  projectId: string
  type: 'full-parse' | 'ast-gen' | 'call-chain' | 'dataflow' | 'dep-analysis'
  name: string
  status: 'done' | 'running' | 'pending' | 'error' | 'stopped'
  progress?: number
  total?: number
  current?: number
  error?: string | null
  createdAt: string
  updatedAt: string
  favorite?: boolean
  pinned?: boolean
  tags?: string[]
  // 分析配置
  scope?: string           // 分析根目录
  extensions?: string[]    // 文件后缀过滤
  excludeDirs?: string[]   // 排除目录
  reportTypes?: string[]   // ['dependency', 'callChain', 'dataFlow']
}

/** 文件统计结果 */
export interface FileStatsResult {
  extensions: Record<string, number>   // { "python": 128, "javascript": 56 }
  totalFiles: number
  totalDirs: number
  directories: string[]
}

/** 扫描选项 */
export interface ScanOptions {
  scope?: string
  patternType?: 'all' | 'glob' | 'regex'
  pattern?: string
  excludeDirs?: string[]
}

/** 任务日志条目 */
export interface TaskLogEntry {
  timestamp: string
  message: string
}

/** 任务日志结果 */
export interface TaskLogsResult {
  logs: TaskLogEntry[]
  completed: boolean
}

/** 任务配置更新 */
export interface TaskConfigUpdate {
  name?: string
  scope?: string
  extensions?: string[]
  excludeDirs?: string[]
  reportTypes?: string[]
}

/** 分析结果 */
export interface AnalysisResult {
  ast?: any
  callChain?: CallChainItem[]
  dependencies?: {
    modules: string[]
    files: string[]
  }
  dataflow?: DataFlowItem[]
}

export interface CallChainItem {
  from: string
  to: string
  function: string
}

export interface DataFlowItem {
  source: string
  target: string
  data: string
}

/** 知识文档 */
export interface KnowledgeDoc {
  id: string
  title: string
  type: 'document' | 'project'
  description: string
  content: string
  projectId: string
  tags: {
    lifecycle: string[]
    techStack: string[]
    abstraction: string[]
    purpose: string[]
  }
  status: 'draft' | 'pending' | 'reviewed'
  favorite: boolean
  pinned: boolean
  createdAt: string
  updatedAt: string
}

/** 知识图谱 */
export interface KnowledgeGraph {
  nodes: KnowledgeGraphNode[]
  edges: KnowledgeGraphEdge[]
}

export interface KnowledgeGraphNode {
  id: string
  label: string
  type: 'module' | 'class' | 'function' | 'knowledge'
  x: number
  y: number
  color: string
}

export interface KnowledgeGraphEdge {
  from: string
  to: string
  type: 'dependency' | 'reference'
}

/** 四维分类 */
export interface Dimensions {
  lifecycle: string[]
  techStack: string[]
  abstraction: string[]
  purpose: string[]
}

/** 模型配置 */
export interface ModelConfigItem {
  id: string
  name: string
  provider: 'ollama' | 'openai' | 'lmstudio' | 'custom'
  model: string
  url: string
  type: 'local' | 'cloud'
  status: 'connected' | 'offline' | 'error'
  isDefault: boolean
  temperature?: number
  maxTokens?: number
  latency?: number
}

/** Agent 配置 */
export interface AgentConfigItem {
  id: string
  name: string
  path: string
  args: string
  status: 'online' | 'offline' | 'not-detected' | 'not-configured'
  version?: string
  isDefault: boolean
}

/** SKILL 配置 */
export interface SkillConfigItem {
  id: string
  name: string
  description: string
  enabled: boolean
}

/** 后端状态 */
export interface BackendStatus {
  status: 'running' | 'stopped' | 'error' | 'restarting'
  pid?: number
  port?: number
  error?: string | null
}

// ==================== 事件推送类型 ====================

export interface TaskProgressEvent {
  taskId: string
  progress: number
  total: number
  current: number
  status: string
}

export interface TaskCompleteEvent {
  taskId: string
  status: string
  progress: number
}

export interface TaskErrorEvent {
  taskId: string
  status: string
  error: string
}

export interface ProjectSyncedEvent {
  projectId: string
  fileCount: number
}

export interface BackendStatusEvent {
  status: string
  pid?: number
  port?: number
}

// ==================== Preload API 类型 ====================

/**
 * IPC API 接口
 * 
 * 当前阶段: 浏览器开发环境使用 mock 实现
 * 后续阶段: Electron 环境通过 window.api 调用 ZeroMQ
 */
export interface IPCAPI {
  // 项目管理
  project: {
    list: () => Promise<Project[]>
    import: (path: string) => Promise<Project>
    get: (id: string) => Promise<Project>
    remove: (id: string) => Promise<void>
    sync: (id: string) => Promise<Project>
    getFileTree: (id: string, fromPath?: string | null) => Promise<FileTreeNode[]>
    updatePath: (id: string, newRootPath: string) => Promise<{ project: Project; invalidFiles: string[]; needsResync: boolean }>
    checkFileChanges: (id: string) => Promise<{ added: string[]; modified: string[]; deleted: string[]; hasChanges: boolean }>
    initSampleData: () => Promise<{ project: Project }>
    clearSampleData: (id: string) => Promise<{ success: boolean }>
  }

  // 代码分析
  analysis: {
    listTasks: (projectId: string) => Promise<AnalysisTask[]>
    createTask: (params: { projectId: string; type: string; name: string; scope?: string; extensions?: string[]; excludeDirs?: string[]; reportTypes?: string[] }) => Promise<AnalysisTask>
    runTask: (taskId: string) => Promise<{ taskId: string; status: string }>
    getTask: (taskId: string) => Promise<AnalysisTask>
    getResults: (taskId: string) => Promise<AnalysisResult>
    updateTask: (params: { taskId: string; favorite?: boolean; pinned?: boolean; tags?: string[] }) => Promise<AnalysisTask>
    deleteTask: (taskId: string) => Promise<void>
    stopTask: (taskId: string) => Promise<void>
    reRunTask: (taskId: string) => Promise<AnalysisTask>
    getTaskLogs: (taskId: string) => Promise<TaskLogsResult>
    updateTaskConfig: (params: { taskId: string; config: TaskConfigUpdate }) => Promise<AnalysisTask>
    scanFileStats: (projectId: string, options?: ScanOptions) => Promise<FileStatsResult>
    onProgress: (cb: (data: TaskProgressEvent) => void) => void
    onComplete: (cb: (data: TaskCompleteEvent) => void) => void
    onError: (cb: (data: TaskErrorEvent) => void) => void
  }

  // 知识库
  knowledge: {
    listDocs: (params: { search?: string; dimensions?: Partial<Dimensions>; sortBy?: string }) => Promise<KnowledgeDoc[]>
    createDoc: (params: { title: string; content: string; projectId: string; tags?: Partial<Dimensions> }) => Promise<KnowledgeDoc>
    getDoc: (id: string) => Promise<KnowledgeDoc>
    updateDoc: (params: { id: string; content?: string; tags?: Partial<Dimensions>; status?: string; favorite?: boolean; pinned?: boolean }) => Promise<KnowledgeDoc>
    deleteDoc: (id: string) => Promise<void>
    getGraph: (params?: { projectId?: string }) => Promise<KnowledgeGraph>
    getDimensions: () => Promise<Dimensions>
  }

  // 设置配置
  settings: {
    getModels: () => Promise<ModelConfigItem[]>
    addModel: (params: { name: string; provider: string; model: string; url: string; type: string; temperature?: number; maxTokens?: number }) => Promise<ModelConfigItem>
    updateModel: (params: { id: string; name?: string; temperature?: number; maxTokens?: number }) => Promise<ModelConfigItem>
    removeModel: (id: string) => Promise<void>
    testModel: (id: string) => Promise<{ status: string; latency: number; model: string }>
    getAgents: () => Promise<AgentConfigItem[]>
    addAgent: (params: { name: string; path: string; args: string }) => Promise<AgentConfigItem>
    updateAgent: (params: { id: string; path?: string; args?: string }) => Promise<AgentConfigItem>
    removeAgent: (id: string) => Promise<void>
    detectAgent: (id: string) => Promise<{ status: string; version?: string }>
    getSkills: () => Promise<SkillConfigItem[]>
    updateSkill: (params: { id: string; enabled: boolean }) => Promise<SkillConfigItem>
    getBindings: () => Promise<Record<string, string>>
    updateBindings: (params: { bindings: Record<string, string> }) => Promise<Record<string, string>>
  }

  // 后端管理
  backend: {
    start: () => Promise<void>
    stop: () => Promise<void>
    restart: () => Promise<void>
    getStatus: () => Promise<BackendStatus>
    onStatusChange: (cb: (data: BackendStatusEvent) => void) => void
  }

  // 系统
  system: {
    selectDirectory: () => Promise<string>
    getAppDataPath: () => Promise<string>
    get: (key: string) => Promise<any>
    set: (key: string, val: any) => Promise<void>
  }
}

// ==================== Window 扩展 ====================

declare global {
  interface Window {
    api?: IPCAPI
  }
}

export {}
