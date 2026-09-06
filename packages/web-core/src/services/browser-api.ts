/**
 * Browser API — 注入 window.api 的浏览器实现（HTTP /api/rpc + /ws/events 传输）。
 *
 * 与 `types/window-api.ts` 声明的 IPCAPI 契约同构：`createRealIPC()`（src/services/ipc.ts）
 * 已把所有调用收敛为 `api.<group>.<method>(...)` 或 `api.call(method, params)`。
 * 本模块在浏览器环境注入 `window.api = createBrowserAPI()`，使 src/ 81+ 处
 * `window.api` / `ipc` 引用零改动存活。
 *
  * 传输层：全部经统一端口 3456 的网关 `POST /api/rpc/{method}`（命名空间路由 + 鉴权）。
  *
  * 鉴权（token）：网关要求 `Authorization: Bearer <token>` 或 `?token=`。
  * 浏览器获取 token（一次粘贴，持久化）：首次用 `http://<host>:3456/#token=<token>` 打开
  * （token 见 `topo serve` 输出或 ~/.topocode/token），本模块自动存入 localStorage
  * `topocode:token` 并清理 URL；之后所有请求自动携带 Bearer，WS 自动携带 ?token=。
  */

/** 读取 token：单一源 ./token（F2 修正，原此处有一份逐字拷贝） */
import { readToken } from './token'

function getToken(): string {
  return readToken()
}

function warn401(): void {
  console.warn(
    '[browser-api] 401 unauthorized: 缺少或无效的 token。' +
    '请用 http://<host>:<port>/#token=<token> 重新打开（token: ~/.topocode/token 或 `topo serve` 输出）。'
  )
}

/**
 * 泛型调用：`POST /api/rpc/{method}`，body = params。
 * 网关返回 data_api `/zmq/{method}` 的 `{"result": ...}`，此处解包。
 */
async function callRpc(method: string, params: Record<string, any> = {}): Promise<any> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' }
  const tok = getToken()
  if (tok) headers['Authorization'] = `Bearer ${tok}`
  const resp = await fetch(`/api/rpc/${method}`, {
    method: 'POST',
    headers,
    body: JSON.stringify(params),
  })
  if (resp.status === 401) warn401()
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      detail = body?.detail || body?.error || detail
    } catch {}
    throw new Error(detail)
  }
  const data = await resp.json()
  return data && typeof data === 'object' && 'result' in data ? data.result : data
}

/** 生成一个组：组内每个方法 → callRpc(`<group>.<method>`, params) */
function makeGroup(group: string, methodNames: string[]): Record<string, (...args: any[]) => Promise<any>> {
  const out: Record<string, (...args: any[]) => Promise<any>> = {}
  for (const name of methodNames) {
    out[name] = (params?: any) => callRpc(`${group}.${name}`, params || {})
  }
  return out
}

/**
 * 构造浏览器 window.api。
 * 覆盖契约的全部方法组；**签名与 types/window-api.ts 一致**（位置参数 →
 * 后端命名参数），使 src/ 调用方零改动。全部参数对象的方法经 makeGroup。
 */
