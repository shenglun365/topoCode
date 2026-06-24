<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
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
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'
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

const props = defineProps<{
  taskId: string
  tabId: string
}>()

const projectId = computed(() => projectStore.selectedProjectId || taskDetail.value?.projectId || '')

const emit = defineEmits<{
  'open-md': [params: { taskId: string; content: string; title: string; subDocId?: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string }]
  'open-presummary': [taskId: string]
}>()

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
    const result = await ipc.report.listSubDocs({ taskId: props.taskId, commId: 'overall' })
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

function startOverviewPoll() {
  stopOverviewPoll()
  overviewPollTimer = setInterval(async () => {
    const found = await loadOverviewDoc(true)
    if (found) stopOverviewPoll()
  }, 5000)
}

function stopOverviewPoll() {
  if (overviewPollTimer !== null) {
    clearInterval(overviewPollTimer)
    overviewPollTimer = null
  }
}

function openOverviewDoc() {
  if (!overviewDocId.value) return
  emit('open-md', {
    taskId: props.taskId,
    content: '',
    title: t('report.architectureOverview', '架构概览'),
    subDocId: overviewDocId.value,
  })
}

const preSummaryStatus = ref<{
  total_files: number
  cached_count: number
  failed_count?: number
  counts: Record<string, number>
  batch_cached: Record<string, number>
  project_root: string
} | null>(null)

const preSummaryLoading = computed(() => preSummaryStatus.value === null)

// 分析范围截断
const MAX_VISIBLE_TAGS = 5
const showScopeModal = ref(false)
const allExtensions = computed(() => taskDetail.value?.extensions || [])
const allScopes = computed(() => taskDetail.value?.scopes || [])
const hasMoreExtensions = computed(() => allExtensions.value.length > MAX_VISIBLE_TAGS)
const hasMoreScopes = computed(() => allScopes.value.length > MAX_VISIBLE_TAGS)
const visibleExtensions = computed(() => hasMoreExtensions.value ? allExtensions.value.slice(0, MAX_VISIBLE_TAGS) : allExtensions.value)
const visibleScopes = computed(() => hasMoreScopes.value ? allScopes.value.slice(0, MAX_VISIBLE_TAGS) : allScopes.value)

function setPreSummaryFromDashboard(dash: any) {
  if (dash?.preSummary) {
    preSummaryStatus.value = {
      total_files: dash.preSummary.total_files,
      cached_count: dash.preSummary.cached_count,
      failed_count: dash.preSummary.failed_count || 0,
      counts: dash.preSummary.counts || { P0: 0, P1: 0, P2: 0 },
      batch_cached: dash.preSummary.batch_cached || { P0: 0, P1: 0, P2: 0 },
      project_root: dash.preSummary.project_root || '',
    }
  }
}

function batchBarStyle(batch: string) {
  const s = preSummaryStatus.value
  if (!s?.batch_cached || !s.counts) return {}
  const cached = s.batch_cached[batch] || 0
  const total = s.counts[batch] || 1
  const pct = Math.min(100, Math.round(cached / total * 100))
  const isP0 = batch === 'P0'
  const isP1 = batch === 'P1'
  const filled = isP0 ? 'color-mix(in srgb, var(--accent) 55%, transparent)'
    : isP1 ? 'color-mix(in srgb, var(--warning) 55%, transparent)'
    : 'color-mix(in srgb, var(--text-muted) 35%, transparent)'
  const unfilled = isP0 ? 'color-mix(in srgb, var(--accent) 10%, transparent)'
    : isP1 ? 'color-mix(in srgb, var(--warning) 10%, transparent)'
    : 'var(--bg-tertiary)'
  return {
    background: `linear-gradient(to right, ${filled} ${pct}%, ${unfilled} ${pct}%)`,
  }
}

async function refreshPreSummary() {
  if (!props.taskId) return
  try {
    const status = await communityStore.getPreSummaryStatus(props.taskId)
    if (status) preSummaryStatus.value = status
  } catch { /* ignore */ }
}

function startPreSummaryPoll() {
  const key = `pre-summary:${props.taskId}`
  if (displayDispatcher.has(key)) return
  refreshPreSummary()
  displayDispatcher.register(key, {
    interval: 10000,
    fetcher: () => communityStore.getPreSummaryStatus(props.taskId).then(s => s || {}),
    onData: (status) => {
      if (status && Object.keys(status).length > 0) {
        preSummaryStatus.value = status
      }
    },
  })
}

