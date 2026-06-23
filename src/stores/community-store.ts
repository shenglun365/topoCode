import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import { isLLMConfigured } from '@/services/llmClient'
import { controlDispatcher } from '@/services/control-dispatcher'
import { useAnalysisStore } from '@/stores/analysis'
import { useProjectStore } from '@/stores/project'
import type { ExternalStatsResult, CrossCommunityEdge, CrossCommunityEdgesResult, TimelineEntry } from '@/types/ipc'
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
  /** Agent 任务队列 */
  agentTasks: Array<{
    id: string; action: string; status: 'queued'|'running'|'completed'|'partial'|'failed'|'cancelled'
    steps: Array<{ description: string; status: 'pending'|'running'|'done'|'failed' }>
    progress: number; message: string; createdAt: string
  }>
  /** 架构时间线 */
  timeline: TimelineEntry[]
  /** 对比模式激活状态 */
  compareActive: boolean
  compareFrom: string
  compareTo: string
}


const _inflightLoads = new Map<string, Promise<any>>()
const _requestVersions = new Map<string, number>()

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
        agentTasks: [],
        timeline: [],
        compareActive: false,
        compareFrom: '',
        compareTo: '',
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
    if (existing) return existing

    const promise = (async () => {
      const t = ensureTask(taskId)
      try {
        const [callLevels, depLevels, callResults, depResults] = await Promise.all([
          ipc.analysis.getCascadeLevels(taskId, 'CALL').catch(() => null),
          ipc.analysis.getCascadeLevels(taskId, 'INCLUDE').catch(() => null),
          ipc.analysis.listCommunityResults(taskId, 'CALL').catch(() => ({ results: [] })),
          ipc.analysis.listCommunityResults(taskId, 'INCLUDE').catch(() => ({ results: [] })),
        ])
        const llmMap: Record<string, any> = {}
        for (const rRaw of [...(callResults?.results || []), ...(depResults?.results || [])]) {
          const r = rRaw as Record<string, unknown>
          const id = (r.commId || r.comm_id) as string | undefined
          if (id) llmMap[id] = { ...r, name: r.name || r.name_manual }
        }
        const communities: CommunityItem[] = []
        if (callLevels?.levels) {
          for (const lv of callLevels.levels) {
            if (!lv.items) continue
            for (const item of lv.items) {
              const saved = llmMap[item.id]
              communities.push({
                id: `CALL-${item.id}`,
                communityId: item.id, level: lv.lv, edgeType: 'CALL',
                nodeCount: item.nodeCount || 0, fileCount: item.fileCount || 0, edgeCount: item.edgeCount || 0,
                qualityScore: item.qualityScore ?? null,
                avgCoreness: (item as any).metadata?.avgCoreness ?? 0,
                maxCoreness: (item as any).metadata?.maxCoreness ?? 0,
                coreNodeRatio: (item as any).metadata?.coreNodeRatio ?? 0,
                status: saved ? 'completed' : ('pending' as any),
                selected: false,
                parentId: item.parentCommId ?? undefined,
                name: saved?.name || item.id,
                summary: saved?.summary || undefined,
              })
            }
          }
        }
        if (depLevels?.levels) {
          for (const lv of depLevels.levels) {
            if (!lv.items) continue
            for (const item of lv.items) {
              const saved = llmMap[item.id]
              communities.push({
                id: `INCLUDE-${item.id}`,
                communityId: item.id, level: lv.lv, edgeType: 'INCLUDE',
                nodeCount: item.nodeCount || 0, fileCount: item.fileCount || 0, edgeCount: item.edgeCount || 0,
                qualityScore: item.qualityScore ?? null,
                avgCoreness: (item as any).metadata?.avgCoreness ?? 0,
                maxCoreness: (item as any).metadata?.maxCoreness ?? 0,
                coreNodeRatio: (item as any).metadata?.coreNodeRatio ?? 0,
                status: saved ? 'completed' : ('pending' as any),
                selected: false,
                parentId: item.parentCommId ?? undefined,
                name: saved?.name || item.id,
                summary: saved?.summary || undefined,
              })
            }
          }
        }
        t.uniqueFileCounts = {
          CALL: (callLevels as any)?.totalUniqueFiles ?? 0,
          INCLUDE: (depLevels as any)?.totalUniqueFiles ?? 0,
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
            if (saved) {
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
          if (saved) {
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
        const callLevels = dash.callLevels
        const depLevels = dash.depLevels
        const callResults = dash.callResults || { results: [] }
        const depResults = dash.depResults || { results: [] }
        const llmMap: Record<string, any> = {}
        for (const rRaw of [...(callResults?.results || []), ...(depResults?.results || [])]) {
          const r = rRaw as Record<string, unknown>
          const id = (r.commId || r.comm_id) as string | undefined
          if (id) llmMap[id] = { ...r, name: r.name || r.name_manual }
        }
        const communities: CommunityItem[] = []
        if (callLevels?.levels) {
          for (const lv of callLevels.levels) {
            if (!lv.items) continue
            for (const item of lv.items) {
              const saved = llmMap[item.id]
              communities.push({
                id: `CALL-${item.id}`,
                communityId: item.id, level: lv.lv, edgeType: 'CALL',
                nodeCount: item.nodeCount || 0, fileCount: item.fileCount || 0, edgeCount: item.edgeCount || 0,
                qualityScore: item.qualityScore ?? null,
                avgCoreness: (item as any).metadata?.avgCoreness ?? 0,
                maxCoreness: (item as any).metadata?.maxCoreness ?? 0,
                coreNodeRatio: (item as any).metadata?.coreNodeRatio ?? 0,
                status: saved ? 'completed' : ('pending' as any),
                selected: false,
                parentId: item.parentCommId ?? undefined,
                name: saved?.name || item.id,
                summary: saved?.summary || undefined,
              })
            }
          }
        }
        if (depLevels?.levels) {
          for (const lv of depLevels.levels) {
            if (!lv.items) continue
            for (const item of lv.items) {
              const saved = llmMap[item.id]
              communities.push({
                id: `INCLUDE-${item.id}`,
                communityId: item.id, level: lv.lv, edgeType: 'INCLUDE',
                nodeCount: item.nodeCount || 0, fileCount: item.fileCount || 0, edgeCount: item.edgeCount || 0,
                qualityScore: item.qualityScore ?? null,
                avgCoreness: (item as any).metadata?.avgCoreness ?? 0,
                maxCoreness: (item as any).metadata?.maxCoreness ?? 0,
                coreNodeRatio: (item as any).metadata?.coreNodeRatio ?? 0,
                status: saved ? 'completed' : ('pending' as any),
                selected: false,
                parentId: item.parentCommId ?? undefined,
                name: saved?.name || item.id,
                summary: saved?.summary || undefined,
              })
            }
          }
        }
        t.uniqueFileCounts = {
          CALL: (callLevels as any)?.totalUniqueFiles ?? 0,
          INCLUDE: (depLevels as any)?.totalUniqueFiles ?? 0,
        }
        const savedIds = getSelections(taskId)
        const savedStatuses = new Map(t.communities.map(c => [c.id, c.status] as const))
        for (const c of communities) {
          const prevStatus = savedStatuses.get(c.id)
          if (prevStatus === 'running' || prevStatus === 'queued') {
            c.status = prevStatus
          }
          if (prevStatus === 'error') {
            c.status = 'error'
          }
          c.selected = savedIds.includes(c.id)
        }
        t.communities = communities
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

  async function analyzeSelected(taskId: string, modelId: string, batchSize: number, projectId: string) {
    const t = ensureTask(taskId)
    if (t.communityRunning || t.communityPaused) return []
    const pending = t.communities.filter(c => c.selected)
    if (pending.length === 0) return []

    t.communityRunning = true
    t.communityPaused = false

    for (let i = 0; i < pending.length; i += batchSize) {
      if (t.communityPaused) break
      const batch = pending.slice(i, i + batchSize)
      batch.forEach(c => { c.status = 'queued' })
      const results = await Promise.allSettled(batch.map(c => runTask(taskId, c, modelId, projectId)))
      for (let idx = 0; idx < batch.length; idx++) {
        const c = batch[idx]
        const r = results[idx]
        if (r.status === 'rejected') {
          c.status = 'error'
          c.error = (r.reason as any)?.message || String(r.reason)
        }
        if (c.status === 'completed') {
          try {
            await ipc.analysis.saveCommunityResult({
              taskId, edgeType: c.edgeType, commLv: c.level, commId: c.communityId,
              name: c.name || c.communityId, summary: c.summary || '',
              modelId, templateId: 'community_analyze',
            })
            t.llmResults[c.communityId] = { comm_id: c.communityId, name: c.name, summary: c.summary }
          } catch { /* skip */ }
        }
      }
    }

    t.communityRunning = false
    // 已完成的组件取消选中，未完成的/失败的保持选中
    for (const c of t.communities) {
      if (c.selected && c.status === 'completed') {
        c.selected = false
      }
    }
    syncSelections(taskId)
    return t.communities
      .filter(c => c.status === 'completed' && c.name)
      .map(c => ({
        communityId: c.communityId, level: c.level, edgeType: c.edgeType,
        name: c.name!, summary: c.summary!,
      }))
  }

  async function runTask(taskId: string, community: CommunityItem, modelId: string, projectId: string): Promise<boolean> {
    community.status = 'running'
    try {
      if (!projectId) { community.status = 'skipped'; return false }
      const result = await ipc.report.getLevelCommunityDetail({ projectId, taskId, level: community.level, edgeType: community.edgeType })
      const commList = result?.communities
      if (!Array.isArray(commList) || commList.length === 0) { community.status = 'skipped'; return false }
      const detail = commList.find((c: Record<string, unknown>) => c.communityId === community.communityId) as Record<string, any> | undefined
      if (!detail) { community.status = 'skipped'; return false }

      const nodeListText = (detail.nodes || []).map((n: Record<string, any>) => {
        const ext = n.filePath && n.filePath !== '?' ? n.filePath.split('.').pop() : ''
        return `- ${ext ? `${n.name}.${ext}` : n.name}  (${n.filePath})`
      }).slice(0, 100).join('\n')
      const edgeListText = (detail.edges || []).map((e: Record<string, any>) => {
        return `- ${e.sourceDisplay || e.source} → ${e.targetDisplay || e.target}`
      }).slice(0, 100).join('\n')

      const t = ensureTask(taskId)
      let parentContext = ''
      const levelNum = parseInt(community.level?.[1] || '')
      if (levelNum > 0 && community.parentId) {
        const parentLv = `L${levelNum - 1}`
        try {
          const parentResult = await window.api?.analysis.getCommunityResult({ taskId, edgeType: community.edgeType, commLv: parentLv, commId: community.parentId })
          if (parentResult?.name || parentResult?.summary) {
            parentContext = `\n\n## 所属父组件\n### ${parentResult.nameManual || parentResult.name || community.parentId}\n${parentResult.summary || ''}`
          }
        } catch { /* skip */ }
      }

      const sessionId = `comm-${taskId}-${community.communityId}-${Date.now()}`
      const chatResult = await window.api!.llm.chat({
        sessionId, modelId,
        templateId: 'community_analyze',
        variables: {
          communityId: community.communityId, level: community.level,
          nodeCount: String(detail.nodeCount), edgeCount: String(detail.edgeCount),
          nodeListWithPaths: nodeListText, edgeListWithDetails: edgeListText,
          parentSummaries: parentContext ? `${t.projectContext}\n${parentContext}` : t.projectContext,
          source: 'community_analysis', community_id: community.communityId,
          community_level: community.level, edge_type: community.edgeType,
          batch_id: `batch-${Date.now()}`,
        },
        mode: 'structured',
        outputSchema: { type: 'object', properties: { name: { type: 'string', maxLength: 20 }, summary: { type: 'string' } }, required: ['name', 'summary'] },
      })
      let fullContent = ''
      await new Promise<void>((resolve, reject) => {
        const unsubscribe = window.api!.llm.subscribe(chatResult.requestId, {
          onChunk(data: { text: string }) { fullContent += data.text },
          onDone(data: { content: string; structured?: Record<string, any> }) {
            const trimmed = (data.structured?.summary || fullContent || '').trim()
            const hasValidName = !!data.structured?.name
            const isError = !trimmed || (!hasValidName && trimmed.length < 5) || trimmed.length < 1 || /^(error|错误|failed|失败|\[error\]|\[ERROR\])/i.test(trimmed)
            if (isError) { community.status = 'error'; community.error = trimmed || 'LLM returned empty response' }
            else if (data.structured) {
              community.name = data.structured.name?.slice(0, 20) || community.communityId
              community.summary = data.structured.summary || ''
              community.status = 'completed'
            } else { community.status = 'completed'; community.name = community.communityId; community.summary = fullContent }
            unsubscribe(); resolve()
          },
          onError(errData: { message: string }) {
            community.status = 'error'; community.error = errData.message; unsubscribe(); reject(new Error(errData.message))
          },
        })
      })
      return true
    } catch (e: unknown) {
      community.status = 'error'; community.error = (e as Error).message || String(e); return false
    }
  }

  function stopAnalysis(taskId: string) {
    const t = tasks.value[taskId]
    if (t) { t.communityPaused = true; t.communityRunning = false }
  }

  async function retryTask(taskId: string, communityId: string, modelId: string, projectId: string): Promise<boolean> {
    const t = ensureTask(taskId)
    const community = t.communities.find(c => c.communityId === communityId)
    if (!community) return false
    community.status = 'pending'; community.error = undefined; community.selected = false; community.name = undefined; community.summary = undefined
    syncSelections(taskId)
    community.status = 'running'
    try {
      const ok = await runTask(taskId, community, modelId, projectId)
      if (ok && (community.status as CommunityItem['status']) === 'completed') {
        await ipc.analysis.saveCommunityResult({ taskId, edgeType: community.edgeType, commLv: community.level, commId: community.communityId, name: community.name || community.communityId, summary: community.summary || '', modelId, templateId: 'community_analyze' })
      }
      return ok
    } catch (e: unknown) { community.status = 'error'; community.error = e instanceof Error ? (e as Error).message : String(e); return false }
  }

  /* Selection management */
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

  function addAgentTask(taskId: string, action: string, steps: string[]) {
    const t = ensureTask(taskId)
    const id = `agent-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`
    t.agentTasks.push({
      id, action, status: 'queued',
      steps: steps.map(s => ({ description: s, status: 'pending' as const })),
      progress: 0, message: '', createdAt: new Date().toISOString(),
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

  async function triggerArchAnalysis(taskId: string, edgeType: string, level: string, modelId?: string, projectId?: string, force = false) {
    const t = ensureTask(taskId)
    const idx = t.agentTasks.length
    addAgentTask(taskId, 'analyze', ['架构分析准备中...'])
    t.agentTasks[idx].status = 'running'

    try {
      // 前置条件：确保项目摘要已生成（后端依赖）
      const pid = projectId || (() => {
        try {
          const analysisStore = useAnalysisStore()
          return analysisStore.tasks.find(t => t.id === taskId)?.projectId || ''
        } catch { return '' }
      })()

      if (pid && isLLMConfigured()) {
        try {
          const summaryResult = await ipc.report.generateProjectSummary({ projectId: pid })
          if (summaryResult?.summary) {
            t.projectContext = `## 项目概要\n${summaryResult.summary}`
          }
        } catch { /* non-blocking */ }
      }

      const result = await ipc.analysis.startArchAnalysis({ taskId, edgeType, level, modelId, force: force || undefined })
      if (result.success && result.agentTaskId) {
        cancelAgentPolling(taskId)
        t.agentTasks[idx].id = result.agentTaskId
        const msg = result.skipped
          ? `社区数: ${result.communities}（跳过 ${result.skipped} 个已分析）`
          : `社区数: ${result.communities}`
        updateAgentTask(taskId, idx, { status: 'running', progress: 0, message: msg })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || '启动失败' })
      }
      return result
    } catch (e: any) {
      updateAgentTask(taskId, idx, { status: 'failed', message: e?.message || 'unknown error' })
      throw e
    }
  }

  function parseArchCommand(input: string): { action: string; args: Record<string, string> } | null {
    const trimmed = input.trim()
    if (!trimmed.startsWith('/arch ') && !trimmed.startsWith('/analyze ') &&
        !trimmed.startsWith('/track ') && !trimmed.startsWith('/diff ')) return null
    const parts = trimmed.slice(1).split(/\s+/)
    const action = parts[0] as string
    const VALID_FLAGS: Record<string, string[]> = {
      analyze: ['level', 'model-id', 'edge-type', 'force'],
      track: ['tag'],
      diff: ['from', 'to'],
    }
    const args: Record<string, string> = {}
    for (let i = 1; i < parts.length; i++) {
      if (parts[i].startsWith('--')) {
        const key = parts[i].slice(2)
        const valid = VALID_FLAGS[action]
        if (valid && !valid.includes(key)) {
          return null
        }
        const val = parts[i + 1] && !parts[i + 1].startsWith('--') ? parts[++i] : 'true'
        args[key] = val
      }
    }
    return { action, args }
  }

  /* ---- Snapshot management ---- */

  function setTimeline(taskId: string, entries: TimelineEntry[]) {
    const t = ensureTask(taskId)
    t.timeline = entries
  }

  function setCompareMode(taskId: string, active: boolean, from?: string, to?: string) {
    const t = ensureTask(taskId)
    t.compareActive = active
    t.compareFrom = from || ''
    t.compareTo = to || ''
  }

  async function triggerComponentAnalysis(taskId: string | null, components: ComponentRef[], language = '', concurrency = 1, agentic = false, maxTurns = 30, summaryModelId = '', subagentConcurrency = 1, analysisMode = 'quick', force = false) {
    if (!taskId || !components.length) return
    const t = ensureTask(taskId)
    const steps = components.map(c => `分析组件: ${c.name} (${c.type === 'community' ? '社区' : '外部包'})`)
    const idx = t.agentTasks.length
    const actionLabel = agentic ? 'agentic_analyze_components' : 'analyze_components'
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
          ? `组件数: ${components.length}（跳过 ${result.skipped} 个已分析）`
          : `组件数: ${components.length}`
        updateAgentTask(taskId, idx, { status: 'running', progress: 0, message: msg })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || '启动失败' })
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

    console.log('[poll] register taskId=%s agent=%s idx=%d key=%s', taskId, agentTaskId, taskIdx, controlKey)

    let lastDoneCount = 0
    controlDispatcher.register(controlKey, {
      interval: 1500,
      fetcher: () => ipc.analysis.getAgentProgress({ agentTaskId }),
      onData: (progress) => {
        if (!progress.found) return
        const t = tasks.value[taskId]
        if (!t || !t.agentTasks[taskIdx]) {
          controlDispatcher.unregister(controlKey)
          return
        }
        const fileCurrent = progress.file_current || 0
        const fileTotal = progress.file_total || 0
        const stepCurrent = progress.step_current || 0
        const stepTotal = progress.step_total || 0
        const pct = fileTotal ? Math.round(fileCurrent / fileTotal * 100) : (stepTotal ? Math.round(stepCurrent / stepTotal * 100) : 0)
        const allStepsDone = progress.steps && progress.steps.length > 0 &&
          progress.steps.every(s => s.status === 'done' || s.status === 'failed')
        const isCompleted = progress.status === 'completed' || progress.status === 'partial' ||
          progress.status === 'failed' || progress.status === 'cancelled' ||
          ((fileTotal ? (fileCurrent >= fileTotal) : (stepCurrent >= stepTotal)) && pct === 100 && allStepsDone)
        const msg = (!progress.message && stepTotal === 0 && stepCurrent === 0)
          ? '正在启动…' : (progress.message || '')
        updateAgentTask(taskId, taskIdx, {
          status: isCompleted
            ? (progress.status === 'failed' ? 'failed' :
               progress.status === 'cancelled' ? 'cancelled' : 'completed')
            : (progress.status || 'running'),
          progress: pct,
          message: msg,
        })
        if (progress.status && stepTotal > 0) {
          console.log('[poll] agent=%s status=%s step=%d/%d pct=%d', agentTaskId, progress.status, stepCurrent, stepTotal, pct)
        }
        if (progress.steps) {
          const doneCount = progress.steps.filter(s => s.status === 'done').length
          if (doneCount > lastDoneCount && taskId) {
            lastDoneCount = doneCount
            const pid = useProjectStore().selectedProjectId
            if (pid) loadCommunities(taskId, pid).catch(() => {})
          }
          const agent = t.agentTasks[taskIdx]
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
            updateAgentStep(taskId, taskIdx, i + stepOffset, runtimeSteps[i].status, runtimeSteps[i].file_count || 1)
          }
        }
        if (isCompleted) {
          controlDispatcher.unregister(controlKey)
          if (progress.status !== 'failed' && progress.status !== 'cancelled' && taskId) {
            const pid = useProjectStore().selectedProjectId
            if (pid) loadCommunities(taskId, pid).catch(() => {})
          }
        }
      },
      onError: () => {
        controlDispatcher.unregister(controlKey)
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

  async function loadAgentTaskHistory(taskId: string, offset = 0, limit = 10) {
    try {
      const resp = await ipc.analysis.getAgentTaskHistory({ taskId, offset, limit })
      agentTaskHistoryTotal.value[taskId] = resp.total
      return resp.results || []
    } catch { return [] }
  }

  async function clearAgentTaskHistory(taskId: string) {
    try {
      await ipc.analysis.clearAgentTaskHistory({ taskId })
      agentTaskHistoryOffset.value[taskId] = 0
      agentTaskHistoryTotal.value[taskId] = 0
      const t = tasks.value[taskId]
      if (t) t.agentTasks = t.agentTasks.filter(at => at.status === 'running' || at.status === 'queued')
      return true
    } catch { return false }
  }

  function ensureAgentPolling(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    for (let i = 0; i < t.agentTasks.length; i++) {
      const at = t.agentTasks[i]
      if (at.status === 'running' && at.id) {
        const controlKey = `agent-progress:${taskId}:${at.id}`
        if (!controlDispatcher.has(controlKey)) {
          console.log('[ensurePolling] starting poll for agent=%s idx=%d', at.id, i)
          _pollAgentProgress(taskId, i, at.id, 0)
        }
      }
    }
  }

  async function cancelAgentTask(taskId: string, agentTaskId: string) {
    try {
      await ipc.analysis.cancelAgentTask({ agentTaskId })
      const t = tasks.value[taskId]
      if (t) {
        // 取消当前 agent
        const idx = t.agentTasks.findIndex(at => at.id === agentTaskId)
        if (idx >= 0) updateAgentTask(taskId, idx, { status: 'cancelled' })
        // 额外取消同任务下所有 presummary_files 类型的 agent（管线场景）
        for (const at of t.agentTasks) {
          if (at.id !== agentTaskId && at.action === 'presummary_files' && (at.status === 'running' || at.status === 'queued')) {
            try { await ipc.analysis.cancelAgentTask({ agentTaskId: at.id }) } catch {}
            at.status = 'cancelled'
            const ck = `agent-progress:${taskId}:${at.id}`
            if (controlDispatcher.has(ck)) controlDispatcher.unregister(ck)
          }
        }
      }
      // 立即停止轮询
      const controlKey = `agent-progress:${taskId}:${agentTaskId}`
      if (controlDispatcher.has(controlKey)) controlDispatcher.unregister(controlKey)
    } catch {}
  }

  // ── 预摘要 ──
  async function getPreSummaryStatus(taskId: string) {
    return await ipc.analysis.getPreSummaryStatus({ taskId })
  }
  async function listPreSummaryFiles(taskId: string, batch = 'P0', page = 1, pageSize = 20) {
    return await ipc.analysis.listPreSummaryFiles({ taskId, batch, page, page_size: pageSize })
  }
  async function startPreSummary(taskId: string, batch = 'P0', limit = 0, subagentConcurrency = 1) {
    const t = ensureTask(taskId)
    const conc = Math.max(1, Math.min(10, subagentConcurrency))
    const concHint = conc > 1 ? ` (并发 ${conc})` : ''
    const stepDesc = `${limit > 0 ? `预摘要 ${batch} (限 ${limit} 个文件)` : `预摘要 ${batch}`}${concHint}`
    const idx = t.agentTasks.length
    addAgentTask(taskId, 'presummary_files', [stepDesc, '等待 LLM 分析完成'])
    t.agentTasks[idx].status = 'running'

    try {
      const result = await ipc.analysis.startPreSummary({ taskId, batch, limit, subagentConcurrency: conc })
      if (result.allCached) {
        t.agentTasks.splice(idx, 1)
        return result
      }
      if (result.success && result.agentTaskId) {
        t.agentTasks[idx].id = result.agentTaskId
        updateAgentTask(taskId, idx, { progress: 0, message: `文件数: ${result.fileCount || 0}` })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || '启动失败' })
      }
      return result
    } catch (e: any) {
      updateAgentTask(taskId, idx, { status: 'failed', message: e?.message || 'unknown error' })
      throw e
    }
  }
  async function startPreSummaryPipeline(taskId: string, batches: string[], limit = 0, subagentConcurrency = 1) {
    const t = ensureTask(taskId)
    const conc = Math.max(1, Math.min(10, subagentConcurrency))
    const concHint = conc > 1 ? ` (并发 ${conc})` : ''
    const stepDesc = `预摘要 ${batches.join('→')} (${batches.length} 批次${concHint})`

    // 清除同任务下旧的 presummary_files agent（防止重复卡片）
    const stale = (t.agentTasks || []).filter(a =>
      a.action === 'presummary_files' && (a.status === 'running' || a.status === 'queued')
    )
    for (const s of stale) {
      const controlKey = `agent-progress:${taskId}:${s.id}`
      if (controlDispatcher.has(controlKey)) controlDispatcher.unregister(controlKey)
      s.status = 'cancelled'
    }

    const idx = t.agentTasks.length
    addAgentTask(taskId, 'presummary_files', [stepDesc, '等待 LLM 分析完成'])
    t.agentTasks[idx].status = 'running'

    try {
      console.log('[pipeline] calling startPreSummaryPipeline taskId=%s batches=%o limit=%d conc=%d', taskId, batches, limit, conc)
      const result = await ipc.analysis.startPreSummaryPipeline({ taskId, batches, limit, subagentConcurrency: conc })
      console.log('[pipeline] response success=%s agentTaskId=%s fileCount=%s', result.success, result.agentTaskId, result.fileCount)
      if (result.success && result.agentTaskId) {
        t.agentTasks[idx].id = result.agentTaskId
        updateAgentTask(taskId, idx, { progress: 0, message: `文件数: ${result.fileCount || 0}` })
        _pollAgentProgress(taskId, idx, result.agentTaskId, 0)
        console.log('[pipeline] polling started for agent=%s idx=%d', result.agentTaskId, idx)
      } else {
        console.log('[pipeline] no agentTaskId returned, keeping placeholder for history poll')
        updateAgentTask(taskId, idx, { status: 'running', progress: 0, message: `全缓存，等待后续批次…` })
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
  async function deleteFileSummary(taskId: string, filePath: string) {
    return await ipc.analysis.deleteFileSummary({ taskId, file_path: filePath })
  }
  async function rerunFileSummary(taskId: string, filePath: string) {
    return await ipc.analysis.rerunFileSummary({ taskId, file_path: filePath })
  }

  return {
    tasks, communitySelections,
    ensureTask, getSelections, setSelections, clearSelections,
    listCommunityResults, getCascadeLevels, saveCommunityResult,
    loadCommunities, loadCommunitiesFromDashboard, loadProjectContext, loadExternalStats, loadCrossCommunityEdges, loadCommunityNodeLists, loadFileDetail, getCrossEdges, analyzeSelected, runTask, stopAnalysis, retryTask,
    toggleSelect, selectAll, selectIncomplete, deselectAll, syncSelections, restoreSelections,
    pushError, clearErrorLogs, clearTask,
    addAgentTask, updateAgentTask, updateAgentStep, triggerArchAnalysis, triggerComponentAnalysis, parseArchCommand,
    setTimeline, setCompareMode,
    loadAgentTaskHistory, clearAgentTaskHistory, agentTaskHistoryOffset, agentTaskHistoryTotal,
    cancelAgentPolling, cancelAgentTask, ensureAgentPolling,
    getPreSummaryStatus, listPreSummaryFiles, startPreSummary, startPreSummaryPipeline,
    getFileSummary, deleteFileSummary, rerunFileSummary,
  }
})