export function createBrowserAPI(): any {
  const project = {
    list: () => callRpc('project.list', {}),
    import: (path: string, opts?: Record<string, any>) => callRpc('project.import', { path, ...(opts || {}) }),
    get: (id: string) => callRpc('project.get', { id }),
    remove: (id: string, wait?: boolean) => callRpc('project.remove', { id, wait }),
    removeStatus: (requestId: string) => callRpc('project.removeStatus', { requestId }),
    sync: (id: string) => callRpc('project.sync', { id }),
    getFileTree: (id: string, fromPath?: string | null) => callRpc('project.getFileTree', { id, fromPath }),
    updatePath: (id: string, newRootPath: string) => callRpc('project.updatePath', { id, newRootPath }),
    checkFileChanges: (id: string) => callRpc('project.checkFileChanges', { id }),
    checkGitRepo: (path: string) => callRpc('project.checkGitRepo', { path }),
    updateMeta: (id: string, meta: Record<string, any>) => callRpc('project.updateMeta', { id, ...meta }),
    initSampleData: () => callRpc('project.initSampleData', {}),
    clearSampleData: (id: string) => callRpc('project.clearSampleData', { id }),
    checkPathValidity: (id: string) => callRpc('project.checkPathValidity', { id }),
    getStorageStats: (projectId: string) => callRpc('project.getStorageStats', { projectId }),
    detectGitInfo: (params: any) => callRpc('project.detectGitInfo', params || {}),
    saveGitInfo: (params: any) => callRpc('project.saveGitInfo', params || {}),
    getGitInfo: (params: any) => callRpc('project.getGitInfo', params || {}),
    saveBaseline: (params: any) => callRpc('project.saveBaseline', params || {}),
    checkImportStatus: (params: any) => callRpc('project.checkImportStatus', params || {}),
  }
  const version = makeGroup('version', [
    'list', 'get', 'preview', 'sync', 'diff', 'materialize', 'cleanup', 'getDiffStats', 'checkout',
  ])
  const group = {
    list: () => callRpc('group.list', {}),
    create: (name: string, parent_id: string | null) => callRpc('group.create', { name, parent_id }),
    update: (id: string, name: string | undefined, parent_id: string | null) => callRpc('group.update', { id, name, parent_id }),
    delete: (id: string) => callRpc('group.delete', { id }),
    addProject: (project_id: string, group_id: string) => callRpc('group.addProject', { project_id, group_id }),
    removeProject: (project_id: string, group_id: string) => callRpc('group.removeProject', { project_id, group_id }),
    getProjectGroups: (project_id: string) => callRpc('group.getProjectGroups', { project_id }),
  }
  const analysis = {
    listTasks: (projectId: string) => callRpc('analysis.listTasks', { projectId }),
    createTask: (params: any) => callRpc('analysis.createTask', params || {}),
    runTask: (taskId: string) => callRpc('analysis.runTask', { taskId }),
    getTask: (taskId: string) => callRpc('analysis.getTask', { taskId }),
    getResults: (taskId: string) => callRpc('analysis.getResults', { taskId }),
    updateTask: (params: any) => callRpc('analysis.updateTask', params || {}),
    deleteTask: (taskId: string) => callRpc('analysis.deleteTask', { taskId }),
    stopTask: (taskId: string) => callRpc('analysis.stopTask', { taskId }),
    listRunningTasks: () => callRpc('analysis.listRunningTasks', {}),
    clearProjectCache: (projectId: string) => callRpc('analysis.clearProjectCache', { projectId }),
    getClearCacheCounts: (projectId: string) => callRpc('analysis.getClearCacheCounts', { projectId }),
    clearProjectCacheTable: (projectId: string, table: string) => callRpc('analysis.clearProjectCacheTable', { projectId, table }),
    reRunTask: (taskId: string) => callRpc('analysis.reRunTask', { taskId }),
    getTaskLogs: (params: any) => callRpc('analysis.getTaskLogs', params || {}),
    getTaskRuns: (taskId: string) => callRpc('analysis.getTaskRuns', { taskId }),
    updateTaskConfig: (params: any) => callRpc('analysis.updateTaskConfig', params || {}),
    scanFileStats: (projectId: string, options?: Record<string, any>) => callRpc('analysis.scanFileStats', { projectId, ...(options || {}) }),
    getAvailableLevels: (taskId: string, edgeType?: string) => callRpc('analysis.getAvailableLevels', { taskId, edgeType }),
    getCommunityGraph: (params: any) => callRpc('analysis.getCommunityGraph', params || {}),
    getSymbolDetail: (params: any) => callRpc('analysis.getSymbolDetail', params || {}),
    getEdgeDetail: (params: any) => callRpc('analysis.getEdgeDetail', params || {}),
    getCascadeLevels: (taskId: string, edgeType?: string) => callRpc('analysis.getCascadeLevels', { taskId, edgeType }),
    getReportDashboard: (taskId: string) => callRpc('analysis.getReportDashboard', { taskId }),
    getQueryStats: (params: any) => callRpc('analysis.getQueryStats', params || {}),
    getExternalStats: (taskId: string) => callRpc('analysis.getExternalStats', { taskId }),
    getCrossCommunityEdges: (params: any) => callRpc('analysis.getCrossCommunityEdges', params || {}),
    getCommunityNodeLists: (params: any) => callRpc('analysis.getCommunityNodeLists', params || {}),
    startOverview: (params: any) => callRpc('analysis.startOverview', params || {}),
    getAgentProgress: (params: any) => callRpc('analysis.getAgentProgress', params || {}),
    getProgressStats: (params: any) => callRpc('analysis.getProgressStats', params || {}),
    cancelAgentTask: (params: any) => callRpc('analysis.cancelAgentTask', params || {}),
    getAgentTaskHistory: (params: any) => callRpc('analysis.getAgentTaskHistory', params || {}),
    clearAgentTaskHistory: (params: any) => callRpc('analysis.clearAgentTaskHistory', params || {}),
    getPreSummaryStatus: (params: any) => callRpc('analysis.getPreSummaryStatus', params || {}),
    listPreSummaryFiles: (params: any) => callRpc('analysis.listPreSummaryFiles', params || {}),
    startPreSummary: (params: any) => callRpc('analysis.startPreSummary', params || {}),
    startPreSummaryPipeline: (params: any) => callRpc('analysis.startPreSummaryPipeline', params || {}),
    getFileSummary: (params: any) => callRpc('analysis.getFileSummary', params || {}),
    getPreSummaryFileSource: (params: any) => callRpc('analysis.getPreSummaryFileSource', params || {}),
    deleteFileSummary: (params: any) => callRpc('analysis.deleteFileSummary', params || {}),
    rerunFileSummary: (params: any) => callRpc('analysis.rerunFileSummary', params || {}),
    startPipeline: (params: any) => callRpc('analysis.startPipeline', params || {}),
    analyzeComponents: (params: any) => callRpc('analysis.analyzeComponents', params || {}),
    getAgentConfig: () => callRpc('agent.getConfig', {}),
    saveCommunityResult: (params: any) => callRpc('analysis.saveCommunityResult', JSON.parse(JSON.stringify(params || {}))),
    getCommunityResult: (params: any) => callRpc('analysis.getCommunityResult', params || {}),
    listCommunityResults: (taskId: string, edgeType: string) => callRpc('analysis.listCommunityResults', { taskId, edgeType }),
    updateCommunityName: (params: any) => callRpc('analysis.updateCommunityName', params || {}),
    getCommunityFileGraph: (params: any) => callRpc('analysis.getCommunityFileGraph', params || {}),
    parseFileAst: (params: any) => callRpc('analysis.parseFileAst', params || {}),
    // 事件订阅（task.* → /ws/events）
    onProgress: (cb: (d: any) => void) => subscribeChannel('event:task.progress', cb),
    onComplete: (cb: (d: any) => void) => subscribeChannel('event:task.complete', cb),
    onError: (cb: (d: any) => void) => subscribeChannel('event:task.error', cb),
    onStopped: (cb: (d: any) => void) => subscribeChannel('event:task.stopped', cb),
  }
  const knowledge = {
    listDocs: (params?: any) => callRpc('knowledge.listDocs', params || {}),
    createDoc: (params: any) => callRpc('knowledge.createDoc', params || {}),
    getDoc: (id: string) => callRpc('knowledge.getDoc', { id }),
    updateDoc: (params: any) => callRpc('knowledge.updateDoc', params || {}),
    deleteDoc: (id: string) => callRpc('knowledge.deleteDoc', { id }),
    getGraph: (params?: any) => callRpc('knowledge.getGraph', params || {}),
    getDimensions: () => callRpc('knowledge.getDimensions', {}),
    pullRequest: (params: any) => callRpc('knowledge.pullRequest', params || {}),
    pendingUpdates: (params: any) => callRpc('knowledge.pendingUpdates', params || {}),
    updateConfirm: (params: any) => callRpc('knowledge.updateConfirm', params || {}),
    updateCancel: (params: any) => callRpc('knowledge.updateCancel', params || {}),
  }
  const report = {
    createSubDoc: (params: any) => callRpc('report.createSubDoc', params || {}),
    listSubDocs: (params: any) => callRpc('report.listSubDocs', params || {}),
    getSubDoc: (subDocId: string) => callRpc('report.getSubDoc', { subDocId }),
    updateSubDoc: (params: any) => callRpc('report.updateSubDoc', params || {}),
    deleteSubDoc: (subDocId: string) => callRpc('report.deleteSubDoc', { subDocId }),
    getReadmeContent: (params: any) => callRpc('report.getReadmeContent', params || {}),
    extractDependencyFiles: (params: any) => callRpc('report.extractDependencyFiles', params || {}),
    generateProjectSummary: (params: any) => callRpc('report.generateProjectSummary', params || {}),
    getProjectSummary: (params: any) => callRpc('report.getProjectSummary', params || {}),
    saveProjectSummary: (params: any) => callRpc('report.saveProjectSummary', params || {}),
    getLevelCommunityDetail: (params: any) => callRpc('report.getLevelCommunityDetail', params || {}),
    saveFileSummaries: (params: any) => callRpc('report.saveFileSummaries', params || {}),
    getFileSummaries: (params: any) => callRpc('report.getFileSummaries', params || {}),
    renderDiagram: (params: any) => callRpc('report.renderDiagram', params || {}),
    getCommunityFileDetail: (params: any) => callRpc('report.getCommunityFileDetail', params || {}),
    getCallLogs: (params: any) => callRpc('report.getCallLogs', params || {}),
    getInteractionLogs: (params: any) => callRpc('report.getInteractionLogs', params || {}),
    saveOverallDoc: (params: any) => callRpc('report.saveOverallDoc', params || {}),
  }
  const settings = {
    getModels: () => callRpc('settings.getModels', {}),
    addModel: (params: any) => callRpc('settings.addModel', params || {}),
    updateModel: (params: any) => callRpc('settings.updateModel', params || {}),
    removeModel: (id: string) => callRpc('settings.removeModel', { id }),
    testModel: (id: string) => callRpc('settings.testModel', { id }),
    getAgents: () => callRpc('settings.getAgents', {}),
    addAgent: (params: any) => callRpc('settings.addAgent', params || {}),
    updateAgent: (params: any) => callRpc('settings.updateAgent', params || {}),
    removeAgent: (id: string) => callRpc('settings.removeAgent', { id }),
    detectAgent: (id: string) => callRpc('settings.detectAgent', { id }),
    executeAgent: (params: any) => callRpc('settings.executeAgent', params || {}),
    getAgentExecution: (execId: string) => callRpc('settings.getAgentExecution', { exec_id: execId }),
    listAgentExecutions: (params?: any) => callRpc('settings.listAgentExecutions', params || {}),
    cancelAgentExecution: (execId: string) => callRpc('settings.cancelAgentExecution', { exec_id: execId }),
    getSkills: () => callRpc('settings.getSkills', {}),
    updateSkill: (params: any) => callRpc('settings.updateSkill', params || {}),
    getBindings: () => callRpc('settings.getBindings', {}),
    updateBindings: (params: any) => callRpc('settings.updateBindings', params || {}),
    getImportConfig: () => callRpc('settings.getImportConfig', {}),
    setImportConfig: (params: any) => callRpc('settings.setImportConfig', params || {}),
  }
  const model = {
    getUsageStats: (modelId?: string, startDate?: string, endDate?: string) =>
      callRpc('model.getUsageStats', { model_id: modelId, start_date: startDate, end_date: endDate }),
    deleteUsageStats: (id: number) => callRpc('model.deleteUsageStats', { id }),
    deleteUsageStatsBatch: (ids: number[]) => callRpc('model.deleteUsageStatsBatch', { ids }),
    deleteUsageStatsByCondition: (params: { modelId?: string; startDate?: string; endDate?: string }) =>
      callRpc('model.deleteUsageStatsByCondition', { model_id: params?.modelId, start_date: params?.startDate, end_date: params?.endDate }),
  }
  const session = makeGroup('session', [
    'list', 'create', 'delete', 'getMessages', 'addMessage', 'deleteMessage',
    'updateMeta', 'clearAll',
  ])
  const analysisSession = makeGroup('analysisSession', [
    'list', 'create', 'delete',
  ])
  const llm = {
    chat: (params: any) => callRpc('llm.chat', params || {}),
    abortChat: (params: any) => callRpc('llm.abortChat', params || {}),
    // 流式订阅：经 /ws/events（ZMQ-SUB 桥），按 requestId 过滤
    subscribe: (requestId: string, callbacks: {
      onChunk?: (d: any) => void
      onToolCall?: (d: any) => void
      onToolResult?: (d: any) => void
      onDone?: (d: any) => void
      onError?: (d: any) => void
    }) => subscribeLlm(requestId, callbacks),
  }
  const promptTemplate = makeGroup('promptTemplate', [
    'list', 'get', 'create', 'update', 'delete', 'render', 'restoreDefaults',
    'getDefaultLocale', 'setDefaultLocale',
  ])
  const render = {
    renderPlantuml: (params: any) => callRpc('render.plantuml', params || {}),
  }
  const module = {
    listRegistry: (registryUrl?: string) => callRpc('module.listRegistry', { registry_url: registryUrl }),
    getInstalled: () => callRpc('module.getInstalled', {}),
    install: (name: string, registryUrl?: string) => callRpc('module.install', { name, registry_url: registryUrl }),
    uninstall: (name: string) => callRpc('module.uninstall', { name }),
    update: (name: string, registryUrl?: string) => callRpc('module.update', { name, registry_url: registryUrl }),
    search: (query: string) => callRpc('module.search', { query }),
  }
  const graph = makeGroup('graph', [
    'savePositions', 'loadPositions', 'clearPositions', 'listSavedPositionKeys',
  ])
  const system = {
    exportProject: (projectId: string, taskIds?: string[]) => callRpc('system.exportProject', { projectId, taskIds }),
    exportStatus: (exportId: string) => callRpc('system.exportStatus', { exportId }),
    exportRemoveArchive: (archivePath: string) => callRpc('system.exportRemoveArchive', { archivePath }),
    exportCleanupOld: (projectId: string) => callRpc('system.exportCleanupOld', { projectId }),
    importProjectArchive: (archivePath: string, importMode?: string, projectId?: string) =>
      callRpc('system.importProjectArchive', { archivePath, importMode, projectId }),
    importStatus: (importId: string) => callRpc('system.importStatus', { importId }),
    verifyFiles: (projectId: string) => callRpc('system.verifyFiles', { projectId }),
    verifyStatus: (verifyId: string) => callRpc('system.verifyStatus', { verifyId }),
    selectDirectory: async () => {
      const r = await callRpc('system.pickDirectory', {})
      return (r && typeof r === 'object' && 'path' in r) ? (r.path as string) : (r || '')
    },
    uploadArchive: async (file: File) => {
      const form = new FormData()
      form.append('file', file)
      const headers: Record<string, string> = {}
      const tok = getToken()
      if (tok) headers['Authorization'] = `Bearer ${tok}`
      const resp = await fetch('/api/upload/archive', {
        method: 'POST',
        headers,
        body: form,
      })
      if (resp.status === 401) warn401()
      if (!resp.ok) {
        let detail = `HTTP ${resp.status}`
        try {
          const body = await resp.json()
          detail = body?.detail || body?.error || detail
        } catch { /* ignore */ }
        throw new Error(detail)
      }
      const data = await resp.json()
      return data?.path || data?.filePath || ''
    },
    getHttpPort: async () => {
      const host = window.location.host
      return { host: host.split(':')[0], port: Number(host.split(':')[1] || 3456) }
    },
    get: (key: string) => Promise.resolve(localStorage.getItem(`topocode:${key}`)),
    set: (key: string, val: any) => {
      localStorage.setItem(`topocode:${key}`, typeof val === 'string' ? val : JSON.stringify(val))
      return Promise.resolve()
    },
    getAppDataPath: async () => '/',
  }
  // Web 模式"backend"= 网关本身：查 /api/health（免鉴权），不走黑名单的 backend.* RPC。
  const _fetchHealth = async (): Promise<any> => {
    try {
      const r = await fetch('/api/health', { cache: 'no-store' })
      if (r.ok) {
        const host = window.location.host
        return { status: 'running', mode: 'web', httpHost: host.split(':')[0], httpPort: Number(host.split(':')[1] || 3456) }
      }
      return { status: 'error', error: `gateway HTTP ${r.status}` }
    } catch (e: any) {
      return { status: 'error', error: String(e?.message || e) }
    }
  }
  const backend = {
    ping: () => _fetchHealth().then((h) => h.status === 'running'),
    getStatus: () => _fetchHealth(),
    getZmqStatus: () => _fetchHealth(),
    getMemoryLimit: () => Promise.resolve(0),
    setMemoryLimit: () => Promise.resolve(),
    getHttpConfig: async () => {
      const host = window.location.host
      return { host: host.split(':')[0], port: Number(host.split(':')[1] || 3456) }
    },
    setHttpConfig: () => Promise.resolve(),
    saveHttpConfig: () => Promise.resolve(),
    testPort: () => Promise.resolve(true),
    setResourceDir: () => Promise.resolve(),
    // 进程控制（restart/start/stop）在 Web 模式只读/不可用 —— 由 CLI/TUI/systemd 管理
    start: () => Promise.resolve({ status: 'not-supported' }),
    stop: () => Promise.resolve({ status: 'not-supported' }),
    restart: () => Promise.resolve({ status: 'not-supported' }),
    onStatusChange: (cb: (d: any) => void) => subscribeEvent('backend', cb),
  }
  const device = {
    getId: async () => {
      const key = 'topocode_device_id'
      let id = localStorage.getItem(key)
      if (!id) {
        id = `${Date.now()}-${Math.random().toString(36).slice(2)}`
        localStorage.setItem(key, id)
      }
      return id
    },
  }
  const dialog = {
    openDirectory: async () => {
      const r = await callRpc('system.pickDirectory', {})
      return (r && typeof r === 'object' && 'path' in r) ? (r.path as string) : (r || '')
    },
    openFile: async () => {
      const r = await callRpc('system.pickFile', {})
      return (r && typeof r === 'object' && 'path' in r) ? (r.path as string) : (r || '')
    },
  }
  const fs = {
    readFile: async (filePath: string) => {
      const res = await callRpc('system.readFile', { path: filePath })
      return (res && res.content) || ''
    },
    addAllowedDir: () => Promise.resolve(true),
    downloadUrl: (url: string) => { window.open(url, '_blank'); return Promise.resolve(true) },
  }
  const plugin = {
    list: () => callRpc('plugin.list', {}),
    get: (name: string) => callRpc('plugin.get', { name }),
    load: (name: string) => callRpc('plugin.load', { name }),
    unload: (name: string) => callRpc('plugin.unload', { name }),
    reload: (name: string) => callRpc('plugin.reload', { name }),
    install: (name: string) => callRpc('plugin.install', { name }),
  }
  const log = {
    debug: () => {}, info: () => {}, warn: () => {}, error: () => {},
  }
  const update = {
    check: () => Promise.resolve({ status: 'not-supported' }),
    download: () => Promise.resolve({ status: 'not-supported' }),
    install: () => Promise.resolve({ status: 'not-supported' }),
    onStatus: (cb: (d: any) => void) => () => {},
  }
  const crash = {
    list: () => Promise.resolve([]),
    dismiss: () => Promise.resolve(),
    report: () => Promise.resolve(),
    onNew: (cb: (d: any) => void) => () => {},
    onPending: (cb: (d: any) => void) => () => {},
  }
  const app = {
    getVersion: async () => 'web',
    quit: () => Promise.resolve(),
    relaunch: () => Promise.resolve(),
    openPath: () => Promise.resolve(),
  }
  const windowGroup = {
    toggleLeftPanel: () => {}, toggleRightPanel: () => {},
    zoomIn: () => {}, zoomOut: () => {}, resetZoom: () => {},
    minimize: () => {}, maximize: () => {}, isMaximized: () => Promise.resolve(false),
    close: () => {}, create: () => {}, list: () => Promise.resolve([]),
    focus: () => {}, getCount: () => Promise.resolve(1), getMaxCount: () => Promise.resolve(1),
    broadcast: () => Promise.resolve(),
    onMaximizedChange: (cb: (d: any) => void) => () => {},
  }

  return {
    call: callRpc,
    project, version, group, analysis, knowledge, report, settings, model,
    session, analysisSession, llm, promptTemplate, render, module, graph,
    system, backend, device, dialog, fs, plugin, log, update, crash,
    app, window: windowGroup,
    // 事件订阅（统一桥 /ws/events，按 topic 过滤）
    on: (channel: string, callback: (...args: any[]) => void) => subscribeChannel(channel, callback),
  }
}

