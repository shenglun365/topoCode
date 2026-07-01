import { defineStore } from 'pinia'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import { useAnalysisStore } from './analysis'
import { useProjectStore } from './project'

export interface DashboardData {
  task: any
  callLevels: any
  depLevels: any
  callResults: { results: any[] }
  depResults: { results: any[] }
  fileStats: any
  preSummary?: {
    counts: Record<string, number>
    total_files: number
    cached_count: number
    project_root: string
  }
}

export const useReportStore = defineStore('report', () => {
  const generatedReports = ref<Record<string, string>>({})
  const dbReportExists = ref<Record<string, boolean>>({})
  const loading = ref<Record<string, boolean>>({})
  const dashboardCache = ref<Record<string, DashboardData>>({})
  const _inflightDashboard = new Map<string, Promise<DashboardData | null>>()

  function setGeneratedReport(taskId: string, content: string) {
    generatedReports.value = { ...generatedReports.value, [taskId]: content }
    dbReportExists.value = { ...dbReportExists.value, [taskId]: true }
  }

  async function checkReportExists(taskId: string) {
    try {
      // 10s 客户端超时，避免 ZMQ 消息丢失时阻塞 loadData
      const docs = await Promise.race([
        ipc.report.listSubDocs({ taskId, commId: 'overall' }),
        new Promise<any>((_, reject) => setTimeout(() => reject(new Error('timeout')), 10000)),
      ])
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

  async function loadDashboard(taskId: string): Promise<DashboardData | null> {
    // 缓存命中
    if (dashboardCache.value[taskId]) return dashboardCache.value[taskId]
    // 在途去重
    const inflight = _inflightDashboard.get(taskId)
    if (inflight) return inflight
    // 标记加载
    loading.value = { ...loading.value, [taskId]: true }

    const promise = (async () => {
      try {
        console.log('[report-store] loadDashboard sending getReportDashboard', { taskId })
        const dash = await ipc.analysis.getReportDashboard(taskId)
        console.log('[report-store] loadDashboard received', { taskId, hasFileStats: !!dash?.fileStats, hasCallLevels: !!dash?.callLevels })
        if (dash) {
          dashboardCache.value = { ...dashboardCache.value, [taskId]: dash }
          // 注入社区数据到 communityStore
          const { useCommunityStore } = await import('./community-store')
          const commStore = useCommunityStore()
          if (dash.callLevels || dash.depLevels || dash.fileStats) {
            console.log('[report-store] loadDashboard calling loadCommunitiesFromDashboard')
            await commStore.loadCommunitiesFromDashboard(taskId, dash)
            console.log('[report-store] loadDashboard loadCommunitiesFromDashboard done')
          }
          // 加载外部依赖统计（并行，不阻塞）
          commStore.loadExternalStats(taskId).catch(() => {})
        }
        loading.value = { ...loading.value, [taskId]: false }
        return dash
      } catch (e) {
        console.warn('[report-store] loadDashboard failed, fallback to direct IPC', { taskId, error: (e as any)?.message })
        // 备路径：dashboard 失败，回退到独立 IPC
        loading.value = { ...loading.value, [taskId]: false }
        const analysisStore = useAnalysisStore()
        const projectStore = useProjectStore()
        const pid = projectStore.selectedProjectId || ''
        if (!pid) return null
        try {
          const [task, fileStats] = await Promise.all([
            analysisStore.getTask(taskId),
            analysisStore.scanFileStats(pid),
          ])
          const { useCommunityStore } = await import('./community-store')
          const commStore = useCommunityStore()
          await commStore.loadCommunities(taskId, pid)
          const fallback: DashboardData = {
            task, fileStats,
            callLevels: null, depLevels: null,
            callResults: { results: [] }, depResults: { results: [] },
            preSummary: { counts: { P0: 0, P1: 0, P2: 0 }, total_files: 0, cached_count: 0, project_root: '' },
          }
          dashboardCache.value = { ...dashboardCache.value, [taskId]: fallback }
          return fallback
        } catch (e2) {
          console.error('[reportStore] loadDashboard fallback also failed:', e2)
          return null
        }
      } finally {
        _inflightDashboard.delete(taskId)
      }
    })()

    _inflightDashboard.set(taskId, promise)
    return promise
  }

  function invalidateDashboard(taskId?: string) {
    if (taskId) {
      const copy = { ...dashboardCache.value }
      delete copy[taskId]
      dashboardCache.value = copy
    } else {
      dashboardCache.value = {}
    }
  }

  async function getFileSummaries(params: { projectId: string; taskId?: string; source?: string }) {
    return await ipc.report.getFileSummaries(params)
  }

  async function saveFileSummaries(params: { projectId: string; taskId: string; summaries: Array<{ filePath: string; summary: string; source?: string }> }) {
    return await ipc.report.saveFileSummaries(params)
  }

  return {
    generatedReports, dbReportExists, loading, dashboardCache,
    setGeneratedReport, checkReportExists,
    getReadmeContent, extractDependencyFiles, generateProjectSummary, getProjectSummary, saveProjectSummary,
    getLevelCommunityDetail, updateCommunityName,
    getSubDoc, updateSubDoc, createSubDoc,
    getFileSummaries, saveFileSummaries,
    loadDashboard, invalidateDashboard,
  }
})
