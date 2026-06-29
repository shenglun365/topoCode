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
  status: 'done' | 'running' | 'pending' | 'modified' | 'error' | 'cancelled' | 'stopping'
  progress?: number
  total?: number
  current?: number
  error?: string | null
  eta?: string
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
}

/** 目录树节点 */
export interface DirTreeNode {
  name: string
  path: string
  fileCount?: number
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

/** 分析结果 (v2) */
export interface AnalysisResult {
    /** 任务 ID */
    id?: string
    task_id?: string
    run_id?: string

    /** 节点统计 */
    total_ast_nodes: number
    total_symbols: number

    /** 边统计 */
    total_call_edges: number
    total_dep_edges: number
    total_extends_edges: number
    total_implements_edges: number
    total_type_of_edges: number
    total_framework_edges: number
    total_synthetic_edges: number

    /** 社区统计 */
    total_communities: number
    total_hubs: number
    total_orphans: number
    best_call_community_id?: string
    best_dep_community_id?: string

    /** 文件处理 */
    files_processed: number
    skipped_files: number
    language_stats: Record<string, number>

    /** 日志 */
    logs?: Array<{ timestamp: string; message: string }>
    summary: string
}

/** 图节点 (v2) */
export interface GraphNode {
    id: string
    task_id: string
    kind: NodeKind
    name: string
    qualified_name: string
    file_path: string
    language: string
    start_line: number
    start_col: number
    end_line: number
    end_col: number
    signature?: string
    visibility?: 'public' | 'private' | 'protected' | 'internal'
    is_exported: boolean
    is_async: boolean
    is_static: boolean
    docstring?: string
    decorators?: string[]
}

/** 图边 (v2) */
export interface GraphEdge {
    id: string
    task_id: string
    source_id: string
    target_id: string
    kind: EdgeKind
    provenance: 'parser' | 'resolution' | 'synthesizer' | 'framework'
    line: number
    col: number
    file_path: string
    metadata?: Record<string, unknown>
}

/** 节点类型 */
export type NodeKind =
    | 'file' | 'module' | 'class' | 'struct' | 'interface'
    | 'trait' | 'protocol' | 'function' | 'method' | 'property'
    | 'field' | 'variable' | 'constant' | 'enum' | 'enum_member'
    | 'type_alias' | 'namespace' | 'parameter' | 'import' | 'export'
    | 'route' | 'component'

/** 边类型 */
export type EdgeKind =
    | 'contains' | 'calls' | 'imports' | 'exports' | 'extends'
    | 'implements' | 'references' | 'type_of' | 'returns'
    | 'instantiates' | 'overrides' | 'decorates' | 'callback'

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
  type: string
  args: string
  status: 'online' | 'offline' | 'not-detected' | 'not-configured' | 'configured' | 'error'
  version?: string
  isDefault: boolean
  extraConfig?: Record<string, unknown>
  timeout?: number
}

/** Agent 执行记录 */
export interface AgentExecution {
  id: string
  agentConfigId: string
  taskId?: string
  status: 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'timed_out'
  args: string
  command: string
  stdoutPath?: string
  stderrPath?: string
  exitCode?: number
  error?: string
  progress: number
  meta?: Record<string, unknown>
  startedAt?: string
  finishedAt?: string
  durationMs?: number
  createdAt: string
}

/** SKILL 配置 */
export interface SkillConfigItem {
  id: string
  name: string
  description: string
  enabled: boolean
}

