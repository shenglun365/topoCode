import { defineStore } from 'pinia'
import { useComponentAnalysis } from './community-analysis/useComponentAnalysis'
import { useAgentTasks } from './community-analysis/useAgentTasks'
import { ref } from 'vue'
import i18n from '@/i18n'
import { ipc } from '@/services/ipc'
import { isLLMConfigured } from '@/services/llmClient'
import { controlDispatcher } from '@/services/control-dispatcher'
import { playSuccessSound, playFailureSound } from '@/services/sound'
import { useAnalysisStore } from '@/stores/analysis'
import { useProjectStore } from '@/stores/project'
import type { ExternalStatsResult, CrossCommunityEdge, CrossCommunityEdgesResult } from '@/types/ipc'
import type { ComponentRef } from '@/stores/component-selection-store'

export interface CommunityItem {
  id: string
  communityId: string
  level: string
  edgeType: string
  nodeCount: number
  fileCount: number
  edgeCount: number
  qualityScore: number | null
  avgCoreness: number
  maxCoreness: number
  coreNodeRatio: number
  status: 'pending' | 'queued' | 'running' | 'completed' | 'error' | 'skipped'
  selected: boolean
  parentId?: string
  parentName?: string
  name?: string
  summary?: string
  error?: string
}

export interface ChildAnalysisState {
  running: boolean
  paused: boolean
  communities: CommunityItem[]
  errorLogs: string[]
  level: string
  parentCommId: string
  edgeType: string
}

interface CommunityTaskRuntime {
  communityRunning: boolean
  communityPaused: boolean
  communities: CommunityItem[]
  projectContext: string
  llmResults: Record<string, any>
  errorLogs: string[]
  analysisStates: Record<string, ChildAnalysisState>
  /** L0 社区覆盖的去重文件数（按 edgeType） */
  uniqueFileCounts: Record<string, number>
  /** 外部依赖/调用统计 */
  externalStats: ExternalStatsResult | null
  /** 跨社区边数据 (edgeType→level→edges) */
  crossCommunityEdges: Record<string, Record<string, CrossCommunityEdge[]>>
  /** 社区 node_list 缓存 (edgeType→level→{commId: [filePaths]}) */
  nodeLists: Record<string, Record<string, Record<string, string[]>>>
  /** 社区文件层详细数据缓存 (commKey→{files,fileCount}) */
  fileDetails: Record<string, { files: Array<{ id: string; name: string; filePath: string; language: string; lines: number; summary: string }>, fileCount: number }>
  /** 文件级图数据缓存 (commId→{nodes,edges}) */
  fileGraphs: Record<string, { nodes: Array<{ id: string; label: string; filePath: string }>; edges: Array<{ source: string; target: string; direction?: string }> }>
  /** Agent 任务队列 */
    agentTasks: Array<{
    id: string; action: string;     status: 'queued'|'running'|'completed'|'partial'|'failed'|'cancelled'|'stopping'
    steps: Array<{ description: string; status: 'pending'|'running'|'done'|'failed'; file_count?: number }>
    progress: number; message: string; createdAt: string
    taskLogs: Array<{ id: string; type: string; name: string; status: string; startTime: string; endTime: string | null; error: string | null }>
    weightedProgress: number
    totalFiles: number
    totalComps: number
    doneFiles: number
    doneComps: number
    currentFile?: string
    currentComponent?: string
    phase?: string
  }>
}


const _inflightLoads = new Map<string, Promise<any>>()
const _requestVersions = new Map<string, number>()

// 流水线完成统计，供 AI 助手注入汇总消息
export const pipelineSummary = ref<{ taskId: string; stats: any } | null>(null)

/** Agent 完成信号（计数器），ReportHome 等组件 watch 此值以刷新独立数据（概览文档、仪表盘） */
export const agentCompletedSignal = ref(0)

function _nextVersion(key: string): number {
  const v = (_requestVersions.get(key) || 0) + 1
  _requestVersions.set(key, v)
  return v
}

function _inflightKey(taskId: string, ...parts: string[]): string {
  return `${taskId}::${parts.join('::')}`
}

