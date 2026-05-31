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
  group?: string          // 项目分组（兼容旧字段）
  groups?: string[]       // 项目所属分组名称列表（M:N）
  favorite?: number       // 收藏标记 (0/1)
  pinned?: number         // 置顶标记 (0/1)
  sortOrder?: number      // 排序权重
  doneTaskCount?: number  // 已完成分析任务数（含各报告类型）
  lastSync: string | null
  createdAt: string
  fileTree?: FileTreeNode[]
}

/** 文件树节点 */
export interface FileTreeNode {
  name: string
  type: 'file' | 'directory'
  path?: string
  language?: string
  size?: number
  is_empty?: boolean       // 后端标记：是否为空目录（无文件，只有空子目录）
  compressedPath?: string  // 压缩显示路径，如 "java/main/com/example"
  children?: FileTreeNode[]
}

/** 分组（树形结构） */
export interface GroupNode {
  id: string
  name: string
  parentId: string | null
  depth: number
  sortOrder: number
  createdAt: string
  children?: GroupNode[]
}

/** 分析任务 */
export interface AnalysisTask {
  id: string
  projectId: string
  type: 'full-parse' | 'ast-gen' | 'call-chain' | 'dataflow' | 'dep-analysis'
  name: string
  status: 'done' | 'running' | 'pending' | 'modified' | 'error' | 'cancelled'
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
  scope?: string           // 分析根目录 (旧字段)
  scopes?: string[]        // 多选目录 (新字段)
  extensions?: string[]    // 文件后缀过滤
  excludeDirs?: string[]   // 排除目录
  reportTypes?: string[]   // ['dependency', 'callChain', 'dataFlow']
  // 运行统计
  configVersion?: number   // 配置版本号
  lastRunId?: string       // 最后一次运行的 ID
  runCount?: number        // 运行次数
  lastRunStatus?: string   // 最后一次运行状态
  lastRunNumber?: number   // 最后一次运行序号
}

/** 任务运行记录 */
export interface TaskRun {
  id: string
  taskId: string
  runNumber: number
  status: 'running' | 'done' | 'error' | 'cancelled'
  progress: number
  total: number
  current: number
  error?: string | null
  startedAt: string
  finishedAt?: string
  durationMs?: number
  // 配置快照
  snapshotScope?: string[]
  snapshotExtensions?: string[]
  snapshotExcludeDirs?: string[]
  snapshotReportTypes?: string[]
}

/** 目录树节点 */
export interface DirTreeNode {
  name: string
  path: string
  children: DirTreeNode[]
}

/** 文件统计结果 */
export interface FileStatsResult {
  extensions: Record<string, number>   // { "python": 128, "javascript": 56 }
  totalFiles: number
  totalDirs: number
  directories: DirTreeNode[]
}

