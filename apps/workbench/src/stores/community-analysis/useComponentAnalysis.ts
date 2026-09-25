/**
 * community-store · useComponentAnalysis 逻辑域（MS6-W5 自 store 机械迁出：正文逐行原文，依赖经 ctx 解构注入）。
 */
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import { isLLMConfigured } from '@/services/llmClient'
import { controlDispatcher } from '@/services/control-dispatcher'
import { useProjectStore } from '@/stores/project'
import i18n from '@/i18n'
import type { CommunityItem } from '../community-store'

export function useComponentAnalysis(ctx: { [k: string]: any }) {
  const {
    ensureTask,
    saveCommunityResult,
    syncSelections,
    tasks,
  } = ctx
  const projectStore = useProjectStore()

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

  return {
    analyzeSelected,
    retryTask,
    runTask,
    stopAnalysis,
  }
}
