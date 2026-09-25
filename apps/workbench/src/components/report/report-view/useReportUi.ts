/**
 * ReportHome · UI 派生域（MS6-W4 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore } from '@/stores/community-store'
import { useProjectStore } from '@/stores/project'
import { useComponentId } from '@/composables/useComponentId'
import type { ReportDeps } from './chatTypes'

export function useReportUi(D: ReportDeps) {
  const { t } = useI18n()
  const communityStore = useCommunityStore()
  const projectStore = useProjectStore()
  const props = D.props
  const emit = D.emit

const project = computed(() => D.load.projectSummary.value || projectStore.selectedProject)
const task = computed(() => D.load.taskDetail.value)

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
    // 组件统一：优先 UNIFIED 口径，兼容旧双线键
    const included = counts['UNIFIED'] ?? 0
    return Math.min(included, D.load.totalScopeFiles.value)
  }
  return 0
})

const coveragePercent = computed(() => {
  if (!D.load.totalScopeFiles.value) return 0
  return Math.round((coveredFileCount.value / D.load.totalScopeFiles.value) * 100)
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
    t('report.communityHeading', { name: params.name }),
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

  return {
    project, task, hasAnyCommunity, depCommunityCount, callCommunityCount,
    externalStats, coveredFileCount, coveragePercent,
    showId, componentId, collapsed, toggleCollapse, truncatePath, handleCommunityMD,
  }
}
