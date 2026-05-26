import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'

export const useReportStore = defineStore('report', () => {
  const communityDataByTask = ref<Record<string, Record<string, any>>>({})
  const communityResultsByTask = ref<Record<string, Record<string, Record<string, any>>>>({})
  const generatedReports = ref<Record<string, string>>({})
  const dbReportExists = ref<Record<string, boolean>>({})
  const loading = ref<Record<string, boolean>>({})

  function getCommunityData(taskId: string, edgeType: string) {
    return communityDataByTask.value[taskId]?.[edgeType] || null
  }

  function getCommunityResults(taskId: string, edgeType: string): Record<string, any> {
    return communityResultsByTask.value[taskId]?.[edgeType] || {}
  }

  function getCommunityResult(taskId: string, edgeType: string, commId: string): any {
    return communityResultsByTask.value[taskId]?.[edgeType]?.[commId] || null
  }

  async function loadCommunityData(taskId: string) {
    loading.value = { ...loading.value, [taskId]: true }
    try {
      const [call, include, resCall, resInclude] = await Promise.all([
        ipc.analysis.getCascadeLevels(taskId, 'CALL').catch(() => null),
        ipc.analysis.getCascadeLevels(taskId, 'INCLUDE').catch(() => null),
        ipc.analysis.listCommunityResults(taskId, 'CALL').catch(() => ({ results: [] })),
        ipc.analysis.listCommunityResults(taskId, 'INCLUDE').catch(() => ({ results: [] })),
      ])
      communityDataByTask.value = {
        ...communityDataByTask.value,
        [taskId]: { CALL: call, INCLUDE: include },
      }
      communityResultsByTask.value = {
        ...communityResultsByTask.value,
        [taskId]: {
          CALL: Object.fromEntries((resCall?.results || []).map((r: any) => [r.comm_id, r])),
          INCLUDE: Object.fromEntries((resInclude?.results || []).map((r: any) => [r.comm_id, r])),
        },
      }
    } finally {
      loading.value = { ...loading.value, [taskId]: false }
    }
  }

  function updateCommunityResult(taskId: string, edgeType: string, commId: string, data: any) {
    const taskResults = { ...(communityResultsByTask.value[taskId] || {}) }
    const edgeResults = { ...(taskResults[edgeType] || {}) }
    edgeResults[commId] = data
    taskResults[edgeType] = edgeResults
    communityResultsByTask.value = { ...communityResultsByTask.value, [taskId]: taskResults }
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

  // === Phase 3: IPC encapsulation ===

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

  return {
    communityDataByTask, communityResultsByTask, generatedReports, dbReportExists, loading,
    getCommunityData, getCommunityResults, getCommunityResult,
    loadCommunityData, updateCommunityResult, setGeneratedReport, checkReportExists,
    getReadmeContent, extractDependencyFiles, generateProjectSummary, getProjectSummary,
    getLevelCommunityDetail, listCommunityResults, getCascadeLevels,
    saveCommunityResult, updateCommunityName,
    getSubDoc, updateSubDoc, createSubDoc,
    getFileSummaries, saveFileSummaries,
  }
})
