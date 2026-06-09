/** pipeline-store — deprecated stub.
 *
 * Pipeline orchestration has moved to the backend Agent via Skills (skill_batch_*).
 * This stub provides a null state to maintain build compatibility with components
 * that still reference pipeline-store.
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { PipelineTaskNode } from '@/types/ipc'

export const usePipelineStore = defineStore('pipeline', () => {
  const tasks = ref<Record<string, { pipelineRootTask?: PipelineTaskNode; isRunning: boolean; isPaused: boolean; progress: number }>>({})

  const setPendingStepRun = (_taskId: string, _nodeId: string) => {}
  const setPipelineRunning = (_taskId: string, _running: boolean) => {}
  const setPipelinePaused = (_taskId: string, _paused: boolean) => {}
  const recalcProgress = (_taskId: string) => {}

  return { tasks, setPendingStepRun, setPipelineRunning, setPipelinePaused, recalcProgress }
})
