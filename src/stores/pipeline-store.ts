import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { PipelineTaskNode } from '@/types/ipc'
import { ipc } from '@/services/ipc'

/** 管道步骤权重配置 */
export interface StepWeight {
  stepId: string
  weight: number        // 该步骤占总进度的权重 (总和 = 100)
  subTotal?: () => number       // 子任务总数（运行时重载）
  subCompleted?: () => number   // 子任务已完成数
}

/** 步骤权重默认值 */
const DEFAULT_WEIGHTS: StepWeight[] = [
  { stepId: 'validation', weight: 5 },
  { stepId: 'project_summary', weight: 20 },
  { stepId: 'community_analysis', weight: 50 },
  { stepId: 'overall_architecture', weight: 25 },
]

interface PipelineTaskRuntime {
  pipelineRunning: boolean
  pipelinePaused: boolean
  pipelineRootTask: PipelineTaskNode | null
  pipelineProgress: number
  pendingStepRun: string | null
  errorLogs: string[]
  stepWeights: StepWeight[]      // 步骤权重列表
}

export const usePipelineStore = defineStore('pipeline', () => {
  const tasks = ref<Record<string, PipelineTaskRuntime>>({})

  function ensureTask(taskId: string): PipelineTaskRuntime {
    if (!tasks.value[taskId]) {
      tasks.value[taskId] = {
        pipelineRunning: false,
        pipelinePaused: false,
        pipelineRootTask: null,
        pipelineProgress: 0,
        pendingStepRun: null,
        errorLogs: [],
        stepWeights: [...DEFAULT_WEIGHTS],
      }
    }
    return tasks.value[taskId]
  }

  function initPipeline(taskId: string, rootStep: PipelineTaskNode) {
    const t = ensureTask(taskId)
    t.pipelineRootTask = rootStep
    t.pipelineProgress = 0
    t.pipelineRunning = false
    t.pipelinePaused = false
  }

  function updateNodeStatus(taskId: string, nodeId: string, status: PipelineTaskNode['status'], error?: string) {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask) return
    const walk = (node: PipelineTaskNode): boolean => {
      if (node.id === nodeId) {
        node.status = status
        if (error) node.error = error
        if (status === 'running') node.progress = 0
        if (status === 'completed') node.progress = 100
        return true
      }
      if (node.children) { for (const c of node.children) { if (walk(c)) return true } }
      return false
    }
    walk(t.pipelineRootTask)
    recalcProgress(taskId)
    saveState(taskId)
  }

  function recalcProgress(taskId: string) {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask) return

    const findNode = (id: string): PipelineTaskNode | undefined => {
      const walk = (n: PipelineTaskNode): PipelineTaskNode | undefined => {
        if (n.id === id) return n
        if (n.children) for (const c of n.children) { const r = walk(c); if (r) return r }
        return undefined
      }
      return walk(t.pipelineRootTask!)
    }

    let totalWeight = 0
    let earnedWeight = 0

    for (const sw of t.stepWeights) {
      totalWeight += sw.weight
      const node = findNode(sw.stepId)
      if (!node) continue

      if (node.status === 'completed' || node.status === 'skipped') {
        earnedWeight += sw.weight
      } else if (node.status === 'running' && sw.subTotal && sw.subCompleted) {
        const subTotal = sw.subTotal()
        const subDone = sw.subCompleted()
        if (subTotal > 0) {
          earnedWeight += sw.weight * (subDone / subTotal)
        }
      }
    }

    t.pipelineProgress = totalWeight > 0 ? Math.round((earnedWeight / totalWeight) * 100) : 0
  }

  function setPipelineRunning(taskId: string, val: boolean) {
    const t = tasks.value[taskId]; if (t) t.pipelineRunning = val
  }

  function setPipelinePaused(taskId: string, val: boolean) {
    const t = tasks.value[taskId]; if (t) t.pipelinePaused = val
  }

  function setPendingStepRun(taskId: string, nodeId: string | null) {
    const t = tasks.value[taskId]; if (t) t.pendingStepRun = nodeId
  }

  function stopPipeline(taskId: string) {
    const t = tasks.value[taskId]; if (t) { t.pipelinePaused = true; t.pipelineRunning = false }
  }

  function pausePipeline(taskId: string) {
    const t = tasks.value[taskId]; if (t) t.pipelinePaused = !t.pipelinePaused
  }

  function resetPipeline(taskId: string) {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask) return
    const resetNodes = (nodes: PipelineTaskNode[]) => {
      for (const n of nodes) { n.status = 'pending'; n.progress = 0; n.error = undefined; if (n.children) resetNodes(n.children) }
    }
    if (t.pipelineRootTask.children) resetNodes(t.pipelineRootTask.children)
    t.pipelineRootTask.status = 'pending'
    t.stepWeights = [...DEFAULT_WEIGHTS]
    t.pipelineProgress = 0; t.pipelineRunning = false; t.pipelinePaused = false
  }

  function setStepWeights(taskId: string, weights: StepWeight[]) {
    const t = tasks.value[taskId]; if (t) t.stepWeights = weights
  }

  function getStepWeight(taskId: string, stepId: string): StepWeight | undefined {
    const t = tasks.value[taskId]; if (!t) return undefined
    return t.stepWeights.find(w => w.stepId === stepId)
  }

  function allPipelineStepsCompleted(taskId: string): boolean {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask?.children) return false
    return t.pipelineRootTask.children.every((n: PipelineTaskNode) => n.status === 'completed' || n.status === 'skipped')
  }

  function hasPipelineError(taskId: string): boolean {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask?.children) return false
    return t.pipelineRootTask.children.some((n: PipelineTaskNode) => n.status === 'error')
  }

  function clearTask(taskId: string) {
    delete tasks.value[taskId]
  }

  function pushError(taskId: string, msg: string) {
    const t = tasks.value[taskId]; if (!t) return
    t.errorLogs.unshift(msg); if (t.errorLogs.length > 50) t.errorLogs.length = 50
  }

  function clearErrorLogs(taskId: string) {
    const t = tasks.value[taskId]; if (t) t.errorLogs = []
  }

  async function saveState(taskId: string) {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask?.children) return
    const snapshot = t.pipelineRootTask.children.map(n => ({ id: n.id, status: n.status, error: n.error }))
    try {
      await ipc.report.savePipelineState({ taskId, stateJson: JSON.stringify(snapshot) })
    } catch { /* non-critical */ }
  }

  async function loadState(taskId: string) {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask?.children) return
    try {
      const res = await ipc.report.loadPipelineState({ taskId })
      if (!res.state) return
      const snapshot = res.state as Array<{ id: string; status: string; error?: string }>
      if (!Array.isArray(snapshot)) return
      for (const s of snapshot) {
        const node = t.pipelineRootTask.children.find(n => n.id === s.id)
        if (node && node.status === 'pending') {
          node.status = s.status as PipelineTaskNode['status']
          node.error = s.error
        }
      }
      recalcProgress(taskId)
    } catch { /* non-critical */ }
  }

  return {
    tasks,
    ensureTask,
    initPipeline, updateNodeStatus, recalcProgress,
    setPipelineRunning, setPipelinePaused, setPendingStepRun,
    stopPipeline, pausePipeline, resetPipeline,
    allPipelineStepsCompleted, hasPipelineError, clearTask,
    pushError, clearErrorLogs,
    saveState, loadState,
    setStepWeights, getStepWeight,
  }
})
