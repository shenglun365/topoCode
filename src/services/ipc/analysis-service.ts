import type {
  AnalysisTask, RunTaskResult, AnalysisResult, ClearCacheResult,
  ClearCacheCountsResult, ClearCacheTableResult, TaskRun, TaskLogsResult,
  FileStatsResult, ScanOptions, TaskConfigUpdate, CommunityGraphResult,
  SymbolDetail, CascadeLevelsResult, QueryStatsResult,
    ExternalStatsResult, CrossCommunityEdgesResult,
  SaveCommunityResultResponse, ListCommunityResultsResponse,
  UpdateCommunityNameResponse, SuccessResponse, TaskProgressEvent,
  TaskCompleteEvent, TaskErrorEvent,
} from '@/types/ipc'

function adaptTask(t: any): AnalysisTask {
  if (!t) return null as any
  return {
    ...t,
    projectId: t.project_id ?? t.projectId ?? '',
    createdAt: t.created_at ?? t.createdAt ?? '',
    updatedAt: t.updated_at ?? t.updatedAt ?? '',
    scopes: t.scopes ?? [],
    extensions: t.extensions ?? [],
    excludeDirs: t.excludeDirs ?? t.exclude_dirs ?? [],
    reportTypes: t.reportTypes ?? t.report_types ?? [],
  }
}

function adaptTaskList(list: any[]): AnalysisTask[] {
  return (list || []).filter(Boolean).map(adaptTask)
}

function adaptRun(r: any): TaskRun {
  if (!r) return null as any
  return {
    ...r,
    taskId: r.task_id ?? r.taskId,
    runNumber: r.run_number ?? r.runNumber,
    startedAt: r.started_at ?? r.startedAt,
    finishedAt: r.finished_at ?? r.finishedAt,
    durationMs: r.duration_ms ?? r.durationMs,
  }
}

