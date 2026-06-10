import { defineStore } from 'pinia'
import { useCommunityStore } from './community-store'
import { ipc } from '@/services/ipc'
import type { CommunityItem, ChildAnalysisState } from './community-store'

export const useChildAnalysisStore = defineStore('childAnalysis', () => {
  const communityStore = useCommunityStore()

  function buildChildStateKey(parentLevel: string, parentCommId: string, edgeType: string): string {
    return `${parentLevel}|${parentCommId}|${edgeType}`
  }

  function ensureChildState(taskId: string, parentLevel: string, parentCommId: string, edgeType: string): ChildAnalysisState {
    const t = communityStore.ensureTask(taskId)
    const key = buildChildStateKey(parentLevel, parentCommId, edgeType)
    if (!t.analysisStates[key]) {
      t.analysisStates[key] = { running: false, paused: false, communities: [], errorLogs: [], level: `L${parseInt(parentLevel[1]) + 1}`, parentCommId, edgeType }
    }
    return t.analysisStates[key]
  }

  async function loadChildCommunities(taskId: string, parentLevel: string, parentCommId: string, edgeType: string) {
    const state = ensureChildState(taskId, parentLevel, parentCommId, edgeType)
    const childLevel = state.level
    try {
      const [levelsResults, results] = await Promise.all([
        ipc.analysis.getCascadeLevels(taskId, edgeType).catch(() => null),
        ipc.analysis.listCommunityResults(taskId, edgeType).catch(() => ({ results: [] })),
      ])
      const llmMap: Record<string, unknown> = {}
      for (const rRaw of (results?.results || [])) { const r = rRaw as Record<string, unknown>; const id = (r.commId || r.comm_id) as string | undefined; if (id) llmMap[id] = r }
      const communities: CommunityItem[] = []
      const seenIds = new Set<string>()
      if (levelsResults?.levels) {
        for (const lv of levelsResults.levels) {
          if (lv.lv !== childLevel || !lv.items) continue
          for (const item of lv.items) {
            if (item.parentCommId !== parentCommId || seenIds.has(item.id)) continue
            seenIds.add(item.id)
            const saved = llmMap[item.id] as Record<string, unknown> | undefined
            communities.push({
              id: `${edgeType}-${item.id}`, communityId: item.id, level: lv.lv, edgeType,
              nodeCount: item.nodeCount || 0, fileCount: item.fileCount || 0, edgeCount: item.edgeCount || 0, qualityScore: item.qualityScore ?? null,
              status: saved ? 'completed' : 'pending' as CommunityItem['status'], selected: false,
              parentId: item.parentCommId ?? undefined,
              name: (saved?.name as string) || item.id, summary: (saved?.summary as string) || undefined,
              mermaid: saved?.mermaid as string | undefined, plantuml: saved?.plantuml as string | undefined,
            })
          }
        }
      }
      state.communities = communities
    } catch { /* skip */ }
  }

  async function analyzeChildSelected(taskId: string, stateKey: string, modelId: string, batchSize: number, projectId: string): Promise<unknown[]> {
    const t = communityStore.tasks[taskId]
    if (!t) return []
    const state = t.analysisStates[stateKey]
    if (!state || state.running || state.paused) return []
    const selected = state.communities.filter(c => c.selected)
    if (selected.length === 0) return []
    state.running = true; state.paused = false
    for (let i = 0; i < selected.length; i += batchSize) {
      if (state.paused) break
      const batch = selected.slice(i, i + batchSize)
      batch.forEach(c => { c.status = 'queued' })
      const results = await Promise.allSettled(batch.map(c => communityStore.runTask(taskId, c, modelId, projectId)))
      for (let idx = 0; idx < batch.length; idx++) {
        const c = batch[idx]; const r = results[idx]
        if (r.status === 'rejected') { c.status = 'error'; c.error = r.reason?.message || String(r.reason) }
        if (c.status === 'completed') {
          c.selected = false
          try {
            await ipc.analysis.saveCommunityResult({ taskId, edgeType: c.edgeType, commLv: c.level, commId: c.communityId, name: c.name || c.communityId, summary: c.summary || '', mermaid: c.mermaid || '', plantuml: c.plantuml || '', modelId, templateId: 'community_analyze' })
            if (t.llmResults) t.llmResults[c.communityId] = { comm_id: c.communityId, name: c.name, summary: c.summary }
          } catch { /* skip */ }
        }
      }
    }
    state.running = false
    return state.communities.filter(c => c.status === 'completed' && c.name).map(c => ({ communityId: c.communityId, level: c.level, edgeType: c.edgeType, name: c.name!, summary: c.summary!, mermaid: c.mermaid, plantuml: c.plantuml }))
  }

  function toggleChildSelect(taskId: string, stateKey: string, commId: string) {
    const t = communityStore.tasks[taskId]; if (!t) return
    const state = t.analysisStates[stateKey]; if (!state || state.running) return
    const comm = state.communities.find(c => c.communityId === commId)
    if (comm) comm.selected = !comm.selected
  }

  function selectChildIncomplete(taskId: string, stateKey: string) {
    const t = communityStore.tasks[taskId]; if (!t) return
    const state = t.analysisStates[stateKey]; if (!state) return
    for (const c of state.communities) { if (c.status !== 'completed') c.selected = true }
  }

  function deselectAllChild(taskId: string, stateKey: string) {
    const t = communityStore.tasks[taskId]; if (!t) return
    const state = t.analysisStates[stateKey]; if (!state) return
    for (const c of state.communities) c.selected = false
  }

  async function retryChildTask(taskId: string, stateKey: string, commId: string, modelId: string, projectId: string): Promise<boolean> {
    const t = communityStore.tasks[taskId]; if (!t) return false
    const state = t.analysisStates[stateKey]; if (!state) return false
    const community = state.communities.find(c => c.communityId === commId); if (!community) return false
    community.status = 'pending'; community.error = undefined; community.selected = false; community.name = undefined; community.summary = undefined; community.status = 'running'
    try {
      const ok = await communityStore.runTask(taskId, community, modelId, projectId)
      if (ok && (community as any).status === 'completed') {
        await ipc.analysis.saveCommunityResult({ taskId, edgeType: community.edgeType, commLv: community.level, commId: community.communityId, name: community.name || community.communityId, summary: community.summary || '', mermaid: community.mermaid || '', plantuml: community.plantuml || '', modelId, templateId: 'community_analyze' })
      }
      return ok
    } catch (e: unknown) { community.status = 'error'; community.error = e instanceof Error ? (e as Error).message : String(e); return false }
  }

  function stopChildAnalysis(taskId: string, stateKey: string) {
    const t = communityStore.tasks[taskId]; if (!t) return
    const state = t.analysisStates[stateKey]
    if (state) { state.paused = true; state.running = false }
  }

  function pushChildError(taskId: string, stateKey: string, msg: string) {
    const t = communityStore.tasks[taskId]; if (!t) return
    const state = t.analysisStates[stateKey]; if (!state) return
    state.errorLogs.unshift(msg); if (state.errorLogs.length > 50) state.errorLogs.length = 50
  }

  function clearChildErrorLogs(taskId: string, stateKey: string) {
    const t = communityStore.tasks[taskId]; if (!t) return
    const state = t.analysisStates[stateKey]; if (state) state.errorLogs = []
  }

  return {
    buildChildStateKey, ensureChildState,
    loadChildCommunities, analyzeChildSelected,
    toggleChildSelect, selectChildIncomplete, deselectAllChild,
    retryChildTask, stopChildAnalysis,
    pushChildError, clearChildErrorLogs,
  }
})
