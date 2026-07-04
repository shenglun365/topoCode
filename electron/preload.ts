/** Preload Script - 暴露安全的 API 给渲染进程 */

import { contextBridge, ipcRenderer } from 'electron'

// ==================== API 定义 ====================

contextBridge.exposeInMainWorld('api', {
  // ==================== 应用控制 ====================
  app: {
    quit: () => ipcRenderer.invoke('app:quit'),
  },

  // ==================== 窗口控制 ====================
  window: {
    toggleLeftPanel: () => ipcRenderer.invoke('window:toggle-left-panel'),
    toggleRightPanel: () => ipcRenderer.invoke('window:toggle-right-panel'),
    zoomIn: () => ipcRenderer.invoke('window:zoom-in'),
    zoomOut: () => ipcRenderer.invoke('window:zoom-out'),
    resetZoom: () => ipcRenderer.invoke('window:zoom-reset'),
    create: () => ipcRenderer.invoke('window:create'),
    close: (windowId?: number) => ipcRenderer.invoke('window:close', windowId),
    minimize: () => ipcRenderer.invoke('window:minimize'),
    maximize: () => ipcRenderer.invoke('window:maximize'),
    isMaximized: () => ipcRenderer.invoke('window:isMaximized'),
    list: () => ipcRenderer.invoke('window:list'),
    focus: (windowId: number) => ipcRenderer.invoke('window:focus', windowId),
    getCount: () => ipcRenderer.invoke('window:getCount'),
    getMaxCount: () => ipcRenderer.invoke('window:getMaxCount'),
    broadcast: (channel: string, data: any) => ipcRenderer.invoke('window:broadcast', channel, data),
    onPanelToggle: (channel: string, callback: () => void) => {
      const listener = (_: any, __: any) => callback()
      ipcRenderer.on(channel, listener)
      return () => ipcRenderer.removeListener(channel, listener)
    },
    onMaximizeChange: (callback: (maximized: boolean) => void) => {
      const listener = (_: any, maximized: boolean) => callback(maximized)
      ipcRenderer.on('window:maximized-changed', listener)
      return () => ipcRenderer.removeListener('window:maximized-changed', listener)
    },
  },

  // ==================== 对话框 ====================
  dialog: {
    openDirectory: () => ipcRenderer.invoke('dialog:open-directory'),
    openFile: (filters?: { name: string; extensions: string[] }[]) =>
      ipcRenderer.invoke('dialog:open-file', filters || []),
  },

  // ==================== 环境变量 (白名单) ====================
  env: {
    get: (key: string) => {
      const ALLOWED = new Set(['TOPCODE_UI_DEBUG', 'TOPOCODE_LOG_LEVEL', 'VITE_LOG_LEVEL'])
      if (!ALLOWED.has(key)) return null
      return ipcRenderer.invoke('env:get', key)
    },
    TOPOCODE_LOG_LEVEL: process.env.TOPOCODE_LOG_LEVEL || null,
    VITE_LOG_LEVEL: process.env.VITE_LOG_LEVEL || null,
    TOPCODE_UI_DEBUG: process.env.TOPCODE_UI_DEBUG || null,
  },

  // ==================== 外部链接 ====================
  shell: {
    openExternal: (url: string) => ipcRenderer.invoke('shell:open-external', url),
  },

  // ==================== 存储 ====================
  store: {
    get: (key: string) => ipcRenderer.invoke('store:get', key),
    set: (key: string, value: any) => ipcRenderer.invoke('store:set', key, value),
  },

  // ==================== 项目管理 ====================
  project: {
    list: () => ipcRenderer.invoke('ipc:call', { method: 'project.list', params: {} }),
    import: (path: string) => ipcRenderer.invoke('ipc:call', { method: 'project.import', params: { path } }),
    get: (id: string) => ipcRenderer.invoke('ipc:call', { method: 'project.get', params: { id } }),
    remove: (id: string) => ipcRenderer.invoke('ipc:call', { method: 'project.remove', params: { id } }),
    sync: (id: string) => ipcRenderer.invoke('ipc:call', { method: 'project.sync', params: { id } }),
    getFileTree: (id: string, fromPath?: string | null) => ipcRenderer.invoke('ipc:call', { method: 'project.getFileTree', params: { id, fromPath } }),
    updatePath: (id: string, newRootPath: string) => ipcRenderer.invoke('ipc:call', { method: 'project.updatePath', params: { id, newRootPath } }),
    checkFileChanges: (id: string) => ipcRenderer.invoke('ipc:call', { method: 'project.checkFileChanges', params: { id } }),
    initSampleData: () => ipcRenderer.invoke('ipc:call', { method: 'project.initSampleData', params: {} }),
    clearSampleData: (id: string) => ipcRenderer.invoke('ipc:call', { method: 'project.clearSampleData', params: { id } }),
    checkPathValidity: (id: string) => ipcRenderer.invoke('ipc:call', { method: 'project.checkPathValidity', params: { id } }),
    updateMeta: (id: string, meta: Record<string, any>) => ipcRenderer.invoke('ipc:call', { method: 'project.updateMeta', params: { id, ...meta } }),
    getStorageStats: (projectId: string) => ipcRenderer.invoke('ipc:call', { method: 'project.getStorageStats', params: { projectId } }),
    detectGitInfo: (params: { projectId: string }) => ipcRenderer.invoke('ipc:call', { method: 'project.detectGitInfo', params }),
    saveGitInfo: (params: any) => ipcRenderer.invoke('ipc:call', { method: 'project.saveGitInfo', params }),
    getGitInfo: (params: { projectId: string }) => ipcRenderer.invoke('ipc:call', { method: 'project.getGitInfo', params }),
    checkImportStatus: (params: { projectId: string }) => ipcRenderer.invoke('ipc:call', { method: 'project.checkImportStatus', params }),
  },

  // ==================== 分组管理 ====================
  group: {
    list: () => ipcRenderer.invoke('ipc:call', { method: 'group.list', params: {} }),
    create: (name: string, parent_id: string | null) => ipcRenderer.invoke('ipc:call', { method: 'group.create', params: { name, parent_id } }),
    update: (id: string, name: string | undefined, parent_id: string | null) => ipcRenderer.invoke('ipc:call', { method: 'group.update', params: { id, name, parent_id } }),
    delete: (id: string) => ipcRenderer.invoke('ipc:call', { method: 'group.delete', params: { id } }),
    addProject: (project_id: string, group_id: string) => ipcRenderer.invoke('ipc:call', { method: 'group.addProject', params: { project_id, group_id } }),
    removeProject: (project_id: string, group_id: string) => ipcRenderer.invoke('ipc:call', { method: 'group.removeProject', params: { project_id, group_id } }),
    getProjectGroups: (project_id: string) => ipcRenderer.invoke('ipc:call', { method: 'group.getProjectGroups', params: { project_id } }),
  },

  // ==================== 代码分析 ====================
  analysis: {
    listTasks: (projectId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.listTasks', params: { projectId } }),
    createTask: (params: { projectId: string; type: string; name: string; scope?: string; extensions?: string[]; excludeDirs?: string[]; reportTypes?: string[] }) => {
      console.log('[Preload] createTask called:', JSON.stringify(params))
      try {
        const result = ipcRenderer.invoke('ipc:call', { method: 'analysis.createTask', params })
        console.log('[Preload] createTask invoke returned (Promise):', typeof result)
        return result
      } catch (err: any) {
        console.error('[Preload] createTask invoke error:', err.message, err)
        throw err
      }
    },
    runTask: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.runTask', params: { taskId } }),
    getTask: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getTask', params: { taskId } }),
    getResults: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getResults', params: { taskId } }),
    updateTask: (params: { taskId: string; favorite?: boolean; pinned?: boolean; tags?: string[] }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.updateTask', params }),
    deleteTask: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.deleteTask', params: { taskId } }),
    stopTask: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.stopTask', params: { taskId } }),
    listRunningTasks: () =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.listRunningTasks', params: {} }),
    clearProjectCache: (projectId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.clearProjectCache', params: { projectId } }),
    getClearCacheCounts: (projectId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getClearCacheCounts', params: { projectId } }),
    clearProjectCacheTable: (projectId: string, table: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.clearProjectCacheTable', params: { projectId, table } }),
    reRunTask: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.reRunTask', params: { taskId } }),
    getTaskLogs: (params: { taskId: string; runId?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getTaskLogs', params }),
    getTaskRuns: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getTaskRuns', params: { taskId } }),
    updateTaskConfig: (params: { taskId: string; config: any }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.updateTaskConfig', params }),
    scanFileStats: (projectId: string, options?: { scope?: string; scopes?: string[]; selectedExtensions?: string[]; patternType?: string; pattern?: string; excludeDirs?: string[] }) => {
      console.log('[Preload] scanFileStats called:', { projectId, options: JSON.stringify(options) })
      const params = { projectId, ...options }
      console.log('[Preload] scanFileStats params to invoke:', JSON.stringify(params))
      try {
        const result = ipcRenderer.invoke('ipc:call', { method: 'analysis.scanFileStats', params })
        console.log('[Preload] scanFileStats invoke returned (Promise):', typeof result)
        return result
      } catch (err: any) {
        console.error('[Preload] scanFileStats invoke error:', err.message, err)
        throw err
      }
    },
    getAvailableLevels: (taskId: string, edgeType?: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getAvailableLevels', params: { taskId, edgeType } }),
    getCommunityGraph: (params: { taskId: string; edgeType: string; commLv: string; commIds: string[]; depth: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getCommunityGraph', params }),
    getSymbolDetail: (params: { taskId: string; symbolId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getSymbolDetail', params }),
    getEdgeDetail: (params: { taskId: string; edgeId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getEdgeDetail', params }),
    getCascadeLevels: (taskId: string, edgeType?: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getCascadeLevels', params: { taskId, edgeType } }),
    getReportDashboard: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getReportDashboard', params: { taskId } }),
    getQueryStats: (params: { taskId: string; edgeType?: string; commLv?: string; commIds?: string[]; depth?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getQueryStats', params }),
    getExternalStats: (taskId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getExternalStats', params: { taskId } }),
    getCrossCommunityEdges: (params: { taskId: string; edgeType: string; commLv: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getCrossCommunityEdges', params }),
    getCommunityNodeLists: (params: { taskId: string; edgeType: string; commLv: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getCommunityNodeLists', params }),
    startOverview: (params: { taskId: string; force?: boolean }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.startOverview', params }),
    getAgentProgress: (params: { agentTaskId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getAgentProgress', params }),
    cancelAgentTask: (params: { agentTaskId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.cancelAgentTask', params }),
    pauseAgentTask: (params: { agentTaskId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.pauseAgentTask', params }),
    resumeAgentTask: (params: { agentTaskId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.resumeAgentTask', params }),
    getAgentTaskHistory: (params: { taskId: string; offset?: number; limit?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getAgentTaskHistory', params }),
    clearAgentTaskHistory: (params: { taskId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.clearAgentTaskHistory', params }),
    // 预摘要
    getPreSummaryStatus: (params: { taskId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getPreSummaryStatus', params }),
    listPreSummaryFiles: (params: { taskId: string; batch?: string; page?: number; page_size?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.listPreSummaryFiles', params }),
    startPreSummary: (params: { taskId: string; batch?: string; limit?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.startPreSummary', params }),
    startPreSummaryPipeline: (params: { taskId: string; batches: string[]; limit?: number; subagentConcurrency?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.startPreSummaryPipeline', params }),
    getFileSummary: (params: { taskId: string; file_path: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getFileSummary', params }),
    deleteFileSummary: (params: { taskId: string; file_path: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.deleteFileSummary', params }),
    rerunFileSummary: (params: { taskId: string; file_path: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.rerunFileSummary', params }),
    startPipeline: (params: { taskId: string; force?: boolean; language?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.startPipeline', params }),
    analyzeComponents: (params: { taskId: string; components: Array<{ id: string; type: string; name: string; metadata?: Record<string, any> }>; language?: string; concurrency?: number; agentic?: boolean; maxTurns?: number; summaryModelId?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.analyzeComponents', params }),
    getAgentConfig: () =>
      ipcRenderer.invoke('ipc:call', { method: 'agent.getConfig', params: {} }),
    // 社区 LLM 结果持久化
    saveCommunityResult: (params: {
      taskId: string; edgeType: string; commLv: string; commId: string;
      name?: string; summary?: string; mermaid?: string; plantuml?: string;
      modelId?: string; templateId?: string;
    }) => {
      // 深拷贝剥离 Pinia 响应式 Proxy → 避免 Electron Structured Clone 失败
      const safe = JSON.parse(JSON.stringify(params))
      return ipcRenderer.invoke('ipc:call', { method: 'analysis.saveCommunityResult', params: safe })
    },
    getCommunityResult: (params: { taskId: string; edgeType: string; commLv: string; commId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getCommunityResult', params }),
    listCommunityResults: (taskId: string, edgeType: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.listCommunityResults', params: { taskId, edgeType } }),
    updateCommunityName: (params: { taskId: string; edgeType: string; commLv: string; commId: string; name: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.updateCommunityName', params }),
    getCommunityFileGraph: (params: { taskId: string; edgeType: string; commId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getCommunityFileGraph', params }),

    // 事件订阅
    onProgress: (callback: (data: any) => void) => {
      const listener = (_: any, data: any) => callback(data)
      ipcRenderer.on('event:task.progress', listener)
      return () => ipcRenderer.removeListener('event:task.progress', listener)
    },
    onComplete: (callback: (data: any) => void) => {
      const listener = (_: any, data: any) => callback(data)
      ipcRenderer.on('event:task.complete', listener)
      return () => ipcRenderer.removeListener('event:task.complete', listener)
    },
    onError: (callback: (data: any) => void) => {
      const listener = (_: any, data: any) => callback(data)
      ipcRenderer.on('event:task.error', listener)
      return () => ipcRenderer.removeListener('event:task.error', listener)
    },
    onStopped: (callback: (data: any) => void) => {
      const listener = (_: any, data: any) => callback(data)
      ipcRenderer.on('event:task.stopped', listener)
      return () => ipcRenderer.removeListener('event:task.stopped', listener)
    },
  },

  // ==================== 知识库 ====================
  knowledge: {
    listDocs: (params: { search?: string; dimensions?: any; sortBy?: string } = {}) =>
      ipcRenderer.invoke('ipc:call', { method: 'knowledge.listDocs', params }),
    createDoc: (params: { title: string; content?: string; projectId?: string; tags?: any; type?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'knowledge.createDoc', params }),
    getDoc: (id: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'knowledge.getDoc', params: { id } }),
    updateDoc: (params: {
      id: string
      content?: string
      tags?: any
      status?: string
      favorite?: boolean
      pinned?: boolean
      title?: string
      description?: string
    }) => ipcRenderer.invoke('ipc:call', { method: 'knowledge.updateDoc', params }),
    deleteDoc: (id: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'knowledge.deleteDoc', params: { id } }),
    getGraph: (params: { projectId?: string } = {}) =>
      ipcRenderer.invoke('ipc:call', { method: 'knowledge.getGraph', params }),
    getDimensions: () =>
      ipcRenderer.invoke('ipc:call', { method: 'knowledge.getDimensions', params: {} }),
  },

  // ==================== 报告子文档 ====================
  report: {
    createSubDoc: (params: { taskId: string; edgeType?: string; commId?: string; title: string; content: string; templateId?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.createSubDoc', params }),
    listSubDocs: (params: { taskId: string; commId?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.listSubDocs', params }),
    getSubDoc: (subDocId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.getSubDoc', params: { subDocId } }),
    updateSubDoc: (params: { subDocId: string; title?: string; content?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.updateSubDoc', params }),
    deleteSubDoc: (subDocId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.deleteSubDoc', params: { subDocId } }),
    // 报告生成辅助
    getReadmeContent: (params: { projectId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.getReadmeContent', params }),
    extractDependencyFiles: (params: { projectId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.extractDependencyFiles', params }),
    generateProjectSummary: (params: { projectId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.generateProjectSummary', params }),
    getProjectSummary: (params: { projectId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.getProjectSummary', params }),
    saveProjectSummary: (params: { projectId: string; summary: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.saveProjectSummary', params }),
    getLevelCommunityDetail: (params: { projectId: string; taskId: string; level?: string; edgeType?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.getLevelCommunityDetail', params }),
    saveFileSummaries: (params: { projectId: string; taskId: string; summaries: any[] }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.saveFileSummaries', params }),
    getFileSummaries: (params: { projectId: string; taskId?: string; source?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.getFileSummaries', params }),
    renderDiagram: (params: { taskId: string; communityId: string; edgeType?: string; mode?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.renderDiagram', params }),
    getCommunityFileDetail: (params: { taskId: string; communityId: string; edgeType?: string; limit?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.getCommunityFileDetail', params }),
    getCallLogs: (params: { sessionId?: string; requestId?: string; templateId?: string; status?: string; limit?: number; offset?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.getCallLogs', params }),
    getInteractionLogs: (params: { sessionId?: string; requestId?: string; templateId?: string; limit?: number; offset?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.getInteractionLogs', params }),
    saveOverallDoc: (params: { taskId: string; title: string; content: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'report.saveOverallDoc', params }),
  },

  // ==================== 设置配置 ====================
  settings: {
    getModels: () => ipcRenderer.invoke('ipc:call', { method: 'settings.getModels', params: {} }),
    addModel: (params: {
      name: string
      provider: string
      model: string
      url: string
      type?: string
      temperature?: number
      maxTokens?: number
      isDefault?: boolean
    }) => ipcRenderer.invoke('ipc:call', { method: 'settings.addModel', params }),
    updateModel: (params: {
      id: string
      name?: string
      temperature?: number
      maxTokens?: number
      url?: string
      isDefault?: boolean
    }) => ipcRenderer.invoke('ipc:call', { method: 'settings.updateModel', params }),
    removeModel: (id: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.removeModel', params: { id } }),
    testModel: (id: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.testModel', params: { id } }),

    getAgents: () => ipcRenderer.invoke('ipc:call', { method: 'settings.getAgents', params: {} }),
    addAgent: (params: { name: string; path: string; args?: string; type?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.addAgent', params }),
    updateAgent: (params: { id: string; path?: string; args?: string; name?: string; type?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.updateAgent', params }),
    removeAgent: (id: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.removeAgent', params: { id } }),
    detectAgent: (id: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.detectAgent', params: { id } }),
    executeAgent: (params: { id: string; task: string; args?: string; taskId?: string; env?: Record<string, string> }) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.executeAgent', params }),
    getAgentExecution: (execId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.getAgentExecution', params: { exec_id: execId } }),
    listAgentExecutions: (params: { agent_id?: string; task_id?: string; status_filter?: string; limit?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.listAgentExecutions', params: params || {} }),
    cancelAgentExecution: (execId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.cancelAgentExecution', params: { exec_id: execId } }),

    getSkills: () => ipcRenderer.invoke('ipc:call', { method: 'settings.getSkills', params: {} }),
    updateSkill: (params: { id: string; enabled: boolean }) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.updateSkill', params }),

    getBindings: () => ipcRenderer.invoke('ipc:call', { method: 'settings.getBindings', params: {} }),
    updateBindings: (params: { bindings: Record<string, string> }) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.updateBindings', params }),
  },

  // ==================== 模型用量统计 ====================
  model: {
    getUsageStats: (modelId?: string, startDate?: string, endDate?: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'model.getUsageStats', params: { model_id: modelId, start_date: startDate, end_date: endDate } }),
    deleteUsageStats: (id: number) =>
      ipcRenderer.invoke('ipc:call', { method: 'model.deleteUsageStats', params: { id } }),
    deleteUsageStatsBatch: (ids: number[]) =>
      ipcRenderer.invoke('ipc:call', { method: 'model.deleteUsageStatsBatch', params: { ids } }),
    deleteUsageStatsByCondition: (params: { modelId?: string; startDate?: string; endDate?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'model.deleteUsageStatsByCondition', params: { model_id: params.modelId, start_date: params.startDate, end_date: params.endDate } }),
  },

  // ==================== 设备指纹 ====================
  device: {
    getId: () => ipcRenderer.invoke('device:getId'),
  },

  // ==================== 后端管理 ====================
  backend: {
    start: () => ipcRenderer.invoke('ipc:call', { method: 'backend.start', params: {} }),
    stop: () => ipcRenderer.invoke('ipc:call', { method: 'backend.stop', params: {} }),
    restart: () => ipcRenderer.invoke('backend:restart'),
    getStatus: () => ipcRenderer.invoke('backend:getStatus'),  // 本地 PythonBridge 状态（不通过 ZMQ）
    getZmqStatus: () => ipcRenderer.invoke('ipc:call', { method: 'backend.getStatus', params: {} }),  // ZMQ Python 后端状态
    ping: () => ipcRenderer.invoke('ipc:call', { method: 'backend.ping', params: {} }),
    testPort: (port: number) => ipcRenderer.invoke('ipc:call', { method: 'backend.testPort', params: { port } }),
    getMemoryLimit: () => ipcRenderer.invoke('backend:getMemoryLimit'),
    setMemoryLimit: (limit: number) => ipcRenderer.invoke('backend:setMemoryLimit', limit),
    getHttpConfig: () => ipcRenderer.invoke('backend:getHttpConfig'),
    setHttpConfig: (config: { host: string; port: number }) => ipcRenderer.invoke('backend:setHttpConfig', config),
    saveHttpConfig: (config: { host?: string; port?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'backend.saveHttpConfig', params: config }),

    // 事件订阅
    onStatusChange: (callback: (data: any) => void) => {
      const listener = (_: any, data: any) => callback(data)
      ipcRenderer.on('event:backend.status', listener)
      return () => ipcRenderer.removeListener('event:backend.status', listener)
    },
  },

  // ==================== LLM Session 管理 (v2) ====================
  session: {
    list: (params?: { moduleType?: string; projectId?: string; status?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'session.list', params: params || {} }),
    create: (params: { moduleType: string; title: string; projectId?: string; metadata?: Record<string, any> }) =>
      ipcRenderer.invoke('ipc:call', { method: 'session.create', params }),
    delete: (params: { sessionId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'session.delete', params }),
    getMessages: (params: { sessionId: string; limit?: number; offset?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'session.getMessages', params }),
    addMessage: (params: { sessionId: string; role: string; content: string; tokenCount?: number; metadata?: Record<string, any> }) =>
      ipcRenderer.invoke('ipc:call', { method: 'session.addMessage', params }),
    deleteMessage: (params: { messageId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'session.deleteMessage', params }),
    updateMeta: (params: { sessionId: string; metadata: Record<string, any> }) =>
      ipcRenderer.invoke('ipc:call', { method: 'session.updateMeta', params }),
    clearAll: () =>
      ipcRenderer.invoke('ipc:call', { method: 'session.clearAll', params: {} }),
    },

  // ==================== 分析会话关联 ====================
  analysisSession: {
    list: (params?: { projectId?: string; taskId?: string; reportId?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysisSession.list', params: params || {} }),
    create: (params: { projectId: string; taskId: string; reportId?: string; sessionId: string; metadata?: Record<string, any> }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysisSession.create', params }),
    delete: (params: { sessionId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysisSession.delete', params }),
  },

  // ==================== LLM 推理 (v2 — 统一入口，所有业务方法使用 templateId) ====================
  llm: {
    chat: (params: {
      sessionId: string
      modelId: string
      mode?: 'chat' | 'tools' | 'structured'
      messages?: Array<{ role: string; content: string }>
      templateId?: string
      variables?: Record<string, any>
      tools?: string[]
      outputSchema?: Record<string, any>
    }) =>
      ipcRenderer.invoke('ipc:call', { method: 'llm.chat', params }),
    abortChat: (params: { requestId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'llm.abortChat', params }),
    // 订阅流式事件 (requestId → callbacks → unsubscribe)
    subscribe: (requestId: string, callbacks: {
      onChunk?: (data: { index: number; text: string }) => void
      onToolCall?: (data: { toolName: string; args: Record<string, any> }) => void
      onToolResult?: (data: { toolName: string; result: Record<string, any> }) => void
      onDone?: (data: { content: string; structured?: Record<string, any> }) => void
      onError?: (data: { message: string; code: string }) => void
    }) => {
      const channel = 'zmq:event'
      const handler = (_event: any, data: any) => {
        if (data.requestId !== requestId) return
        switch (data.eventType) {
          case 'chunk': callbacks.onChunk?.(data.data); break
          case 'tool_call': callbacks.onToolCall?.(data.data); break
          case 'tool_result': callbacks.onToolResult?.(data.data); break
          case 'done': callbacks.onDone?.(data.data); break
          case 'error': callbacks.onError?.(data.data); break
        }
      }
      ipcRenderer.on(channel, handler)
      return () => ipcRenderer.removeListener(channel, handler)
    },
  },

  // ==================== Prompt 模板 ====================
  promptTemplate: {
    list: (params?: { mode?: string; moduleType?: string; category?: string; locale?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.list', params: params || {} }),
    get: (params: { templateId: string; locale?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.get', params }),
    create: (params: {
      name: string; mode: string; moduleType?: string; category?: string; locale?: string
      systemPrompt?: string; userPromptTemplate?: string
      toolsJson?: string; toolStrategy?: string
      outputSchemaJson?: string; outputExample?: string
      variablesJson?: string
    }) =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.create', params }),
    update: (params: { templateId: string;[key: string]: any }) =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.update', params }),
    delete: (params: { templateId: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.delete', params }),
    render: (params: { templateId: string; variables: Record<string, any>; locale?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.render', params }),
    restoreDefaults: (params?: { locale?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.restoreDefaults', params: params || {} }),
    getDefaultLocale: () =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.getDefaultLocale', params: {} }),
    setDefaultLocale: (params: { locale: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'promptTemplate.setDefaultLocale', params }),
  },

  // ==================== 渲染服务 ====================
  render: {
    renderPlantuml: (params: { code: string; format?: string; useRemote?: boolean }) =>
      ipcRenderer.invoke('ipc:call', { method: 'render.plantuml', params }),
  },

  // ==================== 插件管理 ====================
  plugin: {
    list: () => ipcRenderer.invoke('ipc:call', { method: 'plugin.list', params: {} }),
    get: (name: string) => ipcRenderer.invoke('ipc:call', { method: 'plugin.get', params: { name } }),
    load: (name: string) => ipcRenderer.invoke('ipc:call', { method: 'plugin.load', params: { name } }),
    unload: (name: string) => ipcRenderer.invoke('ipc:call', { method: 'plugin.unload', params: { name } }),
    reload: (name: string) => ipcRenderer.invoke('ipc:call', { method: 'plugin.reload', params: { name } }),
    install: (name: string) => ipcRenderer.invoke('ipc:call', { method: 'plugin.install', params: { name } }),
  },

  // ==================== 文件系统 ====================
  fs: {
    addAllowedDir: (dirPath: string) => ipcRenderer.invoke('fs:add-allowed-dir', dirPath),
    readFile: (filePath: string) => ipcRenderer.invoke('fs:read-file', filePath),
  },

  // ==================== 系统 ====================
  system: {
    selectDirectory: () => ipcRenderer.invoke('dialog:open-directory'),
    getAppDataPath: () => ipcRenderer.invoke('system:get-app-data-path'),
    get: (key: string) => ipcRenderer.invoke('store:get', key),
    set: (key: string, val: any) => ipcRenderer.invoke('store:set', key, val),
    getHttpPort: () => ipcRenderer.invoke('system:get-http-port'),
    // 结构分析导入导出
    exportProject: (projectId: string, taskIds?: string[]) =>
      ipcRenderer.invoke('ipc:call', { method: 'system.exportProject', params: { projectId, taskIds } }),
    exportStatus: (exportId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'system.exportStatus', params: { exportId } }),
    importProjectArchive: (archivePath: string, importMode?: string, projectId?: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'system.importProjectArchive', params: { archivePath, importMode, projectId } }),
    importStatus: (importId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'system.importStatus', params: { importId } }),
    verifyFiles: (projectId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'system.verifyFiles', params: { projectId } }),
    verifyStatus: (verifyId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'system.verifyStatus', params: { verifyId } }),
  },

  // ==================== 事件订阅 ====================
  // 使用 on() 返回的清理函数取消订阅，不要直接使用 removeListener
  on: (channel: string, callback: (...args: any[]) => void) => {
    const listener = (_: any, ...args: any[]) => callback(...args)
    ipcRenderer.on(channel, listener)
    return () => ipcRenderer.removeListener(channel, listener)
  },

  // ==================== Auto-update ====================
  update: {
    check: () => ipcRenderer.invoke('update:check'),
    download: () => ipcRenderer.invoke('update:download'),
    install: () => ipcRenderer.invoke('update:install'),
    onStatus: (cb: (info: any) => void) => {
      const listener = (_: any, info: any) => cb(info)
      ipcRenderer.on('update:status', listener)
      return () => ipcRenderer.removeListener('update:status', listener)
    },
  },

  // ==================== 模块管理（远程下载） ====================
  module: {
    listRegistry: (registryUrl?: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'module.listRegistry', params: { registry_url: registryUrl } }),
    getInstalled: () =>
      ipcRenderer.invoke('ipc:call', { method: 'module.getInstalled', params: {} }),
    install: (name: string, registryUrl?: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'module.install', params: { name, registry_url: registryUrl } }),
    uninstall: (name: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'module.uninstall', params: { name } }),
    update: (name: string, registryUrl?: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'module.update', params: { name, registry_url: registryUrl } }),
    search: (query: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'module.search', params: { query } }),
  },

  // ==================== 图位置 ====================
  graph: {
    savePositions: (params: any) => ipcRenderer.invoke('ipc:call', { method: 'graph.savePositions', params }),
    loadPositions: (params: any) => ipcRenderer.invoke('ipc:call', { method: 'graph.loadPositions', params }),
    clearPositions: (params: any) => ipcRenderer.invoke('ipc:call', { method: 'graph.clearPositions', params }),
    listSavedPositionKeys: (params: any) => ipcRenderer.invoke('ipc:call', { method: 'graph.listSavedPositionKeys', params }),
  },

  // ==================== 日志系统 ====================
  log: {
    debug: (source: string, message: string, data?: any) => {
      ipcRenderer.send('log:debug', source, message, data)
    },
    info: (source: string, message: string, data?: any) => {
      ipcRenderer.send('log:info', source, message, data)
    },
    warn: (source: string, message: string, data?: any) => {
      ipcRenderer.send('log:warn', source, message, data)
    },
    error: (source: string, message: string, data?: any) => {
      ipcRenderer.send('log:error', source, message, data)
    },
  },
})

// Window API 类型由 src/types/ipc.ts 中的 IPCAPI 统一声明
// (含 session / llm / promptTemplate 等 v2 API)
