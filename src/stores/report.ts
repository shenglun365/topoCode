import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import type { PipelineTaskNode } from '@/types/ipc'
import { useSettingsStore } from '@/stores/settings'
import { useProjectStore } from '@/stores/project'

export interface CommunityItem {
  id: string
  communityId: string
  level: string
  edgeType: string
  nodeCount: number
  edgeCount: number
  qualityScore: number | null
  status: 'pending' | 'queued' | 'running' | 'completed' | 'error' | 'skipped'
  selected: boolean
  parentId?: string
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

interface ReportTaskRuntime {
  pipelineRunning: boolean
  pipelinePaused: boolean
  pipelineRootTask: PipelineTaskNode | null
  pipelineProgress: number
  pendingStepRun: string | null
  communityRunning: boolean
  communityPaused: boolean
  communities: CommunityItem[]
  projectContext: string
  llmResults: Record<string, any>
  errorLogs: string[]
  analysisStates: Record<string, ChildAnalysisState>
}

function normalizeDiagramField(val: any): string {
  if (!val) return ''
  if (typeof val === 'string') return val
  if (typeof val === 'object') {
    return val.content || val.code || JSON.stringify(val) || ''
  }
  return String(val)
}

export const useReportStore = defineStore('report', () => {
  const generatedReports = ref<Record<string, string>>({})
  const dbReportExists = ref<Record<string, boolean>>({})
  const loading = ref<Record<string, boolean>>({})

  // === Per-task runtime state (new) ===
  const tasks = ref<Record<string, ReportTaskRuntime>>({})

  function ensureTask(taskId: string): ReportTaskRuntime {
    if (!tasks.value[taskId]) {
      tasks.value[taskId] = {
        pipelineRunning: false,
        pipelinePaused: false,
        pipelineRootTask: null,
        pipelineProgress: 0,
        pendingStepRun: null,
        communityRunning: false,
        communityPaused: false,
        communities: [],
        projectContext: '',
        llmResults: {},
        errorLogs: [],
        analysisStates: {},
      }
    }
    return tasks.value[taskId]
  }

  function setGeneratedReport(taskId: string, content: string) {
    generatedReports.value = { ...generatedReports.value, [taskId]: content }
    dbReportExists.value = { ...dbReportExists.value, [taskId]: true }
  }

  async function checkReportExists(taskId: string) {
    try {
      const docs = await ipc.report.listSubDocs({ taskId, commId: 'overall' })
      dbReportExists.value = { ...dbReportExists.value, [taskId]: !!(docs?.length) }
    } catch {
      dbReportExists.value = { ...dbReportExists.value, [taskId]: false }
    }
  }

  // === IPC encapsulation ===
  async function getReadmeContent(projectId: string) {
    return await ipc.report.getReadmeContent({ projectId })
  }

  async function extractDependencyFiles(projectId: string) {
    return await ipc.report.extractDependencyFiles({ projectId })
  }

  async function generateProjectSummary(projectId: string) {
    return await ipc.report.generateProjectSummary({ projectId })
  }

  async function getProjectSummary(projectId: string) {
    return await ipc.report.getProjectSummary({ projectId })
  }

  async function getLevelCommunityDetail(params: { projectId: string; taskId: string; level?: string; edgeType?: string }) {
    return await ipc.report.getLevelCommunityDetail(params)
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
    try {
      JSON.stringify(params)
    } catch (e) {
      console.error(`[reportStore] saveCommunityResult params NOT JSON-serializable:`, e, JSON.stringify(Object.keys(params)), `mermaidLen=${(params.mermaid||'').length} plantumlLen=${(params.plantuml||'').length} summaryLen=${(params.summary||'').length}`)
      for (const [k, v] of Object.entries(params)) {
        try { JSON.stringify(v) } catch (e2) { console.error(`[reportStore] saveCommunityResult field ${k} not serializable:`, typeof v, e2) }
      }
      return { success: false }
    }
    return await ipc.analysis.saveCommunityResult(params)
  }

  function updateCommunityName(taskId: string, edgeType: string, commLv: string, commId: string, name: string) {
    return ipc.analysis.updateCommunityName({ taskId, edgeType, commLv, commId, name })
  }

  async function getSubDoc(subDocId: string) {
    return await ipc.report.getSubDoc(subDocId)
  }

  async function updateSubDoc(params: { subDocId: string; title?: string; content?: string }) {
    return await ipc.report.updateSubDoc(params)
  }

  async function createSubDoc(params: { taskId: string; edgeType?: string; commId?: string; title: string; content: string; templateId?: string }) {
    return await ipc.report.createSubDoc(params)
  }

  async function getFileSummaries(params: { projectId: string; taskId?: string; source?: string }) {
    return await ipc.report.getFileSummaries(params)
  }

  async function saveFileSummaries(params: { projectId: string; taskId: string; summaries: Array<{ filePath: string; summary: string; source?: string }> }) {
    return await ipc.report.saveFileSummaries(params)
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

  // ============================================================
  // === Community Analysis Actions (new)                      ===
  // ============================================================

  async function loadCommunities(taskId: string, projectId: string) {
    const t = ensureTask(taskId)
    console.log(`[reportStore] loadCommunities ENTRY taskId=${taskId} projectId=${projectId} existingCommunities=${t.communities.length}`)
    try {
      const [callLevels, depLevels, callResults, depResults] = await Promise.all([
        getCascadeLevels(taskId, 'CALL').catch(() => null),
        getCascadeLevels(taskId, 'INCLUDE').catch(() => null),
        listCommunityResults(taskId, 'CALL').catch(() => ({ results: [] })),
        listCommunityResults(taskId, 'INCLUDE').catch(() => ({ results: [] })),
      ])
      console.log(`[reportStore] loadCommunities IPC results: callLevels=${callLevels?.levels?.length ?? 'null'} depLevels=${depLevels?.levels?.length ?? 'null'} callResults=${callResults?.results?.length ?? 0} depResults=${depResults?.results?.length ?? 0}`)
      const llmMap: Record<string, any> = {}
      for (const r of [...(callResults?.results || []), ...(depResults?.results || [])]) {
        llmMap[r.comm_id] = r
      }
      console.log(`[reportStore] loadCommunities llmMap keys=${Object.keys(llmMap).length}`)
      const communities: CommunityItem[] = []
      if (callLevels?.levels) {
        for (const lv of callLevels.levels) {
          if (!lv.items) continue
          for (const item of lv.items) {
            const comm: CommunityItem = {
              id: `CALL-${item.id}`,
              communityId: item.id,
              level: lv.lv,
              edgeType: 'CALL',
              nodeCount: item.nodeCount || 0,
              edgeCount: item.edgeCount || 0,
              qualityScore: item.qualityScore ?? null,
              status: 'pending',
              selected: false,
              parentId: item.parentCommId ?? undefined,
            }
            const saved = llmMap[item.id]
            if (saved) {
              comm.name = saved.name || item.id
              comm.summary = saved.summary || undefined
              comm.status = 'completed'
            }
            communities.push(comm)
          }
        }
      }
      if (depLevels?.levels) {
        for (const lv of depLevels.levels) {
          if (!lv.items) continue
          for (const item of lv.items) {
            const comm: CommunityItem = {
              id: `INCLUDE-${item.id}`,
              communityId: item.id,
              level: lv.lv,
              edgeType: 'INCLUDE',
              nodeCount: item.nodeCount || 0,
              edgeCount: item.edgeCount || 0,
              qualityScore: item.qualityScore ?? null,
              status: 'pending',
              selected: false,
              parentId: item.parentCommId ?? undefined,
            }
            const saved = llmMap[item.id]
            if (saved) {
              comm.name = saved.name || item.id
              comm.summary = saved.summary || undefined
              comm.status = 'completed'
            }
            communities.push(comm)
          }
        }
      }
      // 合并到现有数组，保留对象的引用不变（避免 analyzerSelected 中已捕获的引用失效）
      const savedIds = getSelections(taskId)
      const newCommMap = new Map(communities.map(c => [c.id, c]))
      let mergedExisting = 0, mergedNew = 0
      for (const existing of t.communities) {
        const newData = newCommMap.get(existing.id)
        if (newData) {
          // 保留运行中的状态，不覆盖
          if (existing.status === 'error' || existing.status === 'running' || existing.status === 'queued') {
            console.log(`[reportStore] loadCommunities preserve existing id=${existing.id} status=${existing.status}`)
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
          console.log(`[reportStore] loadCommunities merge existing id=${existing.id} edgeType=${existing.edgeType} level=${existing.level} status=${existing.status} selected=${savedIds.includes(existing.id)}`)
          existing.selected = savedIds.includes(existing.id)
          newCommMap.delete(existing.id)
          mergedExisting++
        }
      }
      // 新增的社区（旧数组中没有的）
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
        console.log(`[reportStore] loadCommunities add new id=${c.id} edgeType=${c.edgeType} level=${c.level} status=${c.status} selected=${c.selected}`)
        t.communities.push(c)
        mergedNew++
      }
      t.llmResults = llmMap
      console.log(`[reportStore] loadCommunities DONE mergedExisting=${mergedExisting} mergedNew=${mergedNew} total=${t.communities.length} savedIds=${savedIds.length}`)
      // Load project context
      loadProjectContext(taskId, projectId)
    } catch (e) {
      console.error('[reportStore] loadCommunities error:', e)
      pushError(taskId, `loadCommunities: ${(e as any)?.message || e}`)
    }
  }

  async function loadProjectContext(taskId: string, projectId: string) {
    if (!projectId) return
    try {
      const result = await getProjectSummary(projectId)
      if (result?.summary) {
        ensureTask(taskId).projectContext = `## 项目概要\n${result.summary}`
      }
    } catch (e) {
      console.warn('[reportStore] loadProjectContext failed:', e)
    }
  }

  async function analyzeSelected(taskId: string, modelId: string, batchSize: number, projectId: string): Promise<Array<{ communityId: string; level: string; edgeType: string; name: string; summary: string; mermaid?: string; plantuml?: string }>> {
    const t = ensureTask(taskId)
    if (t.communityRunning || t.communityPaused) {
      console.log(`[reportStore] analyzeSelected SKIP running=${t.communityRunning} paused=${t.communityPaused}`)
      return []
    }
    const selected = t.communities.filter(c => c.selected)
    if (selected.length === 0) {
      console.log(`[reportStore] analyzeSelected SKIP no selected communities`)
      return []
    }
    console.log(`[reportStore] analyzeSelected START taskId=${taskId} selected=${selected.length} batchSize=${batchSize} modelId=${modelId}`)

    t.communityRunning = true
    t.communityPaused = false

    for (let i = 0; i < selected.length; i += batchSize) {
      if (t.communityPaused) break
      const batch = selected.slice(i, i + batchSize)
      console.log(`[reportStore] analyzeSelected batch ${i / batchSize + 1}/${Math.ceil(selected.length / batchSize)} ids=${batch.map(c => c.communityId).join(',')}`)
      batch.forEach(c => { c.status = 'queued' })
      const results = await Promise.allSettled(batch.map(c => runTask(taskId, c, modelId, projectId)))
      for (let idx = 0; idx < batch.length; idx++) {
        const c = batch[idx]
        const r = results[idx]
        if (r.status === 'rejected') {
          c.status = 'error'
          c.error = r.reason?.message || String(r.reason)
          console.log(`[reportStore] analyzeSelected REJECTED id=${c.communityId} error=${c.error}`)
        }
        if (c.status === 'completed') {
          console.log(`[reportStore] analyzeSelected COMPLETED id=${c.communityId} name=${c.name}`)
          c.selected = false
          try {
            await saveCommunityResult({
              taskId, edgeType: c.edgeType, commLv: c.level, commId: c.communityId,
              name: c.name || c.communityId, summary: c.summary || '',
              mermaid: c.mermaid || '', plantuml: c.plantuml || '',
              modelId, templateId: 'community_analyze',
            })
            t.llmResults[c.communityId] = { comm_id: c.communityId, name: c.name, summary: c.summary }
            console.log(`[reportStore] analyzeSelected saved to DB id=${c.communityId}`)
          } catch (e) {
            console.warn('[reportStore] saveCommunityResult failed:', e)
          }
        }
      }
    }

    t.communityRunning = false
    console.log(`[reportStore] analyzeSelected DONE final completed=${t.communities.filter(c => c.status === 'completed').length} error=${t.communities.filter(c => c.status === 'error').length}`)
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
    console.log(`[reportStore] runTask START id=${community.communityId} edgeType=${community.edgeType} level=${community.level} modelId=${modelId}`)
    try {
      if (!projectId) {
        console.log(`[reportStore] runTask SKIP no projectId`)
        community.status = 'skipped'
        return false
      }
      const result = await getLevelCommunityDetail({ projectId, taskId, level: community.level, edgeType: community.edgeType })
      const commList = result?.communities
      console.log(`[reportStore] runTask getLevelCommunityDetail returned ${commList?.length ?? 0} communities`)
      if (!Array.isArray(commList) || commList.length === 0) {
        console.log(`[reportStore] runTask SKIP no communities in detail`)
        community.status = 'skipped'
        return false
      }
      const detail = commList.find((c: any) => c.communityId === community.communityId)
      if (!detail) {
        console.log(`[reportStore] runTask SKIP community ${community.communityId} not found in level detail (found ids=${commList.map((c:any)=>c.communityId).join(',')})`)
        community.status = 'skipped'
        return false
      }
      console.log(`[reportStore] runTask detail found nodeCount=${detail.nodeCount} edgeCount=${detail.edgeCount}`)
      const nodeListText = detail.nodes.map((n: any) => {
        const ext = n.filePath && n.filePath !== '?' ? n.filePath.split('.').pop() : ''
        const label = ext ? `${n.name}.${ext}` : n.name
        return `- ${label}  (${n.filePath})`
      }).slice(0, 100).join('\n')
      const edgeListText = detail.edges.map((e: any) => {
        return `- ${e.sourceDisplay || e.source} → ${e.targetDisplay || e.target}`
      }).slice(0, 100).join('\n')

      const t = ensureTask(taskId)
      // For child-level analysis (L1+), fetch parent community context
      let parentContext = ''
      const levelNum = parseInt(community.level?.[1] || '')
      if (levelNum > 0 && community.parentId) {
        const parentLv = `L${levelNum - 1}`
        try {
          const parentResult = await window.api.analysis.getCommunityResult({
            taskId,
            edgeType: community.edgeType,
            commLv: parentLv,
            commId: community.parentId,
          })
          if (parentResult?.name || parentResult?.summary) {
            const pName = parentResult.name_manual || parentResult.name || community.parentId
            const pSummary = parentResult.summary || ''
            parentContext = `\n\n## 所属父组件\n### ${pName}\n${pSummary}`
          }
        } catch (e) {
          console.warn(`[reportStore] runTask parent context fetch failed:`, e)
        }
      }
      const sessionId = `comm-${taskId}-${community.communityId}-${Date.now()}`
      console.log(`[reportStore] runTask LLM chat START sessionId=${sessionId} modelId=${modelId}`)
      const chatResult = await window.api.llm.chat({
        sessionId,
        modelId,
        templateId: 'community_analyze',
        variables: {
          communityId: community.communityId,
          level: community.level,
          nodeCount: String(detail.nodeCount),
          edgeCount: String(detail.edgeCount),
          nodeListWithPaths: nodeListText,
          edgeListWithDetails: edgeListText,
          parentSummaries: parentContext ? `${t.projectContext}\n${parentContext}` : t.projectContext,
          source: 'community_analysis',
          community_id: community.communityId,
          community_level: community.level,
          edge_type: community.edgeType,
          batch_id: `batch-${Date.now()}`,
        },
        mode: 'structured',
        outputSchema: {
          type: 'object',
          properties: {
            name: { type: 'string', maxLength: 20 },
            summary: { type: 'string' },
            mermaid: { type: 'string' },
            plantuml: { type: 'string' },
          },
          required: ['name', 'summary', 'mermaid'],
        },
      })
      console.log(`[reportStore] runTask LLM chat response requestId=${chatResult.requestId}`)
      let fullContent = ''
      await new Promise<void>((resolve, reject) => {
        const unsubscribe = window.api.llm.subscribe(chatResult.requestId, {
          onChunk(data: { text: string }) { fullContent += data.text },
          onDone(data: { content: string; structured?: Record<string, any> }) {
            const trimmed = (data.structured?.summary || fullContent || '').trim()
            const hasValidName = !!data.structured?.name
            const isError = !trimmed || (!hasValidName && trimmed.length < 5) || trimmed.length < 1 ||
              /^(error|错误|failed|失败|\[error\]|\[ERROR\])/i.test(trimmed)
            console.log(`[reportStore] runTask LLM onDone id=${community.communityId} trimmedLen=${trimmed.length} isError=${isError} hasStructured=${!!data.structured}`)
            if (isError) {
              community.status = 'error'
              community.error = trimmed || (chatResult as any).error || 'LLM returned empty response'
              console.log(`[reportStore] runTask LLM ERROR id=${community.communityId} error=${community.error}`)
            } else if (data.structured) {
              community.name = data.structured.name?.slice(0, 20) || community.communityId
              community.summary = data.structured.summary || ''
              community.mermaid = normalizeDiagramField(data.structured.mermaid)
              community.plantuml = normalizeDiagramField(data.structured.plantuml)
              community.status = 'completed'
              console.log(`[reportStore] runTask LLM SUCCESS id=${community.communityId} name=${community.name} summaryLen=${community.summary.length} mermaidType=${typeof data.structured.mermaid} plantumlType=${typeof data.structured.plantuml}`)
            } else {
              community.status = 'completed'
              community.name = community.communityId
              community.summary = fullContent
              console.log(`[reportStore] runTask LLM FALLBACK (no structured) id=${community.communityId}`)
            }
            unsubscribe()
            resolve()
          },
          onError(errData: { message: string }) {
            community.status = 'error'
            community.error = errData.message
            console.log(`[reportStore] runTask LLM onError id=${community.communityId} msg=${errData.message}`)
            unsubscribe()
            reject(new Error(errData.message))
          },
        })
      })
      return true
    } catch (e: any) {
      community.status = 'error'
      community.error = e.message || String(e)
      return false
    }
  }

  function stopAnalysis(taskId: string) {
    const t = tasks.value[taskId]
    if (t) {
      t.communityPaused = true
      t.communityRunning = false
    }
  }

  async function retryTask(taskId: string, communityId: string, modelId: string, projectId: string): Promise<boolean> {
    const t = ensureTask(taskId)
    const community = t.communities.find(c => c.communityId === communityId)
    if (!community) return false
    community.status = 'pending'
    community.error = undefined
    community.selected = false
    community.name = undefined
    community.summary = undefined
    syncSelections(taskId)

    community.status = 'running'
    try {
      const ok = await runTask(taskId, community, modelId, projectId)
      if (ok && community.status === 'completed') {
        await saveCommunityResult({
          taskId, edgeType: community.edgeType, commLv: community.level, commId: community.communityId,
          name: community.name || community.communityId, summary: community.summary || '',
          mermaid: community.mermaid || '', plantuml: community.plantuml || '',
          modelId, templateId: 'community_analyze',
        })
      }
      return ok
    } catch (e: any) {
      community.status = 'error'
      community.error = e.message || String(e)
      return false
    }
  }

  // ============================================================
  // === Child Level (L1/L2/L3/L4) Analysis Actions            ===
  // ============================================================

  function buildChildStateKey(parentLevel: string, parentCommId: string, edgeType: string): string {
    return `${parentLevel}|${parentCommId}|${edgeType}`
  }

  function ensureChildState(taskId: string, parentLevel: string, parentCommId: string, edgeType: string): ChildAnalysisState {
    const t = ensureTask(taskId)
    const key = buildChildStateKey(parentLevel, parentCommId, edgeType)
    if (!t.analysisStates[key]) {
      t.analysisStates[key] = {
        running: false,
        paused: false,
        communities: [],
        errorLogs: [],
        level: `L${parseInt(parentLevel[1]) + 1}`,
        parentCommId,
        edgeType,
      }
    }
    return t.analysisStates[key]
  }

  async function loadChildCommunities(taskId: string, parentLevel: string, parentCommId: string, edgeType: string) {
    const state = ensureChildState(taskId, parentLevel, parentCommId, edgeType)
    const childLevel = state.level
    console.log(`[reportStore] loadChildCommunities ENTRY taskId=${taskId} parentLevel=${parentLevel} parentCommId=${parentCommId} edgeType=${edgeType} childLevel=${childLevel}`)
    try {
      const [levels, results] = await Promise.all([
        getCascadeLevels(taskId, edgeType).catch(() => null),
        listCommunityResults(taskId, edgeType).catch(() => ({ results: [] })),
      ])
      const llmMap: Record<string, any> = {}
      for (const r of (results?.results || [])) {
        llmMap[r.comm_id] = r
      }
      // 诊断：打印前3个 L1 结果的 mermaid/plantuml 状态
      const l1Results = (results?.results || []).filter((r: any) => r.comm_lv === childLevel).slice(0, 3)
      for (const r of l1Results) {
        console.log(`[reportStore] loadChildCommunities LLM result id=${r.comm_id} name=${r.name} mermaidLen=${(r.mermaid||'').length} plantumlLen=${(r.plantuml||'').length}`)
      }
      const communities: CommunityItem[] = []
      const seenIds = new Set<string>()
      if (levels?.levels) {
        for (const lv of levels.levels) {
          if (lv.lv !== childLevel || !lv.items) continue
          for (const item of lv.items) {
            if (item.parentCommId !== parentCommId) continue
            if (seenIds.has(item.id)) continue
            seenIds.add(item.id)
            const comm: CommunityItem = {
              id: `${edgeType}-${item.id}`,
              communityId: item.id,
              level: lv.lv,
              edgeType,
              nodeCount: item.nodeCount || 0,
              edgeCount: item.edgeCount || 0,
              qualityScore: item.qualityScore ?? null,
              status: 'pending',
              selected: false,
              parentId: item.parentCommId ?? undefined,
            }
            const saved = llmMap[item.id]
            if (saved) {
              comm.name = saved.name || item.id
              comm.summary = saved.summary || undefined
              comm.mermaid = saved.mermaid || undefined
              comm.plantuml = saved.plantuml || undefined
              comm.status = 'completed'
            }
            communities.push(comm)
          }
        }
      }
      state.communities = communities
      console.log(`[reportStore] loadChildCommunities DONE childLevel=${childLevel} count=${communities.length}`)
    } catch (e) {
      console.error('[reportStore] loadChildCommunities error:', e)
    }
  }

  async function analyzeChildSelected(taskId: string, stateKey: string, modelId: string, batchSize: number, projectId: string): Promise<any[]> {
    const t = tasks.value[taskId]
    if (!t) return []
    const state = t.analysisStates[stateKey]
    if (!state || state.running || state.paused) return []
    const selected = state.communities.filter(c => c.selected)
    if (selected.length === 0) return []
    console.log(`[reportStore] analyzeChildSelected START stateKey=${stateKey} selected=${selected.length} batchSize=${batchSize}`)
    state.running = true
    state.paused = false
    for (let i = 0; i < selected.length; i += batchSize) {
      if (state.paused) break
      const batch = selected.slice(i, i + batchSize)
      batch.forEach(c => { c.status = 'queued' })
      const results = await Promise.allSettled(batch.map(c => runTask(taskId, c, modelId, projectId)))
      for (let idx = 0; idx < batch.length; idx++) {
        const c = batch[idx]
        const r = results[idx]
        if (r.status === 'rejected') {
          c.status = 'error'
          c.error = r.reason?.message || String(r.reason)
        }
        if (c.status === 'completed') {
          c.selected = false
          try {
            await saveCommunityResult({
              taskId, edgeType: c.edgeType, commLv: c.level, commId: c.communityId,
              name: c.name || c.communityId, summary: c.summary || '',
              mermaid: c.mermaid || '', plantuml: c.plantuml || '',
              modelId, templateId: 'community_analyze',
            })
            if (t.llmResults) t.llmResults[c.communityId] = { comm_id: c.communityId, name: c.name, summary: c.summary }
          } catch (e) {
            console.warn('[reportStore] analyzeChildSelected save failed:', e)
          }
        }
      }
    }
    state.running = false
    console.log(`[reportStore] analyzeChildSelected DONE stateKey=${stateKey}`)
    return state.communities
      .filter(c => c.status === 'completed' && c.name)
      .map(c => ({
        communityId: c.communityId, level: c.level, edgeType: c.edgeType,
        name: c.name!, summary: c.summary!, mermaid: c.mermaid, plantuml: c.plantuml,
      }))
  }

  function toggleChildSelect(taskId: string, stateKey: string, commId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const state = t.analysisStates[stateKey]
    if (!state || state.running) return
    const comm = state.communities.find(c => c.communityId === commId)
    if (comm) comm.selected = !comm.selected
  }

  function selectChildIncomplete(taskId: string, stateKey: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const state = t.analysisStates[stateKey]
    if (!state) return
    for (const c of state.communities) {
      if (c.status !== 'completed') c.selected = true
    }
  }

  function deselectAllChild(taskId: string, stateKey: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const state = t.analysisStates[stateKey]
    if (!state) return
    for (const c of state.communities) {
      c.selected = false
    }
  }

  async function retryChildTask(taskId: string, stateKey: string, commId: string, modelId: string, projectId: string): Promise<boolean> {
    const t = tasks.value[taskId]
    if (!t) return false
    const state = t.analysisStates[stateKey]
    if (!state) return false
    const community = state.communities.find(c => c.communityId === commId)
    if (!community) return false
    community.status = 'pending'
    community.error = undefined
    community.selected = false
    community.name = undefined
    community.summary = undefined
    community.status = 'running'
    try {
      const ok = await runTask(taskId, community, modelId, projectId)
      if (ok && community.status === 'completed') {
        await saveCommunityResult({
          taskId, edgeType: community.edgeType, commLv: community.level, commId: community.communityId,
          name: community.name || community.communityId, summary: community.summary || '',
          mermaid: community.mermaid || '', plantuml: community.plantuml || '',
          modelId, templateId: 'community_analyze',
        })
      }
      return ok
    } catch (e: any) {
      community.status = 'error'
      community.error = e.message || String(e)
      return false
    }
  }

  function stopChildAnalysis(taskId: string, stateKey: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const state = t.analysisStates[stateKey]
    if (state) {
      state.paused = true
      state.running = false
    }
  }

  function pushChildError(taskId: string, stateKey: string, msg: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const state = t.analysisStates[stateKey]
    if (!state) return
    state.errorLogs.unshift(msg)
    if (state.errorLogs.length > 50) state.errorLogs.length = 50
  }

  function clearChildErrorLogs(taskId: string, stateKey: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const state = t.analysisStates[stateKey]
    if (state) state.errorLogs = []
  }

  // ============================================================
  // === Regeneration Methods                                  ===
  // ============================================================

  async function regenerateCommunityDoc(taskId: string, communityId: string, level: string, edgeType: string, projectId: string, additionalPrompt: string): Promise<{ success: boolean; content?: string; error?: string }> {
    try {
      const result = await getLevelCommunityDetail({ projectId, taskId, level, edgeType })
      const commList = result?.communities
      if (!Array.isArray(commList) || commList.length === 0) return { success: false, error: 'No community detail found' }
      const detail = commList.find((c: any) => c.communityId === communityId)
      if (!detail) return { success: false, error: `Community ${communityId} not found in detail` }
      const nodeListText = detail.nodes.map((n: any) => {
        const ext = n.filePath && n.filePath !== '?' ? n.filePath.split('.').pop() : ''
        const label = ext ? `${n.name}.${ext}` : n.name
        return `- ${label}  (${n.filePath})`
      }).slice(0, 100).join('\n')
      const edgeListText = detail.edges.map((e: any) => {
        return `- ${e.sourceDisplay || e.source} → ${e.targetDisplay || e.target}`
      }).slice(0, 100).join('\n')

      const t = ensureTask(taskId)
      // Project context
      let parentSummaries = t.projectContext
      // For child-level (L1+), fetch parent context
      const levelNum = parseInt(level?.[1] || '')
      if (levelNum > 0) {
        const parentLv = `L${levelNum - 1}`
        try {
          const parentResult = await window.api.analysis.getCommunityResult({ taskId, edgeType, commLv: parentLv, commId: communityId })
          if (parentResult?.name || parentResult?.summary) {
            const pName = parentResult.name_manual || parentResult.name || communityId
            const pSummary = parentResult.summary || ''
            parentSummaries = parentSummaries
              ? `${parentSummaries}\n\n## 所属父组件\n### ${pName}\n${pSummary}`
              : `## 所属父组件\n### ${pName}\n${pSummary}`
          }
        } catch { /* skip parent context */ }
      }

      const modelId = useSettingsStore().models.find((m: any) => m.isDefault)?.id
      if (!modelId) return { success: false, error: 'No default model configured' }

      const sessionId = `regen-${taskId}-${communityId}-${Date.now()}`
      const chatResult = await window.api.llm.chat({
        sessionId, modelId,
        templateId: 'community_analyze',
        variables: {
          communityId, level,
          nodeCount: String(detail.nodeCount), edgeCount: String(detail.edgeCount),
          nodeListWithPaths: nodeListText, edgeListWithDetails: edgeListText,
          parentSummaries,
          userAdditionalPrompt: additionalPrompt || '',
        },
        mode: 'structured',
        outputSchema: {
          type: 'object',
          properties: {
            name: { type: 'string', maxLength: 20 },
            summary: { type: 'string' },
            mermaid: { type: 'string' },
            plantuml: { type: 'string' },
          },
          required: ['name', 'summary', 'mermaid'],
        },
      })
      let fullContent = ''
      const parsed = await new Promise<{ name: string; summary: string; mermaid?: string; plantuml?: string } | null>((resolve, reject) => {
        const unsubscribe = window.api.llm.subscribe(chatResult.requestId, {
          onChunk(data: { text: string }) { fullContent += data.text },
          onDone(data: { content: string; structured?: Record<string, any> }) {
            unsubscribe()
            const trimmed = (data.structured?.summary || fullContent || '').trim()
            const hasValidName = !!data.structured?.name
            if (!trimmed || (!hasValidName && trimmed.length < 5) || trimmed.length < 1) {
              reject(new Error('LLM returned empty or too short response'))
              return
            }
            if (data.structured) {
              resolve({
                name: (data.structured.name || '').slice(0, 20) || communityId,
                summary: data.structured.summary || '',
                mermaid: normalizeDiagramField(data.structured.mermaid),
                plantuml: normalizeDiagramField(data.structured.plantuml),
              })
            } else {
              resolve({ name: communityId, summary: fullContent })
            }
          },
          onError(errData: { message: string }) {
            unsubscribe()
            reject(new Error(errData.message))
          },
        })
      })
      if (!parsed) return { success: false, error: 'Failed to parse LLM response' }

      // Save result
      await saveCommunityResult({
        taskId, edgeType, commLv: level, commId: communityId,
        name: parsed.name, summary: parsed.summary,
        mermaid: parsed.mermaid || '', plantuml: parsed.plantuml || '',
        modelId, templateId: 'community_analyze',
      })

      // Build MD content
      const parts: string[] = [
        `# 社区: ${parsed.name}`,
        '', `**ID**: ${communityId}`, '',
        parsed.summary,
      ]
      if (parsed.mermaid) parts.push('', '```mermaid', parsed.mermaid, '```')
      if (parsed.plantuml) parts.push('', '```plantuml', parsed.plantuml, '```')
      return { success: true, content: parts.join('\n') }
    } catch (e: any) {
      return { success: false, error: e.message || String(e) }
    }
  }

  async function regenerateCommunityDiagram(taskId: string, communityId: string, level: string, edgeType: string, projectId: string, existingCode: string, userInstruction: string, diagramType: 'mermaid' | 'plantuml'): Promise<{ success: boolean; code?: string; error?: string }> {
    const templateId = diagramType === 'mermaid' ? 'diagram_regenerate_mermaid' : 'diagram_regenerate_plantuml'
    try {
      const modelId = useSettingsStore().models.find((m: any) => m.isDefault)?.id
      if (!modelId) return { success: false, error: 'No default model configured' }
      const sessionId = `regen-${diagramType}-${taskId}-${communityId}-${Date.now()}`
      const chatResult = await window.api.llm.chat({
        sessionId, modelId,
        templateId,
        variables: {
          existingCode: existingCode || '（无现有代码）',
          userInstruction: userInstruction || '请重新生成',
        },
        mode: 'structured',
        outputSchema: {
          type: 'object',
          properties: { code: { type: 'string' } },
          required: ['code'],
        },
      })
      let fullContent = ''
      function extractDiagramCode(structured: Record<string, any> | undefined, fallback: string): string {
        if (!structured) {
          // 无结构化输出 → 从纯文本中提取 ```mermaid/```plantuml 代码块
          const m = fallback.match(/```(?:\w+)?\n([\s\S]*?)```/)
          return m ? m[1].trim() : fallback.trim()
        }
        // 尝试各种可能字段名
        return structured.code || structured.content || structured.diagram ||
               structured.mermaid || structured.plantuml ||
               structured.result || structured.output || ''
      }
      const parsed = await new Promise<{ code: string } | null>((resolve, reject) => {
        const unsubscribe = window.api.llm.subscribe(chatResult.requestId, {
          onChunk(data: { text: string }) { fullContent += data.text },
          onDone(data: { content: string; structured?: Record<string, any> }) {
            unsubscribe()
            const rawCode = extractDiagramCode(data.structured, data.content || fullContent)
            if (rawCode) {
              resolve({ code: rawCode })
            } else {
              reject(new Error('LLM did not return valid diagram code'))
            }
          },
          onError(errData: { message: string }) {
            unsubscribe()
            reject(new Error(errData.message))
          },
        })
      })
      if (!parsed) return { success: false, error: 'Failed to parse LLM response' }
      // Update in DB: fetch current result, replace diagram, save back
      const current = await window.api.analysis.getCommunityResult({ taskId, edgeType, commLv: level, commId: communityId })
      await saveCommunityResult({
        taskId, edgeType, commLv: level, commId: communityId,
        name: current?.name || communityId,
        summary: current?.summary || '',
        mermaid: diagramType === 'mermaid' ? parsed.code : (current?.mermaid || ''),
        plantuml: diagramType === 'plantuml' ? parsed.code : (current?.plantuml || ''),
        modelId, templateId,
      })
      return { success: true, code: parsed.code }
    } catch (e: any) {
      return { success: false, error: e.message || String(e) }
    }
  }

  async function regenerateOverallDoc(taskId: string, projectId: string, additionalPrompt: string): Promise<{ success: boolean; content?: string; error?: string }> {
    try {
      const project = useProjectStore().projects.find((p: any) => p.id === projectId)
      if (!project) return { success: false, error: 'Project not found' }

      const t = ensureTask(taskId)
      const modelId = useSettingsStore().models.find((m: any) => m.isDefault)?.id
      if (!modelId) return { success: false, error: 'No default model configured' }

      // Gather community name map + details (same as prepareStepVariables in ReportGenerationPipeline)
      const [callResults, depResults] = await Promise.all([
        listCommunityResults(taskId, 'CALL').catch(() => ({ results: [] })),
        listCommunityResults(taskId, 'INCLUDE').catch(() => ({ results: [] })),
      ])
      const nameMap: string[] = []
      const allResults = [...(callResults?.results || []), ...(depResults?.results || [])]
      for (const r of allResults) {
        if (r.comm_lv === 'L0' && (r.name || r.name_manual)) {
          nameMap.push(`- ${r.comm_id}: ${r.name_manual || r.name}`)
        }
      }
      // Also add communities without LLM results (use ID as name)
      const [callLevels, depLevels] = await Promise.all([
        getCascadeLevels(taskId, 'CALL').catch(() => null),
        getCascadeLevels(taskId, 'INCLUDE').catch(() => null),
      ])
      const l0Ids = new Set<string>()
      for (const lv of [...(callLevels?.levels || []), ...(depLevels?.levels || [])]) {
        if (lv.lv === 'L0') for (const item of lv.items) l0Ids.add(item.id)
      }
      for (const id of l0Ids) {
        if (!nameMap.some(l => l.includes(id))) nameMap.push(`- ${id}: ${id}`)
      }

      const [callDetail, depDetail] = await Promise.all([
        getLevelCommunityDetail({ projectId, taskId, level: 'L0', edgeType: 'CALL' }).catch(() => null),
        getLevelCommunityDetail({ projectId, taskId, level: 'L0', edgeType: 'INCLUDE' }).catch(() => null),
      ])

      function formatCommunityDetail(detail: any, edgeType: string): string {
        if (!detail?.communities) return '（无数据）'
        return detail.communities.map((c: any) => {
          const nodes = (c.nodes || []).slice(0, 20).map((n: any) => `  - ${n.name} (${n.filePath})`).join('\n')
          const edges = (c.edges || []).slice(0, 20).map((e: any) => `  - ${e.sourceDisplay || e.source} → ${e.targetDisplay || e.target}`).join('\n')
          return `### ${c.communityId}\n- 节点数: ${c.nodeCount}, 边数: ${c.edgeCount}\n#### 节点\n${nodes}\n#### 边\n${edges}`
        }).join('\n\n')
      }

      const sessionId = `regen-overall-${taskId}-${Date.now()}`
      const chatResult = await window.api.llm.chat({
        sessionId, modelId,
        templateId: 'report_overall_architecture',
        variables: {
          projectName: project.name || '',
          language: project.language || '',
          fileCount: String(project.fileCount || 0),
          rootPath: project.rootPath || '',
          readmeContent: t.projectContext || '',
          dependencySummary: '',
          communityNameMap: nameMap.join('\n') || '（无命名映射）',
          callCommunityDetail: formatCommunityDetail(callDetail, 'CALL'),
          includeCommunityDetail: formatCommunityDetail(depDetail, 'INCLUDE'),
          userAdditionalPrompt: additionalPrompt || '',
        },
        mode: 'chat',
      })
      let fullContent = ''
      await new Promise<void>((resolve, reject) => {
        const unsubscribe = window.api.llm.subscribe(chatResult.requestId, {
          onChunk(data: { text: string }) { fullContent += data.text },
          onDone() { unsubscribe(); resolve() },
          onError(errData: { message: string }) { unsubscribe(); reject(new Error(errData.message)) },
        })
      })
      if (!fullContent || fullContent.trim().length < 50) {
        return { success: false, error: 'LLM returned empty or too short response' }
      }

      // Save to report_subdocs
      const docId = `overall-${taskId}`
      const existing = await getSubDoc(docId).catch(() => null)
      if (existing) {
        await updateSubDoc({ subDocId: docId, title: '整体架构分析', content: fullContent })
      } else {
        await createSubDoc({ taskId, title: '整体架构分析', content: fullContent })
      }
      return { success: true, content: fullContent }
    } catch (e: any) {
      return { success: false, error: e.message || String(e) }
    }
  }

  function toggleSelect(taskId: string, id: string) {
    const t = tasks.value[taskId]
    if (!t || t.communityRunning) {
      console.log(`[reportStore] toggleSelect SKIP taskId=${taskId} id=${id} running=${t?.communityRunning}`)
      return
    }
    const community = t.communities.find(c => c.id === id)
    if (community) {
      community.selected = !community.selected
      console.log(`[reportStore] toggleSelect id=${id} edgeType=${community.edgeType} level=${community.level} newSelected=${community.selected}`)
      syncSelections(taskId)
    } else {
      console.log(`[reportStore] toggleSelect NOT FOUND id=${id}`)
    }
  }

  function selectAll(taskId: string, ids: string[], selected: boolean) {
    const t = tasks.value[taskId]
    if (!t) return
    let count = 0
    for (const c of t.communities) {
      if (ids.includes(c.id)) { c.selected = selected; count++ }
    }
    console.log(`[reportStore] selectAll taskId=${taskId} ids=${ids.length} selected=${selected} matched=${count} totalSelectedNow=${t.communities.filter(c=>c.selected).length}`)
    syncSelections(taskId)
  }

  function selectIncomplete(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    let count = 0
    for (const c of t.communities) {
      if (c.level !== 'L0') continue
      if (c.status !== 'completed') { c.selected = true; count++ }
    }
    console.log(`[reportStore] selectIncomplete taskId=${taskId} selected=${count} totalSelectedNow=${t.communities.filter(c=>c.selected).length}`)
    syncSelections(taskId)
  }

  function deselectAll(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    for (const c of t.communities) {
      c.selected = false
    }
    console.log(`[reportStore] deselectAll taskId=${taskId} totalSelectedNow=${t.communities.filter(c=>c.selected).length}`)
    syncSelections(taskId)
  }

  function syncSelections(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const ids = t.communities.filter(c => c.selected).map(c => c.id)
    console.log(`[reportStore] syncSelections taskId=${taskId} selectedIds=[${ids.join(',')}]`)
    setSelections(taskId, ids)
  }

  function restoreSelections(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const savedIds = getSelections(taskId)
    if (!savedIds.length) return
    for (const c of t.communities) {
      c.selected = savedIds.includes(c.id)
    }
  }

  function pushError(taskId: string, msg: string) {
    const t = tasks.value[taskId]
    if (!t) return
    t.errorLogs.unshift(msg)
    if (t.errorLogs.length > 50) t.errorLogs.length = 50
  }

  function clearErrorLogs(taskId: string) {
    const t = tasks.value[taskId]
    if (t) t.errorLogs = []
  }

  function clearTask(taskId: string) {
    delete tasks.value[taskId]
  }

  // ============================================================
  // === Pipeline Actions                                     ===
  // ============================================================

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
      if (node.children) {
        for (const c of node.children) {
          if (walk(c)) return true
        }
      }
      return false
    }
    walk(t.pipelineRootTask)
    recalcProgress(taskId)
  }

  function recalcProgress(taskId: string) {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask) return
    const flatten = (node: PipelineTaskNode): PipelineTaskNode[] => {
      if (!node.children) return [node]
      return [node, ...node.children.flatMap(flatten)]
    }
    const all = flatten(t.pipelineRootTask)
    const leaves = all.filter(n => !n.children || n.children.length === 0)
    const done = leaves.filter(n => n.status === 'completed' || n.status === 'skipped')
    const oldProgress = t.pipelineProgress
    t.pipelineProgress = all.length > 0 ? Math.round((done.length / all.length) * 100) : 0
    if (t.pipelineProgress !== oldProgress) {
      console.log(`[reportStore] recalcProgress taskId=${taskId} leaves=${all.length} done=${done.length} progress=${oldProgress}->${t.pipelineProgress}`)
    }
  }

