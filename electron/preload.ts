/** Preload Script - 暴露安全的 API 给渲染进程 */

import { contextBridge, ipcRenderer } from 'electron'

// ==================== API 定义 ====================

contextBridge.exposeInMainWorld('api', {
  // ==================== 窗口控制 ====================
  window: {
    toggleLeftPanel: () => ipcRenderer.invoke('window:toggle-left-panel'),
    toggleRightPanel: () => ipcRenderer.invoke('window:toggle-right-panel'),
    zoomIn: () => ipcRenderer.invoke('window:zoom-in'),
    zoomOut: () => ipcRenderer.invoke('window:zoom-out'),
    create: () => ipcRenderer.invoke('window:create'),
    close: (windowId: number) => ipcRenderer.invoke('window:close', windowId),
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
  },

  // ==================== 对话框 ====================
  dialog: {
    openDirectory: () => ipcRenderer.invoke('dialog:open-directory'),
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
    clearProjectCache: (projectId: string) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.clearProjectCache', params: { projectId } }),
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
    getQueryStats: (params: { taskId: string; edgeType?: string; commLv?: string; commIds?: string[]; depth?: number }) =>
      ipcRenderer.invoke('ipc:call', { method: 'analysis.getQueryStats', params }),

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

    getSkills: () => ipcRenderer.invoke('ipc:call', { method: 'settings.getSkills', params: {} }),
    updateSkill: (params: { id: string; enabled: boolean }) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.updateSkill', params }),

    getBindings: () => ipcRenderer.invoke('ipc:call', { method: 'settings.getBindings', params: {} }),
    updateBindings: (params: { bindings: Record<string, string> }) =>
      ipcRenderer.invoke('ipc:call', { method: 'settings.updateBindings', params }),
  },

  // ==================== 后端管理 ====================
  backend: {
    start: () => ipcRenderer.invoke('ipc:call', { method: 'backend.start', params: {} }),
    stop: () => ipcRenderer.invoke('ipc:call', { method: 'backend.stop', params: {} }),
    restart: () => ipcRenderer.invoke('ipc:call', { method: 'backend.restart', params: {} }),
    getStatus: () => ipcRenderer.invoke('ipc:call', { method: 'backend.getStatus', params: {} }),
    ping: () => ipcRenderer.invoke('ipc:call', { method: 'backend.ping', params: {} }),
    testPort: (port: number) => ipcRenderer.invoke('ipc:call', { method: 'backend.testPort', params: { port } }),

    // 事件订阅
    onStatusChange: (callback: (data: any) => void) => {
      const listener = (_: any, data: any) => callback(data)
      ipcRenderer.on('event:backend.status', listener)
      return () => ipcRenderer.removeListener('event:backend.status', listener)
    },
  },

  // ==================== Chat 会话 ====================
  chat: {
    listSessions: () =>
      ipcRenderer.invoke('ipc:call', { method: 'chat.listSessions', params: {} }),
    createSession: (params: { id: string; title: string; mode?: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'chat.createSession', params }),
    deleteSession: (params: { id: string }) =>
      ipcRenderer.invoke('ipc:call', { method: 'chat.deleteSession', params }),
    saveMessage: (params: { sessionId: string; message: any }) =>
      ipcRenderer.invoke('ipc:call', { method: 'chat.saveMessage', params }),
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
  },

  // ==================== 事件订阅 ====================
  on: (channel: string, callback: (...args: any[]) => void) => {
    const listener = (_: any, ...args: any[]) => callback(...args)
    ipcRenderer.on(channel, listener)
    return () => ipcRenderer.removeListener(channel, listener)
  },
  removeListener: (channel: string, callback: (...args: any[]) => void) => {
    ipcRenderer.removeListener(channel, callback)
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

// ==================== 类型声明 ====================

declare global {
  interface Window {
    api: {
      window: {
        toggleLeftPanel: () => Promise<void>
        toggleRightPanel: () => Promise<void>
        zoomIn: () => Promise<void>
        zoomOut: () => Promise<void>
        create: () => Promise<number | null>
        close: (windowId: number) => Promise<boolean>
        list: () => Promise<Array<{ id: number; title: string; isFocused: boolean }>>
        focus: (windowId: number) => Promise<boolean>
        getCount: () => Promise<number>
        getMaxCount: () => Promise<number>
        broadcast: (channel: string, data: any) => Promise<boolean>
        onPanelToggle: (channel: string, callback: () => void) => () => void
      }
      dialog: {
        openDirectory: () => Promise<string | null>
      }
      shell: {
        openExternal: (url: string) => Promise<void>
      }
      store: {
        get: (key: string) => Promise<any>
        set: (key: string, value: any) => Promise<boolean>
      }
      fs: {
        addAllowedDir: (dirPath: string) => Promise<void>
        readFile: (filePath: string) => Promise<string>
      }
      project: {
        list: () => Promise<any[]>
        import: (path: string) => Promise<any>
        get: (id: string) => Promise<any>
        remove: (id: string) => Promise<void>
        sync: (id: string) => Promise<any>
        getFileTree: (id: string) => Promise<any[]>
        checkPathValidity: (id: string) => Promise<{ pathValid: boolean; rootPath: string; needsResync: boolean }>
      }
      analysis: {
        listTasks: (projectId: string) => Promise<any[]>
        createTask: (params: { projectId: string; type: string; name: string; scope?: string; extensions?: string[]; excludeDirs?: string[]; reportTypes?: string[] }) => Promise<any>
        runTask: (taskId: string) => Promise<{ taskId: string; status: string }>
        getTask: (taskId: string) => Promise<any>
        getResults: (taskId: string) => Promise<any>
        updateTask: (params: { taskId: string; favorite?: boolean; pinned?: boolean; tags?: string[] }) => Promise<any>
        deleteTask: (taskId: string) => Promise<void>
        stopTask: (taskId: string) => Promise<void>
        clearProjectCache: (projectId: string) => Promise<{ projectId: string; deletedTasks: number; fileCount: number }>
        reRunTask: (taskId: string) => Promise<any>
        getTaskLogs: (params: { taskId: string; runId?: string }) => Promise<any>
        getTaskRuns: (taskId: string) => Promise<any>
        updateTaskConfig: (params: { taskId: string; config: any }) => Promise<any>
        scanFileStats: (projectId: string, options?: { scope?: string; scopes?: string[]; selectedExtensions?: string[]; patternType?: string; pattern?: string; excludeDirs?: string[] }) => Promise<any>
        getAvailableLevels: (taskId: string, edgeType?: string) => Promise<string[]>
        getCommunityGraph: (params: { taskId: string; edgeType: string; commLv: string; commIds: string[]; depth: number }) => Promise<{ nodes: any[]; edges: any[]; communities: any[] }>
        getSymbolDetail: (params: { taskId: string; symbolId: string }) => Promise<any>
        getEdgeDetail: (params: { taskId: string; edgeId: string }) => Promise<any>
        getCascadeLevels: (taskId: string, edgeType?: string) => Promise<{ levels: Array<{ lv: string; items: Array<{ id: string; label: string; parentCommId: string | null; nodeCount: number; qualityScore: number }> }> }>
        getQueryStats: (params: { taskId: string; edgeType?: string; commLv?: string; commIds?: string[]; depth?: number }) => Promise<{ communityCount: number; nodeCount: number; edgeCount: number }>
        onProgress: (callback: (data: any) => void) => () => void
        onComplete: (callback: (data: any) => void) => () => void
        onError: (callback: (data: any) => void) => () => void
      }
      knowledge: {
        listDocs: (params?: any) => Promise<any[]>
        createDoc: (params: { title: string; content?: string; projectId?: string; tags?: any; type?: string }) => Promise<any>
        getDoc: (id: string) => Promise<any>
        updateDoc: (params: any) => Promise<any>
        deleteDoc: (id: string) => Promise<void>
        getGraph: (params?: { projectId?: string }) => Promise<any>
        getDimensions: () => Promise<any>
      }
      report: {
        createSubDoc: (params: { taskId: string; edgeType?: string; commId?: string; title: string; content: string; templateId?: string }) => Promise<{ id: string }>
        listSubDocs: (params: { taskId: string; commId?: string }) => Promise<any[]>
        getSubDoc: (subDocId: string) => Promise<any>
        updateSubDoc: (params: { subDocId: string; title?: string; content?: string }) => Promise<{ ok: boolean }>
        deleteSubDoc: (subDocId: string) => Promise<{ ok: boolean }>
      }
      settings: {
        getModels: () => Promise<any[]>
        addModel: (params: any) => Promise<any>
        updateModel: (params: any) => Promise<any>
        removeModel: (id: string) => Promise<void>
        testModel: (id: string) => Promise<any>
        getAgents: () => Promise<any[]>
        addAgent: (params: { name: string; path: string; args?: string; type?: string }) => Promise<any>
        updateAgent: (params: any) => Promise<any>
        removeAgent: (id: string) => Promise<void>
        detectAgent: (id: string) => Promise<any>
        getSkills: () => Promise<any[]>
        updateSkill: (params: { id: string; enabled: boolean }) => Promise<any>
        getBindings: () => Promise<Record<string, string>>
        updateBindings: (params: { bindings: Record<string, string> }) => Promise<Record<string, string>>
      }
      backend: {
        start: () => Promise<any>
        stop: () => Promise<any>
        restart: () => Promise<any>
        getStatus: () => Promise<any>
        ping: () => Promise<any>
        onStatusChange: (callback: (data: any) => void) => () => void
      }
      chat: {
        listSessions: () => Promise<any>
        createSession: (params: { id: string; title: string; mode?: string }) => Promise<any>
        deleteSession: (params: { id: string }) => Promise<any>
        saveMessage: (params: { sessionId: string; message: any }) => Promise<any>
      }
      system: {
        selectDirectory: () => Promise<string | null>
        getAppDataPath: () => Promise<string>
        get: (key: string) => Promise<any>
        set: (key: string, val: any) => Promise<boolean>
        readFile: (filePath: string) => Promise<string>
      }
      on: (channel: string, callback: (...args: any[]) => void) => () => void
      removeListener: (channel: string, callback: (...args: any[]) => void) => void
      log: {
        debug: (source: string, message: string, data?: any) => void
        info: (source: string, message: string, data?: any) => void
        warn: (source: string, message: string, data?: any) => void
        error: (source: string, message: string, data?: any) => void
      }
    }
  }
}