/** 扫描选项 */
export interface ScanOptions {
  scopes?: string[]          // 多选目录 (新增)
  scope?: string             // 单选目录 (保留兼容)
  selectedExtensions?: string[] // 选中的扩展名 (新增)
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
  scope?: string          // 旧字段，保留兼容
  scopes?: string[]       // 多选目录
  extensions?: string[]
  excludeDirs?: string[]
  reportTypes?: string[]
  patternType?: string    // 匹配模式：all | glob | regex
  pattern?: string        // 匹配表达式
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

/** 流水线任务节点（动态树结构） */
export interface PipelineTaskNode {
  id: string
  label: string
  type: 'group' | 'step' | 'subtask'
  status: 'pending' | 'running' | 'completed' | 'error' | 'skipped'
  progress: number
  children?: PipelineTaskNode[]
  error?: string
  templateId?: string
  dependsOn?: string[]
}

/** 流水线控制函数 */
export interface PipelineControlFunctions {
  runAll: () => Promise<void>
  runNode: (nodeId: string) => Promise<void>
  pause: () => void
  resume: () => void
  reset: () => void
  stop: () => void
}

/** 流水线状态 */
export interface PipelineState {
  rootTask: PipelineTaskNode
  currentPhase: 'validating' | 'preprocessing' | 'community_analysis' | 'step1' | 'step2' | 'step3' | 'step4' | 'step5' | 'done' | 'error'
  overallProgress: number
  startedAt: string
  completedAt?: string
}

/** 模型配置 */
export interface ModelConfigItem {
  id: string
  name: string
  provider: 'ollama' | 'openai' | 'lm-studio' | 'custom'
  model: string
  url: string
  type: 'local' | 'cloud'
  status: 'connected' | 'offline' | 'error'
  isDefault: boolean
  temperature?: number
  maxTokens?: number
  latency?: number
  apiKey?: string
  maxRequestsPerDay?: number
  maxTokensPerDay?: number
}

/** 模型每日用量统计 */
export interface UsageStatItem {
  id: number
  modelId: string
  modelName: string
  date: string
  requestCount: number
  promptTokens: number
  completionTokens: number
  totalTokens: number
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
    updateMeta: (id: string, meta: Record<string, any>) => Promise<Project>
    initSampleData: () => Promise<{ project: Project }>
    clearSampleData: (id: string) => Promise<{ success: boolean }>
    checkPathValidity: (id: string) => Promise<{ pathValid: boolean; rootPath: string; needsResync: boolean }>
    getStorageStats: (projectId: string) => Promise<{ projectId: string; dbSize: number; dbFileSize: number; walSize: number; shmSize: number; sourceSize: number }>
  }

  // 分组管理
  group: {
    list: () => Promise<GroupNode[]>
    create: (name: string, parentId?: string | null) => Promise<{ id: string; name: string; parentId: string | null; depth: number }>
    update: (id: string, name?: string, parentId?: string | null) => Promise<{ success: boolean }>
    delete: (id: string) => Promise<{ success: boolean }>
    addProject: (projectId: string, groupId: string) => Promise<{ success: boolean }>
    removeProject: (projectId: string, groupId: string) => Promise<{ success: boolean }>
    getProjectGroups: (projectId: string) => Promise<GroupNode[]>
  }

  // 代码分析
  analysis: {
    listTasks: (projectId: string) => Promise<AnalysisTask[]>
    createTask: (params: { projectId: string; type: string; name: string; scope?: string; scopes?: string[]; extensions?: string[]; excludeDirs?: string[]; reportTypes?: string[] }) => Promise<AnalysisTask>
    runTask: (taskId: string) => Promise<{ taskId: string; status: string }>
    getTask: (taskId: string) => Promise<AnalysisTask>
    getResults: (taskId: string) => Promise<AnalysisResult>
    updateTask: (params: { taskId: string; favorite?: boolean; pinned?: boolean; tags?: string[] }) => Promise<AnalysisTask>
    deleteTask: (taskId: string) => Promise<void>
    stopTask: (taskId: string) => Promise<void>
    clearProjectCache: (projectId: string) => Promise<{ projectId: string; deletedTasks: number; fileCount: number; deletedTables: Record<string, number> }>
    getClearCacheCounts: (projectId: string) => Promise<{ projectId: string; counts: Record<string, number> }>
    clearProjectCacheTable: (projectId: string, table: string) => Promise<{ table: string; deleted: number }>
    reRunTask: (taskId: string) => Promise<AnalysisTask>
    getTaskLogs: (params: { taskId: string; runId?: string }) => Promise<TaskLogsResult>
    getTaskRuns: (taskId: string) => Promise<TaskRun[]>
    updateTaskConfig: (params: { taskId: string; config: TaskConfigUpdate }) => Promise<AnalysisTask>
    scanFileStats: (projectId: string, options?: ScanOptions) => Promise<FileStatsResult>
    getAvailableLevels: (taskId: string, edgeType?: string) => Promise<string[]>
    getCommunityGraph: (params: { taskId: string; edgeType: string; commLv: string; commIds: string[]; depth: number }) => Promise<any>
    getSymbolDetail: (params: { taskId: string; symbolId: string }) => Promise<any>
    getEdgeDetail: (params: { taskId: string; edgeId: string }) => Promise<any>
    getCascadeLevels: (taskId: string, edgeType?: string) => Promise<{ levels: Array<{ lv: string; items: Array<{ id: string; label: string; parentCommId: string | null; nodeCount: number; edgeCount: number; qualityScore: number }> }> }>
    getQueryStats: (params: { taskId: string; edgeType?: string; commLv?: string; commIds?: string[]; depth?: number }) => Promise<{ communityCount: number; nodeCount: number; edgeCount: number }>
    // 社区 LLM 结果持久化
    saveCommunityResult: (params: {
      taskId: string; edgeType: string; commLv: string; commId: string;
      name?: string; summary?: string; mermaid?: string; plantuml?: string;
      modelId?: string; templateId?: string;
    }) => Promise<{ success: boolean }>
    getCommunityResult: (params: { taskId: string; edgeType: string; commLv: string; commId: string }) => Promise<any>
    listCommunityResults: (taskId: string, edgeType: string) => Promise<{ results: Array<{
      id: number; taskId: string; edgeType: string; commLv: string; commId: string;
      name: string | null; summary: string | null; mermaid: string | null; plantuml: string | null;
      nameManual: string | null;
    }> }>
    updateCommunityName: (params: { taskId: string; edgeType: string; commLv: string; commId: string; name: string }) => Promise<{ success: boolean }>
    onProgress: (cb: (data: TaskProgressEvent) => void) => void
    onComplete: (cb: (data: TaskCompleteEvent) => void) => void
    onError: (cb: (data: TaskErrorEvent) => void) => void
  }

