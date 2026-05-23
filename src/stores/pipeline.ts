import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PipelineTaskNode, PipelineControlFunctions } from '@/types/ipc'

export const usePipelineStore = defineStore('pipeline', () => {
  const rootTask = ref<PipelineTaskNode | null>(null)
  const running = ref(false)
  const paused = ref(false)
  const progress = ref(0)
  const controls = ref<PipelineControlFunctions | null>(null)

  const allTasks = computed(() => {
    if (!rootTask.value) return []
    return flatten(rootTask.value)
  })

  const completedCount = computed(() => allTasks.value.filter(t => t.status === 'completed' || t.status === 'skipped').length)
  const errorCount = computed(() => allTasks.value.filter(t => t.status === 'error').length)
  const totalCount = computed(() => allTasks.value.filter(t => !t.children || t.children.length === 0).length)

  function flatten(node: PipelineTaskNode): PipelineTaskNode[] {
    if (!node.children || node.children.length === 0) return [node]
    return [node, ...node.children.flatMap(flatten)]
  }

  function updateTask(root: PipelineTaskNode): PipelineTaskNode | null {
    rootTask.value = root
    return root
  }

  function updateRunning(v: boolean) { running.value = v }
  function updatePaused(v: boolean) { paused.value = v }
  function updateProgress(v: number) { progress.value = v }
  function registerControls(fns: PipelineControlFunctions) { controls.value = fns }
  function unregisterControls() { controls.value = null }

  function reset() {
    rootTask.value = null
    running.value = false
    paused.value = false
    progress.value = 0
    controls.value = null
  }

  return {
    rootTask, running, paused, progress, controls,
    allTasks, completedCount, errorCount, totalCount,
    updateTask, updateRunning, updatePaused, updateProgress,
    registerControls, unregisterControls, reset,
  }
})
