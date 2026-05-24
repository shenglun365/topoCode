import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PipelineTaskNode, PipelineControlFunctions } from '@/types/ipc'

interface PipelineTabState {
  rootTask: PipelineTaskNode
  running: boolean
  paused: boolean
  progress: number
  stepOutputs: Record<string, string>
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

  const allTasks = computed(() => {
    return Object.values(byTaskId.value)
  })

  function registerControls(fns: PipelineControlFunctions) { controls.value = fns }
  function unregisterControls() { controls.value = null }

  function reset() {
    byTaskId.value = {}
    controls.value = null
  }

  return {
    byTaskId,
    controls,
    allTasks,
    getTaskState, updateTaskState, removeTaskState,
    registerControls, unregisterControls, reset,
  }
})
