import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import { useModelConfigStore } from '@/stores/model-config-store'

export const useReportStore = defineStore('report', () => {
  const generatedReports = ref<Record<string, string>>({})
  const dbReportExists = ref<Record<string, boolean>>({})
  const loading = ref<Record<string, boolean>>({})

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

  async function saveProjectSummary(projectId: string, summary: string) {
    return await ipc.report.saveProjectSummary({ projectId, summary })
  }

  async function getLevelCommunityDetail(params: { projectId: string; taskId: string; level?: string; edgeType?: string }) {
    return await ipc.report.getLevelCommunityDetail(params)
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

  type LlmChatResult = { requestId: string }

  async function regenerateCommunityDiagram(
    taskId: string, parentCommId: string, parentLevel: string, parentEdgeType: string,
    _projectId: string, _existing: string, prompt: string, mode: string,
  ): Promise<{ success: boolean; code?: string; error?: string }> {
    try {
      if (!window.api) return { success: false, error: 'API not available' }
      const sessionId = `regen-diag-${taskId}-${parentCommId}-${Date.now()}`
      const modelConfigStore = useModelConfigStore()
      const modelId = modelConfigStore.models.find(m => m.isDefault)?.id || modelConfigStore.models[0]?.id || 'default'
      const chatResult = await window.api!.llm.chat({
        sessionId,
        templateId: 'regenerate_diagram',
        modelId,
        variables: {
          existing_diagram: _existing, user_prompt: prompt, diagram_type: mode,
          community_id: parentCommId, community_level: parentLevel, edge_type: parentEdgeType,
        },
        mode: 'structured',
        outputSchema: { type: 'object', properties: { code: { type: 'string' } }, required: ['code'] },
      })
      let fullContent = ''
      const code = await new Promise<string>((resolve, reject) => {
        const { requestId } = chatResult as LlmChatResult
      const unsubscribe = window.api!.llm.subscribe(requestId, {
          onChunk(data: unknown) { if (data && typeof data === 'object' && 'text' in (data as Record<string, unknown>)) fullContent += (data as { text: string }).text },
          onDone(data: unknown) {
            const d = data as { content: string; structured?: Record<string, unknown> }
            unsubscribe(); resolve((d.structured?.code as string) || fullContent || '')
          },
          onError(data: unknown) { const e = data as { message: string }; unsubscribe(); reject(new Error((e as Error).message)) },
        })
      })
      if (code) return { success: true, code }
      return { success: false, error: 'Empty response from LLM' }
    } catch (e: unknown) {
      return { success: false, error: e instanceof Error ? (e as Error).message : String(e) }
    }
  }

  async function regenerateCommunityDoc(
    taskId: string, parentCommId: string, parentLevel: string, parentEdgeType: string,
    _projectId: string, prompt: string,
  ): Promise<{ success: boolean; content?: string; error?: string }> {
    try {
      if (!window.api) return { success: false, error: 'API not available' }
      const sessionId = `regen-doc-${taskId}-${parentCommId}-${Date.now()}`
      const modelConfigStore = useModelConfigStore()
      const modelId = modelConfigStore.models.find(m => m.isDefault)?.id || modelConfigStore.models[0]?.id || 'default'
      const chatResult = await window.api!.llm.chat({
        sessionId,
        templateId: 'regenerate_community_doc',
        modelId,
        variables: {
          user_prompt: prompt,
          community_id: parentCommId, community_level: parentLevel, edge_type: parentEdgeType,
        },
        mode: 'structured',
        outputSchema: { type: 'object', properties: { content: { type: 'string' } }, required: ['content'] },
      })
      const { requestId } = chatResult as LlmChatResult
      let fullContent = ''
      const content = await new Promise<string>((resolve, reject) => {
        const unsubscribe = window.api!.llm.subscribe(requestId, {
          onChunk(data: unknown) { if (data && typeof data === 'object' && 'text' in (data as Record<string, unknown>)) fullContent += (data as { text: string }).text },
          onDone(data: unknown) {
            const d = data as { content: string; structured?: Record<string, unknown> }
            unsubscribe(); resolve((d.structured?.content as string) || fullContent || '')
          },
          onError(data: unknown) { const e = data as { message: string }; unsubscribe(); reject(new Error((e as Error).message)) },
        })
      })
      if (content) return { success: true, content }
      return { success: false, error: 'Empty response from LLM' }
    } catch (e: unknown) {
      return { success: false, error: e instanceof Error ? (e as Error).message : String(e) }
    }
  }

  async function regenerateOverallDoc(
    taskId: string, _projectId: string, prompt: string,
  ): Promise<{ success: boolean; content?: string; error?: string }> {
    try {
      if (!window.api) return { success: false, error: 'API not available' }
      const sessionId = `regen-overall-${taskId}-${Date.now()}`
      const modelConfigStore = useModelConfigStore()
      const modelId = modelConfigStore.models.find(m => m.isDefault)?.id || modelConfigStore.models[0]?.id || 'default'
      const chatResult = await window.api!.llm.chat({
        sessionId,
        templateId: 'regenerate_overall_doc',
        modelId,
        variables: { user_prompt: prompt, task_id: taskId },
        mode: 'structured',
        outputSchema: { type: 'object', properties: { content: { type: 'string' } }, required: ['content'] },
      })
      const { requestId } = chatResult as LlmChatResult
      let fullContent = ''
      const content = await new Promise<string>((resolve, reject) => {
        const unsubscribe = window.api!.llm.subscribe(requestId, {
          onChunk(data: unknown) { if (data && typeof data === 'object' && 'text' in (data as Record<string, unknown>)) fullContent += (data as { text: string }).text },
          onDone(data: unknown) {
            const d = data as { content: string; structured?: Record<string, unknown> }
            unsubscribe(); resolve((d.structured?.content as string) || fullContent || '')
          },
          onError(data: unknown) { const e = data as { message: string }; unsubscribe(); reject(new Error((e as Error).message)) },
        })
      })
      if (content) return { success: true, content }
      return { success: false, error: 'Empty response from LLM' }
    } catch (e: unknown) {
      return { success: false, error: e instanceof Error ? (e as Error).message : String(e) }
    }
  }

  return {
    generatedReports, dbReportExists, loading,
    setGeneratedReport, checkReportExists,
    getReadmeContent, extractDependencyFiles, generateProjectSummary, getProjectSummary, saveProjectSummary,
    getLevelCommunityDetail, updateCommunityName,
    getSubDoc, updateSubDoc, createSubDoc,
    getFileSummaries, saveFileSummaries,
    regenerateCommunityDiagram, regenerateCommunityDoc, regenerateOverallDoc,
  }
})
