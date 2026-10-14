<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch, provide } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentMagnifyingGlassIcon,
  ChartBarIcon,
  ExclamationTriangleIcon,
  XMarkIcon,
  MinusIcon,
  PlusIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'

import { useReportStore } from '@/stores/report-store'
import { useCommunityStore, type CommunityItem, agentCompletedSignal } from '@/stores/community-store'
import { ipc } from '@/services/ipc'
import { displayDispatcher } from '@/services/display-dispatcher'
import ProjectSummaryCard from '@/components/home/ProjectSummaryCard.vue'
import CommunitySection from '@/components/report/CommunitySection.vue'
import CommunityArchitecturePanel from '@/components/report/CommunityArchitecturePanel.vue'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()
const communityStore = useCommunityStore()
const reportStore = useReportStore()

import { useReportLoad } from './report-view/useReportLoad'
import { useReportUi } from './report-view/useReportUi'
import { useReportPresum } from './report-view/useReportPresum'
import type { ReportDeps } from './report-view/chatTypes'
import { WS_KEY } from './report-view/key'
import ReportMainPanel from './report-view/panels/ReportMainPanel.vue'

const props = defineProps<{
  taskId: string
  tabId: string
}>()

const projectId = computed(() => projectStore.selectedProjectId || taskDetail.value?.projectId || '')

const emit = defineEmits<{
  'open-md': [params: { taskId: string; content: string; title: string; subDocId?: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string }]
  'open-presummary': [taskId: string]
}>()

onMounted(() => { loadData() })

// ---- MS6-W3: 逻辑层2域(report-view/)——本文件保留 props/emit/模板 ----
const D: ReportDeps = { props, emit }
D.load = useReportLoad(D)
D.presum = useReportPresum(D)
D.ui = useReportUi(D)
const ws = Object.assign({}, D.load, D.presum, D.ui)
provide(WS_KEY, ws)
provide(WS_KEY, ws)
const {
  MAX_VISIBLE_TAGS,
  OVERVIEW_POLL_INITIAL_MS,
  OVERVIEW_POLL_MAX_RETRIES,
  allExtensions,
  allScopes,
  batchBarStyle,
  editSummaryText,
  editingSummary,
  fileStats,
  hasMoreExtensions,
  hasMoreScopes,
  loadData,
  loadError,
  loadOverviewDoc,
  loadOverviewDocAndPoll,
  loading,
  openOverviewDoc,
  openSummaryModal,
  overviewDocId,
  overviewLoading,
  overviewPollTimer,
  overviewPreview,
  overviewRetries,
  preSummaryLoading,
  preSummaryStatus,
  projectSummary,
  projectSummaryDate,
  projectSummaryText,
  refreshPreSummary,
  saveSummary,
  scheduleOverviewPoll,
  setPreSummaryFromDashboard,
  showScopeModal,
  showSummaryModal,
  startOverviewPoll,
  startPreSummaryPoll,
  stopOverviewPoll,
  stopPreSummaryPoll,
  taskDetail,
  totalScopeFiles,
  visibleExtensions,
  visibleScopes,
  hasAnyCommunity,
  depCommunityCount,
  callCommunityCount,
  externalStats,
  coveredFileCount,
  coveragePercent,
  showId,
  componentId,
  collapsed,
  toggleCollapse,
  truncatePath,
  handleCommunityMD,
} = ws

onUnmounted(() => { stopPreSummaryPoll(); stopOverviewPoll() })
watch(() => props.taskId, () => {
  stopPreSummaryPoll()
  stopOverviewPoll()
  reportStore.invalidateDashboard(props.taskId)
  loadData()
})
// agent 完成时刷新概览文档、项目摘要和仪表盘（不依赖初始 7s 轮询窗口）
watch(agentCompletedSignal, async () => {
  loadOverviewDoc(true)
  startOverviewPoll()
  if (props.taskId) {
    reportStore.invalidateDashboard(props.taskId)
    reportStore.loadDashboard(props.taskId).then((dash) => {
      if (dash) {
        setPreSummaryFromDashboard(dash)
        fileStats.value = dash.fileStats?.extensions || {}
      }
    })
    reportStore.checkReportExists(props.taskId)
  }
  // 刷新项目摘要（流水线可能在 AST 阶段无模型时未执行摘要）
  const pid = projectId.value
  if (pid) {
    const projSummary = await reportStore.getProjectSummary(pid).catch(() => null)
    if (projSummary?.summary) {
      projectSummaryText.value = projSummary.summary
      projectSummaryDate.value = projSummary.generated_at || ''
    }
  }
})
</script>

<template>
  <ReportMainPanel
      :project-id="projectId"
      :task-id="props.taskId"
      :tab-id="props.tabId"
      @open-md="(p: any) => emit('open-md', p)"
      @open-presummary="(taskId: string) => emit('open-presummary', taskId)"
    />
</template>
