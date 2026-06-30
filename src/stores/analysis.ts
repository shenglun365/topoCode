/** Analysis Store - 分析任务管理 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AnalysisTask, AnalysisResult, FileStatsResult, ScanOptions, TaskRun } from '@/types/ipc'
import { ipc } from '@/services/ipc'
import { createLogger } from '@/utils/logger'

const logger = createLogger('analysis')

export interface TaskFilter {
  status: string[]
  viewMode: 'card' | 'list'
}

const _taskLoading = new Set<string>()

export const useAnalysisStore = defineStore('analysis', () => {
  // State
  const tasks = ref<AnalysisTask[]>([])
  const selectedTaskId = ref<string | null>(null)
  const filter = ref<TaskFilter>({
    status: ['all'],
    viewMode: 'card',
  })
  const loading = ref(false)
  const fileStatsCache = ref<Map<string, FileStatsResult>>(new Map())

  // Getters
  const selectedTask = computed(() =>
    tasks.value.find(t => t.id === selectedTaskId.value)
  )

  const filteredTasks = computed(() => {
    let result = filter.value.status.includes('all')
      ? tasks.value
      : tasks.value.filter(t => filter.value.status.includes(t.status))
    return [...result].sort((a, b) => ((b.createdAt || '') > (a.createdAt || '') ? 1 : -1))
  })

  const favoritedTasks = computed(() =>
    tasks.value.filter(t => t.favorite)
  )

  const pinnedTasks = computed(() =>
    tasks.value.filter(t => t.pinned)
  )

  const taskStats = computed(() => ({
    total: tasks.value.length,
    done: tasks.value.filter(t => t.status === 'done').length,
    running: tasks.value.filter(t => t.status === 'running').length,
    pending: tasks.value.filter(t => t.status === 'pending').length,
    error: tasks.value.filter(t => t.status === 'error').length,
  }))

  const _inflightLoad = new Map<string, Promise<AnalysisTask[]>>()

  async function loadTasks(projectId: string) {
    const inflight = _inflightLoad.get(projectId)
    if (inflight) {
      logger.debug('loadTasks dedup in-flight request')
      tasks.value = await inflight
      return
    }
    loading.value = true
    const promise = (async () => {
      try {
        return await ipc.analysis.listTasks(projectId)
      } finally {
        _inflightLoad.delete(projectId)
        loading.value = false
      }
    })()
    _inflightLoad.set(projectId, promise)
    tasks.value = await promise
  }

  async function createTask(params: { projectId: string; type: string; name: string; scope?: string; scopes?: string[]; extensions?: string[]; excludeDirs?: string[]; reportTypes?: string[] }) {
    logger.info('createTask', { projectId: params.projectId, name: params.name })
    try {
      const task = await ipc.analysis.createTask(params)
      tasks.value.unshift(task)
      logger.info('createTask completed', { taskId: task.id })
      return task
    } catch (err: any) {
      logger.error('createTask failed:', err)
      throw err
    }
  }

  async function stopTask(taskId: string) {
    await ipc.analysis.stopTask(taskId)
    const task = tasks.value.find(t => t.id === taskId)
    if (task) {
      task.status = 'stopping'
    }
  }

  async function reRunTask(taskId: string) {
    if (_taskLoading.has(taskId)) return
    _taskLoading.add(taskId)
    try {
      await ipc.analysis.reRunTask(taskId)
      const task = tasks.value.find(t => t.id === taskId)
      if (task) {
        task.status = 'running'
        task.progress = 0
        task.error = null
      }
    } finally {
      _taskLoading.delete(taskId)
    }
  }

  function isTaskLoading(taskId: string): boolean {
    return _taskLoading.has(taskId)
  }

  async function getTaskLogs(taskId: string, runId?: string) {
    return await ipc.analysis.getTaskLogs({ taskId, runId })
  }

  async function getTaskRuns(taskId: string): Promise<TaskRun[]> {
    const runs = await ipc.analysis.getTaskRuns(taskId)
    // 后端返回 snake_case，前端期望 camelCase
    return runs.map((r: any) => ({
      id: r.id,
      taskId: r.task_id,
      runNumber: r.run_number,
      status: r.status,
      progress: r.progress,
      total: r.total,
      current: r.current,
      error: r.error,
      startedAt: r.started_at,
      finishedAt: r.finished_at,
      durationMs: r.duration_ms,
    }))
  }

  async function updateTaskConfig(taskId: string, config: { name?: string; scope?: string; scopes?: string[]; extensions?: string[]; excludeDirs?: string[]; reportTypes?: string[] }) {
    logger.info('updateTaskConfig', { taskId })
    try {
      const updated = await ipc.analysis.updateTaskConfig({ taskId, config })
      const idx = tasks.value.findIndex(t => t.id === taskId)
      if (idx >= 0) tasks.value[idx] = updated
      logger.info('updateTaskConfig completed', { taskId })
      return updated
    } catch (err: any) {
      logger.error('updateTaskConfig failed:', err)
      throw err
    }
  }

  async function runTask(taskId: string) {
    if (_taskLoading.has(taskId)) return
    _taskLoading.add(taskId)
    try {
      await ipc.analysis.runTask(taskId)
      const task = tasks.value.find(t => t.id === taskId)
      if (task) {
        task.status = 'running'
        task.progress = 0
      }
    } finally {
      _taskLoading.delete(taskId)
    }
  }

  async function getTask(taskId: string) {
    return await ipc.analysis.getTask(taskId)
  }

  async function getResults(taskId: string) {
    return await ipc.analysis.getResults(taskId)
  }

  function selectTask(id: string) {
    selectedTaskId.value = id
  }

  function deselectTask() {
    selectedTaskId.value = null
  }

  async function toggleFavorite(taskId: string) {
    const task = tasks.value.find(t => t.id === taskId)
    if (task) {
      const updated = await ipc.analysis.updateTask({ taskId, favorite: !task.favorite })
      const idx = tasks.value.findIndex(t => t.id === taskId)
      if (idx >= 0) tasks.value[idx] = updated
    }
  }

  async function togglePin(taskId: string) {
    const task = tasks.value.find(t => t.id === taskId)
    if (task) {
      const updated = await ipc.analysis.updateTask({ taskId, pinned: !task.pinned })
      const idx = tasks.value.findIndex(t => t.id === taskId)
      if (idx >= 0) tasks.value[idx] = updated
    }
  }

  async function deleteTask(taskId: string) {
    await ipc.analysis.deleteTask(taskId)
    const idx = tasks.value.findIndex(t => t.id === taskId)
    if (idx >= 0) tasks.value.splice(idx, 1)
    if (selectedTaskId.value === taskId) selectedTaskId.value = null
  }

  function setViewMode(mode: 'card' | 'list') {
    filter.value.viewMode = mode
  }

  function setStatusFilter(statuses: string[]) {
    filter.value.status = statuses
  }

  // 事件订阅 (在 store 初始化时注册)
  function subscribeToEvents() {
    ipc.analysis.onProgress((data) => {
      const task = tasks.value.find(t => t.id === data.taskId)
      if (task) {
        task.progress = data.progress
        task.current = data.current
        task.total = data.total
        task.eta = data.eta
      }
    })

    ipc.analysis.onComplete((data) => {
      const task = tasks.value.find(t => t.id === data.taskId)
      if (task) {
        task.status = 'done'
        task.progress = 100
        task.error = null
      }
    })

    ipc.analysis.onError((data) => {
      const task = tasks.value.find(t => t.id === data.taskId)
      if (task) {
        task.status = 'error'
        task.error = data.error
      }
    })

    ipc.analysis.onStopped((data) => {
      const task = tasks.value.find(t => t.id === data.taskId)
      if (task) {
        task.status = 'cancelled'
      }
    })
  }

  const _inflightStats = new Map<string, Promise<FileStatsResult>>()

  async function scanFileStats(projectId: string, options?: ScanOptions) {
    const cacheKey = JSON.stringify({ projectId, ...options })
    if (fileStatsCache.value.has(cacheKey)) {
      logger.debug('scanFileStats cache hit')
      return fileStatsCache.value.get(cacheKey)!
    }
    const inflight = _inflightStats.get(cacheKey)
    if (inflight) {
      logger.debug('scanFileStats dedup in-flight request')
      return inflight
    }
    logger.debug('scanFileStats cache miss, calling IPC')
    const promise = (async () => {
      try {
        const result = await ipc.analysis.scanFileStats(projectId, options)
        fileStatsCache.value.set(cacheKey, result)
        return result
      } catch (err: any) {
        logger.error('scanFileStats IPC error:', err)
        throw err
      } finally {
        _inflightStats.delete(cacheKey)
      }
    })()
    _inflightStats.set(cacheKey, promise)
    return promise
  }

  return {
    tasks,
    selectedTaskId,
    filter,
    loading,
    selectedTask,
    filteredTasks,
    favoritedTasks,
    pinnedTasks,
    taskStats,
    loadTasks,
    createTask,
    stopTask,
    reRunTask,
    isTaskLoading,
    getTaskLogs,
    getTaskRuns,
    updateTaskConfig,
    runTask,
    getTask,
    getResults,
    selectTask,
    deselectTask,
    toggleFavorite,
    togglePin,
    deleteTask,
    setViewMode,
    setStatusFilter,
    subscribeToEvents,
    scanFileStats,
  }
})