export const useCommunityStore = defineStore('community', () => {
  const tasks = ref<Record<string, CommunityTaskRuntime>>({})

  function ensureTask(taskId: string): CommunityTaskRuntime {
    if (!tasks.value[taskId]) {
      tasks.value[taskId] = {
        communityRunning: false,
        communityPaused: false,
        communities: [],
        projectContext: '',
        llmResults: {},
        errorLogs: [],
        analysisStates: {},
        uniqueFileCounts: {},
        externalStats: null,
        crossCommunityEdges: {},
        nodeLists: {},
        fileDetails: {},
        fileGraphs: {},
        agentTasks: [],
      }
    }
    return tasks.value[taskId]
  }

  const communitySelections = ref<Record<string, string[]>>({})

  function getSelections(taskId: string): string[] {
    return communitySelections.value[taskId] || []
  }

  function setSelections(taskId: string, ids: string[]) {
    communitySelections.value = { ...communitySelections.value, [taskId]: ids }
  }

  function clearSelections(taskId: string) {
    communitySelections.value = { ...communitySelections.value, [taskId]: [] }
  }

  async function listCommunityResults(taskId: string, edgeType: string) {
    return await ipc.analysis.listCommunityResults(taskId, edgeType)
  }

  async function getCascadeLevels(taskId: string, edgeType?: string) {
    return await ipc.analysis.getCascadeLevels(taskId, edgeType)
  }

  async function saveCommunityResult(params: {
    taskId: string; edgeType: string; commLv: string; commId: string;
    name?: string; summary?: string;
    modelId?: string; templateId?: string;
  }) {
    try { JSON.stringify(params) } catch {
      return { success: false }
    }
    return await ipc.analysis.saveCommunityResult(params)
  }

  async function loadCommunities(taskId: string, projectId: string) {
    const key = _inflightKey(taskId, 'loadCommunities')
    const existing = _inflightLoads.get(key)
    if (existing) {
      // console.log('[community-store] loadCommunities reuse inflight', { taskId, key })
      return existing
    }
    // console.log('[community-store] loadCommunities start', { taskId, projectId })

    const promise = (async () => {
      const t = ensureTask(taskId)
      try {
        const _t0 = Date.now()
        // 组件统一（kb-unified-components-plan）：仅加载 UNIFIED 单套口径
        const [uniLevels, uniResults] = await Promise.all([
          ipc.analysis.getCascadeLevels(taskId, 'UNIFIED').catch((e: any) => { console.warn('[community-store] getCascadeLevels UNIFIED failed', e?.message); return null }),
          ipc.analysis.listCommunityResults(taskId, 'UNIFIED').catch((e: any) => { console.warn('[community-store] listCommunityResults UNIFIED failed', e?.message); return ({ results: [] }) }),
        ])
        // console.log('[community-store] loadCommunities 4 requests done', { taskId, ms: Date.now() - _t0 })
        const llmMap: Record<string, any> = {}
        for (const rRaw of [...(uniResults?.results || [])]) {
          const r = rRaw as Record<string, unknown>
          const id = (r.commId || r.comm_id) as string | undefined
          // 人工命名优先（name_manual 由 updateCommunityName 写入，消歧流程不改）
          if (id) llmMap[id] = { ...r, name: r.name_manual || r.name }
        }
        const communities: CommunityItem[] = []
        if (uniLevels?.levels) {
          for (const lv of uniLevels.levels) {
            if (!lv.items) continue
            for (const item of lv.items) {
              const saved = llmMap[item.id]
              communities.push({
                id: `UNIFIED-${item.id}`,
                communityId: item.id, level: lv.lv, edgeType: 'UNIFIED',
                nodeCount: item.nodeCount || 0, fileCount: item.fileCount || 0, edgeCount: item.edgeCount || 0,
                qualityScore: item.qualityScore ?? null,
                avgCoreness: (item as any).metadata?.avgCoreness ?? 0,
                maxCoreness: (item as any).metadata?.maxCoreness ?? 0,
                coreNodeRatio: (item as any).metadata?.coreNodeRatio ?? 0,
                status: saved?.status === 'completed' ? 'completed' : ('pending' as any),
                selected: false,
                parentId: item.parentCommId ?? undefined,
                name: saved?.name || item.id,
                summary: saved?.summary || undefined,
              })
            }
          }
        }
        t.uniqueFileCounts = {
          UNIFIED: (uniLevels as any)?.totalUniqueFiles ?? 0,
        }
        const savedIds = getSelections(taskId)
        const newCommMap = new Map(communities.map(c => [c.id, c]))
        for (const existing of t.communities) {
          const newData = newCommMap.get(existing.id)
          if (newData) {
            if (existing.status === 'error' || existing.status === 'running' || existing.status === 'queued') {
              existing.selected = savedIds.includes(existing.id)
              newCommMap.delete(existing.id)
              continue
            }
            const saved = llmMap[existing.communityId]
            if (saved && saved.status === 'completed') {
              existing.status = 'completed'
              existing.name = saved.name || existing.communityId
              existing.summary = saved.summary || undefined
            } else {
              existing.status = 'pending'
            }
            existing.selected = savedIds.includes(existing.id)
            newCommMap.delete(existing.id)
          }
        }
        for (const c of Array.from(newCommMap.values())) {
          const saved = llmMap[c.communityId]
          if (saved && saved.status === 'completed') {
            c.status = 'completed'
            c.name = saved.name || c.communityId
            c.summary = saved.summary || undefined
          }
          c.selected = savedIds.includes(c.id)
          t.communities.push(c)
        }
        t.llmResults = llmMap
        loadProjectContext(taskId, projectId)
      } catch (e: any) {
        pushError(taskId, `loadCommunities: ${e?.message || String(e)}`)
      } finally {
        _inflightLoads.delete(key)
      }
    })()

    _inflightLoads.set(key, promise)
    return promise
  }

  /** 从 getReportDashboard 合并响应中加载社区数据（一次 RPC 替代 4 次独立调用） */
  async function loadCommunitiesFromDashboard(taskId: string, dash: any) {
    const key = _inflightKey(taskId, 'loadCommunitiesFromDashboard')
    const existing = _inflightLoads.get(key)
    if (existing) return existing
    
    const promise = (async () => {
      const t = ensureTask(taskId)
      try {
        const uniLevels = dash.uniLevels
        const uniResults = dash.uniResults || { results: [] }
        const llmMap: Record<string, any> = {}
        for (const rRaw of [...(uniResults?.results || [])]) {
          const r = rRaw as Record<string, unknown>
          const id = (r.commId || r.comm_id) as string | undefined
          // 人工命名优先（name_manual 由 updateCommunityName 写入，消歧流程不改）
          if (id) llmMap[id] = { ...r, name: r.name_manual || r.name }
        }
        const communities: CommunityItem[] = []
        if (uniLevels?.levels) {
          for (const lv of uniLevels.levels) {
            if (!lv.items) continue
            for (const item of lv.items) {
              const saved = llmMap[item.id]
              communities.push({
                id: `UNIFIED-${item.id}`,
                communityId: item.id, level: lv.lv, edgeType: 'UNIFIED',
                nodeCount: item.nodeCount || 0, fileCount: item.fileCount || 0, edgeCount: item.edgeCount || 0,
                qualityScore: item.qualityScore ?? null,
                avgCoreness: (item as any).metadata?.avgCoreness ?? 0,
                maxCoreness: (item as any).metadata?.maxCoreness ?? 0,
                coreNodeRatio: (item as any).metadata?.coreNodeRatio ?? 0,
                status: saved?.status === 'completed' ? 'completed' : ('pending' as any),
                selected: false,
                parentId: item.parentCommId ?? undefined,
                name: saved?.name || item.id,
                summary: saved?.summary || undefined,
              })
            }
          }
        }
        t.uniqueFileCounts = {
          UNIFIED: (uniLevels as any)?.totalUniqueFiles ?? 0,
        }
        const savedIds = getSelections(taskId)
        const newCommMap = new Map(communities.map(c => [c.id, c]))
        for (const existing of t.communities) {
          const newData = newCommMap.get(existing.id)
          if (newData) {
            if (existing.status === 'error' || existing.status === 'running' || existing.status === 'queued') {
              existing.selected = savedIds.includes(existing.id)
              newCommMap.delete(existing.id)
              continue
            }
            const saved = llmMap[existing.communityId]
            if (saved && saved.status === 'completed') {
              existing.status = 'completed'
              existing.name = saved.name || existing.communityId
              existing.summary = saved.summary || undefined
            } else {
              existing.status = 'pending'
            }
            existing.selected = savedIds.includes(existing.id)
            newCommMap.delete(existing.id)
          }
        }
        for (const c of Array.from(newCommMap.values())) {
          const saved = llmMap[c.communityId]
          if (saved && saved.status === 'completed') {
            c.status = 'completed'
            c.name = saved.name || c.communityId
            c.summary = saved.summary || undefined
          }
          c.selected = savedIds.includes(c.id)
          t.communities.push(c)
        }
        t.llmResults = llmMap
        const pid = dash.task?.project_id || dash.task?.projectId
        if (pid) loadProjectContext(taskId, pid)
      } catch (e: any) {
        pushError(taskId, `loadCommunitiesFromDashboard: ${e?.message || String(e)}`)
      } finally {
        _inflightLoads.delete(key)
      }
    })()

    _inflightLoads.set(key, promise)
    return promise
  }

  /** 从 getReportDashboard 合并响应中加载社区数据（一次 RPC 替代 4 次独立调用） */
  async function loadProjectContext(taskId: string, projectId: string) {
    if (!projectId) return

    const key = _inflightKey(taskId, 'projectContext', projectId)
    const t = ensureTask(taskId)
    if (t.projectContext || _inflightLoads.get(key)) return

    const promise = (async () => {
      try {
        const result = await ipc.report.getProjectSummary({ projectId })
        if (result?.summary) {
          ensureTask(taskId).projectContext = `## 项目概要\n${result.summary}`
        }
      } catch { /* skip */ } finally {
        _inflightLoads.delete(key)
      }
    })()

    _inflightLoads.set(key, promise)
    return promise
  }

  async function loadExternalStats(taskId: string, force = false) {
    const t = ensureTask(taskId)
    // 非强制时，已有数据则跳过（避免重复请求）
    if (!force && t.externalStats) return

    const key = _inflightKey(taskId, 'externalStats')
    const existing = _inflightLoads.get(key)
    if (existing) return existing

    const promise = (async () => {
      try {
        const result = await ipc.analysis.getExternalStats(taskId)
        // 只有结果含有效数据才缓存，否则设为 null 允许后续重试
        if (result && (
          (result.externalDeps && result.externalDeps.length > 0) ||
          (result.externalCalls && result.externalCalls.length > 0)
        )) {
          ensureTask(taskId).externalStats = result
        } else {
          ensureTask(taskId).externalStats = null
        }
      } catch (e: any) {
        console.warn('[community-store] loadExternalStats failed:', e?.message || e)
        // 失败则设为 null，允许下次重试
        ensureTask(taskId).externalStats = null
      } finally {
        _inflightLoads.delete(key)
      }
    })()

    _inflightLoads.set(key, promise)
    return promise
  }

  async function loadCrossCommunityEdges(taskId: string, edgeType: string, commLv: string) {
    const t = ensureTask(taskId)
    if (t.crossCommunityEdges[edgeType]?.[commLv]) return

    const key = _inflightKey(taskId, 'crossEdges', edgeType, commLv)
    const existing = _inflightLoads.get(key)
    if (existing) return existing

    const version = _nextVersion(key)
    const promise = (async () => {
      try {
        const result = await ipc.analysis.getCrossCommunityEdges({ taskId, edgeType, commLv })
        if (result?.crossEdges && _requestVersions.get(key) === version) {
          if (!t.crossCommunityEdges[edgeType]) {
            t.crossCommunityEdges[edgeType] = {}
          }
          t.crossCommunityEdges[edgeType][commLv] = result.crossEdges
        }
      } catch (e: any) {
        console.warn('[community-store] loadCrossCommunityEdges failed:', e?.message || e)
      } finally {
        _inflightLoads.delete(key)
      }
    })()

    _inflightLoads.set(key, promise)
    return promise
  }

  function getCrossEdges(taskId: string, edgeType: string, commLv: string): CrossCommunityEdge[] {
    return tasks.value[taskId]?.crossCommunityEdges?.[edgeType]?.[commLv] || []
  }

  async function loadCommunityNodeLists(taskId: string, edgeType: string, commLv: string) {
    const t = ensureTask(taskId)
    if (t.nodeLists[edgeType]?.[commLv]) return

    const key = _inflightKey(taskId, 'nodeLists', edgeType, commLv)
    const existing = _inflightLoads.get(key)
    if (existing) return existing

    const version = _nextVersion(key)
    const promise = (async () => {
      try {
        const result = await ipc.analysis.getCommunityNodeLists({ taskId, edgeType, commLv })
        if (result && _requestVersions.get(key) === version) {
          if (!t.nodeLists[edgeType]) t.nodeLists[edgeType] = {}
          t.nodeLists[edgeType][commLv] = result
        }
      } catch (e: any) {
        console.warn('[community-store] loadCommunityNodeLists failed:', e?.message || e)
      } finally {
        _inflightLoads.delete(key)
      }
    })()

    _inflightLoads.set(key, promise)
    return promise
  }

  async function loadCommunityFileGraph(taskId: string, commId: string, edgeType: string) {
    const t = ensureTask(taskId)
    const cacheKey = `${commId}::${edgeType}`
    if (t.fileGraphs[cacheKey]) return t.fileGraphs[cacheKey]
    try {
      const result = await ipc.analysis.getCommunityFileGraph({ taskId, edgeType, commId })
      if (result) t.fileGraphs[cacheKey] = result
      return result
    } catch { return { nodes: [], edges: [] } }
  }

  async function loadFileDetail(taskId: string, commId: string, edgeType: string, limit = 300) {
    const t = ensureTask(taskId)
    const cacheKey = `${commId}::${edgeType}`
    if (t.fileDetails[cacheKey]) return t.fileDetails[cacheKey]

    const key = _inflightKey(taskId, 'fileDetail', commId, edgeType)
    const existing = _inflightLoads.get(key)
    if (existing) return existing

    const version = _nextVersion(key)
    const promise = (async () => {
      try {
        const result = await ipc.report.getCommunityFileDetail({ taskId, communityId: commId, edgeType, limit })
        if (result && result.found && _requestVersions.get(key) === version) {
          t.fileDetails[cacheKey] = { files: result.files, fileCount: result.fileCount }
        }
        return result
      } catch (e: any) {
        console.warn('[community-store] loadFileDetail failed:', e?.message || e)
        return { files: [], edges: [], found: false }
      } finally {
        _inflightLoads.delete(key)
      }
    })()

    _inflightLoads.set(key, promise)
    return promise
  }

  function toggleSelect(taskId: string, id: string) {
    const t = tasks.value[taskId]
    if (!t || t.communityRunning) return
    const community = t.communities.find(c => c.id === id)
    if (community) { community.selected = !community.selected; syncSelections(taskId) }
  }

  function selectAll(taskId: string, ids: string[], selected: boolean) {
    const t = tasks.value[taskId]; if (!t) return
    for (const c of t.communities) { if (ids.includes(c.id)) c.selected = selected }
    syncSelections(taskId)
  }

  function selectIncomplete(taskId: string) {
    const t = tasks.value[taskId]; if (!t) return
    for (const c of t.communities) { if (c.level === 'L0' && c.status !== 'completed') c.selected = true }
    syncSelections(taskId)
  }

  function deselectAll(taskId: string) {
    const t = tasks.value[taskId]
    if (t) { for (const c of t.communities) c.selected = false; syncSelections(taskId) }
  }

  function syncSelections(taskId: string) {
    const t = tasks.value[taskId]; if (!t) return
    setSelections(taskId, t.communities.filter(c => c.selected).map(c => c.id))
  }

  function restoreSelections(taskId: string) {
    const t = tasks.value[taskId]; if (!t) return
    const savedIds = getSelections(taskId)
    if (!savedIds.length) return
    for (const c of t.communities) c.selected = savedIds.includes(c.id)
  }

  function pushError(taskId: string, msg: string) {
    const t = tasks.value[taskId]; if (!t) return
    t.errorLogs.unshift(msg); if (t.errorLogs.length > 50) t.errorLogs.length = 50
  }

  function clearErrorLogs(taskId: string) {
    const t = tasks.value[taskId]; if (t) t.errorLogs = []
  }

  function clearTask(taskId: string) {
    delete tasks.value[taskId]
  }

  /* ---- Agent task management ---- */

  /** 移除指定 action 类型的已终态 agent，避免残留卡片 */
  const _TERMINAL = new Set(['completed', 'failed', 'cancelled', 'skipped', 'partial'])
  function _cleanTerminalAgents(taskId: string, action: string) {
    const t = tasks.value[taskId]
    if (!t) return
    for (const at of t.agentTasks) {
      if (at.action === action && _TERMINAL.has(at.status)) {
        const ck = `agent-progress:${taskId}:${at.id}`
        if (controlDispatcher.has(ck)) controlDispatcher.unregister(ck)
      }
    }
    t.agentTasks = t.agentTasks.filter(at => at.action !== action || !_TERMINAL.has(at.status))
  }


  function ensureAgentPolling(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    for (let i = 0; i < t.agentTasks.length; i++) {
      const at = t.agentTasks[i]
      if (at.status === 'running' && at.id) {
        const controlKey = `agent-progress:${taskId}:${at.id}`
        if (!controlDispatcher.has(controlKey)) {
          // console.log('[ensurePolling] starting poll for agent=%s idx=%d', at.id, i)
          _pollAgentProgress(taskId, i, at.id, 0)
        }
      }
    }
  }

  async function cancelAgentTask(taskId: string, agentTaskId: string) {
    try {
      const result = await ipc.analysis.cancelAgentTask({ agentTaskId })
      const t = tasks.value[taskId]
      if (!t) return
      const idx = t.agentTasks.findIndex(at => at.id === agentTaskId)
      if (idx < 0) return
      if (result.cancelled) {
        // 后端已接受停止请求 → 标记 stopping，等待 polling 更新为最终状态
        updateAgentTask(taskId, idx, { status: 'stopping', message: i18n.global.t('report.agent.cancelling') })
        // 保底：30 秒后若仍为 stopping，强制标记 cancelled
        setTimeout(() => {
          const t2 = tasks.value[taskId]
          if (t2) {
            const idx2 = t2.agentTasks.findIndex(at => at.id === agentTaskId)
            if (idx2 >= 0 && t2.agentTasks[idx2].status === 'stopping') {
              updateAgentTask(taskId, idx2, { status: 'cancelled', message: i18n.global.t('report.agent.stopTimeout') })
            }
          }
        }, 30000)
      } else {
        // 任务已处于完成状态
        updateAgentTask(taskId, idx, { status: 'cancelled', message: i18n.global.t('report.agent.taskCancelled') })
      }
      // 取消 presummary 管线队友
      for (const at of t.agentTasks) {
        if (at.id !== agentTaskId && at.action === 'presummary_files' && (at.status === 'running' || at.status === 'queued')) {
          try { await ipc.analysis.cancelAgentTask({ agentTaskId: at.id }) } catch {}
        }
      }
    } catch {}
  }

  // ── 预摘要 ──
  async function getPreSummaryStatus(taskId: string) {
    return await ipc.analysis.getPreSummaryStatus({ taskId })
  }
  async function listPreSummaryFiles(taskId: string, batch = 'P0', page = 1, pageSize = 20, search = '') {
    return await ipc.analysis.listPreSummaryFiles({ taskId, batch, page, page_size: pageSize, search })
  }
  async function startPreSummary(taskId: string, batch = 'P0', limit = 0, subagentConcurrency = 1) {
    const t = ensureTask(taskId)
    // 清理已终态的 presummary_files agent
    _cleanTerminalAgents(taskId, 'presummary_files')
    const conc = Math.max(1, Math.min(10, subagentConcurrency))
    const concHint = conc > 1 ? i18n.global.t('report.agent.concHint', { n: conc }) : ''
    const stepDesc = `${limit > 0 ? i18n.global.t('report.agent.presummaryBatchLimited', { batch, limit }) : i18n.global.t('report.agent.presummaryBatch', { batch })}${concHint}`
    const idx = t.agentTasks.length
    addAgentTask(taskId, 'presummary_files', [stepDesc, i18n.global.t('report.agent.waitingLlm')])
    t.agentTasks[idx].status = 'running'

    try {
      const result = await ipc.analysis.startPreSummary({ taskId, batch, limit, subagentConcurrency: conc })
      if (result.allCached) {
        console.log('[CS] startPreSummary allCached, splice idx=%d agentTasks before=%d', idx, t.agentTasks.length)
        t.agentTasks.splice(idx, 1)
        console.log('[CS] startPreSummary after splice agentTasks=%d', t.agentTasks.length)
        return result
      }
      if (result.success && result.agentTaskId) {
        t.agentTasks[idx].id = result.agentTaskId
        updateAgentTask(taskId, idx, { progress: 0, message: i18n.global.t('report.agent.fileCountMsg', { count: result.fileCount || 0 }) })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || i18n.global.t('report.agent.startFailed') })
      }
      return result
    } catch (e: any) {
      updateAgentTask(taskId, idx, { status: 'failed', message: e?.message || 'unknown error' })
      throw e
    }
  }
  async function startPreSummaryPipeline(taskId: string, batches: string[], limit = 0, subagentConcurrency = 1) {
    const t = ensureTask(taskId)
    // 清理已终态的 presummary_files agent
    _cleanTerminalAgents(taskId, 'presummary_files')
    const conc = Math.max(1, Math.min(10, subagentConcurrency))
    const concHint = conc > 1 ? i18n.global.t('report.agent.concHint', { n: conc }) : ''
    const stepDesc = i18n.global.t('report.agent.presummaryPipelineStep', { batches: batches.join('→'), count: batches.length, hint: concHint })

    // 清除同任务下旧的 presummary_files agent（防止重复卡片）
    const stale = (t.agentTasks || []).filter(a =>
      a.action === 'presummary_files' && (a.status === 'running' || a.status === 'queued')
    )
    if (stale.length > 0) {
      console.log('[CS] cancelling stale presummary agents', { count: stale.length, ids: stale.map(s => s.id).join(',') })
    }
    for (const s of stale) {
      const controlKey = `agent-progress:${taskId}:${s.id}`
      if (controlDispatcher.has(controlKey)) controlDispatcher.unregister(controlKey)
      s.status = 'cancelled'
    }

    const idx = t.agentTasks.length
    addAgentTask(taskId, 'presummary_files', [stepDesc, i18n.global.t('report.agent.waitingLlm')])
    t.agentTasks[idx].status = 'running'

    try {
      // console.log('[pipeline] calling startPreSummaryPipeline taskId=%s batches=%o limit=%d conc=%d', taskId, batches, limit, conc)
      const result = await ipc.analysis.startPreSummaryPipeline({ taskId, batches, limit, subagentConcurrency: conc })
      // console.log('[pipeline] response success=%s agentTaskId=%s fileCount=%s', result.success, result.agentTaskId, result.fileCount)
      if (result.success && result.agentTaskId) {
        t.agentTasks[idx].id = result.agentTaskId
        updateAgentTask(taskId, idx, { progress: 0, message: i18n.global.t('report.agent.fileCountMsg', { count: result.fileCount || 0 }) })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
        // console.log('[pipeline] polling started for agent=%s idx=%d', result.agentTaskId, idx)
      } else if (result.success) {
        // 无 agentTaskId = 全部批次已缓存（后端已跳过）→ 快速标记完成，不留 running
        // 同步替换占位 steps（卡片无 taskLogs 时渲染最后一个 step 的描述，占位文案"等待 LLM 分析完成"对已完成卡片是错的）
        t.agentTasks[idx].steps = [{ description: i18n.global.t('report.agent.allCachedSkipped'), status: 'done' }]
        updateAgentTask(taskId, idx, { status: 'completed', progress: 100, message: i18n.global.t('report.agent.allCachedSkipped') })
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || i18n.global.t('report.agent.startFailed') })
      }
      return result
    } catch (e: any) {
      console.error('[pipeline] error:', e)
      updateAgentTask(taskId, idx, { status: 'failed', message: e?.message || 'unknown error' })
      throw e
    }
  }
  async function getFileSummary(taskId: string, filePath: string) {
    return await ipc.analysis.getFileSummary({ taskId, file_path: filePath })
  }

  async function getPreSummaryFileSource(taskId: string, filePath: string) {
    return await ipc.analysis.getPreSummaryFileSource({ taskId, file_path: filePath })
  }
  async function deleteFileSummary(taskId: string, filePath: string) {
    return await ipc.analysis.deleteFileSummary({ taskId, file_path: filePath })
  }
  async function rerunFileSummary(taskId: string, filePath: string) {
    return await ipc.analysis.rerunFileSummary({ taskId, file_path: filePath })
  }

  async function startPipeline(taskId: string, force = false, language = '', concurrency = 1, componentTimeout?: number) {
    const t = ensureTask(taskId)
    // 清理上次残留的 pipeline agent（有且应只有一个）
    t.agentTasks = t.agentTasks.filter(at => at.action !== 'pipeline')
    const idx = t.agentTasks.length
    const subConc = Math.max(1, Math.min(5, concurrency))
    const concHint = subConc > 1 ? i18n.global.t('report.agent.concHintFull', { n: subConc }) : ''
    addAgentTask(taskId, 'pipeline', [
      i18n.global.t('report.agent.pipelineStart', { hint: concHint }),
      i18n.global.t('report.pipeline.preprocessing'),
      i18n.global.t('report.agent.pipelinePreSummary'),
      i18n.global.t('report.agent.pipelineComponentAnalysis'),
      i18n.global.t('report.pipeline.overallArchitecture'),
    ])
    t.agentTasks[idx].status = 'running'
    try {
      const result = await ipc.analysis.startPipeline({
        taskId, force: force || undefined, language: language || undefined,
        concurrency: subConc > 1 ? subConc : undefined,
        subagent_concurrency: subConc > 1 ? subConc : undefined,
        component_timeout: componentTimeout,
      })
      if (result.success && result.agentTaskId) {
        t.agentTasks[idx].id = result.agentTaskId
        updateAgentTask(taskId, idx, { progress: 0, message: i18n.global.t('report.agent.pipelineStarting') })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
        _pollProgressStats(taskId)
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || i18n.global.t('report.agent.startFailed') })
      }
      return result
    } catch (e: any) {
      updateAgentTask(taskId, idx, { status: 'failed', message: e?.message || 'unknown error' })
      throw e
    }
  }

  // ── 组件命名消歧（独立流程，可按需反复运行） ──────────────────
  async function scanNameConflicts(taskId: string, commIds?: string[]) {
    return await ipc.analysis.scanComponentNameConflicts({ taskId, commIds })
  }

  async function resolveNameConflicts(taskId: string, members: Array<{ commId: string; commLv: string; edgeType?: string }>, language = '') {
    const safe = JSON.parse(JSON.stringify({ taskId, members, language }))
    return await ipc.analysis.resolveComponentNameConflicts(safe)
  }

  async function cleanCommunitySummaries(taskId: string) {
    return await ipc.analysis.cleanCommunitySummaries({ taskId })
  }

  // ---- MS6-W5: 组件分析/agent 任务逻辑外移(community-analysis/)，store 仍是唯一 API 面 ----
  const analysisApi = useComponentAnalysis({ tasks, ensureTask, saveCommunityResult, syncSelections })
  const agentApi = useAgentTasks({ tasks, ensureTask, saveCommunityResult, syncSelections, loadCommunities,
    loadExternalStats, loadCommunityFileGraph, loadFileDetail, getCrossEdges })
  const { _pollAgentProgress, _pollProgressStats, addAgentTask, agentTaskHistoryOffset, agentTaskHistoryTotal, analyzeSelected, cancelAgentPolling, clearAgentTaskHistory, getCachedTaskLogs, getProgressStats, loadAgentTaskHistory, retryTask, runTask, stopAnalysis, triggerComponentAnalysis, triggerOverview, updateAgentStep, updateAgentTask } = { ...analysisApi, ...agentApi }
  return {
    ...analysisApi, ...agentApi,
    tasks, communitySelections,
    ensureTask, getSelections, setSelections, clearSelections,
    listCommunityResults, getCascadeLevels, saveCommunityResult,
    loadCommunities, loadCommunitiesFromDashboard, loadProjectContext, loadExternalStats, loadCrossCommunityEdges, loadCommunityNodeLists, loadFileDetail, loadCommunityFileGraph, getCrossEdges, analyzeSelected, runTask, stopAnalysis, retryTask,
    toggleSelect, selectAll, selectIncomplete, deselectAll, syncSelections, restoreSelections, triggerOverview,
    pushError, clearErrorLogs, clearTask,
    addAgentTask, updateAgentTask, updateAgentStep, triggerComponentAnalysis,
    loadAgentTaskHistory, clearAgentTaskHistory, getCachedTaskLogs, agentTaskHistoryOffset, agentTaskHistoryTotal,
    cancelAgentPolling, cancelAgentTask, ensureAgentPolling,
    getPreSummaryStatus, listPreSummaryFiles, startPreSummary, startPreSummaryPipeline,
    getFileSummary, getPreSummaryFileSource, deleteFileSummary, rerunFileSummary, startPipeline, getProgressStats,
    scanNameConflicts, resolveNameConflicts, cleanCommunitySummaries,
  }
})
