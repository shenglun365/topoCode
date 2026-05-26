import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { ipc } from '@/services/ipc'
import type { PipelineTaskNode, PipelineControlFunctions } from '@/types/ipc'

export interface EdgeProgress {
  total: number
  completed: number
  running: number
}

export interface PipelineTabState {
  rootTask: PipelineTaskNode
  running: boolean
  paused: boolean
  progress: number
  stepOutputs: Record<string, string>
  communityProgress?: {
    INCLUDE: EdgeProgress
    CALL: EdgeProgress
  }
}

export const usePipelineStore = defineStore('pipeline', () => {
  const byTaskId = ref<Record<string, PipelineTabState>>({})
  const controls = ref<PipelineControlFunctions | null>(null)

  function getTaskState(taskId: string): PipelineTabState | null {
    return byTaskId.value[taskId] || null
  }

  function updateTaskState(taskId: string, state: PipelineTabState) {
    byTaskId.value = { ...byTaskId.value, [taskId]: state }
  }

  function removeTaskState(taskId: string) {
    const { [taskId]: _, ...rest } = byTaskId.value
    byTaskId.value = rest
  }

  function updateCommunityProgress(taskId: string, edgeType: 'INCLUDE' | 'CALL', progress: EdgeProgress) {
    const state = byTaskId.value[taskId]
    if (!state) return
    const cp = { ...(state.communityProgress || { INCLUDE: { total: 0, completed: 0, running: 0 }, CALL: { total: 0, completed: 0, running: 0 } }), [edgeType]: progress }
    byTaskId.value = { ...byTaskId.value, [taskId]: { ...state, communityProgress: cp } }
  }

  function ensureTaskState(taskId: string, rootTask: PipelineTaskNode) {
    if (!byTaskId.value[taskId]) {
      byTaskId.value = { ...byTaskId.value, [taskId]: { rootTask, running: false, paused: false, progress: 0, stepOutputs: {} } }
    }
  }

  const allTasks = computed(() => {
    return Object.values(byTaskId.value)
  })

  function registerControls(fns: PipelineControlFunctions) { controls.value = fns }
  function unregisterControls() { controls.value = null }

  // === Phase 2: DB persistence ===

  async function saveStateToDb(taskId: string) {
    const state = byTaskId.value[taskId]
    if (!state) return
    try {
      await ipc.report.savePipelineState({ taskId, stateJson: JSON.stringify(state) })
    } catch (e) {
      console.warn('[pipelineStore] saveStateToDb failed:', e)
    }
  }

  async function loadStateFromDb(taskId: string): Promise<PipelineTabState | null> {
    try {
      const result = await ipc.report.loadPipelineState({ taskId })
      if (result?.state) {
        const s = result.state as PipelineTabState
        byTaskId.value = { ...byTaskId.value, [taskId]: s }
        return s
      }
    } catch (e) {
      console.warn('[pipelineStore] loadStateFromDb failed:', e)
    }
    return null
  }

  function reset() {
    byTaskId.value = {}
    controls.value = null
  }

  return {
    byTaskId,
    controls,
    allTasks,
    getTaskState, updateTaskState, removeTaskState,
    updateCommunityProgress, ensureTaskState,
    registerControls, unregisterControls, reset,
    saveStateToDb, loadStateFromDb,
  }
})