// ═══════════════════════════════════════════════════════════════
// 事件桥（/ws/events）
// ═══════════════════════════════════════════════════════════════

type Handler = (data: any) => void

let _wsEvents: WebSocket | null = null
const _handlers = new Map<string, Set<Handler>>()   // topic/eventType → handlers
const _queued: Array<{ channel: string; data: any }> = []
const _listeners: Array<{ channel: string; handler: Handler; dispose: () => void }> = []

function _ensureWs(): WebSocket | null {
  // CONNECTING 或 OPEN 均复用：CONNECTING 期间再开会建出并行连接，
  // 每条存活连接都会把同一事件分派进 _handlers → 流式内容被重复 N 次
  if (_wsEvents && _wsEvents.readyState <= WebSocket.OPEN) return _wsEvents
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
  const tok = getToken()
  const wsUrl = `${proto}://${window.location.host}/ws/events${tok ? `?token=${encodeURIComponent(tok)}` : ''}`
  const ws = new WebSocket(wsUrl)
  _wsEvents = ws
  ws.onmessage = (e) => {
    let msg: any
    try { msg = JSON.parse(e.data) } catch { return }
    if (!msg || msg.type === 'ping') return
    const topic = String(msg.topic || '')
    const eventType = String(msg.eventType || '')
    const channel = `event:${topic}.${eventType}`
    const topicKey = `event:${topic}`
    const data = msg.data
    // topic 级 handler 需要 eventType 上下文（llm.subscribe 依此分流）
    const enriched = (typeof data === 'object' && data !== null)
      ? { ...data, eventType, topic }
      : data
    // 分发给 topic 级（event:llm）与 channel 级（event:llm.chunk）handler
    for (const [key, set] of _handlers) {
      if (key === channel || key === topicKey) {
        const payload = key === topicKey ? enriched : data
        for (const h of [...set]) {
          try { h(payload) } catch {}
        }
      }
    }
    for (const l of [..._listeners]) {
      if (l.channel === channel || l.channel === topicKey || l.channel === topic) {
        try { l.handler(enriched) } catch {}
      }
    }
    // 回放缓存（供晚注册的 llm.subscribe 消费）
    _queued.push({ channel, data: enriched })
    if (_queued.length > 500) _queued.shift()
  }
  ws.onclose = () => {
    if (_wsEvents !== ws) return  // 已被新连接取代，勿清空
    _wsEvents = null
    // 仍有活动订阅（channel 级 _listeners 或 topic 级 _handlers，如 llm.subscribe）才重连
    setTimeout(() => { if (_listeners.length || _handlers.size) _ensureWs() }, 2000)
  }
  return ws
}