/** 导入配置 */
export interface ImportConfig {
  ignoreMode: 'standard' | 'strict' | 'minimal'
  extraIgnoreFiles: string[]
  customPatterns: string[]
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
  eta?: string
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
    detectGitInfo: (params: { projectId: string }) => Promise<GitInfo>
    saveGitInfo: (params: { projectId: string; remoteUrl?: string; currentBranch?: string; currentCommit?: string; latestTag?: string; tags?: string; branches?: string; recentCommits?: string }) => Promise<{ status: string }>
    getGitInfo: (params: { projectId: string }) => Promise<GitInfo>
    checkImportStatus: (params: { projectId: string }) => Promise<{ hasSnapshot: boolean; needsSavePrompt: boolean }>
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
    listRunningTasks: () => Promise<Array<{ id: string; name: string; project_id: string }>>
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
    getReportDashboard: (taskId: string) => Promise<{ task: any; callLevels: any; depLevels: any; callResults: { results: any[] }; depResults: { results: any[] }; fileStats: any; preSummary?: { counts: Record<string, number>; total_files: number; cached_count: number; project_root: string } }>
    getCascadeLevels: (taskId: string, edgeType?: string) => Promise<{ levels: Array<{ lv: string; items: Array<{ id: string; label: string; parentCommId: string | null; nodeCount: number; fileCount: number; edgeCount: number; qualityScore: number; metadata?: { avgCoreness?: number; maxCoreness?: number; coreNodeRatio?: number } }> }>; totalUniqueFiles: number }>
    getQueryStats: (params: { taskId: string; edgeType?: string; commLv?: string; commIds?: string[]; depth?: number }) => Promise<{ communityCount: number; nodeCount: number; edgeCount: number }>
    getExternalStats: (taskId: string) => Promise<ExternalStatsResult>
    getCrossCommunityEdges: (params: { taskId: string; edgeType: string; commLv: string }) => Promise<CrossCommunityEdgesResult>
    getCommunityNodeLists: (params: { taskId: string; edgeType: string; commLv: string }) => Promise<Record<string, string[]>>
    startOverview: (params: { taskId: string; force?: boolean }) => Promise<{ taskId: string; success: boolean; agentTaskId?: string | null; skipped?: boolean; error?: string }>
    getAgentProgress: (params: { agentTaskId: string }) => Promise<{ found: boolean; status?: string; step_current?: number; step_total?: number; file_current?: number; file_total?: number; tokens_used?: number; elapsed_sec?: number; message?: string; steps?: Array<{ description: string; status: string; file_count?: number }>; error?: string }>
    cancelAgentTask: (params: { agentTaskId: string }) => Promise<{ cancelled: boolean }>
    pauseAgentTask: (params: { agentTaskId: string }) => Promise<{ paused: boolean }>
    resumeAgentTask: (params: { agentTaskId: string }) => Promise<{ resumed: boolean }>
    getAgentTaskHistory: (params: { taskId: string; offset?: number; limit?: number }) => Promise<{ results: Array<{ project_id: string; task_id: string; agent_id: string; action: string; status: string; steps: string | null; message: string; error: string | null; created_at: string | null; finished_at: string | null }>; total: number }>
    clearAgentTaskHistory: (params: { taskId: string }) => Promise<{ success: boolean }>
    // 预摘要
    getPreSummaryStatus: (params: { taskId: string }) => Promise<{ counts: Record<string, number>; total_files: number; cached_count: number; project_root: string; failed_count: number }>
    listPreSummaryFiles: (params: { taskId: string; batch?: string; page?: number; page_size?: number }) => Promise<{ batch: string; page: number; page_size: number; total: number; files: Array<{ file_path: string; score: number; cross: number; edges: number; size: number; is_large: number; quality: number; batch: string; has_summary?: boolean }> }>
    startPreSummary: (params: { taskId: string; batch?: string; limit?: number }) => Promise<{ success: boolean; agentTaskId?: string; fileCount?: number; error?: string }>
    startPreSummaryPipeline: (params: { taskId: string; batches: string[]; limit?: number; subagentConcurrency?: number }) => Promise<{ success: boolean; batches: string[]; total: number }>
    getFileSummary: (params: { taskId: string; file_path: string }) => Promise<{ found: boolean; summary?: string; summary_len?: number; created_at?: string; source?: string }>
    deleteFileSummary: (params: { taskId: string; file_path: string }) => Promise<{ success: boolean; deleted?: number }>
    rerunFileSummary: (params: { taskId: string; file_path: string }) => Promise<{ success: boolean; agentTaskId?: string }>
    startPipeline: (params: { taskId: string; force?: boolean; language?: string }) => Promise<{ success: boolean; agentTaskId?: string; error?: string }>
    getAgentConfig: () => Promise<{ routes: Array<{ action: string; workflow: string; description: string }>; skills: Array<{ name: string; description: string; steps: number }>; tools: Array<{ name: string; description: string; category: string; llm_visible: boolean }> }>
    // 组件分析
    analyzeComponents: (params: { taskId: string; components: Array<{ id: string; type: string; name: string; metadata?: Record<string, any> }>; language?: string; concurrency?: number; agentic?: boolean; maxTurns?: number; summaryModelId?: string; analysisMode?: string; force?: boolean }) => Promise<{ success: boolean; agentTaskId?: string; error?: string; skipped?: number }>
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
    getCommunityFileGraph: (params: { taskId: string; edgeType: string; commId: string }) => Promise<{
      nodes: Array<{ id: string; label: string; filePath: string }>
      edges: Array<{ source: string; target: string; direction?: string }>
    }>
    onProgress: (cb: (data: TaskProgressEvent) => void) => void
    onComplete: (cb: (data: TaskCompleteEvent) => void) => void
    onError: (cb: (data: TaskErrorEvent) => void) => void
    onStopped: (cb: (data: any) => void) => void
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
    saveProjectSummary: (params: { projectId: string; summary: string }) => Promise<{ success: boolean; summary: string; generated_at: string }>
    saveOverallDoc: (params: { taskId: string; title: string; content: string }) => Promise<{ id: string; title: string; content: string; createdAt: string }>
    getLevelCommunityDetail: (params: { projectId: string; taskId: string; level?: string; edgeType?: string }) => Promise<{ communities: Array<{ communityId: string; parentCommunityId: string | null; level: string; nodeCount: number; edgeCount: number; qualityScore: number | null; nodes: Array<{ id: string; name: string; type: string; filePath: string }>; edges: Array<{ source: string; target: string; type: string; direction: string }> }>; count: number; level: string; taskId: string }>
    renderDiagram: (params: { taskId: string; communityId: string; edgeType?: string; mode?: 'mermaid' | 'plantuml' }) => Promise<{ communityId: string; mode: string; code: string }>
    getCommunityFileDetail: (params: { taskId: string; communityId: string; edgeType?: string; limit?: number }) => Promise<{ files: Array<{ id: string; name: string; filePath: string; language: string; lines: number; summary: string }>; communityId: string; edgeType: string; found: boolean; fileCount: number }>
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
    addAgent: (params: { name: string; path: string; args: string; type?: string }) => Promise<AgentConfigItem>
    updateAgent: (params: { id: string; path?: string; args?: string; name?: string; type?: string }) => Promise<AgentConfigItem>
    removeAgent: (id: string) => Promise<void>
    detectAgent: (id: string) => Promise<{ status: string; version?: string }>
    executeAgent: (params: { id: string; task: string; args?: string; taskId?: string; env?: Record<string, string> }) => Promise<{ id: string; agentId: string; command: string; status: string }>
    getAgentExecution: (execId: string) => Promise<AgentExecution | { found: false }>
    listAgentExecutions: (params?: { agentId?: string; taskId?: string; status?: string; limit?: number }) => Promise<AgentExecution[]>
    cancelAgentExecution: (execId: string) => Promise<{ cancelled: boolean; message?: string }>
    getSkills: () => Promise<SkillConfigItem[]>
    updateSkill: (params: { id: string; enabled: boolean }) => Promise<SkillConfigItem>
    getBindings: () => Promise<Record<string, string>>
    updateBindings: (params: { bindings: Record<string, string> }) => Promise<Record<string, string>>
    getImportConfig: () => Promise<ImportConfig>
    setImportConfig: (params: { ignoreMode?: string; customPatterns?: string[]; extraIgnoreFiles?: string[] }) => Promise<ImportConfig>
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
    saveHttpConfig: (config: { host?: string; port?: number }) => Promise<{ success: boolean }>
    testPort: (port: number) => Promise<PortTestResult>
    ping: () => Promise<PingResult>
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