export interface AnalysisService {
  listTasks(projectId: string): Promise<AnalysisTask[]>
  listRunningTasks(): Promise<Array<{ id: string; name: string; project_id: string }>>
  createTask(params: {
    projectId: string; type: string; name: string;
    scope?: string; extensions?: string[]; excludeDirs?: string[]; reportTypes?: string[]
  }): Promise<AnalysisTask>
  runTask(taskId: string): Promise<RunTaskResult>
  getTask(taskId: string): Promise<AnalysisTask | null>
  getResults(taskId: string): Promise<AnalysisResult>
  updateTask(params: { taskId: string; favorite?: boolean; pinned?: boolean; tags?: string[] }): Promise<AnalysisTask>
  deleteTask(taskId: string): Promise<number>
  stopTask(taskId: string): Promise<SuccessResponse>
  clearProjectCache(projectId: string): Promise<ClearCacheResult>
  getClearCacheCounts(projectId: string): Promise<ClearCacheCountsResult>
  clearProjectCacheTable(projectId: string, table: string): Promise<ClearCacheTableResult>
  reRunTask(taskId: string): Promise<TaskRun>
  getTaskLogs(params: { taskId: string; runId?: string }): Promise<TaskLogsResult>
  getTaskRuns(taskId: string): Promise<TaskRun[]>
  updateTaskConfig(params: { taskId: string; config: TaskConfigUpdate }): Promise<AnalysisTask>
  scanFileStats(projectId: string, options?: ScanOptions): Promise<FileStatsResult>
  getAvailableLevels(taskId: string, edgeType?: string): Promise<string[]>
  getCommunityGraph(params: {
    taskId: string; edgeType: string; commLv: string; commIds: string[]; depth: number
  }): Promise<CommunityGraphResult>
  getSymbolDetail(params: { taskId: string; symbolId: string }): Promise<SymbolDetail | null>
  getEdgeDetail(params: { taskId: string; edgeId: string }): Promise<any | null>
  getCascadeLevels(taskId: string, edgeType?: string): Promise<CascadeLevelsResult>
  getQueryStats(params: {
    taskId: string; edgeType?: string; commLv?: string; commIds?: string[]; depth?: number
  }): Promise<QueryStatsResult>
  getExternalStats(taskId: string): Promise<ExternalStatsResult>
  getCrossCommunityEdges(params: { taskId: string; edgeType: string; commLv: string }): Promise<CrossCommunityEdgesResult>
  getCommunityNodeLists(params: { taskId: string; edgeType: string; commLv: string }): Promise<Record<string, string[]>>
  startOverview(params: { taskId: string; force?: boolean }): Promise<{ taskId: string; success: boolean; agentTaskId?: string | null; skipped?: boolean; error?: string }>
  getAgentProgress(params: { agentTaskId: string }): Promise<{ found: boolean; status?: string; step_current?: number; step_total?: number; file_current?: number; file_total?: number; tokens_used?: number; elapsed_sec?: number; message?: string; steps?: Array<{ description: string; status: string; file_count?: number }>; error?: string }>
  cancelAgentTask(params: { agentTaskId: string }): Promise<{ cancelled: boolean }>
  getAgentTaskHistory(params: { taskId: string; offset?: number; limit?: number }): Promise<{ results: Array<any>; total: number }>
  clearAgentTaskHistory(params: { taskId: string }): Promise<{ success: boolean }>
  // 预摘要
  getPreSummaryStatus(params: { taskId: string }): Promise<{ counts: Record<string, number>; total_files: number; cached_count: number; project_root: string; failed_count: number }>
  listPreSummaryFiles(params: { taskId: string; batch?: string; page?: number; page_size?: number }): Promise<{ batch: string; page: number; page_size: number; total: number; files: Array<any> }>
  startPreSummary(params: { taskId: string; batch?: string; limit?: number; subagentConcurrency?: number }): Promise<{ success: boolean; agentTaskId?: string; fileCount?: number; error?: string }>
  startPreSummaryPipeline(params: { taskId: string; batches: string[]; limit?: number; subagentConcurrency?: number }): Promise<{ success: boolean; batches: string[]; total: number }>
  getFileSummary(params: { taskId: string; file_path: string }): Promise<{ found: boolean; summary?: string; summary_len?: number; created_at?: string }>
  deleteFileSummary(params: { taskId: string; file_path: string }): Promise<{ success: boolean; deleted?: number }>
  rerunFileSummary(params: { taskId: string; file_path: string }): Promise<{ success: boolean; agentTaskId?: string }>
  analyzeComponents(params: { taskId: string; components: Array<{ id: string; type: string; name: string; metadata?: Record<string, any> }>; language?: string; concurrency?: number; agentic?: boolean; maxTurns?: number; summaryModelId?: string; analysisMode?: string; force?: boolean }): Promise<{ success: boolean; agentTaskId?: string; error?: string; skipped?: number }>
  saveCommunityResult(params: any): Promise<SaveCommunityResultResponse>
  getCommunityResult(params: any): Promise<any>
  listCommunityResults(taskId: string, edgeType: string): Promise<ListCommunityResultsResponse>
  updateCommunityName(params: any): Promise<UpdateCommunityNameResponse>
  getCommunityFileGraph(params: { taskId: string; edgeType: string; commId: string }): Promise<{ nodes: Array<{ id: string; label: string; filePath: string }>; edges: Array<{ source: string; target: string; direction?: string }> }>
  getReportDashboard(taskId: string): Promise<{
    task: any; callLevels: any; depLevels: any;
    callResults: { results: any[] }; depResults: { results: any[] };
    fileStats: any; preSummary?: any
  }>
  onProgress(cb: (data: TaskProgressEvent) => void): void
  onComplete(cb: (data: TaskCompleteEvent) => void): void
  onError(cb: (data: TaskErrorEvent) => void): void
  onStopped(cb: (data: any) => void): void
}

