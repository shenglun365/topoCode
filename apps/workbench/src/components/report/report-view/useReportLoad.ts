/**
 * useReport · load 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { useAnalysisStore } from '@/stores/analysis'
import { useProjectStore } from '@/stores/project'
import { useReportStore } from '@/stores/report-store'
import { ref } from 'vue'
import { ipc } from '@/services/ipc'
import { useI18n } from 'vue-i18n'

import type { ReportDeps } from './chatTypes'

export function useReportLoad(D: ReportDeps) {
  const projectStore = useProjectStore()
  const analysisStore = useAnalysisStore()
  const reportStore = useReportStore()
  const { t } = useI18n()
  const props = D.props
  const emit = D.emit

const loading = ref(true)
const loadError = ref<string | null>(null)
const projectSummary = ref<any>(null)
const taskDetail = ref<any>(null)
const fileStats = ref<Record<string, number>>({})
const totalScopeFiles = ref(0)

const projectSummaryText = ref('')
const projectSummaryDate = ref('')
const showSummaryModal = ref(false)
const editingSummary = ref(false)
const editSummaryText = ref('')

// 文件预摘要状态（来自 dashboard，轮询刷新）
const overviewDocId = ref('')
const overviewPreview = ref('')
const overviewLoading = ref(false)
let overviewPollTimer: ReturnType<typeof setTimeout> | null = null

async function loadOverviewDoc(silent = false) {
  if (!props.taskId) return false
  if (!silent) overviewLoading.value = true
  try {
    // 10s 客户端超时，避免 ZMQ 消息丢失时无限等待
    const result = await Promise.race([
      ipc.report.listSubDocs({ taskId: props.taskId, commId: 'overall' }),
      new Promise<any>((_, reject) => setTimeout(() => reject(new Error('timeout')), 10000)),
    ])
    const docs = result || []
    if (docs.length > 0) {
      const doc = docs[0]
      overviewDocId.value = doc.id || ''
      overviewPreview.value = (doc.title || doc.name || '').slice(0, 100)
      return true
    }
  } catch { /* ignore */ }
  finally { if (!silent) overviewLoading.value = false }
  return false
}

async function loadOverviewDocAndPoll() {
  const found = await loadOverviewDoc(false)
  if (!found) startOverviewPoll()
}

let overviewRetries = 0
const OVERVIEW_POLL_MAX_RETRIES = 3
const OVERVIEW_POLL_INITIAL_MS = 1000

function startOverviewPoll() {
  stopOverviewPoll()
  overviewRetries = 0
  scheduleOverviewPoll()
}

function scheduleOverviewPoll() {
  if (overviewRetries >= OVERVIEW_POLL_MAX_RETRIES) return
  const delay = OVERVIEW_POLL_INITIAL_MS * Math.pow(2, overviewRetries)
  overviewRetries++
  overviewPollTimer = setTimeout(async () => {
    const found = await loadOverviewDoc(true)
    if (!found) scheduleOverviewPoll()
  }, delay)
}

function stopOverviewPoll() {
  if (overviewPollTimer !== null) {
    clearTimeout(overviewPollTimer)
    overviewPollTimer = null
  }
}

function openOverviewDoc() {
  if (!overviewDocId.value) return
  emit('open-md', {
    taskId: props.taskId,
    content: '',
    title: t('report.architectureOverview'),
    subDocId: overviewDocId.value,
  })
}

async function loadData() {
  loading.value = true
  loadError.value = null
  reportStore.invalidateDashboard(props.taskId)
  projectSummary.value = projectStore.selectedProject
  try {
    taskDetail.value = await analysisStore.getTask(props.taskId)
    if (!taskDetail.value) {
      loadError.value = t('report.taskNotFound')
      return
    }
    const pid = taskDetail.value?.projectId || projectStore.selectedProjectId

    // 并行：项目信息 + 项目概要 + dashboard（三者独立）
    const [projInfo, projSummary, dash] = await Promise.all([
      pid ? ipc.project.get(pid).catch(() => projectStore.selectedProject || null) : Promise.resolve(null),
      pid ? reportStore.getProjectSummary(pid).catch(() => null) : Promise.resolve(null),
      pid ? reportStore.loadDashboard(props.taskId) : Promise.resolve(null),
    ])

    if (projInfo) projectSummary.value = projInfo
    if (projSummary?.summary) {
      projectSummaryText.value = projSummary.summary
      projectSummaryDate.value = projSummary.generated_at || ''
    }

    if (dash) {
      // 文件统计（从 dashboard 获取，避免额外 scanFileStats）
      fileStats.value = dash.fileStats?.extensions || {}

      // 按任务条件统计文件数（用作覆盖率分母）— 与 dashboard 已并行
      const task = taskDetail.value
      if (pid) {
        const scanOptions: Record<string, any> = {}
        const exts: string[] = JSON.parse(JSON.stringify(task?.extensions || []))
        const scopes: string[] = JSON.parse(JSON.stringify(task?.scopes || []))
        const excludeDirs: string[] = JSON.parse(JSON.stringify(task?.excludeDirs || []))
        if (exts.length > 0) scanOptions.selectedExtensions = exts
        if (scopes.length > 0) scanOptions.scopes = scopes
        if (excludeDirs.length > 0) scanOptions.excludeDirs = excludeDirs
        if (task?.patternType && task.patternType !== 'all') scanOptions.patternType = task.patternType
        if (task?.pattern) scanOptions.pattern = task.pattern
        try {
          const fs = await analysisStore.scanFileStats(pid, scanOptions)
          totalScopeFiles.value = fs?.totalFiles || 0
        } catch {
          totalScopeFiles.value = dash?.fileStats?.totalFiles || 0
        }
      }

      // 预摘要状态
      D.presum.setPreSummaryFromDashboard(dash)
      D.presum.startPreSummaryPoll()
    }

    // 检查报告 + 概览文档（与上面不冲突）
    await Promise.all([
      reportStore.checkReportExists(props.taskId),
      loadOverviewDocAndPoll(),
    ])
  } catch (e: any) {
    console.error('[ReportHome] loadData error:', e)
    loadError.value = e?.message || 'Failed to load data'
  } finally {
    loading.value = false
  }
}

  return {
    OVERVIEW_POLL_INITIAL_MS,
    OVERVIEW_POLL_MAX_RETRIES,
    editSummaryText,
    editingSummary,
    fileStats,
    loadData,
    loadError,
    loadOverviewDoc,
    loadOverviewDocAndPoll,
    loading,
    openOverviewDoc,
    overviewDocId,
    overviewLoading,
    overviewPollTimer,
    overviewPreview,
    overviewRetries,
    projectSummary,
    projectSummaryDate,
    projectSummaryText,
    scheduleOverviewPoll,
    showSummaryModal,
    startOverviewPoll,
    stopOverviewPoll,
    taskDetail,
    totalScopeFiles,
  }
}
