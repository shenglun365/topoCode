/** IPC Service - 真实后端调用 (Electron 环境) */

import type {
  IPCAPI,
  Project,
  FileTreeNode,
  AnalysisTask,
  AnalysisResult,
  KnowledgeDoc,
  KnowledgeGraph,
  Dimensions,
  ModelConfigItem,
  AgentConfigItem,
  SkillConfigItem,
  ImportConfig,
  TaskProgressEvent,
  TaskCompleteEvent,
  TaskErrorEvent,
  BackendStatusEvent,
  TaskConfigUpdate,
  ScanOptions,
  GitInfo,
} from '@/types/ipc'

/**
 * 字段适配：后端 snake_case → 前端 camelCase
 */
function adaptProject(p: any): Project {
  if (!p) return null as any
  return {
    ...p,
    rootPath: p.root_path || p.rootPath || '',
    path: p.root_path || p.path || '',
    fileCount: p.file_count ?? p.fileCount ?? 0,
    needsResync: p.needs_resync ?? p.needsResync ?? 0,
    hasFileChanges: p.has_file_changes ?? p.hasFileChanges ?? 0,
    isSample: p.is_sample ?? p.isSample ?? 0,
    lastSync: p.last_sync ?? p.lastSync ?? null,
    createdAt: p.created_at ?? p.createdAt ?? '',
    groups: p.groups || [],
    doneTaskCount: p.done_task_count ?? p.doneTaskCount ?? 0,
  }
}

function adaptProjectList(list: any[]): Project[] {
  return (list || []).filter(Boolean).map(adaptProject)
}

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

/**
 * IPC Service
 *
 * Electron 环境: 通过 window.api 调用 ZeroMQ → Python 后端
 * 浏览器环境: 不可用 (需 Electron 运行)
 */
export const ipc: IPCAPI = createRealIPC() as unknown as IPCAPI