export function createAnalysisService(api: any): AnalysisService {
  return {
    listTasks: async (projectId: string) => {
      const list = await api.analysis.listTasks(projectId)
      return adaptTaskList(list)
    },
    createTask: async (params) => {
      const result = await api.analysis.createTask(params)
      return adaptTask(result)
    },
    runTask: async (taskId: string) => {
      return await api.analysis.runTask(taskId) as RunTaskResult
    },
    getTask: async (taskId: string) => {
      const t = await api.analysis.getTask(taskId)
      return t ? adaptTask(t) : null
    },
    getResults: async (taskId: string) => {
      return await api.analysis.getResults(taskId) as AnalysisResult
    },
    updateTask: async (params) => {
      const result = await api.analysis.updateTask(params)
      return adaptTask(result)
    },
    deleteTask: async (taskId: string) => {
      return await api.analysis.deleteTask(taskId) as number
    },
    stopTask: async (taskId: string) => {
      return await api.analysis.stopTask(taskId) as SuccessResponse
    },
    listRunningTasks: async () => {
      return await api.analysis.listRunningTasks() as Array<{ id: string; name: string; project_id: string }>
    },
    clearProjectCache: async (projectId: string) => {
      return await api.analysis.clearProjectCache(projectId) as ClearCacheResult
    },
    getClearCacheCounts: async (projectId: string) => {
      return await api.analysis.getClearCacheCounts(projectId) as ClearCacheCountsResult
    },
    clearProjectCacheTable: async (projectId: string, table: string) => {
      return await api.analysis.clearProjectCacheTable(projectId, table) as ClearCacheTableResult
    },
    reRunTask: async (taskId: string) => {
      const r = await api.analysis.reRunTask(taskId)
      return adaptRun(r)
    },
    getTaskLogs: async (params) => {
      return await api.analysis.getTaskLogs(params) as TaskLogsResult
    },
    getTaskRuns: async (taskId: string) => {
      const list = await api.analysis.getTaskRuns(taskId)
      return (list || []).map(adaptRun)
    },
    updateTaskConfig: async (params) => {
      const result = await api.analysis.updateTaskConfig(params)
      return adaptTask(result)
    },
    scanFileStats: async (projectId: string, options?: ScanOptions) => {
      const scopes = options?.scopes
      const selectedExtensions = options?.selectedExtensions
      const rest: Record<string, any> = { ...options }
      delete rest.scopes
      delete rest.selectedExtensions
      const params: Record<string, any> = { ...rest, scopes, selectedExtensions }
      for (const k of Object.keys(params)) { if (params[k] === undefined) delete params[k] }
      return await api.analysis.scanFileStats(projectId, params) as FileStatsResult
    },
    getAvailableLevels: async (taskId: string, edgeType?: string) => {
      return await api.analysis.getAvailableLevels(taskId, edgeType) as string[]
    },
    getCommunityGraph: async (params) => {
      return await api.analysis.getCommunityGraph(params) as CommunityGraphResult
    },
    getSymbolDetail: async (params) => {
      return await api.analysis.getSymbolDetail(params) as SymbolDetail | null
    },
    getEdgeDetail: async (params) => {
      return await api.analysis.getEdgeDetail(params) as any | null
    },
    getCascadeLevels: async (taskId: string, edgeType?: string) => {
      return await api.analysis.getCascadeLevels(taskId, edgeType) as CascadeLevelsResult
    },
    getReportDashboard: async (taskId: string) => {
      return await api.analysis.getReportDashboard(taskId)
    },
    getQueryStats: async (params) => {
      return await api.analysis.getQueryStats(params) as QueryStatsResult
    },
    getExternalStats: async (taskId: string) => {
      return await api.analysis.getExternalStats(taskId) as ExternalStatsResult
    },
    getCrossCommunityEdges: async (params: { taskId: string; edgeType: string; commLv: string }) => {
      return await api.analysis.getCrossCommunityEdges(params) as CrossCommunityEdgesResult
    },
    getCommunityNodeLists: async (params: { taskId: string; edgeType: string; commLv: string }) => {
      return await api.analysis.getCommunityNodeLists(params) as Record<string, string[]>
    },
    startOverview: async (params) => {
      return await api.analysis.startOverview(params)
    },
    saveCommunityResult: async (params: any) => {
      const safe = JSON.parse(JSON.stringify(params))
      return await api.analysis.saveCommunityResult(safe) as SaveCommunityResultResponse
    },
    getCommunityResult: async (params: any) => {
      return await api.analysis.getCommunityResult(params)
    },
    listCommunityResults: async (taskId: string, edgeType: string) => {
      return await api.analysis.listCommunityResults(taskId, edgeType) as ListCommunityResultsResponse
    },
    updateCommunityName: async (params: any) => {
      return await api.analysis.updateCommunityName(params) as UpdateCommunityNameResponse
    },
    getCommunityFileGraph: async (params: any) => {
      return await api.analysis.getCommunityFileGraph(params)
    },
    onProgress: (cb: (data: TaskProgressEvent) => void) => {
      api.analysis.onProgress(cb)
    },
    onComplete: (cb: (data: TaskCompleteEvent) => void) => {
      api.analysis.onComplete(cb)
    },
    onError: (cb: (data: TaskErrorEvent) => void) => {
      api.analysis.onError(cb)
    },
    onStopped: (cb: (data: any) => void) => {
      api.analysis.onStopped(cb)
    },
  }
}
