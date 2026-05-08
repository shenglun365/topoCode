/** Analysis Store - 分析任务管理 */
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { AnalysisTask, AnalysisResult } from '@/types/ipc'
import { ipc } from '@/services/ipc'

export interface TaskFilter {
  status: string[]
  viewMode: 'card' | 'list'
}

export const useAnalysisStore = defineStore('analysis', () => {
  // State
  const tasks = ref<AnalysisTask[]>([])
  const selectedTaskId = ref<string | null>(null)
  const filter = ref<TaskFilter>({
    status: ['all'],
    viewMode: 'card',
  })
  const loading = ref(false)

  // Getters
  const selectedTask = computed(() =>
    tasks.value.find(t => t.id === selectedTaskId.value)
  )

  const filteredTasks = computed(() => {
    if (filter.value.status.includes('all')) return tasks.value
    return tasks.value.filter(t => filter.value.status.includes(t.status))
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

  // Actions
  async function loadTasks(projectId: string) {
    loading.value = true
    try {
      tasks.value = await ipc.analysis.listTasks(projectId)
    } finally {
      loading.value = false
    }
  }

  async function createTask(projectId: string, type: string, name: string) {
    const task = await ipc.analysis.createTask({ projectId, type, name })
    tasks.value.push(task)
    return task
  }

  async function runTask(taskId: string) {
    await ipc.analysis.runTask(taskId)
    const task = tasks.value.find(t => t.id === taskId)
    if (task) {
      task.status = 'running'
      task.progress = 0
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
      }
    })

    ipc.analysis.onComplete((data) => {
      const task = tasks.value.find(t => t.id === data.taskId)
      if (task) {
        task.status = 'done'
        task.progress = 100
      }
    })

    ipc.analysis.onError((data) => {
      const task = tasks.value.find(t => t.id === data.taskId)
      if (task) {
        task.status = 'error'
        task.error = data.error
      }
    })
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
  }
})
