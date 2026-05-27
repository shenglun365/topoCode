import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import type { PipelineTaskNode } from '@/types/ipc'

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
    try {
      const [callLevels, depLevels, callResults, depResults] = await Promise.all([
        getCascadeLevels(taskId, 'CALL').catch(() => null),
        getCascadeLevels(taskId, 'INCLUDE').catch(() => null),
        listCommunityResults(taskId, 'CALL').catch(() => ({ results: [] })),
        listCommunityResults(taskId, 'INCLUDE').catch(() => ({ results: [] })),
      ])
      const llmMap: Record<string, any> = {}
      for (const r of [...(callResults?.results || []), ...(depResults?.results || [])]) {
        llmMap[r.comm_id] = r
      }
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
      // 合并：保留旧数组的 selected/error/name，status 优先用旧值中的 error，再从 llmMap 推断
      const oldCommMap = new Map<string, CommunityItem>()
      for (const c of (t.communities || [])) oldCommMap.set(c.id, c)
      for (const c of communities) {
        const old = oldCommMap.get(c.id)
        if (old) {
          c.selected = old.selected
          if (old.status === 'error') c.status = 'error'
          c.error = old.error
          if (old.name && old.name !== old.communityId) {
            c.name = old.name
            c.summary = old.summary || c.summary
          }
          if (old.mermaid) c.mermaid = old.mermaid
          if (old.plantuml) c.plantuml = old.plantuml
        }
      }
      // 从 llmMap 确定 status / name / summary（覆盖 pending 状态）
      const savedIds = getSelections(taskId)
      for (const c of communities) {
        if (c.status === 'error') continue
        const saved = llmMap[c.communityId]
        if (saved) {
          c.status = 'completed'
          c.name = saved.name || c.communityId
          c.summary = saved.summary || undefined
          c.mermaid = saved.mermaid || undefined
          c.plantuml = saved.plantuml || undefined
        } else {
          c.status = 'pending'
        }
        if (savedIds.includes(c.id)) c.selected = true
      }
      t.communities = communities
      t.llmResults = llmMap
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
    if (t.communityRunning || t.communityPaused) return []
    const selected = t.communities.filter(c => c.selected)
    if (selected.length === 0) return []

    t.communityRunning = true
    t.communityPaused = false

    for (let i = 0; i < selected.length; i += batchSize) {
      if (t.communityPaused) break
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
            t.llmResults[c.communityId] = { comm_id: c.communityId, name: c.name, summary: c.summary }
          } catch (e) {
            console.warn('[reportStore] saveCommunityResult failed:', e)
          }
        }
      }
    }

    t.communityRunning = false
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
      if (!projectId) {
        community.status = 'skipped'
        return false
      }
      const result = await getLevelCommunityDetail({ projectId, taskId, level: community.level, edgeType: community.edgeType })
      const commList = result?.communities
      if (!Array.isArray(commList) || commList.length === 0) {
        community.status = 'skipped'
        return false
      }
      const detail = commList.find((c: any) => c.communityId === community.communityId)
      if (!detail) {
        community.status = 'skipped'
        return false
      }
      const nodeListText = detail.nodes.map((n: any) => {
        const ext = n.filePath && n.filePath !== '?' ? n.filePath.split('.').pop() : ''
        const label = ext ? `${n.name}.${ext}` : n.name
        return `- ${label}  (${n.filePath})`
      }).slice(0, 100).join('\n')
      const edgeListText = detail.edges.map((e: any) => {
        return `- ${e.sourceDisplay || e.source} → ${e.targetDisplay || e.target}`
      }).slice(0, 100).join('\n')

      const t = ensureTask(taskId)
      const sessionId = `comm-${taskId}-${community.communityId}-${Date.now()}`
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
          parentSummaries: t.projectContext,
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
      let fullContent = ''
      await new Promise<void>((resolve, reject) => {
        const unsubscribe = window.api.llm.subscribe(chatResult.requestId, {
          onChunk(data: { text: string }) { fullContent += data.text },
          onDone(data: { content: string; structured?: Record<string, any> }) {
            const trimmed = (data.structured?.summary || fullContent || '').trim()
            const isError = !trimmed || trimmed.length < 20 ||
              /^(error|错误|failed|失败|\[error\]|\[ERROR\])/i.test(trimmed)
            if (isError) {
              community.status = 'error'
              community.error = trimmed || (chatResult as any).error || 'LLM returned empty response'
            } else if (data.structured) {
              community.name = data.structured.name?.slice(0, 20) || community.communityId
              community.summary = data.structured.summary || ''
              community.mermaid = data.structured.mermaid || ''
              community.plantuml = data.structured.plantuml || ''
              community.status = 'completed'
            } else {
              community.status = 'completed'
              community.name = community.communityId
              community.summary = fullContent
            }
            unsubscribe()
            resolve()
          },
          onError(errData: { message: string }) {
            community.status = 'error'
            community.error = errData.message
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

  function toggleSelect(taskId: string, id: string) {
    const t = tasks.value[taskId]
    if (!t || t.communityRunning) return
    const community = t.communities.find(c => c.id === id)
    if (community) {
      community.selected = !community.selected
      syncSelections(taskId)
    }
  }

  function selectAll(taskId: string, ids: string[], selected: boolean) {
    const t = tasks.value[taskId]
    if (!t) return
    for (const c of t.communities) {
      if (ids.includes(c.id)) c.selected = selected
    }
    syncSelections(taskId)
  }

  function selectIncomplete(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    for (const c of t.communities) {
      if (c.level !== 'L0') continue
      if (c.status !== 'completed') c.selected = true
    }
    syncSelections(taskId)
  }

  function deselectAll(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    for (const c of t.communities) {
      c.selected = false
    }
    syncSelections(taskId)
  }

  function syncSelections(taskId: string) {
    const t = tasks.value[taskId]
    if (!t) return
    const ids = t.communities.filter(c => c.selected).map(c => c.id)
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
    t.pipelineProgress = all.length > 0 ? Math.round((done.length / all.length) * 100) : 0
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

    // Pipeline actions
    initPipeline, updateNodeStatus, recalcProgress,
    setPipelineRunning, setPipelinePaused, setPendingStepRun,
    stopPipeline, pausePipeline, resetPipeline,
    allPipelineStepsCompleted, hasPipelineError,
  }
})