function createRealIPC() {
  const api: any = typeof window !== 'undefined' ? (window as any).api : null

  if (!api) {
    console.warn('[IPC] window.api not available - running in browser without Electron')
  }

  // 事件回调存储 (用于浏览器降级)
  const taskProgressCbs: Array<(data: TaskProgressEvent) => void> = []
  const taskCompleteCbs: Array<(data: TaskCompleteEvent) => void> = []
  const taskErrorCbs: Array<(data: TaskErrorEvent) => void> = []
  const taskStoppedCbs: Array<(data: any) => void> = []
  const backendStatusCbs: Array<(data: BackendStatusEvent) => void> = []

  return {
    // ==================== 项目管理 ====================
    project: {
      list: async () => {
        const list = await api.project.list()
        return adaptProjectList(list)
      },
      import: async (path: string) => {
        const result = await api.project.import(path)
        return adaptProject(result)
      },
      get: async (id: string) => {
        const result = await api.project.get(id)
        return adaptProject(result)
      },
      remove: async (id: string) => {
        await api.project.remove(id)
      },
      sync: async (id: string) => {
        const result = await api.project.sync(id)
        return adaptProject(result)
      },
      getFileTree: async (id: string, fromPath?: string | null) => {
        return await api.project.getFileTree(id, fromPath)
      },
      updatePath: async (id: string, newRootPath: string) => {
        return await api.project.updatePath(id, newRootPath)
      },
      checkFileChanges: async (id: string) => {
        return await api.project.checkFileChanges(id)
      },
      initSampleData: async () => {
        return await api.project.initSampleData()
      },
      clearSampleData: async (id: string) => {
        return await api.project.clearSampleData(id)
      },
      checkPathValidity: async (id: string) => {
        return await api.project.checkPathValidity(id)
      },
      updateMeta: async (id: string, meta: Record<string, any>) => {
        const result = await api.project.updateMeta(id, meta)
        return adaptProject(result)
      },
      getStorageStats: async (projectId: string) => {
        return await api.project.getStorageStats(projectId)
      },
      detectGitInfo: async (params: { projectId: string }) => {
        return await api.project.detectGitInfo(params)
      },
      saveGitInfo: async (params: any) => {
        return await api.project.saveGitInfo(params)
      },
      getGitInfo: async (params: { projectId: string }) => {
        return await api.project.getGitInfo(params)
      },
      checkImportStatus: async (params: { projectId: string }) => {
        return await api.project.checkImportStatus(params)
      },
    },

    // ==================== 分组管理 ====================
    group: {
      list: async () => {
        return await api.group.list()
      },
      create: async (name: string, parentId?: string | null) => {
        return await api.group.create(name, parentId || null)
      },
      update: async (id: string, name?: string, parentId?: string | null) => {
        return await api.group.update(id, name, parentId ?? null)
      },
      delete: async (id: string) => {
        return await api.group.delete(id)
      },
      addProject: async (projectId: string, groupId: string) => {
        return await api.group.addProject(projectId, groupId)
      },
      removeProject: async (projectId: string, groupId: string) => {
        return await api.group.removeProject(projectId, groupId)
      },
      getProjectGroups: async (projectId: string) => {
        return await api.group.getProjectGroups(projectId)
      },
    },

    // ==================== 代码分析 ====================
    analysis: {
      listTasks: async (projectId: string) => {
        const list = await api.analysis.listTasks(projectId)
        return adaptTaskList(list)
      },
      listRunningTasks: async () => {
        return await api.analysis.listRunningTasks()
      },
      createTask: async (params: { projectId: string; type: string; name: string; scope?: string; extensions?: string[]; excludeDirs?: string[]; reportTypes?: string[] }) => {
        console.log('[IPC] createTask -> api.analysis.createTask:', JSON.stringify(params))
        try {
          const result = await api.analysis.createTask(params)
          console.log('[IPC] createTask result:', JSON.stringify(result))
          return adaptTask(result)
        } catch (err: any) {
          console.error('[IPC] createTask error:', err.message, err)
          throw err
        }
      },
      runTask: async (taskId: string) => {
        return await api.analysis.runTask(taskId)
      },
      getTask: async (taskId: string) => {
        const t = await api.analysis.getTask(taskId)
        if (!t) return null
        return { ...t, projectId: t.project_id ?? t.projectId ?? '', createdAt: t.created_at ?? t.createdAt ?? '' }
      },
      getResults: async (taskId: string) => {
        return await api.analysis.getResults(taskId)
      },
      updateTask: async (params: { taskId: string; favorite?: boolean; pinned?: boolean; tags?: string[] }) => {
        const result = await api.analysis.updateTask(params)
        return adaptTask(result)
      },
      deleteTask: async (taskId: string) => {
        return await api.analysis.deleteTask(taskId)
      },
      stopTask: async (taskId: string) => {
        return await api.analysis.stopTask(taskId)
      },
      clearProjectCache: async (projectId: string) => {
        return await api.analysis.clearProjectCache(projectId)
      },
      getClearCacheCounts: async (projectId: string) => {
        return await api.analysis.getClearCacheCounts(projectId)
      },
      clearProjectCacheTable: async (projectId: string, table: string) => {
        return await api.analysis.clearProjectCacheTable(projectId, table)
      },
      reRunTask: async (taskId: string) => {
        return await api.analysis.reRunTask(taskId)
      },
      getTaskLogs: async (params: { taskId: string; runId?: string }) => {
        return await api.analysis.getTaskLogs(params)
      },
      getTaskRuns: async (taskId: string) => {
        return await api.analysis.getTaskRuns(taskId)
      },
      updateTaskConfig: async (params: { taskId: string; config: TaskConfigUpdate }) => {
        return await api.analysis.updateTaskConfig(params)
      },
      scanFileStats: async (projectId: string, options?: ScanOptions) => {
        console.log('[IPC] scanFileStats -> api.analysis.scanFileStats:', { projectId, options: JSON.stringify(options) })
        const scopes = options?.scopes
        const selectedExtensions = options?.selectedExtensions
        const rest: Record<string, any> = { ...options }
        delete rest.scopes
        delete rest.selectedExtensions
        // JSON round-trip 去除 Vue reactive Proxy（contextBridge structuredClone 拒绝 Proxy）
        const callParams: Record<string, any> = JSON.parse(JSON.stringify({ ...rest, scopes, selectedExtensions }))
        console.log('[IPC] scanFileStats callParams:', JSON.stringify(callParams))
        try {
          const result = await api.analysis.scanFileStats(projectId, callParams)
          console.log('[IPC] scanFileStats result:', JSON.stringify(result))
          return result
        } catch (err: any) {
          console.error('[IPC] scanFileStats error:', err.message, err)
          throw err
        }
      },
      getAvailableLevels: async (taskId: string, edgeType?: string) => {
        return await api.analysis.getAvailableLevels(taskId, edgeType)
      },
      getCommunityGraph: async (params: { taskId: string; edgeType: string; commLv: string; commIds: string[]; depth: number }) => {
        return await api.analysis.getCommunityGraph(params)
      },
      getSymbolDetail: async (params: { taskId: string; symbolId: string }) => {
        return await api.analysis.getSymbolDetail(params)
      },
      getEdgeDetail: async (params: { taskId: string; edgeId: string }) => {
        return await api.analysis.getEdgeDetail(params)
      },
      getCascadeLevels: async (taskId: string, edgeType?: string) => {
        return await api.analysis.getCascadeLevels(taskId, edgeType)
      },
      getReportDashboard: async (taskId: string) => {
        return await api.analysis.getReportDashboard(taskId)
      },
      getQueryStats: async (params: {
        taskId: string
        edgeType?: string
        commLv?: string
        commIds?: string[]
        depth?: number
      }) => {
        return await api.analysis.getQueryStats(params)
      },
      getExternalStats: async (taskId: string) => {
        return await api.analysis.getExternalStats(taskId)
      },
      getCrossCommunityEdges: async (params: { taskId: string; edgeType: string; commLv: string }) => {
        return await api.analysis.getCrossCommunityEdges(params)
      },
      getCommunityNodeLists: async (params: { taskId: string; edgeType: string; commLv: string }) => {
        return await api.analysis.getCommunityNodeLists(params)
      },
      startOverview: async (params: { taskId: string; force?: boolean }) => {
        return await api.analysis.startOverview(params)
      },
      getAgentProgress: async (params: { agentTaskId: string }) => {
        return await api.analysis.getAgentProgress(params)
      },
      cancelAgentTask: async (params: { agentTaskId: string }) => {
        return await api.analysis.cancelAgentTask(params)
      },
      getAgentTaskHistory: async (params: { taskId: string; offset?: number; limit?: number }) => {
        return await api.analysis.getAgentTaskHistory(params)
      },
      clearAgentTaskHistory: async (params: { taskId: string }) => {
        return await api.analysis.clearAgentTaskHistory(params)
      },
      getPreSummaryStatus: async (params: { taskId: string }) => {
        return await api.analysis.getPreSummaryStatus(params)
      },
      listPreSummaryFiles: async (params: { taskId: string; batch?: string; page?: number; page_size?: number }) => {
        return await api.analysis.listPreSummaryFiles(params)
      },
      startPreSummary: async (params: { taskId: string; batch?: string; limit?: number }) => {
        return await api.analysis.startPreSummary(params)
      },
      startPreSummaryPipeline: async (params: { taskId: string; batches: string[]; limit?: number; subagentConcurrency?: number }) => {
        return await api.analysis.startPreSummaryPipeline(params)
      },
      getFileSummary: async (params: { taskId: string; file_path: string }) => {
        return await api.analysis.getFileSummary(params)
      },
      deleteFileSummary: async (params: { taskId: string; file_path: string }) => {
        return await api.analysis.deleteFileSummary(params)
      },
      rerunFileSummary: async (params: { taskId: string; file_path: string }) => {
        return await api.analysis.rerunFileSummary(params)
      },
      startPipeline: async (params: { taskId: string; force?: boolean; language?: string }) => {
        return await api.analysis.startPipeline(params)
      },
      getAgentConfig: async () => {
        return await api.analysis.getAgentConfig()
      },
      analyzeComponents: async (params: { taskId: string; components: Array<{ id: string; type: string; name: string; metadata?: Record<string, any> }>; language?: string; concurrency?: number; agentic?: boolean; maxTurns?: number; summaryModelId?: string; analysisMode?: string; force?: boolean }) => {
        return await api.analysis.analyzeComponents(params)
      },
      saveCommunityResult: async (params: any) => {
        // 深拷贝剥离 Pinia 响应式 Proxy → 避免 Electron Structured Clone 失败
        const safe = JSON.parse(JSON.stringify(params))
        return await api.analysis.saveCommunityResult(safe)
      },
      getCommunityResult: async (params: any) => {
        return await api.analysis.getCommunityResult(params)
      },
      listCommunityResults: async (taskId: string, edgeType: string) => {
        return await api.analysis.listCommunityResults(taskId, edgeType)
      },
      updateCommunityName: async (params: any) => {
        return await api.analysis.updateCommunityName(params)
      },
      getCommunityFileGraph: async (params: any) => {
        return await api.analysis.getCommunityFileGraph(params)
      },
      onProgress: (cb: (data: TaskProgressEvent) => void) => {
        if (api.analysis.onProgress) {
          api.analysis.onProgress(cb)
        } else {
          taskProgressCbs.push(cb)
        }
      },
      onComplete: (cb: (data: TaskCompleteEvent) => void) => {
        if (api.analysis.onComplete) {
          api.analysis.onComplete(cb)
        } else {
          taskCompleteCbs.push(cb)
        }
      },
      onError: (cb: (data: TaskErrorEvent) => void) => {
        if (api.analysis.onError) {
          api.analysis.onError(cb)
        } else {
          taskErrorCbs.push(cb)
        }
      },
      onStopped: (cb: (data: any) => void) => {
        if (api.analysis.onStopped) {
          api.analysis.onStopped(cb)
        } else {
          taskStoppedCbs.push(cb)
        }
      },
    },

    // ==================== 报告子文档 ====================
    report: {
      createSubDoc: async (params: {
        taskId: string
        edgeType?: string
        commId?: string
        title: string
        content: string
        templateId?: string
      }) => {
        return await api.report.createSubDoc(params)
      },
      listSubDocs: async (params: { taskId: string; commId?: string }) => {
        return await api.report.listSubDocs(params)
      },
      getSubDoc: async (subDocId: string) => {
        return await api.report.getSubDoc(subDocId)
      },
      updateSubDoc: async (params: {
        subDocId: string
        title?: string
        content?: string
      }) => {
        return await api.report.updateSubDoc(params)
      },
      deleteSubDoc: async (subDocId: string) => {
        return await api.report.deleteSubDoc(subDocId)
      },
      saveOverallDoc: async (params: { taskId: string; title: string; content: string }) => {
        return await api.report.saveOverallDoc(params)
      },
      getReadmeContent: async (params: { projectId: string }) => {
        return await api.report.getReadmeContent(params)
      },
      extractDependencyFiles: async (params: { projectId: string }) => {
        return await api.report.extractDependencyFiles(params)
      },
      generateProjectSummary: async (params: { projectId: string }) => {
        return await api.report.generateProjectSummary(params)
      },
      getProjectSummary: async (params: { projectId: string }) => {
        return await api.report.getProjectSummary(params)
      },
      saveProjectSummary: async (params: { projectId: string; summary: string }) => {
        return await api.report.saveProjectSummary(params)
      },
      getLevelCommunityDetail: async (params: { projectId: string; taskId: string; level?: string; edgeType?: string }) => {
        return await api.report.getLevelCommunityDetail(params)
      },
      saveFileSummaries: async (params: { projectId: string; taskId: string; summaries: any[] }) => {
        return await api.report.saveFileSummaries(params)
      },
      getFileSummaries: async (params: { projectId: string; taskId?: string; source?: string }) => {
        return await api.report.getFileSummaries(params)
      },
      getCommunityFileDetail: async (params: { taskId: string; communityId: string; edgeType?: string; limit?: number }) => {
        return await api.report.getCommunityFileDetail(params)
      },
      getCallLogs: async (params: any) => {
        return await api.report.getCallLogs(params)
      },
      getInteractionLogs: async (params: any) => {
        return await api.report.getInteractionLogs(params)
      },
    } as IPCAPI['report'],

    // ==================== 知识库 ====================
    knowledge: {
      listDocs: async (params?: { search?: string; dimensions?: Partial<Dimensions>; sortBy?: string }) => {
        return await api.knowledge.listDocs(params || {})
      },
      createDoc: async (params: { title: string; content: string; projectId: string; tags?: Partial<Dimensions> }) => {
        return await api.knowledge.createDoc(params)
      },
      getDoc: async (id: string) => {
        return await api.knowledge.getDoc(id)
      },
      updateDoc: async (params: { id: string; content?: string; tags?: Partial<Dimensions>; status?: string; favorite?: boolean; pinned?: boolean }) => {
        return await api.knowledge.updateDoc(params)
      },
      deleteDoc: async (id: string) => {
        return await api.knowledge.deleteDoc(id)
      },
      getGraph: async (params?: { projectId?: string }) => {
        return await api.knowledge.getGraph(params || {})
      },
      getDimensions: async () => {
        return await api.knowledge.getDimensions()
      },
    },

    // ==================== 设置配置 ====================
    settings: {
      getModels: async () => {
        return await api.settings.getModels()
      },
      addModel: async (params: { name: string; provider: string; model: string; url: string; type: string; temperature?: number; maxTokens?: number; frequencyPenalty?: number; presencePenalty?: number }) => {
        return await api.settings.addModel(params)
      },
      updateModel: async (params: { id: string; name?: string; temperature?: number; maxTokens?: number; frequencyPenalty?: number; presencePenalty?: number }) => {
        return await api.settings.updateModel(params)
      },
      removeModel: async (id: string) => {
        return await api.settings.removeModel(id)
      },
      testModel: async (id: string) => {
        return await api.settings.testModel(id)
      },
      getAgents: async () => {
        return await api.settings.getAgents()
      },
      addAgent: async (params: { name: string; path: string; args: string; type?: string }) => {
        return await api.settings.addAgent(params)
      },
      updateAgent: async (params: { id: string; path?: string; args?: string; name?: string; type?: string }) => {
        return await api.settings.updateAgent(params)
      },
      removeAgent: async (id: string) => {
        return await api.settings.removeAgent(id)
      },
      detectAgent: async (id: string) => {
        return await api.settings.detectAgent(id)
      },
      executeAgent: async (params: { id: string; task: string; args?: string; taskId?: string; env?: Record<string, string> }) => {
        return await api.settings.executeAgent(params)
      },
      getAgentExecution: async (execId: string) => {
        return await api.settings.getAgentExecution(execId)
      },
      listAgentExecutions: async (params?: { agentId?: string; taskId?: string; status?: string; limit?: number }) => {
        return await api.settings.listAgentExecutions(params || {})
      },
      cancelAgentExecution: async (execId: string) => {
        return await api.settings.cancelAgentExecution(execId)
      },
      getSkills: async () => {
        return await api.settings.getSkills()
      },
      updateSkill: async (params: { id: string; enabled: boolean }) => {
        return await api.settings.updateSkill(params)
      },
      getBindings: async () => {
        return await api.settings.getBindings()
      },
      updateBindings: async (params: { bindings: Record<string, string> }) => {
        return await api.settings.updateBindings(params)
      },
      getImportConfig: async () => {
        const result: ImportConfig = await api.settings.getImportConfig()
        return {
          ignoreMode: result.ignoreMode || 'strict',
          extraIgnoreFiles: result.extraIgnoreFiles || [],
          customPatterns: result.customPatterns || [],
        }
      },
      setImportConfig: async (params: { ignoreMode?: string; customPatterns?: string[]; extraIgnoreFiles?: string[] }) => {
        const result: ImportConfig = await api.settings.setImportConfig(params)
        return {
          ignoreMode: result.ignoreMode || 'strict',
          extraIgnoreFiles: result.extraIgnoreFiles || [],
          customPatterns: result.customPatterns || [],
        }
      },
    },

    // ==================== 模型用量统计 ====================
    model: {
      getUsageStats: async (modelId?: string, startDate?: string, endDate?: string) => {
        return await api.model.getUsageStats(modelId, startDate, endDate)
      },
      deleteUsageStats: async (id: number) => {
        return await api.model.deleteUsageStats(id)
      },
      deleteUsageStatsBatch: async (ids: number[]) => {
        return await api.model.deleteUsageStatsBatch(ids)
      },
      deleteUsageStatsByCondition: async (params: { modelId?: string; startDate?: string; endDate?: string }) => {
        return await api.model.deleteUsageStatsByCondition(params)
      },
    },

    // ==================== 后端管理 ====================
    backend: {
      start: async () => {
        return await api.backend.start()
      },
      stop: async () => {
        return await api.backend.stop()
      },
      restart: async () => {
        return await api.backend.restart()
      },
      getStatus: async () => {
        return await api.backend.getStatus()
      },
      getMemoryLimit: async () => {
        return await (api.backend as any).getMemoryLimit()
      },
      setMemoryLimit: async (limit: number) => {
        await (api.backend as any).setMemoryLimit(limit)
      },
      ping: async () => {
        return await (api.backend as any).ping()
      },
      testPort: async (port: number) => {
        return await (api.backend as any).testPort(port)
      },
      onStatusChange: (cb: (data: BackendStatusEvent) => void) => {
        if (api.backend.onStatusChange) {
          api.backend.onStatusChange(cb)
        } else {
          backendStatusCbs.push(cb)
        }
      },
      getHttpConfig: async () => {
        return await api.backend.getHttpConfig()
      },
      setHttpConfig: async (config: { host: string; port: number }) => {
        return await api.backend.setHttpConfig(config)
      },
      saveHttpConfig: async (config: { host?: string; port?: number }) => {
        return await api.backend.saveHttpConfig(config)
      },
    },


  }
}