function subscribeChannel(channel: string, callback: Handler): () => void {
  const listener = { channel, handler: callback, dispose: () => {} }
  _listeners.push(listener)
  _ensureWs()
  return () => {
    const i = _listeners.indexOf(listener)
    if (i >= 0) _listeners.splice(i, 1)
  }
}

function subscribeEvent(topic: string, cb: Handler): () => void {
  let set = _handlers.get(`event:${topic}`)
  if (!set) { set = new Set(); _handlers.set(`event:${topic}`, set) }
  set.add(cb)
  _ensureWs()
  return () => { set!.delete(cb) }
}

/** llm.subscribe —— 经 /ws/events 按 requestId 过滤流式事件 */
function subscribeLlm(requestId: string, callbacks: {
  onChunk?: (d: any) => void
  onToolCall?: (d: any) => void
  onToolResult?: (d: any) => void
  onDone?: (d: any) => void
  onError?: (d: any) => void
}): () => void {
  const handler = (data: any) => {
    if (!data || data.requestId !== requestId) return
    switch (data.eventType) {
      case 'chunk': callbacks.onChunk?.(data.data ?? data); break
      case 'tool_call': callbacks.onToolCall?.(data.data ?? data); break
      case 'tool_result': callbacks.onToolResult?.(data.data ?? data); break
      case 'done': callbacks.onDone?.(data.data ?? data); break
      case 'error': callbacks.onError?.(data.data ?? data); break
    }
  }
  return subscribeEvent('llm', handler)
}

/** 安装浏览器 API：存在 window.api 则跳过（防御），否则注入 */
export function installBrowserAPI(): void {
  if (typeof window !== 'undefined' && !(window as any).api) {
    ;(window as any).api = createBrowserAPI()
    console.info('[browser-api] window.api installed (HTTP /api/rpc + /ws/events)')
  }
}
