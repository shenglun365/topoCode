import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'

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

  return {
    generatedReports, dbReportExists, loading,
    setGeneratedReport, checkReportExists,
    getReadmeContent, extractDependencyFiles, generateProjectSummary, getProjectSummary, saveProjectSummary,
    getLevelCommunityDetail, updateCommunityName,
    getSubDoc, updateSubDoc, createSubDoc,
    getFileSummaries, saveFileSummaries,
  }
})