  // 报告子文档 + 报告生成辅助
  report: {
    createSubDoc: (params: { taskId: string; edgeType?: string; commId?: string; title: string; content: string; templateId?: string }) => Promise<{ id: string }>
    listSubDocs: (params: { taskId: string; commId?: string }) => Promise<Array<{ id: string; title: string; templateId: string; createdAt: string; updatedAt: string }>>
    getSubDoc: (subDocId: string) => Promise<{ id: string; taskId: string; edgeType: string; commId: string; title: string; content: string; templateId: string; createdAt: string; updatedAt: string }>
    updateSubDoc: (params: { subDocId: string; title?: string; content?: string }) => Promise<{ ok: boolean }>
    deleteSubDoc: (subDocId: string) => Promise<{ ok: boolean }>
    // 报告生成辅助
    getReadmeContent: (params: { projectId: string }) => Promise<{ path: string | null; content: string; fullLength: number; error?: string }>
    extractDependencyFiles: (params: { projectId: string }) => Promise<{ dependencyFiles: Array<{ file: string; type: string; dependencies: Record<string, string>; count: number }>; count: number }>
    generateProjectSummary: (params: { projectId: string }) => Promise<{ success: boolean; summary: string; generated_at: string }>
    getProjectSummary: (params: { projectId: string }) => Promise<{ summary: string; generated_at: string | null }>
    savePipelineState: (params: { taskId: string; stateJson: string }) => Promise<{ ok: boolean; id: string }>
    loadPipelineState: (params: { taskId: string }) => Promise<{ state: Record<string, any> | null }>
    getLevelCommunityDetail: (params: { projectId: string; taskId: string; level?: string; edgeType?: string }) => Promise<{ communities: Array<{ communityId: string; parentCommunityId: string | null; level: string; nodeCount: number; edgeCount: number; qualityScore: number | null; nodes: Array<{ id: string; name: string; type: string; filePath: string }>; edges: Array<{ source: string; target: string; type: string; direction: string }> }>; count: number; level: string; taskId: string }>
    saveFileSummaries: (params: { projectId: string; taskId: string; summaries: Array<{ filePath: string; summary: string; source?: string }> }) => Promise<{ saved: number }>
    getFileSummaries: (params: { projectId: string; taskId?: string; source?: string }) => Promise<{ summaries: Array<{ id: string; project_id: string; task_id: string | null; file_path: string; summary: string; source: string; created_at: string }>; count: number }>
    // LLM 调用日志查询
    getCallLogs: (params: { sessionId?: string; requestId?: string; templateId?: string; status?: string; limit?: number; offset?: number }) => Promise<{ logs: Array<Record<string, any>>; count: number }>
    getInteractionLogs: (params: { sessionId?: string; requestId?: string; templateId?: string; limit?: number; offset?: number }) => Promise<{ logs: Array<Record<string, any>>; count: number }>
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
    addModel: (params: { name: string; provider: string; model: string; url: string; type: string; temperature?: number; maxTokens?: number; apiKey?: string; isDefault?: boolean }) => Promise<ModelConfigItem>
    updateModel: (params: { id: string; name?: string; provider?: string; model?: string; url?: string; temperature?: number; maxTokens?: number; isDefault?: boolean; apiKey?: string; maxRequestsPerDay?: number; maxTokensPerDay?: number }) => Promise<ModelConfigItem>
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

  // 模型用量统计
  model: {
    getUsageStats: (modelId?: string, startDate?: string, endDate?: string) => Promise<UsageStatItem[]>
    deleteUsageStats: (id: number) => Promise<void>
    deleteUsageStatsBatch: (ids: number[]) => Promise<void>
    deleteUsageStatsByCondition: (params: { modelId?: string; startDate?: string; endDate?: string }) => Promise<void>
  }

  // 后端管理
  backend: {
    start: () => Promise<void>
    stop: () => Promise<void>
    restart: () => Promise<BackendStatus>
    getStatus: () => Promise<BackendStatus>
    getMemoryLimit: () => Promise<number>
    setMemoryLimit: (limit: number) => Promise<void>
    getHttpConfig: () => Promise<{ host: string; port: number }>
    setHttpConfig: (config: { host: string; port: number }) => Promise<void>
    onStatusChange: (cb: (data: BackendStatusEvent) => void) => void
  }

  // 系统
  system: {
    selectDirectory: () => Promise<string>
    getAppDataPath: () => Promise<string>
    get: (key: string) => Promise<any>
    set: (key: string, val: any) => Promise<void>
    getHttpPort: () => Promise<number>
  }

  // LLM Session 管理 (v2)
  session: {
    list: (params?: { moduleType?: string; projectId?: string; status?: string }) => Promise<{ sessions: Array<{ id: string; module_type: string; project_id: string | null; title: string; status: string; metadata: string | null; created_at: string; updated_at: string }> }>
    create: (params: { moduleType: string; title: string; projectId?: string; metadata?: Record<string, any> }) => Promise<{ id: string; moduleType: string; title: string }>
    delete: (params: { sessionId: string }) => Promise<{ success: boolean }>
    getMessages: (params: { sessionId: string; limit?: number; offset?: number }) => Promise<{ messages: Array<{ id: string; session_id: string; role: string; content: string; token_count: number | null; metadata: string | null; created_at: string }> }>
    addMessage: (params: { sessionId: string; role: string; content: string; tokenCount?: number; metadata?: Record<string, any> }) => Promise<{ id: string }>
    deleteMessage: (params: { messageId: string }) => Promise<{ success: boolean }>
    updateMeta: (params: { sessionId: string; metadata: Record<string, any> }) => Promise<{ sessionId: string; metadata: Record<string, any> }>
    clearAll: () => Promise<{ success: boolean; count: number }>
  }

  // LLM 推理 (v2 — 统一入口)
  llm: {
    chat: (params: {
      sessionId: string; modelId: string; mode?: 'chat' | 'tools' | 'structured'
      messages?: Array<{ role: string; content: string }>; templateId?: string
      variables?: Record<string, any>; tools?: string[]; outputSchema?: Record<string, any>
    }) => Promise<{ requestId: string; status: string }>
    abortChat: (params: { requestId: string }) => Promise<{ success: boolean }>
    subscribe: (requestId: string, callbacks: {
      onChunk?: (data: { index: number; text: string }) => void
      onToolCall?: (data: { toolName: string; args: Record<string, any> }) => void
      onToolResult?: (data: { toolName: string; result: Record<string, any> }) => void
      onDone?: (data: { content: string; structured?: Record<string, any> }) => void
      onError?: (data: { message: string; code: string }) => void
    }) => () => void
  }

  // 分析报告会话管理 (项目/任务/报告 三级隔离)
  analysisSession: {
    list: (params?: { projectId?: string; taskId?: string; reportId?: string }) => Promise<{ sessions: Array<{ id: string; project_id: string; task_id: string; report_id: string | null; session_id: string; metadata: string | null; created_at: string; updated_at: string }> }>
    create: (params: { projectId: string; taskId: string; sessionId: string; reportId?: string; metadata?: Record<string, any> }) => Promise<{ id: string; sessionId: string }>
    delete: (params: { id?: string; sessionId?: string }) => Promise<{ success: boolean }>
  }

  // Prompt 模板
  promptTemplate: {
    list: (params?: { mode?: string; moduleType?: string; category?: string; locale?: string }) => Promise<{ templates: Array<{ id: string; name: string; mode: string; module_type: string | null; category: string; is_builtin: number; locale: string; base_id?: string }> }>
    get: (params: { templateId: string; locale?: string }) => Promise<Record<string, any>>
    create: (params: { name: string; mode: string; moduleType?: string; category?: string; locale?: string; systemPrompt?: string; userPromptTemplate?: string; toolsJson?: string; toolStrategy?: string; outputSchemaJson?: string; outputExample?: string; variablesJson?: string }) => Promise<Record<string, any>>
    update: (params: { templateId: string;[key: string]: any }) => Promise<Record<string, any>>
    delete: (params: { templateId: string }) => Promise<{ success: boolean }>
    render: (params: { templateId: string; variables: Record<string, any>; locale?: string }) => Promise<{ messages: any[]; mode: string; tools: string[] | null; outputSchema: Record<string, any> | null }>
    restoreDefaults: (params?: { locale?: string }) => Promise<{ success: boolean; count: number }>
    getDefaultLocale: () => Promise<{ locale: string }>
    setDefaultLocale: (params: { locale: string }) => Promise<{ success: boolean; locale: string }>
  }

  // 渲染服务
  render: {
    renderPlantuml: (params: { code: string; format?: string; useRemote?: boolean }) => Promise<{ data: string; format: string; size: number }>
  }

  // Electron 专用 (preload 暴露)
  app: {
    quit: () => Promise<void>
  }
  window: {
    toggleLeftPanel: () => Promise<void>
    toggleRightPanel: () => Promise<void>
    zoomIn: () => Promise<number>
    zoomOut: () => Promise<number>
    resetZoom: () => Promise<number>
    create: () => Promise<number | null>
    close: (windowId: number) => Promise<boolean>
    minimize: () => Promise<boolean>
    maximize: () => Promise<boolean>
    isMaximized: () => Promise<boolean>
    list: () => Promise<Array<{ id: number; title: string; isFocused: boolean }>>
    focus: (windowId: number) => Promise<boolean>
    getCount: () => Promise<number>
    getMaxCount: () => Promise<number>
    broadcast: (channel: string, data: any) => Promise<boolean>
    onPanelToggle: (channel: string, callback: () => void) => () => void
  }
  dialog: { openDirectory: () => Promise<string | null> }
  shell: { openExternal: (url: string) => Promise<void> }
  store: { get: (key: string) => Promise<any>; set: (key: string, value: any) => Promise<boolean> }
  fs: { addAllowedDir: (dirPath: string) => Promise<void>; readFile: (filePath: string) => Promise<string> }
  on: (channel: string, callback: (...args: any[]) => void) => () => void
  removeListener: (channel: string, callback: (...args: any[]) => void) => void
  log: {
    debug: (source: string, message: string, data?: any) => void
    info: (source: string, message: string, data?: any) => void
    warn: (source: string, message: string, data?: any) => void
    error: (source: string, message: string, data?: any) => void
  }
}

// ==================== Window 扩展 ====================

declare global {
  interface Window {
    api?: IPCAPI
  }
}

export {}
