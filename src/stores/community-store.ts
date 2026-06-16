import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import { isLLMConfigured } from '@/services/llmClient'
import { useAnalysisStore } from '@/stores/analysis'
import type { ExternalStatsResult, CrossCommunityEdge, CrossCommunityEdgesResult, TimelineEntry } from '@/types/ipc'

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
  mermaid?: string
  plantuml?: string
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

function normalizeDiagramField(val: unknown): string {
  if (!val) return ''
  if (typeof val === 'string') return val
  if (typeof val === 'object') return (val as Record<string, any>).content || (val as Record<string, any>).code || JSON.stringify(val) || ''
  return String(val)
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
    name?: string; summary?: string; mermaid?: string; plantuml?: string;
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
              existing.mermaid = saved.mermaid || undefined
              existing.plantuml = saved.plantuml || undefined
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
            c.mermaid = saved.mermaid || undefined
            c.plantuml = saved.plantuml || undefined
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

  async function loadExternalStats(taskId: string) {
    const t = ensureTask(taskId)
    if (t.externalStats) return

    const key = _inflightKey(taskId, 'externalStats')
    const existing = _inflightLoads.get(key)
    if (existing) return existing

    const promise = (async () => {
      try {
        const result = await ipc.analysis.getExternalStats(taskId)
        if (result) {
          ensureTask(taskId).externalStats = result
        }
      } catch (e: any) {
        console.warn('[community-store] loadExternalStats failed:', e?.message || e)
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
              mermaid: c.mermaid || '', plantuml: c.plantuml || '',
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
        name: c.name!, summary: c.summary!, mermaid: c.mermaid, plantuml: c.plantuml,
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
        outputSchema: { type: 'object', properties: { name: { type: 'string', maxLength: 20 }, summary: { type: 'string' }, mermaid: { type: 'string' }, plantuml: { type: 'string' } }, required: ['name', 'summary', 'mermaid'] },
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
              community.mermaid = normalizeDiagramField(data.structured.mermaid)
              community.plantuml = normalizeDiagramField(data.structured.plantuml)
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
        await ipc.analysis.saveCommunityResult({ taskId, edgeType: community.edgeType, commLv: community.level, commId: community.communityId, name: community.name || community.communityId, summary: community.summary || '', mermaid: community.mermaid || '', plantuml: community.plantuml || '', modelId, templateId: 'community_analyze' })
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

  function updateAgentStep(taskId: string, taskIdx: number, stepIdx: number, status: string) {
    const t = tasks.value[taskId]; if (!t || !t.agentTasks[taskIdx]) return
    const steps = t.agentTasks[taskIdx].steps
    if (steps[stepIdx]) steps[stepIdx].status = status as any
  }

  async function triggerArchAnalysis(taskId: string, edgeType: string, level: string, modelId?: string, projectId?: string) {
    const STEPS = {
      SUMMARY: 0,
      LOAD_COMMS: 1,
      ANALYZE: 2,
      OVERVIEW: 3,
      PERSIST: 4,
    }
    const steps = [
      '生成项目摘要',
      `加载社区列表 (${level}, ${edgeType})`,
      'LLM 分析社区',
      '生成架构概览文档',
      '持久化分析结果',
    ]
    const t = ensureTask(taskId)
    const idx = t.agentTasks.length
    addAgentTask(taskId, 'analyze', steps)
    t.agentTasks[idx].status = 'running'

    try {
      // Step 0: 生成项目摘要（复用 README + 依赖文件上下文）
      updateAgentStep(taskId, idx, STEPS.SUMMARY, 'running')

      const pid = projectId || (() => {
        try {
          const analysisStore = useAnalysisStore()
          return analysisStore.tasks.find(t => t.id === taskId)?.projectId || ''
        } catch { return '' }
      })()

      if (pid) {
        if (!isLLMConfigured()) {
          updateAgentStep(taskId, idx, STEPS.SUMMARY, 'failed')
          pushError(taskId, '生成项目摘要: LLM 模型未配置，跳过')
        } else {
          try {
            const summaryResult = await ipc.report.generateProjectSummary({ projectId: pid })
            if (summaryResult?.summary) {
              updateAgentStep(taskId, idx, STEPS.SUMMARY, 'done')
              t.projectContext = `## 项目概要\n${summaryResult.summary}`
            } else {
              updateAgentStep(taskId, idx, STEPS.SUMMARY, 'failed')
              pushError(taskId, '生成项目摘要: LLM 返回结果为空')
            }
          } catch (e: any) {
            updateAgentStep(taskId, idx, STEPS.SUMMARY, 'failed')
            pushError(taskId, `生成项目摘要: ${e?.message || '调用失败'}`)
          }
        }
      } else {
        updateAgentStep(taskId, idx, STEPS.SUMMARY, 'failed')
        pushError(taskId, '生成项目摘要: 未找到项目 ID')
      }

      const result = await ipc.analysis.startArchAnalysis({ taskId, edgeType, level, modelId })
      if (result.success && result.agentTaskId) {
        updateAgentTask(taskId, idx, { status: 'running', progress: 0, message: `社区数: ${result.communities}` })
        _pollAgentProgress(taskId, idx, result.agentTaskId, STEPS.LOAD_COMMS)
      } else {
        updateAgentTask(taskId, idx, { status: 'failed', message: result.error || '启动失败' })
      }
      return result
    } catch (e: any) {
      updateAgentTask(taskId, idx, { status: 'failed', message: e?.message || 'unknown error' })
      throw e
    }
  }

  function _pollAgentProgress(taskId: string, taskIdx: number, agentTaskId: string, stepOffset = 0) {
    const poll = setInterval(async () => {
      try {
        const progress = await ipc.analysis.getAgentProgress({ agentTaskId })
        if (!progress.found) return
        const t = tasks.value[taskId]
        if (!t || !t.agentTasks[taskIdx]) {
          clearInterval(poll)
          return
        }
        updateAgentTask(taskId, taskIdx, {
          status: progress.status || 'running',
          progress: progress.step_total ? Math.round((progress.step_current || 0) / (progress.step_total || 1) * 100) : 0,
          message: progress.message || '',
        })
        if (progress.steps) {
          for (let i = 0; i < progress.steps.length; i++) {
            updateAgentStep(taskId, taskIdx, i + stepOffset, progress.steps[i].status)
          }
        }
        if (progress.status === 'completed' || progress.status === 'partial' ||
            progress.status === 'failed' || progress.status === 'cancelled') {
          clearInterval(poll)
        }
      } catch {
        clearInterval(poll)
      }
    }, 1500)
  }

  function parseArchCommand(input: string): { action: string; args: Record<string, string> } | null {
    const trimmed = input.trim()
    if (!trimmed.startsWith('/arch ') && !trimmed.startsWith('/analyze ') &&
        !trimmed.startsWith('/track ') && !trimmed.startsWith('/diff ')) return null
    const parts = trimmed.slice(1).split(/\s+/)
    const action = parts[0] as string
    const args: Record<string, string> = {}
    for (let i = 1; i < parts.length; i++) {
      if (parts[i].startsWith('--')) {
        const key = parts[i].slice(2)
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

  return {
    tasks, communitySelections,
    ensureTask, getSelections, setSelections, clearSelections,
    listCommunityResults, getCascadeLevels, saveCommunityResult,
    loadCommunities, loadCommunitiesFromDashboard, loadProjectContext, loadExternalStats, loadCrossCommunityEdges, loadCommunityNodeLists, loadFileDetail, getCrossEdges, analyzeSelected, runTask, stopAnalysis, retryTask,
    toggleSelect, selectAll, selectIncomplete, deselectAll, syncSelections, restoreSelections,
    pushError, clearErrorLogs, clearTask,
    addAgentTask, updateAgentTask, updateAgentStep, triggerArchAnalysis, parseArchCommand,
    setTimeline, setCompareMode,
  }
})
