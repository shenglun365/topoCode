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
        templateId: mode === 'mermaid' ? 'diagram_regenerate_mermaid' : 'diagram_regenerate_plantuml',
        modelId,
        variables: {
          existingCode: _existing,
          userInstruction: prompt,
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
    projectId: string, prompt: string,
  ): Promise<{ success: boolean; content?: string; error?: string }> {
    try {
      if (!window.api) return { success: false, error: 'API not available' }
      const sessionId = `regen-doc-${taskId}-${parentCommId}-${Date.now()}`
      const modelConfigStore = useModelConfigStore()
      const modelId = modelConfigStore.models.find(m => m.isDefault)?.id || modelConfigStore.models[0]?.id || 'default'

      // 获取社区详情，构建完整上下文
      const variables: Record<string, string> = {
        communityId: parentCommId,
        level: parentLevel,
        userAdditionalPrompt: prompt,
        parentSummaries: '',
      }
      if (projectId) {
        const detailResult = await ipc.report.getLevelCommunityDetail({
          projectId, taskId, level: parentLevel, edgeType: parentEdgeType,
        }).catch(() => null)
        const commList = detailResult?.communities
        if (Array.isArray(commList)) {
          const detail = commList.find((c: Record<string, unknown>) => c.communityId === parentCommId) as Record<string, any> | undefined
          if (detail) {
            variables.nodeCount = String(detail.nodeCount || 0)
            variables.edgeCount = String(detail.edgeCount || 0)
            variables.nodeListWithPaths = (detail.nodes || []).map((n: Record<string, any>) => {
              const ext = n.filePath && n.filePath !== '?' ? n.filePath.split('.').pop() : ''
              return `- ${ext ? `${n.name}.${ext}` : n.name}  (${n.filePath})`
            }).slice(0, 100).join('\n')
            variables.edgeListWithDetails = (detail.edges || []).map((e: Record<string, any>) => {
              return `- ${e.sourceDisplay || e.source} → ${e.targetDisplay || e.target}`
            }).slice(0, 100).join('\n')

            // 父组件摘要（非 L0 层级）
            const levelNum = parseInt(parentLevel?.[1] || '')
            if (levelNum > 0) {
              const parentResult = await window.api?.analysis.getCommunityResult({
                taskId, edgeType: parentEdgeType,
                commLv: `L${levelNum - 1}`, commId: detail.parentId || '',
              }).catch(() => null)
              if (parentResult?.name || parentResult?.summary) {
                variables.parentSummaries = `\n\n## 所属父组件\n### ${parentResult.nameManual || parentResult.name || detail.parentId}\n${parentResult.summary || ''}`
              }
            }
          }
        }
      }

      const chatResult = await window.api!.llm.chat({
        sessionId,
        templateId: 'regenerate_community_doc',
        modelId,
        variables,
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
    taskId: string, projectId: string, prompt: string,
  ): Promise<{ success: boolean; content?: string; error?: string }> {
    try {
      if (!window.api) return { success: false, error: 'API not available' }
      const sessionId = `regen-overall-${taskId}-${Date.now()}`
      const modelConfigStore = useModelConfigStore()
      const modelId = modelConfigStore.models.find(m => m.isDefault)?.id || modelConfigStore.models[0]?.id || 'default'

      // 构建上下文变量（由后端 Agent Skills 驱动的文档生成）
      const variables: Record<string, string> = {
        userAdditionalPrompt: prompt,
      }
      if (projectId) {
        const projectStore = await import('@/stores/project').then(m => m.useProjectStore())
        const project = projectStore.selectedProject
        if (project) {
          variables.projectName = project.name || ''
          variables.language = project.language || ''
          variables.fileCount = String(project.fileCount || 0)
          variables.rootPath = (project as any).rootPath || project.path || ''
        }

        const readme = await ipc.report.getReadmeContent({ projectId }).catch(() => null)
        if (readme?.content) variables.readmeContent = readme.content

        const deps = await ipc.report.extractDependencyFiles({ projectId }).catch(() => null)
        if (deps && deps.count > 0) {
          variables.dependencySummary = deps.dependencyFiles.map(
            (d: any) => `${d.file} (${d.type}): ${Object.keys(d.dependencies).slice(0, 8).join(', ')}`
          ).join('\n')
        }

        const [callResults, depResults] = await Promise.all([
          ipc.analysis.listCommunityResults(taskId, 'CALL').catch(() => ({ results: [] })),
          ipc.analysis.listCommunityResults(taskId, 'INCLUDE').catch(() => ({ results: [] })),
        ])
        const nameMap = new Map<string, string>()
        for (const r of [...(callResults?.results || []), ...(depResults?.results || [])]) {
          if (r.name && r.name !== r.commId) nameMap.set(r.commId, r.name)
        }
        variables.communityNameMap = nameMap.size > 0
          ? [...nameMap.entries()].map(([id, name]) => `- ${id} → ${name}`).join('\n')
          : '(无命名结果，将使用原始社区 ID)'

        const formatCommunities = (detail: any) => {
          if (!detail?.communities?.length) return ''
          return detail.communities.map((c: any) => {
            const name = nameMap.get(c.communityId) || c.communityId
            const nodes = c.nodes.map((n: any) => `    - ${n.name} (${n.filePath})`).join('\n')
            const edges = c.edges.map((e: any) => `    - ${e.sourceDisplay} → ${e.targetDisplay}`).join('\n')
            return [
              `### ${name} (community: ${c.communityId})`,
              `- 节点数: ${c.nodeCount}, 边数: ${c.edgeCount}`,
              `- 节点列表:\n${nodes}`,
              `- 边列表:\n${edges}`,
            ].join('\n')
          }).join('\n\n')
        }

        const callDetail = projectId ? await ipc.report.getLevelCommunityDetail({
          projectId, taskId, level: 'L0', edgeType: 'CALL',
        }).catch(() => null) : null
        variables.callCommunityDetail = formatCommunities(callDetail) || '（无数据）'

        const includeDetail = projectId ? await ipc.report.getLevelCommunityDetail({
          projectId, taskId, level: 'L0', edgeType: 'INCLUDE',
        }).catch(() => null) : null
        variables.includeCommunityDetail = formatCommunities(includeDetail) || '（无数据）'
      }

      const chatResult = await window.api!.llm.chat({
        sessionId,
        templateId: 'regenerate_overall_doc',
        modelId,
        variables,
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
