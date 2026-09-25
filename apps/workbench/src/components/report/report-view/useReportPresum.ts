/**
 * useReport · presum 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { useCommunityStore, type CommunityItem, agentCompletedSignal } from '@/stores/community-store'
import { useProjectStore } from '@/stores/project'
import { useReportStore } from '@/stores/report-store'
import { ref, computed } from 'vue'
import { displayDispatcher } from '@/services/display-dispatcher'

import type { ReportDeps } from './chatTypes'

export function useReportPresum(D: ReportDeps) {
  const projectStore = useProjectStore()
  const communityStore = useCommunityStore()
  const reportStore = useReportStore()
  const props = D.props

const preSummaryStatus = ref<{
  total_files: number
  cached_count: number
  failed_count?: number
  counts: Record<string, number>
  batch_cached?: Record<string, number>
  project_root: string
} | null>(null)

const preSummaryLoading = computed(() => preSummaryStatus.value === null)

// 分析范围截断
const MAX_VISIBLE_TAGS = 5
const showScopeModal = ref(false)
const allExtensions = computed(() => D.load.taskDetail.value?.extensions || [])
const allScopes = computed(() => D.load.taskDetail.value?.scopes || [])
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
      counts: dash.preSummary.counts || { P0: 0, P1: 0, P2: 0, P3: 0 },
      batch_cached: dash.preSummary.batch_cached || { P0: 0, P1: 0, P2: 0, P3: 0 },
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
    onError: () => {
      displayDispatcher.unregister(key)
    },
  })
}

function stopPreSummaryPoll() {
  if (!props.taskId) return
  displayDispatcher.unregister(`pre-summary:${props.taskId}`)
}

function openSummaryModal() {
  D.load.editSummaryText.value = D.load.projectSummaryText.value
  D.load.editingSummary.value = false
  D.load.showSummaryModal.value = true
}

async function saveSummary() {
  const pid = D.load.taskDetail.value?.projectId || projectStore.selectedProjectId
  if (!pid) return
  try {
    const result = await reportStore.saveProjectSummary(pid, D.load.editSummaryText.value)
    if (result?.success) {
      D.load.projectSummaryText.value = result.summary
      D.load.projectSummaryDate.value = result.generated_at
      D.load.showSummaryModal.value = false
      D.load.editingSummary.value = false
    }
  } catch (e: any) {
    console.error('[ReportHome] saveSummary error:', e)
  }
}

  return {
    MAX_VISIBLE_TAGS,
    allExtensions,
    allScopes,
    batchBarStyle,
    hasMoreExtensions,
    hasMoreScopes,
    openSummaryModal,
    preSummaryLoading,
    preSummaryStatus,
    refreshPreSummary,
    saveSummary,
    setPreSummaryFromDashboard,
    showScopeModal,
    startPreSummaryPoll,
    stopPreSummaryPoll,
    visibleExtensions,
    visibleScopes,
  }
}