function stopPreSummaryPoll() {
  if (!props.taskId) return
  displayDispatcher.unregister(`pre-summary:${props.taskId}`)
}

const project = computed(() => projectSummary.value || projectStore.selectedProject)
const task = computed(() => taskDetail.value)

const hasAnyCommunity = computed(() => {
  const coms = communityStore.tasks[props.taskId]?.communities || []
  return coms.length > 0
})

const depCommunityCount = computed(() =>
  (communityStore.tasks[props.taskId]?.communities || []).filter(c => c.edgeType === 'INCLUDE').length
)
const callCommunityCount = computed(() =>
  (communityStore.tasks[props.taskId]?.communities || []).filter(c => c.edgeType === 'CALL').length
)

const externalStats = computed(() =>
  communityStore.tasks[props.taskId]?.externalStats || null
)

const coveredFileCount = computed(() => {
  const counts = communityStore.tasks[props.taskId]?.uniqueFileCounts
  if (counts) {
    const included = Math.max((counts['INCLUDE'] ?? 0), (counts['CALL'] ?? 0))
    return Math.min(included, totalScopeFiles.value)
  }
  return 0
})

const coveragePercent = computed(() => {
  if (!totalScopeFiles.value) return 0
  return Math.round((coveredFileCount.value / totalScopeFiles.value) * 100)
})

const { showId, componentId } = useComponentId('RP-001')

const COLLAPSE_STORAGE_KEY = 'report-home-collapsed'

function loadCollapsed(): { project: boolean; task: boolean } {
  try {
    const raw = localStorage.getItem(COLLAPSE_STORAGE_KEY)
    if (raw) return JSON.parse(raw)
  } catch {}
  return { project: false, task: false }
}

function saveCollapsed(state: { project: boolean; task: boolean }) {
  localStorage.setItem(COLLAPSE_STORAGE_KEY, JSON.stringify(state))
}

const collapsed = ref<{ project: boolean; task: boolean }>(loadCollapsed())

function toggleCollapse(section: 'project' | 'task') {
  collapsed.value[section] = !collapsed.value[section]
  saveCollapsed(collapsed.value)
}

function truncatePath(p: string): string {
  if (!p || p.length <= 35) return p || '-'
  return p.slice(0, 10) + '…' + p.slice(-20)
}

async function handleCommunityMD(params: {
  communityId: string; name: string; summary: string;
  mermaid?: string; plantuml?: string;
  parentLevel?: string; parentCommId?: string; parentEdgeType?: string;
}) {
  const parts: string[] = [
    `# 社区: ${params.name}`,
    '',
    `**ID**: ${params.communityId}`,
    '',
    params.summary,
  ]
  if (params.mermaid) {
    parts.push('', '```mermaid', params.mermaid, '```')
  }
  if (params.plantuml) {
    parts.push('', '```plantuml', params.plantuml, '```')
  }
  emit('open-md', {
    taskId: props.taskId,
    content: parts.join('\n'),
    title: params.name,
    parentLevel: params.parentLevel,
    parentCommId: params.parentCommId,
    parentEdgeType: params.parentEdgeType,
  })
}
async function loadData() {
  loading.value = true
  loadError.value = null
  // 切换 task 时强制清除 dashboard 缓存，避免读旧数据
  reportStore.invalidateDashboard(props.taskId)
  projectSummary.value = projectStore.selectedProject
  try {
    taskDetail.value = await analysisStore.getTask(props.taskId)
    if (!taskDetail.value) {
      loadError.value = t('report.taskNotFound')
      return
    }
    const pid = taskDetail.value?.projectId || projectStore.selectedProjectId
    if (pid) {
      projectSummary.value = await ipc.project.get(pid).catch(() => projectStore.selectedProject || null)
      const ps = await reportStore.getProjectSummary(pid).catch(() => null)
      if (ps?.summary) {
        projectSummaryText.value = ps.summary
        projectSummaryDate.value = ps.generated_at || ''
      }
    }

    // 统一 dashboard 加载（含主/备路径、社区数据注入、预摘要状态）
    if (pid) {
      const dash = await reportStore.loadDashboard(props.taskId)

      // 文件统计（从 dashboard 或独立查询）
      if (dash?.fileStats) {
        fileStats.value = dash.fileStats.extensions || {}
      } else {
        const fs = await analysisStore.scanFileStats(pid).catch(() => null)
        if (fs) {
          fileStats.value = fs.extensions || {}
        }
      }

      // 按任务条件（extensions / scopes / excludeDirs / pattern）统计文件数，用作覆盖率分母
      {
        const task = taskDetail.value as any
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
          console.log('[ReportHome] scopeFiles: options=%o totalFiles=%d', scanOptions, fs?.totalFiles)
          totalScopeFiles.value = fs?.totalFiles || 0
        } catch {
          totalScopeFiles.value = dash?.fileStats?.totalFiles || 0
          console.warn('[ReportHome] scanFileStats failed, fallback to dash.fileStats.totalFiles=%d', totalScopeFiles.value)
        }
      }

      // 预摘要状态（来自 dashboard）
      setPreSummaryFromDashboard(dash)

      // 启动预摘要轮询（如有 running agent 会自动保持；否则单次后停止）
      startPreSummaryPoll()
    }
    await reportStore.checkReportExists(props.taskId)
    await loadOverviewDocAndPoll()
  } catch (e: any) {
    console.error('[ReportHome] loadData error:', e)
    loadError.value = e?.message || 'Failed to load data'
  } finally {
    loading.value = false
  }
}

