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
    snapshotScope: r.snapshot_scope ?? r.snapshotScope,
    snapshotExtensions: r.snapshot_extensions ?? r.snapshotExtensions,
    snapshotExcludeDirs: r.snapshot_excludeDirs ?? r.snapshotExcludeDirs,
    snapshotReportTypes: r.snapshot_report_types ?? r.snapshotReportTypes,
  }
}

export interface AnalysisService {
  listTasks(projectId: string): Promise<AnalysisTask[]>
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
  startArchAnalysis(params: { taskId: string; edgeType: string; level: string; modelId?: string }): Promise<{ taskId: string; success: boolean }>
  listArchSnapshots(params: { taskId: string }): Promise<Array<{ id: string; ts: string; commCount: number; summary: string }>>
  getArchSnapshot(params: { taskId: string; versionId: string }): Promise<Array<{ communityId: string; name: string; nodeCount: number; qualityScore: number; summary: string }>>
  startArchTrack(params: { taskId: string; tag: string }): Promise<{ versionId: string }>
  stopArchTrack(params: { taskId: string; tag: string }): Promise<{ versionId: string; summary: string; risk: string; added: number; removed: number; changed: number }>
  getAgentProgress(params: { agentTaskId: string }): Promise<{ found: boolean; status?: string; step_current?: number; step_total?: number; tokens_used?: number; elapsed_sec?: number; message?: string; steps?: Array<{ description: string; status: string }>; error?: string }>
  cancelAgentTask(params: { agentTaskId: string }): Promise<{ cancelled: boolean }>
  saveCommunityResult(params: any): Promise<SaveCommunityResultResponse>
  getCommunityResult(params: any): Promise<any>
  listCommunityResults(taskId: string, edgeType: string): Promise<ListCommunityResultsResponse>
  updateCommunityName(params: any): Promise<UpdateCommunityNameResponse>
  onProgress(cb: (data: TaskProgressEvent) => void): void
  onComplete(cb: (data: TaskCompleteEvent) => void): void
  onError(cb: (data: TaskErrorEvent) => void): void
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
      return await api.analysis.scanFileStats(projectId, { ...rest, scopes, selectedExtensions }) as FileStatsResult
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
    startArchAnalysis: async (params) => {
      return await api.analysis.startArchAnalysis(params) as { taskId: string; success: boolean }
    },
    listArchSnapshots: async (params) => {
      return await api.analysis.listArchSnapshots(params)
    },
    getArchSnapshot: async (params) => {
      return await api.analysis.getArchSnapshot(params)
    },
    startArchTrack: async (params) => {
      return await api.analysis.startArchTrack(params) as { versionId: string }
    },
    stopArchTrack: async (params) => {
      return await api.analysis.stopArchTrack(params) as { versionId: string; summary: string; risk: string; added: number; removed: number; changed: number }
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
    onProgress: (cb: (data: TaskProgressEvent) => void) => {
      api.analysis.onProgress(cb)
    },
    onComplete: (cb: (data: TaskCompleteEvent) => void) => {
      api.analysis.onComplete(cb)
    },
    onError: (cb: (data: TaskErrorEvent) => void) => {
      api.analysis.onError(cb)
    },
  }
}
