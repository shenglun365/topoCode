import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import type { ExternalStatsResult, CrossCommunityEdge, CrossCommunityEdgesResult } from '@/types/ipc'

export interface CommunityItem {
  id: string
  communityId: string
  level: string
  edgeType: string
  nodeCount: number
  fileCount: number
  edgeCount: number
  qualityScore: number | null
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
}

function normalizeDiagramField(val: unknown): string {
  if (!val) return ''
  if (typeof val === 'string') return val
  if (typeof val === 'object') return (val as Record<string, any>).content || (val as Record<string, any>).code || JSON.stringify(val) || ''
  return String(val)
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
    }
  }

  /** 从 getReportDashboard 合并响应中加载社区数据（一次 RPC 替代 4 次独立调用） */
  async function loadCommunitiesFromDashboard(taskId: string, dash: any) {
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
      t.communities = communities
      t.llmResults = llmMap
      const pid = dash.task?.project_id || dash.task?.projectId
      if (pid) loadProjectContext(taskId, pid)
    } catch (e: any) {
      pushError(taskId, `loadCommunitiesFromDashboard: ${e?.message || String(e)}`)
    }
  }

  async function loadProjectContext(taskId: string, projectId: string) {
    if (!projectId) return
    try {
      const result = await ipc.report.getProjectSummary({ projectId })
      if (result?.summary) {
        ensureTask(taskId).projectContext = `## 项目概要\n${result.summary}`
      }
    } catch { /* skip */ }
  }

  async function loadExternalStats(taskId: string) {
    try {
      const result = await ipc.analysis.getExternalStats(taskId)
      if (result) {
        ensureTask(taskId).externalStats = result
      }
    } catch (e: any) {
      console.warn('[community-store] loadExternalStats failed:', e?.message || e)
    }
  }

  async function loadCrossCommunityEdges(taskId: string, edgeType: string, commLv: string) {
    const t = ensureTask(taskId)
    try {
      const result = await ipc.analysis.getCrossCommunityEdges({ taskId, edgeType, commLv })
      if (result?.crossEdges) {
        if (!t.crossCommunityEdges[edgeType]) {
          t.crossCommunityEdges[edgeType] = {}
        }
        t.crossCommunityEdges[edgeType][commLv] = result.crossEdges
      }
    } catch (e: any) {
      console.warn('[community-store] loadCrossCommunityEdges failed:', e?.message || e)
    }
  }

  function getCrossEdges(taskId: string, edgeType: string, commLv: string): CrossCommunityEdge[] {
    return tasks.value[taskId]?.crossCommunityEdges?.[edgeType]?.[commLv] || []
  }

  async function loadCommunityNodeLists(taskId: string, edgeType: string, commLv: string) {
    const t = ensureTask(taskId)
    if (t.nodeLists[edgeType]?.[commLv]) return
    try {
      const result = await ipc.analysis.getCommunityNodeLists({ taskId, edgeType, commLv })
      if (result) {
        if (!t.nodeLists[edgeType]) t.nodeLists[edgeType] = {}
        t.nodeLists[edgeType][commLv] = result
      }
    } catch (e: any) {
      console.warn('[community-store] loadCommunityNodeLists failed:', e?.message || e)
    }
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

  return {
    tasks, communitySelections,
    ensureTask, getSelections, setSelections, clearSelections,
    listCommunityResults, getCascadeLevels, saveCommunityResult,
    loadCommunities, loadCommunitiesFromDashboard, loadProjectContext, loadExternalStats, loadCrossCommunityEdges, loadCommunityNodeLists, getCrossEdges, analyzeSelected, runTask, stopAnalysis, retryTask,
    toggleSelect, selectAll, selectIncomplete, deselectAll, syncSelections, restoreSelections,
    pushError, clearErrorLogs, clearTask,
  }
})
