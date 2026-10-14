/**
 * community-store · useAgentTasks 逻辑域（MS6-W5 自 store 机械迁出：正文逐行原文，依赖经 ctx 解构注入）。
 */
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import { isLLMConfigured } from '@/services/llmClient'
import { controlDispatcher } from '@/services/control-dispatcher'
import { useProjectStore } from '@/stores/project'
import i18n from '@/i18n'
import { playSuccessSound, playFailureSound } from '@/services/sound'
import type { ComponentRef } from '@/stores/component-selection-store'
import { agentCompletedSignal, pipelineSummary } from '../community-store'

export function useAgentTasks(ctx: { [k: string]: any }) {
  const {
    _cleanTerminalAgents,
    ensureTask,
    loadCommunities,
    tasks,
  } = ctx
  const projectStore = useProjectStore()

  function addAgentTask(taskId: string, action: string, steps: string[]) {
    const t = ensureTask(taskId)
    const id = `agent-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    t.agentTasks.push({
      id, action, status: 'queued',
      steps: steps.map(s => ({ description: s, status: 'pending' as const })),
      progress: 0, message: '', createdAt: new Date().toISOString(),
      taskLogs: [], weightedProgress: 0, totalFiles: 0, totalComps: 0, doneFiles: 0, doneComps: 0,
    })
    return id
  }

  function updateAgentTask(taskId: string, taskIdx: number, updates: Partial<{
    status: string; progress: number; message: string
  }>) {
    const t = tasks.value[taskId]; if (!t || !t.agentTasks[taskIdx]) return
    Object.assign(t.agentTasks[taskIdx], updates)
  }

  function updateAgentStep(taskId: string, taskIdx: number, stepIdx: number, status: string, fileCount?: number) {
    const t = tasks.value[taskId]; if (!t || !t.agentTasks[taskIdx]) return
    const steps = t.agentTasks[taskIdx].steps
    if (steps[stepIdx]) {
      steps[stepIdx].status = status as any
      if (fileCount !== undefined) steps[stepIdx].file_count = fileCount
    }
  }

  async function triggerOverview(taskId: string, force = false, language = '') {
    const t = ensureTask(taskId)
    _cleanTerminalAgents(taskId, 'overview')
    const idx = t.agentTasks.length
    const actionLabel = 'overview'
    addAgentTask(taskId, actionLabel, [i18n.global.t('report.agent.overviewGenerating')])
    t.agentTasks[idx].status = 'running'

    try {
      const result = await ipc.analysis.startOverview({ taskId, force: force || undefined, language: language || undefined })
      if (result.success && result.agentTaskId) {
        cancelAgentPolling(taskId)
        t.agentTasks[idx].id = result.agentTaskId
        updateAgentTask(taskId, idx, { status: 'running', progress: 0, message: i18n.global.t('report.agent.overviewGenerating') })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
      } else if (result.success && result.skipped) {
        updateAgentTask(taskId, idx, { status: 'skipped', progress: 100, message: i18n.global.t('report.agent.overviewExists') })
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || i18n.global.t('report.agent.startFailed') })
      }
      return result
    } catch (e: any) {
      updateAgentTask(taskId, idx, { status: 'failed', message: e?.message || i18n.global.t('report.agent.unknownError') })
      throw e
    }
  }

  async function triggerComponentAnalysis(taskId: string | null, components: ComponentRef[], language = '', concurrency = 1, agentic = false, maxTurns = 30, summaryModelId = '', subagentConcurrency = 1, analysisMode = 'quick', force = false) {
    if (!taskId || !components.length) return
    const t = ensureTask(taskId)
    const actionLabel = agentic ? 'agentic_analyze_components' : 'analyze_components'
    _cleanTerminalAgents(taskId, actionLabel)
    const steps = components.map(c => i18n.global.t('report.agent.analyzeComponentStep', { name: c.name, type: c.type === 'community' ? i18n.global.t('report.agent.communityType') : i18n.global.t('report.agent.externalPackageType') }))
    const idx = t.agentTasks.length
    addAgentTask(taskId, actionLabel, steps)
    t.agentTasks[idx].status = 'running'

    try {
      const safeComponents = JSON.parse(JSON.stringify(
        components.map(c => ({
          id: c.id,
          type: c.type,
          name: c.name,
          metadata: c.metadata || {},
        }))
      ))
      const result = await ipc.analysis.analyzeComponents({
        taskId,
        components: safeComponents,
        language: language || undefined,
        concurrency: concurrency > 1 ? concurrency : undefined,
        agentic: agentic || undefined,
        maxTurns: agentic ? maxTurns : undefined,
        summaryModelId: agentic && summaryModelId ? summaryModelId : undefined,
        subagentConcurrency: agentic && subagentConcurrency > 1 ? subagentConcurrency : undefined,
        analysisMode,
        force: force || undefined,
      })
      if (result.success && result.agentTaskId) {
        cancelAgentPolling(taskId)
        t.agentTasks[idx].id = result.agentTaskId
        const msg = result.skipped
          ? i18n.global.t('report.agent.componentsCountSkipped', { count: components.length, skipped: result.skipped })
          : i18n.global.t('report.agent.componentsCount', { count: components.length })
        updateAgentTask(taskId, idx, { status: 'running', progress: 0, message: msg })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
      } else if (result.success && !result.agentTaskId) {
        const skipped = result.skipped || 0
        updateAgentTask(taskId, idx, { status: 'skipped', progress: 100, message: i18n.global.t('report.agent.allSkipped', { skipped }) })
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || i18n.global.t('report.agent.startFailed') })
      }
      return result
    } catch (e: any) {
      updateAgentTask(taskId, idx, { status: 'failed', message: e?.message || 'unknown error' })
      throw e
    }
  }

  const agentTaskHistoryOffset = ref<Record<string, number>>({})
  const agentTaskHistoryTotal = ref<Record<string, number>>({})

  function _pollAgentProgress(taskId: string, taskIdx: number, agentTaskId: string, stepOffset = 0) {
    const controlKey = `agent-progress:${taskId}:${agentTaskId}`
    // 清除同一 agent 的旧 polling（兜底）
    if (controlDispatcher.has(controlKey)) controlDispatcher.unregister(controlKey)

    // console.log('[poll] register taskId=%s agent=%s idx=%d key=%s', taskId, agentTaskId, taskIdx, controlKey)

    let lastDoneCount = 0
    let lastCommunityReload = 0
    let _lastPct = -1
    let _lastMsg = ''
    let _lastStatus = ''
    controlDispatcher.register(controlKey, {
      interval: 1500,
      fetcher: () => ipc.analysis.getAgentProgress({ agentTaskId }),
      onData: (progress) => {
        if (!progress.found) {
          const t = tasks.value[taskId]
          if (t && t.agentTasks[taskIdx]) {
            updateAgentTask(taskId, taskIdx, { status: 'failed', message: i18n.global.t('report.agent.taskInterrupted') })
          }
          controlDispatcher.unregister(controlKey)
          return
        }
        const t = tasks.value[taskId]
        if (!t || !t.agentTasks[taskIdx]) {
          controlDispatcher.unregister(controlKey)
          return
        }
        const stepCurrent = progress.step_current || 0
        const stepTotal = progress.step_total || 0
        const allStepsDone = progress.steps && progress.steps.length > 0 &&
          progress.steps.every(s => s.status === 'done' || s.status === 'failed')
        const isCompleted = progress.status === 'completed' || progress.status === 'partial' ||
          progress.status === 'failed' || progress.status === 'cancelled'
        const msg = (!progress.message && stepTotal === 0 && stepCurrent === 0)
          ? i18n.global.t('report.agent.starting') : (progress.message || '')
        const newStatus = isCompleted
          ? (progress.status === 'failed' ? 'failed' :
             progress.status === 'cancelled' ? 'cancelled' :
             progress.status === 'partial' ? 'partial' : 'completed')
          : (progress.status || 'running')
        if (newStatus !== _lastStatus || msg !== _lastMsg) {
          _lastStatus = newStatus
          _lastMsg = msg
          updateAgentTask(taskId, taskIdx, {
            status: newStatus,
            message: msg,
          })
        }
        // Sync item_logs (仅批量级日志，无需逐文件转发)
        const agent = t.agentTasks[taskIdx]
        if (progress.item_logs && progress.item_logs.length > 0) {
          const existingMap = new Map<any, any>(agent.taskLogs.map((l: any) => [l.id, l]))
          for (const log of progress.item_logs) {
            const existing = existingMap.get(log.id)
            if (existing) {
              if (existing.status !== log.status || existing.endTime !== log.endTime) {
                existing.status = log.status
                existing.endTime = log.endTime
                if (log.error) existing.error = log.error
              }
            } else {
              const copy = { ...log }
              agent.taskLogs.push(copy)
              existingMap.set(log.id, copy)
            }
          }
        }
        if (progress.steps) {
          const doneCount = progress.steps.filter(s => s.status === 'done').length
          if (doneCount > lastDoneCount && taskId) {
            lastDoneCount = doneCount
            const pid = useProjectStore().selectedProjectId
            if (pid) loadCommunities(taskId, pid).catch(() => {})
          }
          const runtimeSteps = progress.steps || []
          while ((agent.steps || []).length < runtimeSteps.length) {
            const idx = agent.steps.length
            agent.steps.push({
              description: runtimeSteps[idx].description,
              status: 'pending',
              file_count: runtimeSteps[idx].file_count || 1,
            })
          }
          for (let i = 0; i < runtimeSteps.length; i++) {
            const rt = runtimeSteps[i]
            const local = agent.steps[i + stepOffset]
            if (!local) continue
            const localFileCount = (local as any).file_count ?? 1
            if (local.status !== rt.status || local.description !== rt.description || localFileCount !== (rt.file_count || 1)) {
              local.status = rt.status as any
              if (rt.description && local.description !== rt.description) {
                local.description = rt.description
              }
              ;(local as any).file_count = rt.file_count || 1
            }
          }
        }
        // 定时刷新社区数据（长时间运行的步骤，如流水线组件分析，内部子任务完成时前端无感知）
        const now = Date.now()
        if (now - lastCommunityReload > 10000 && taskId) {
          lastCommunityReload = now
          const pid = useProjectStore().selectedProjectId
          if (pid) loadCommunities(taskId, pid).catch(() => {})
        }
        if (isCompleted) {
          controlDispatcher.unregister(controlKey)
          agentCompletedSignal.value++
          if (progress.status === 'completed' || progress.status === 'partial') {
            playSuccessSound()
          } else if (progress.status === 'failed') {
            playFailureSound()
          }
          if (progress.status !== 'failed' && progress.status !== 'cancelled' && taskId) {
            const pid = useProjectStore().selectedProjectId
            if (pid) {
              loadCommunities(taskId, pid).catch(() => {})
              // 延迟加载：等待 ingest consumer 完成异步写入 DB
              setTimeout(() => loadCommunities(taskId, pid).catch(() => {}), 3000)
            }
          }
          // 流水线完成时发出统计，供 AI 面板注入汇总消息
          if (progress.stats && taskId) {
            pipelineSummary.value = { taskId, stats: progress.stats }
          }
        }
      },
      onError: () => {
        // 不卸载 polling — 暂时性 disk I/O 等错误会在下次轮询自动恢复
      },
    })
  }

  function cancelAgentPolling(taskId?: string) {
    const activeKeys = controlDispatcher.getActiveKeys()
    for (const key of activeKeys) {
      if (!key.startsWith('agent-progress:')) continue
      if (!taskId || key.startsWith(`agent-progress:${taskId}:`)) {
        controlDispatcher.unregister(key)
      }
    }
  }

  let _statsPollKey = ''

  async function getProgressStats(taskId: string) {
    try {
      return await ipc.analysis.getProgressStats({ taskId })
    } catch { return null }
  }

  function _pollProgressStats(taskId: string) {
    // 停止旧轮询
    if (_statsPollKey && controlDispatcher.has(_statsPollKey)) {
      controlDispatcher.unregister(_statsPollKey)
    }
    _statsPollKey = `progress-stats:${taskId}`
    controlDispatcher.register(_statsPollKey, {
      interval: 3000,
      fetcher: () => ipc.analysis.getProgressStats({ taskId }),
      onData: (stats) => {
        if (!stats || !stats.found) return
        const t = tasks.value[taskId]
        if (!t || t.agentTasks.length === 0) return
        for (const agent of t.agentTasks) {
          agent.doneFiles = stats.doneFiles
          agent.totalFiles = stats.totalFiles
          agent.doneComps = stats.doneComps
          agent.totalComps = stats.totalComps
          agent.weightedProgress = stats.weightedProgress
          agent.progress = Math.round(stats.weightedProgress)
          if (stats.currentFile) agent.currentFile = stats.currentFile
          if (stats.currentComponent) agent.currentComponent = stats.currentComponent
          if (stats.phase) agent.phase = stats.phase
        }
      },
    })
  }

  async function loadAgentTaskHistory(taskId: string, offset = 0, limit = 10) {
    try {
      const resp = await ipc.analysis.getAgentTaskHistory({ taskId, offset, limit })
      agentTaskHistoryTotal.value[taskId] = resp.total
      return resp.results || []
    } catch { return [] }
  }

  const _completedTaskLogs = new Map<string, any[]>()

  function getCachedTaskLogs(agentId: string): any[] {
    return _completedTaskLogs.get(agentId) || []
  }

  async function clearAgentTaskHistory(taskId: string) {
    try {
      await ipc.analysis.clearAgentTaskHistory({ taskId })
      agentTaskHistoryOffset.value[taskId] = 0
      agentTaskHistoryTotal.value[taskId] = 0
      const t = tasks.value[taskId]
      if (t) {
        const toCache = t.agentTasks.filter(at => at.status !== 'running' && at.status !== 'queued')
        console.log('[CS] clearAgentTaskHistory caching', { taskId, count: toCache.length, agentTasksBefore: t.agentTasks.length })
        for (const at of toCache) {
          _completedTaskLogs.set(at.id, at.taskLogs)
        }
        t.agentTasks = t.agentTasks.filter(at => at.status === 'running' || at.status === 'queued')
        console.log('[CS] clearAgentTaskHistory done', { taskId, agentTasksAfter: t.agentTasks.length })
      }
      return true
    } catch { return false }
  }

  return {
    _completedTaskLogs,
    _pollAgentProgress,
    _pollProgressStats,
    _statsPollKey,
    addAgentTask,
    agentTaskHistoryOffset,
    agentTaskHistoryTotal,
    cancelAgentPolling,
    clearAgentTaskHistory,
    getCachedTaskLogs,
    getProgressStats,
    loadAgentTaskHistory,
    triggerComponentAnalysis,
    triggerOverview,
    updateAgentStep,
    updateAgentTask,
  }
}