  // 图位置
  graph: {
    savePositions: (params: { taskId: string; edgeType: string; drillKey: string; layoutType: string; positions: PositionEntry[]; snapshotId?: string }) => Promise<{ saved: number }>
    loadPositions: (params: { taskId: string; edgeType: string; drillKey: string; layoutType: string; snapshotId?: string }) => Promise<{ positions: Record<string, NodePosition> }>
    clearPositions: (params: { taskId: string; edgeType: string; drillKey: string; layoutType: string }) => Promise<{ deleted: number }>
    listSavedPositionKeys: (params: { projectId: string }) => Promise<{ keys: SavedPositionKey[] }>
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

/* ====== IPC Service 边界类型 ====== */

export interface SuccessResponse { success: boolean }
export interface BackendActionResult { status: string; pid?: number; port?: number; error?: string }
export interface PingResult { ok: boolean; timestamp?: string }
export interface PortTestResult { available: boolean }
export interface HttpConfigDTO { host: string; port: number }

export interface SubDocDTO { id: string; taskId: string; title: string; content: string; createdAt?: string; updatedAt?: string }
export interface SubDocCreateResponse { id: string; subDocId?: string }
export interface SubDocUpdateResponse { success: boolean }
export interface SubDocDeleteResponse { success: boolean }
export interface SaveOverallDocResponse { success: boolean; id?: string }
export interface ReadmeContentResponse { content: string }
export interface DependencyFilesResult { files: string[] }
export interface ProjectSummaryResponse { summary?: string }
export interface ProjectSummaryData { summary: string; projectId: string }
export interface LevelCommunityDetailResult { communities?: Array<Record<string, unknown>> }
export interface SaveFileSummariesResponse { success: boolean }
export interface FileSummariesResult { summaries: Array<Record<string, unknown>> }

export interface ModelTestResult { success: boolean; status?: string; latency?: number }
export interface AgentDetectResult { status: string; version?: string }
export interface BindingsDTO { [key: string]: string }

export interface PluginInfoDTO { id: string; name: string; version?: string; enabled: boolean; description?: string; loaded?: boolean; platforms?: string[] }
export interface ModuleRegistryItemDTO { id: string; name: string; version: string; description?: string; size_kb?: number; platforms?: string[] }
export interface InstalledModuleDTO { name: string; version: string; enabled: boolean }

export interface RunTaskResult { success: boolean }
export interface ClearCacheResult { success: boolean }
export interface ClearCacheTableResult { success: boolean }
export interface ClearCacheCountsResult { counts: Record<string, number> }
export interface CommunityGraphResult { nodes: GraphNode[]; edges: GraphEdge[] }
export interface CascadeLevelsResult { levels: Array<Record<string, unknown>> }
export interface QueryStatsResult { stats: Record<string, unknown> }
export interface SymbolDetail { id: string; name: string; kind: string; qualified_name: string; filePath: string; start_line: number; end_line: number; signature?: string; visibility?: string }
export interface EdgeDetail { id: string; kind: string; source_id: string; target_id: string; provenance: string; sourceName?: string; targetName?: string }
export interface ListCommunityResultsResponse { results: Array<Record<string, unknown>> }
export interface SaveCommunityResultResponse { success: boolean }
export interface UpdateCommunityNameResponse { success: boolean }

export interface ProjectStorageStats { fileCount: number; totalSize: number }
export interface PathValidityResult { valid: boolean; error?: string }
export interface FileChangesResult { changed: boolean; files?: string[] }
export interface UpdatePathResult { success: boolean }
export interface DimensionsResult { dimensions: string[] }

export interface ProjectMeta { name?: string; favorite?: number; pinned?: number }
export interface TreeNode { id: string; name: string; children?: TreeNode[] }
export interface UsageStatDTO { id: number; modelId: string; modelName: string; date: string; requestCount: number; promptTokens: number; completionTokens: number; totalTokens: number }

declare global {
  interface Window {
    api?: IPCAPI
  }
}

// ==================== DTO type aliases for service layer ====================

// 外部依赖/调用统计
export interface ExternalDepItem {
  package: string
  fileCount: number
  files: string[]
  communities?: Array<{ communityId: string; name?: string }>
}

export interface ExternalCallItem {
  name: string
  count: number
  files: string[]
  communities?: Array<{ communityId: string; name?: string }>
}

export interface ExternalStatsResult {
  externalDeps: ExternalDepItem[]
  externalCalls: ExternalCallItem[]
  totalExternalDeps: number
  uniqueExternalDepFiles: number
  totalExternalCalls: number
  uniqueExternalCallFiles: number
}

export interface CrossCommunityEdge {
  sourceCommId: string
  targetCommId: string
  edgeCount: number
}

export interface CrossCommunityEdgesResult {
  crossEdges: CrossCommunityEdge[]
}

export type ModelConfigDTO = ModelConfigItem
export type AgentConfigDTO = AgentConfigItem
export type AgentExecutionDTO = AgentExecution
export type SkillConfigDTO = SkillConfigItem
export type AnalysisTaskDTO = AnalysisTask
export type AnalysisResultsDTO = AnalysisResult
export type TaskRunDTO = TaskRun
export type ScanOptionsDTO = ScanOptions
export type TaskConfigUpdateDTO = TaskConfigUpdate

// ==================== 架构时间线 & 位置 类型 ====================

export interface GitInfo {
  projectId?: string
  remoteUrl: string
  currentBranch: string
  currentCommit: string
  latestTag?: string
  tags?: string
  branches?: string
  recentCommits?: string
  detectedAt?: string
  manuallyEdited?: number
}

export interface PositionEntry {
  nodeId: string
  x: number
  y: number
}

export interface NodePosition {
  x: number
  y: number
}

export interface SavedPositionKey {
  taskId: string
  edgeType: string
  drillKey: string
  layoutType: string
  count: number
}

export {}