function openSummaryModal() {
  editSummaryText.value = projectSummaryText.value
  editingSummary.value = false
  showSummaryModal.value = true
}

async function saveSummary() {
  const pid = taskDetail.value?.projectId || projectStore.selectedProjectId
  if (!pid) return
  try {
    const result = await reportStore.saveProjectSummary(pid, editSummaryText.value)
    if (result?.success) {
      projectSummaryText.value = result.summary
      projectSummaryDate.value = result.generated_at
      showSummaryModal.value = false
      editingSummary.value = false
    }
  } catch (e: any) {
    console.error('[ReportHome] saveSummary error:', e)
  }
}



onMounted(() => { loadData() })
onUnmounted(() => { stopPreSummaryPoll(); stopOverviewPoll() })
watch(() => props.taskId, () => {
  stopPreSummaryPoll()
  stopOverviewPoll()
  reportStore.invalidateDashboard(props.taskId)
  loadData()
})
</script>

<template>
  <div class="report-home">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <template v-if="loading">
      <div class="loading-state">
        <div class="loading-spinner" />
        <span>{{ t('common.loading') }}</span>
      </div>
    </template>

    <div
      v-else-if="loadError"
      class="load-error"
    >
      <ExclamationTriangleIcon class="w-4 h-4" />
      <span>{{ loadError }}</span>
      <button
        class="btn btn-ghost btn-xs"
        @click="loadData"
      >
        {{ t('common.retry') }}
      </button>
    </div>

    <template v-else>
      <div class="report-home-scroll">
        <!-- 项目概要 + 任务概要 折叠容器 -->
        <div
          v-if="collapsed.project || collapsed.task"
          class="collapsed-tags"
        >
          <button
            v-if="collapsed.project"
            class="collapsed-tag"
            @click="toggleCollapse('project')"
          >
            <PlusIcon class="w-3 h-3" />
            <span>{{ t('report.projectSummary') }}: {{ project?.name || '-' }}</span>
          </button>
          <button
            v-if="collapsed.task"
            class="collapsed-tag"
            @click="toggleCollapse('task')"
          >
            <PlusIcon class="w-3 h-3" />
            <span>架构概览: {{ task?.name || '-' }}</span>
          </button>
        </div>

        <!-- 项目概要 -->
        <ProjectSummaryCard
          v-if="!collapsed.project"
          :project-name="project?.name || '-'"
          :language="project?.language || '-'"
          :file-count="project?.fileCount || 0"
          :root-path="project?.rootPath || project?.path || '-'"
          :show-minimize="true"
          @minimize="toggleCollapse('project')"
        />

        <!-- 架构概览 -->
        <section
          v-if="!collapsed.task"
          class="home-section"
        >
          <div class="section-header">
            <ChartBarIcon class="w-4 h-4" />
            <span>{{ t('report.architectureOverview', '架构概览') }}</span>
            <div class="header-spacer" />
            <button
              class="collapse-btn"
              :title="t('common.minimize', '最小化')"
              @click="toggleCollapse('task')"
            >
              <MinusIcon class="w-3.5 h-3.5" />
            </button>
          </div>
          <div class="summary-cards">
            <div class="summary-card">
              <span class="card-label">{{ t('analysis.taskName') }}</span>
              <span class="card-value">{{ task?.name || '-' }}</span>
            </div>
            <div
              class="summary-card clickable"
              :class="{ 'summary-empty': !overviewDocId }"
              @click="openOverviewDoc"
            >
              <span class="card-label">架构概览</span>
              <span
                v-if="overviewLoading"
                class="card-value card-summary-empty"
              >{{ t('common.loading', '加载中...') }}</span>
              <span
                v-else-if="overviewDocId"
                class="card-value"
              >              ><span class="status-text status-green">已生成 可查看</span></span>
              <span
                v-else
                class="card-value card-summary-empty"
              ><span class="status-text status-orange">未生成</span></span>
            </div>
            <div class="summary-card">
              <span class="card-label">{{ t('analysis.taskStatus') }}</span>
              <span
                class="card-value status-badge"
                :class="task?.status"
              >{{ task?.status }}</span>
            </div>
            <div class="summary-card">
              <span class="card-label">{{ t('analysis.createdAt') }}</span>
              <span class="card-value">{{ task?.createdAt ? new Date(task.createdAt).toLocaleString() : '-' }}</span>
            </div>
            <div
              class="summary-card summary-card-wide clickable"
              :class="{ 'summary-empty': !projectSummaryText }"
              @click="openSummaryModal"
            >
              <span class="card-label">{{ t('report.aiSummary') }}</span>
              <span
                v-if="projectSummaryText"
                class="card-value card-summary-preview"
              >{{ projectSummaryText.slice(0, 100) }}{{ projectSummaryText.length > 100 ? '…' : '' }}</span>
              <span
                v-else
                class="card-value card-summary-empty"
              >{{ t('report.pipeline.generateProjectSummaryHint') }}</span>
            </div>
          </div>

          <div class="summary-cards-bottom">
            <div
              class="summary-card summary-card-half clickable presummary-card"
              :class="{ 'presummary-loading': preSummaryLoading, 'presummary-empty': !preSummaryStatus }"
              @click="preSummaryStatus && emit('open-presummary', props.taskId)"
            >
              <div class="ps-header-row">
                <span class="card-label">{{ t('report.filePreSummary') }}</span>
                <span class="card-summary-hint">{{ t('report.preSummaryViewDetails') }}</span>
              </div>
              <template v-if="preSummaryLoading">
                <span class="card-value card-summary-empty">{{ t('common.loading') }}</span>
              </template>
              <template v-else-if="preSummaryStatus">
                <div class="ps-summary-stat">
                  {{ t('report.preSummaryProgress') }}: {{ preSummaryStatus.cached_count }}/{{ preSummaryStatus.total_files }}
                  <span v-if="preSummaryStatus.total_files > 0" class="presummary-pct">
                    ({{ Math.round(preSummaryStatus.cached_count / preSummaryStatus.total_files * 100) }}%)
                  </span>
                  <span v-if="preSummaryStatus.failed_count" class="presummary-failed">
                    失败: {{ preSummaryStatus.failed_count }}
                  </span>
                </div>
                <div class="ps-batches-compact">
                  <span
                    class="presummary-batch presummary-batch-p0"
                    :style="batchBarStyle('P0')"
                  >
                    P0: {{ preSummaryStatus.counts?.P0 || 0 }} ({{ preSummaryStatus.counts?.P0 ? Math.round((preSummaryStatus.batch_cached?.P0 || 0) / preSummaryStatus.counts.P0 * 100) : 0 }}%)
                  </span>
                  <span
                    class="presummary-batch presummary-batch-p1"
                    :style="batchBarStyle('P1')"
                  >
                    P1: {{ preSummaryStatus.counts?.P1 || 0 }} ({{ preSummaryStatus.counts?.P1 ? Math.round((preSummaryStatus.batch_cached?.P1 || 0) / preSummaryStatus.counts.P1 * 100) : 0 }}%)
                  </span>
                  <span
                    class="presummary-batch presummary-batch-p2"
                    :style="batchBarStyle('P2')"
                  >
                    P2: {{ preSummaryStatus.counts?.P2 || 0 }} ({{ preSummaryStatus.counts?.P2 ? Math.round((preSummaryStatus.batch_cached?.P2 || 0) / preSummaryStatus.counts.P2 * 100) : 0 }}%)
                  </span>
                </div>
              </template>
              <template v-else>
                <span class="card-value card-summary-empty">{{ t('common.loading') }}</span>
              </template>
            </div>
            <div
              class="summary-card summary-card-half summary-card-scope"
              @click="showScopeModal = true"
            >
              <div class="card-label-row">
                <span class="card-label">{{ t('report.analysisScope') }}</span>
                <span class="scope-view-detail">{{ t('analysis.viewDetail') }}</span>
              </div>
              <div class="scope-compact">
                <div class="scope-compact-row">
                  <span class="scope-compact-label">{{ t('analysis.fileType') }}</span>
                  <div class="scope-compact-tags">
                    <span
                      v-if="!taskDetail?.extensions?.length"
                      class="scope-tag scope-tag-all"
                    >{{ t('analysis.allFiles') }}</span>
                    <span
                      v-for="ext in (visibleExtensions)"
                      :key="ext"
                      class="scope-tag"
                    >{{ ext }} <span class="scope-tag-count">{{ fileStats[ext] ?? '-' }}</span></span>
                    <span
                      v-if="hasMoreExtensions"
                      class="scope-tag scope-tag-more"
                    >...</span>
                  </div>
                </div>
                <div class="scope-compact-row">
                  <span class="scope-compact-label">{{ t('analysis.directoryScope') }}</span>
                  <div class="scope-compact-tags">
                    <span
                      v-if="!taskDetail?.scopes?.length"
                      class="scope-tag scope-tag-all"
                    >{{ t('analysis.allDirectories') }}</span>
                    <span
                      v-for="s in (visibleScopes)"
                      :key="s"
                      class="scope-tag"
                    >{{ s }}</span>
                    <span
                      v-if="hasMoreScopes"
                      class="scope-tag scope-tag-more"
                    >...</span>
                  </div>
                </div>
              </div>
            </div>
            <!-- 分析范围详情弹窗 -->
            <div
              v-if="showScopeModal"
              class="dialog-overlay"
              @click.self="showScopeModal = false"
            >
              <div class="dialog-content scope-dialog">
                <div class="scope-dialog-header">
                  <span>{{ t('report.analysisScope') }}</span>
                  <button
                    class="icon-btn"
                    @click="showScopeModal = false"
                  >
                    <XMarkIcon class="w-4 h-4" />
                  </button>
                </div>
                <div class="scope-dialog-body">
                  <div class="scope-dialog-section">
                    <h4>{{ t('analysis.fileType') }}</h4>
                    <div class="scope-dialog-tags">
                      <span
                        v-if="!taskDetail?.extensions?.length"
                        class="scope-tag scope-tag-all"
                      >{{ t('analysis.allFiles') }}</span>
                      <span
                        v-for="ext in (taskDetail?.extensions || [])"
                        :key="ext"
                        class="scope-tag scope-tag-lg"
                      >{{ ext }} <span class="scope-tag-count">{{ fileStats[ext] ?? '-' }}</span></span>
                    </div>
                  </div>
                  <div class="scope-dialog-section">
                    <h4>{{ t('analysis.directoryScope') }}</h4>
                    <div class="scope-dialog-tags">
                      <span
                        v-if="!taskDetail?.scopes?.length"
                        class="scope-tag scope-tag-all"
                      >{{ t('analysis.allDirectories') }}</span>
                      <span
                        v-for="s in (taskDetail?.scopes || [])"
                        :key="s"
                        class="scope-tag scope-tag-lg"
                      >{{ s }}</span>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- 组件架构 — Tag/Graph 双模式 — 填充剩余空间 -->
      <div class="report-arch-panel">
        <CommunityArchitecturePanel
          :task-id="props.taskId"
          :tab-id="props.tabId"
          :project-id="projectId"
          :task-updated-at="taskDetail?.updatedAt || ''"
          :has-any-community="hasAnyCommunity"
          :total-scope-files="totalScopeFiles"
          :coverage-percent="coveragePercent"
          :covered-file-count="coveredFileCount"
          :dep-community-count="depCommunityCount"
          :call-community-count="callCommunityCount"
          :external-stats="externalStats"
          @open-md="(p) => emit('open-md', p)"
        />
      </div>

      <!-- 项目摘要弹窗 -->
      <div
        v-if="showSummaryModal"
        class="dialog-overlay"
        @click.self="showSummaryModal = false"
      >
        <div class="dialog-content summary-dialog">
          <div class="summary-dialog-header">
            <DocumentMagnifyingGlassIcon class="w-5 h-5" />
            <span>{{ t('report.aiSummary') }}</span>
            <div class="summary-dialog-spacer" />
            <button
              v-if="!editingSummary"
              class="btn btn-ghost btn-xs"
              @click="editingSummary = true; editSummaryText = projectSummaryText"
            >
              {{ t('common.edit') }}
            </button>
            <button
              class="icon-btn summary-dialog-close"
              @click="showSummaryModal = false; editingSummary = false"
            >
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div
            class="summary-dialog-body"
            :class="{ 'summary-body-editing': editingSummary }"
          >
            <textarea
              v-if="editingSummary"
              v-model="editSummaryText"
              class="summary-textarea"
              :placeholder="t('report.pipeline.generateProjectSummaryHint')"
            />
            <template v-else>
              {{ projectSummaryText || t('report.pipeline.generateProjectSummaryHint') }}
            </template>
          </div>
          <div class="summary-dialog-footer">
            <span
              v-if="projectSummaryDate && !editingSummary"
              class="summary-dialog-date"
            >{{ projectSummaryDate }}</span>
            <div
              v-if="editingSummary"
              class="summary-dialog-actions"
            >
              <button
                class="btn btn-ghost btn-xs"
                @click="editingSummary = false; editSummaryText = projectSummaryText"
              >
                {{ t('common.cancel') }}
              </button>
              <button
                class="btn btn-primary btn-xs"
                @click="saveSummary"
              >
                {{ t('common.save') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.report-home {
  height: 100%;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.loading-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 12px;
}

.load-error {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--error);
  font-size: 12px;
  padding: 20px;
}

.report-home-scroll {
  flex: 0 1 auto;
  padding: 16px 20px;
  min-height: 0;
}
.report-arch-panel {
  flex: 1;
  min-height: 0;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
}

.home-section {
  margin-bottom: 20px;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  margin-bottom: 10px;
  padding-bottom: 6px;
  border-bottom: 1px solid var(--border);
}

.summary-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px 8px;
}