  function setPipelineRunning(taskId: string, val: boolean) {
    const t = tasks.value[taskId]
    if (t) t.pipelineRunning = val
  }

  function setPipelinePaused(taskId: string, val: boolean) {
    const t = tasks.value[taskId]
    if (t) t.pipelinePaused = val
  }

  function setPendingStepRun(taskId: string, nodeId: string | null) {
    const t = tasks.value[taskId]
    if (t) t.pendingStepRun = nodeId
  }

  function stopPipeline(taskId: string) {
    const t = tasks.value[taskId]
    if (t) {
      t.pipelinePaused = true
      t.pipelineRunning = false
    }
  }

  function pausePipeline(taskId: string) {
    const t = tasks.value[taskId]
    if (t) t.pipelinePaused = !t.pipelinePaused
  }

  function resetPipeline(taskId: string) {
    const t = tasks.value[taskId]
    if (!t || !t.pipelineRootTask) return
    const resetNodes = (nodes: PipelineTaskNode[]) => {
      for (const n of nodes) {
        n.status = 'pending'
        n.progress = 0
        n.error = undefined
        if (n.children) resetNodes(n.children)
      }
    }
    if (t.pipelineRootTask.children) resetNodes(t.pipelineRootTask.children)
    t.pipelineRootTask.status = 'pending'
    t.pipelineProgress = 0
    t.pipelineRunning = false
    t.pipelinePaused = false
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

  // ============================================================
  // === Return                                               ===
  // ============================================================

  return {
    generatedReports, dbReportExists, loading,
    setGeneratedReport, checkReportExists,
    getReadmeContent, extractDependencyFiles, generateProjectSummary, getProjectSummary,
    getLevelCommunityDetail, listCommunityResults, getCascadeLevels,
    saveCommunityResult, updateCommunityName,
    getSubDoc, updateSubDoc, createSubDoc,
    getFileSummaries, saveFileSummaries,
    communitySelections, getSelections, setSelections, clearSelections,

    // Runtime state
    tasks, ensureTask,

    // Community actions
    loadCommunities, loadProjectContext, analyzeSelected, runTask,
    stopAnalysis, retryTask,
    toggleSelect, selectAll, selectIncomplete, deselectAll, syncSelections, restoreSelections,
    pushError, clearErrorLogs, clearTask,

    // Child level actions
    buildChildStateKey, ensureChildState,
    loadChildCommunities, analyzeChildSelected,
    toggleChildSelect, selectChildIncomplete, deselectAllChild,
    retryChildTask, stopChildAnalysis,
    pushChildError, clearChildErrorLogs,

    // Regeneration actions
    regenerateCommunityDoc, regenerateOverallDoc, regenerateCommunityDiagram,

    // Pipeline actions
    initPipeline, updateNodeStatus, recalcProgress,
    setPipelineRunning, setPipelinePaused, setPendingStepRun,
    stopPipeline, pausePipeline, resetPipeline,
    allPipelineStepsCompleted, hasPipelineError,
  }
})