.summary-card {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
}

.card-label {
  font-size: 10px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.card-value {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.card-path {
  font-size: 11px;
  font-family: var(--font-mono);
  word-break: break-all;
}

.status-badge.done { color: var(--success); }
.status-badge.running { color: var(--accent); }
.status-badge.error { color: var(--error); }



.scope-tag {
  display: inline-block;
  padding: 1px 8px;
  background: var(--bg-tertiary);
  border: 1px solid var(--border);
  border-radius: 4px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.scope-tag-all {
  font-family: inherit;
  color: var(--text-muted);
}

.scope-tag-count {
  margin-left: 4px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 10px;
}

.scope-tag-more {
  background: transparent;
  border-color: transparent;
  color: var(--text-muted);
  font-weight: 600;
  letter-spacing: 1px;
}

.scope-dialog {
  max-width: 520px;
  max-height: 70vh;
}
.scope-dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  font-size: 13px;
  font-weight: 600;
}
.scope-dialog-body {
  padding: 12px 16px;
  overflow-y: auto;
}
.scope-dialog-section {
  margin-bottom: 16px;
}
.scope-dialog-section h4 {
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 8px;
  color: var(--text-primary);
}
.scope-dialog-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.scope-tag-lg {
  font-size: 11px;
  padding: 2px 10px;
}

.comm-et-tabs {
  display: flex; gap: 0; margin-bottom: 8px; border-bottom: 1px solid var(--border);
}
.comm-et-tab {
  flex: 1; padding: 4px 8px; text-align: center; font-size: 10px; font-weight: 500;
  color: var(--text-muted); background: transparent; border: none; cursor: pointer;
  border-bottom: 2px solid transparent; transition: all 0.15s;
}
.comm-et-tab:hover { color: var(--text-primary); background: var(--bg-tertiary); }
.comm-et-tab.active { color: var(--accent); border-bottom-color: var(--accent); }

.comm-stats {
  display: flex; gap: 10px; margin-bottom: 8px; flex-wrap: wrap;
}
.comm-stat {
  display: flex; align-items: center; gap: 3px;
  font-size: 10px; color: var(--text-muted); font-family: var(--font-mono);
}

.community-items {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.community-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 2px 8px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 10px;
  font-size: 10px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
}

.community-chip:hover {
  border-color: var(--accent);
  background: color-mix(in srgb, var(--accent) 8%, transparent);
}
.community-chip.has-result { border-color: var(--accent); }
.community-chip.has-result .chip-name { color: var(--success); }

.chip-name {
  color: var(--text-primary);
  max-width: 100px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.chip-count {
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 9px;
}

.comm-empty {
  font-size: 10px; color: var(--text-muted); padding: 4px 0;
}

/* Community search */
.comm-search { margin-bottom: 8px; }
.comm-search-input {
  width: 100%; padding: 4px 8px; font-size: 11px; border: 1px solid var(--border);
  border-radius: 4px; background: var(--bg-primary); color: var(--text-primary); outline: none;
  box-sizing: border-box;
}
.comm-search-input:focus { border-color: var(--accent); }

/* Quality hint */
.quality-stat { cursor: help; position: relative; }
.quality-hint { font-size: 9px; color: var(--text-muted); margin-left: 2px; }

/* Community pagination */
.comm-pagination {
  display: flex; align-items: center; justify-content: center; gap: 8px;
  margin-top: 8px; padding-top: 6px; border-top: 1px solid var(--border);
}
.comm-page-info { font-size: 10px; color: var(--text-muted); font-family: var(--font-mono); }

.model-warning {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  margin-bottom: 8px;
  background: color-mix(in srgb, var(--warning) 10%, transparent);
  border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
  border-radius: 6px;
  font-size: 11px;
  color: var(--warning);
}

.actions-section .actions-row {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

/* DOM dialog */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.dialog-content {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 24px;
  min-width: 300px;
  max-width: 400px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
}

.dialog-warning-icon {
  color: var(--warning);
}

.dialog-message {
  font-size: 13px;
  color: var(--text-primary);
  text-align: center;
  line-height: 1.5;
}

.dialog-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

/* Component analysis button with progress bar */
.comp-analysis-btn {
  position: relative;
  overflow: hidden;
}

.comp-analysis-progress {
  position: absolute;
  inset: 0;
  background: color-mix(in srgb, #74eca0 22%, transparent);
  transition: width 0.4s ease;
  pointer-events: none;
}

.comp-analysis-btn :deep(.btn-content),
.comp-analysis-btn > *:not(.comp-analysis-progress) {
  position: relative;
  z-index: 1;
}

.comp-analysis-pct {
  font-size: 9px;
  font-family: var(--font-mono);
  color: var(--text-muted);
  position: relative;
  z-index: 1;
}

/* Overall architecture button: light green when content available */
.btn-has-result {
  background: color-mix(in srgb, #74eca0 18%, transparent);
  border-color: color-mix(in srgb, #74eca0 30%, transparent);
  color: var(--text-primary);
}

.btn-has-result:hover {
  background: color-mix(in srgb, #74eca0 28%, transparent);
  border-color: color-mix(in srgb, #74eca0 40%, transparent);
}

.summary-card-wide {
  grid-column: 1 / -1;
}

.summary-card.clickable {
  cursor: pointer;
  transition: border-color 0.15s;
}

.summary-card.clickable:hover {
  border-color: var(--accent);
}

.presummary-card {
  gap: 4px;
}
.presummary-loading {
  opacity: 0.6;
}
.presummary-empty {
  opacity: 0.6;
  cursor: default;
}
.presummary-pct {
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
}
.presummary-failed {
  margin-left: 6px;
  font-size: 11px;
  color: var(--color-danger, #e74c3c);
}
.ps-summary-stat {
  font-size: 11px;
  color: var(--text-primary);
}

.ps-header-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.ps-batches-compact {
  display: flex;
  gap: 4px;
}
.presummary-batch {
  padding: 0px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-family: var(--font-mono);
  line-height: 1.6;
  white-space: nowrap;
}
.presummary-batch-p0 {
  background: color-mix(in srgb, var(--accent) 15%, transparent);
  color: var(--accent);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
}
.presummary-batch-p1 {
  background: color-mix(in srgb, var(--warning) 15%, transparent);
  color: var(--warning);
  border: 1px solid color-mix(in srgb, var(--warning) 30%, transparent);
}
.presummary-batch-p2 {
  background: var(--bg-tertiary);
  color: var(--text-muted);
  border: 1px solid var(--border);
}
.card-summary-hint {
  font-size: 10px;
  color: var(--text-muted);
  font-style: italic;
  margin-top: 1px;
}

.summary-cards-bottom {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px 8px;
  margin-top: 12px;
}
.summary-card-half {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
}
.summary-card-scope {
  gap: 4px;
  cursor: pointer;
}
.card-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
}
.scope-view-detail {
  font-size: 10px;
  color: var(--text-muted);
  font-style: italic;
}
.scope-compact {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.scope-compact-row {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 10px;
}
.scope-compact-label {
  flex-shrink: 0;
  width: 48px;
  color: var(--text-muted);
  padding-top: 1px;
}
.scope-compact-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 3px;
}

.summary-empty {
  opacity: 0.6;
}

.card-summary-preview {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-secondary);
  line-height: 1.5;
}

.card-summary-empty {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-muted);
  font-style: italic;
}

/* 状态文本颜色（柔和） */
.status-text { font-size: 12px; font-weight: 500; }
.status-green { color: #5a9e6f; }
.status-orange { color: #c08a4b; }

/* Project summary dialog */
.summary-dialog {
  width: 560px;
  max-width: 90vw;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  padding: 0;
  align-items: stretch;
}

.summary-dialog-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 14px 16px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
  border-bottom: 1px solid var(--border);
}

.summary-dialog-spacer {
  flex: 1;
}

.summary-dialog-close {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  cursor: pointer;
  color: var(--text-muted);
  background: transparent;
  border: none;
}

.summary-dialog-close:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.summary-dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-primary);
  white-space: pre-wrap;
  min-height: 120px;
}

.summary-body-editing {
  padding: 16px;
}

.summary-textarea {
  width: 100%;
  min-height: 280px;
  padding: 8px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--bg-primary);
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.7;
  resize: vertical;
  outline: none;
  font-family: inherit;
  box-sizing: border-box;
}

.summary-textarea:focus {
  border-color: var(--accent);
}

.summary-dialog-footer {
  display: flex;
  align-items: center;
  padding: 8px 16px;
  font-size: 10px;
  color: var(--text-muted);
  border-top: 1px solid var(--border);
  gap: 8px;
}

.summary-dialog-date {
  flex: 1;
}

.summary-dialog-actions {
  display: flex;
  gap: 6px;
  margin-left: auto;
}

/* Collapse / minimize */
.collapse-btn {
  display: flex; align-items: center; justify-content: center;
  width: 22px; height: 22px; padding: 0;
  background: transparent; border: 1px solid transparent; border-radius: 0.25rem;
  color: var(--text-muted); cursor: pointer; transition: all 0.15s;
}
.collapse-btn:hover { background: var(--bg-tertiary); color: var(--text-primary); border-color: var(--border); }

.collapsed-tags {
  display: flex; flex-wrap: wrap; gap: 0.35rem; margin-bottom: 0.5rem;
}
.collapsed-tag {
  display: flex; align-items: center; gap: 0.3rem;
  padding: 0.2rem 0.5rem; border-radius: 0.375rem;
  background: var(--bg-secondary); border: 1px solid var(--border);
  font-size: 0.75rem; color: var(--text-muted); cursor: pointer;
  transition: all 0.15s; white-space: nowrap;
}
.collapsed-tag:hover { border-color: var(--accent, #7c3aed); color: var(--text-primary); background: var(--bg-accent-subtle, #2d1f5e); }
</style>
