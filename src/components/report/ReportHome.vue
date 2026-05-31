<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextIcon,
  ChartBarIcon,
  FolderIcon,
  RectangleGroupIcon,
  SparklesIcon,
  ExclamationTriangleIcon,
  HashtagIcon,
  ListBulletIcon,
} from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import { useSettingsStore } from '@/stores/settings'
import { useFuncGroupStore } from '@/stores/funcGroup'

import { useReportStore, type CommunityItem } from '@/stores/report'
import { ipc } from '@/services/ipc'
import ReportGenerationPipeline from './ReportGenerationPipeline.vue'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const panelStore = usePanelStore()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()
const settingsStore = useSettingsStore()
const funcGroup = useFuncGroupStore()
const reportStore = useReportStore()

const props = defineProps<{
  taskId: string
}>()

const projectId = computed(() => projectStore.selectedProjectId || taskDetail.value?.projectId || '')

const emit = defineEmits<{
  'open-md': [params: { taskId: string; content: string; title: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string; regenerationType?: 'community' | 'overall' }]
}>()

const loading = ref(true)
const loadError = ref<string | null>(null)
const showNoReportDialog = ref(false)
const projectSummary = ref<any>(null)
const taskDetail = ref<any>(null)
const commEdgeType = ref<'INCLUDE' | 'CALL'>('INCLUDE')
const communitySearch = ref('')
const communityPage = ref(1)
const communityPageSize = 100

const hasModel = computed(() => settingsStore.models.some(m => m.isDefault))
const project = computed(() => projectSummary.value || projectStore.selectedProject)
const task = computed(() => taskDetail.value)

const runtimeCommunities = computed(() => {
  const coms = reportStore.tasks[props.taskId]?.communities || []
  const filtered = coms.filter(c => c.level === 'L0' && c.edgeType === commEdgeType.value)
  console.log(`[RP-001] runtimeCommunities edgeType=${commEdgeType.value} total=${coms.length} filtered=${filtered.length} completed=${filtered.filter(c=>c.status==='completed').length}`)
  return filtered
})

const communityAnalysisProgress = computed(() => {
  const allL0 = (reportStore.tasks[props.taskId]?.communities || []).filter(c => c.level === 'L0')
  if (allL0.length === 0) return 0
  const done = allL0.filter(c => c.status === 'completed').length
  const pct = Math.round((done / allL0.length) * 100)
  console.log(`[RP-001] communityAnalysisProgress allL0=${allL0.length} done=${done} pct=${pct}`)
  return pct
})

const hasArchitectureReport = computed(() => {
  if (reportStore.generatedReports[props.taskId]) return true
  return !!reportStore.dbReportExists[props.taskId]
})

const commStats = computed(() => {
  const items = communityItems.value
  const nodes = items.map(c => c.nodeCount || 0)
  const quals = items.map(c => c.qualityScore).filter((q): q is number => q != null)
  const stats = {
    count: items.length,
    maxNodes: nodes.length ? Math.max(...nodes) : 0,
    minNodes: nodes.length ? Math.min(...nodes) : 0,
    avgQuality: quals.length ? (quals.reduce((a, b) => a + b, 0) / quals.length) : 0,
  }
  console.log(`[RP-001] commStats count=${stats.count} maxNodes=${stats.maxNodes} minNodes=${stats.minNodes} avgQuality=${stats.avgQuality}`)
  return stats
})

const communityItems = computed(() => {
  const q = communitySearch.value.trim().toLowerCase()
  if (!q) return runtimeCommunities.value
  return runtimeCommunities.value.filter(c => {
    const id = c.communityId.toLowerCase()
    const name = (c.name || '').toLowerCase()
    return id.includes(q) || name.includes(q)
  })
})

const communityTotalPages = computed(() => Math.max(1, Math.ceil(communityItems.value.length / communityPageSize)))
const pagedCommunityItems = computed(() => {
  const start = (communityPage.value - 1) * communityPageSize
  return communityItems.value.slice(start, start + communityPageSize)
})

watch(communitySearch, () => { communityPage.value = 1 })

const { showId, componentId } = useComponentId('RP-001')

function truncatePath(p: string): string {
  if (!p || p.length <= 35) return p || '-'
  return p.slice(0, 10) + '…' + p.slice(-20)
}

function formatCommId(item: { id: string; level?: string }): string {
  const parts = item.id.split('-')
  const num = parts[parts.length - 1]
  const level = item.level || parts[parts.length - 2] || 'L0'
  return `${level}-${num}`
}

function commName(item: CommunityItem): string {
  const name = item.name && item.name !== item.communityId ? item.name : ''
  if (name) return name.length > 10 ? name.slice(0, 10) + '…' : name
  return formatCommId(item)
}

async function openCommunityDoc(item: CommunityItem) {
  try {
    if (item.name || item.summary) {
      handleCommunityMD({ communityId: item.communityId, name: item.name || formatCommId(item), summary: item.summary || '', mermaid: item.mermaid, plantuml: item.plantuml, parentLevel: item.level, parentCommId: item.communityId, parentEdgeType: commEdgeType.value })
      return
    }
    const pid = projectStore.selectedProjectId || taskDetail.value?.projectId
    if (!pid) return
    const detail = await reportStore.getLevelCommunityDetail({
      projectId: pid, taskId: props.taskId,
      level: item.level || 'L0', edgeType: commEdgeType.value,
    })
    const community = detail.communities.find((c: any) => c.communityId === item.communityId)
    if (!community) return
    const nodeLines = community.nodes.map((n: any) => `- ${n.name} (${n.filePath})`).join('\n')
    const edgeLines = community.edges.map((e: any) => `- ${e.source} → ${e.target} [${e.type}]`).join('\n')
    const md = [
      `# 社区: ${item.communityId}`,
      '',
      `**层级**: ${item.level || 'L0'} | **边缘类型**: ${commEdgeType.value}`,
      `**节点数**: ${community.nodeCount} | **边数**: ${community.edgeCount} | **质量分**: ${community.qualityScore ?? '-'}`,
      '',
      '## 节点列表',
      nodeLines || '（空）',
      '',
      '## 边列表',
      edgeLines || '（空）',
    ].join('\n')
    emit('open-md', {
      taskId: props.taskId,
      content: md,
      title: formatCommId(item),
      parentLevel: item.level,
      parentCommId: item.communityId,
      parentEdgeType: commEdgeType.value,
      regenerationType: 'community',
    })
  } catch (e) {
    console.error('[ReportHome] openCommunityDoc error:', e)
  }
}

function handleCommunityMD(params: { communityId: string; name: string; summary: string; mermaid?: string; plantuml?: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string }) {
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
    regenerationType: 'community',
  })
}

async function loadData() {
  console.log(`[RP-001] loadData ENTRY taskId=${props.taskId}`)
  loading.value = true
  loadError.value = null
  projectSummary.value = projectStore.selectedProject
  try {
    taskDetail.value = await analysisStore.getTask(props.taskId)
    if (!taskDetail.value) {
      console.log(`[RP-001] loadData task not found taskId=${props.taskId}`)
      loadError.value = t('report.taskNotFound')
      return
    }
    console.log(`[RP-001] loadData task found name=${taskDetail.value.name} type=${taskDetail.value.type}`)
    const pid = projectStore.selectedProjectId || taskDetail.value?.projectId
    if (pid) {
      projectSummary.value = await ipc.project.get(pid).catch(() => projectStore.selectedProject || null)
    }
    await reportStore.loadCommunities(props.taskId, pid || '')
    await reportStore.checkReportExists(props.taskId)
    console.log(`[RP-001] loadData DONE communities=${(reportStore.tasks[props.taskId]?.communities || []).length}`)
  } catch (e: any) {
    console.error('[ReportHome] loadData error:', e)
    loadError.value = e?.message || 'Failed to load data'
  } finally {
    loading.value = false
  }
}

function openTaskList() {
  panelStore.setRightCollapsed(false)
  panelStore.setRightTab('detail')
}

function openCommunityAnalysis() {
  const ctx = funcGroup.context.analysis
  const existing = ctx.tabs.find(
    t => t.kind === 'componentAnalysis' && (t as any).taskId === props.taskId
  )
  if (existing) {
    funcGroup.setActiveTab('analysis', existing.id)
    return
  }
  funcGroup.openTab('analysis', {
    id: `comp-analysis-${props.taskId}-${Date.now()}`,
    kind: 'componentAnalysis',
    title: t('report.pipeline.communityAnalysis'),
    taskId: props.taskId,
    projectId: projectId.value,
  })
}

async function handleReportGenerated(content: string) {
  reportStore.setGeneratedReport(props.taskId, content)
  try {
    await ipc.report.saveOverallDoc({
      taskId: props.taskId,
      title: t('report.pipeline.overallArchitecture'),
      content,
    })
  } catch (e) {
    console.warn('[ReportHome] saveOverallDoc on generated failed:', e)
  }
}

function escapeTbl(val: any): string {
  return String(val ?? '')
    .replace(/\|/g, '\\|')
    .replace(/\n/g, ' ')
    .replace(/^### /gm, '')
    .replace(/^- /gm, '')
    .replace(/\*\*(.*?)\*\*/g, '$1')
    .replace(/\*(.*?)\*/g, '$1')
    .replace(/`(.*?)`/g, '$1')
    .trim()
}

function buildCommunityAppendix(): string {
  const parts: string[] = ['## 组件附录', '']
  const edges: { key: 'CALL' | 'INCLUDE'; label: string }[] = [
    { key: 'CALL', label: '调用' },
    { key: 'INCLUDE', label: '依赖' },
  ]
  const coms = reportStore.tasks[props.taskId]?.communities || []
  let hasItems = false
  parts.push('| 类型 | 名称 |')
  parts.push('|------|------|')
  for (const et of edges) {
    const items = coms.filter(c => c.level === 'L0' && c.edgeType === et.key)
    for (const item of items) {
      hasItems = true
      const name = escapeTbl(item.name || item.communityId)
      parts.push(`| ${et.label} | [${name}](##community:${et.key}:${item.communityId}) |`)
    }
  }
  if (!hasItems) {
    parts.push('| - | （暂无组件数据） |')
  }
  parts.push('')
  return parts.join('\n')
}

async function openOverallArchitecture() {
  let content = reportStore.generatedReports[props.taskId]
  if (!content) {
    try {
      const docs = await ipc.report.listSubDocs({ taskId: props.taskId, commId: 'overall' })
      if (docs?.length) {
        const doc = await ipc.report.getSubDoc(docs[0].id)
        content = doc.content
      }
    } catch (e) {
      console.warn('[ReportHome] DB fetch for overall doc failed:', e)
    }
  }
  if (!content) {
    showNoReportDialog.value = true
    return
  }
  // 避免重复追加附录
  if (!content.includes('## 组件附录')) {
    content = content + '\n\n---\n\n' + buildCommunityAppendix()
  }
  let docId = ''
  try {
    const result = await ipc.report.saveOverallDoc({
      taskId: props.taskId,
      title: t('report.pipeline.overallArchitecture'),
      content,
    })
    docId = result.id
  } catch (e) {
    console.warn('[ReportHome] saveOverallDoc failed:', e)
  }
  const tabId = `tab-overall-arch-${props.taskId}`
  const ctx = funcGroup.context.analysis
  const existing = ctx.tabs.find(t => t.id === tabId)
  if (existing) {
    funcGroup.setActiveTab('analysis', existing.id)
    return
  }
  funcGroup.openTab('analysis', {
    id: tabId,
    kind: 'subdoc',
    title: t('report.pipeline.overallArchitecture'),
    content,
    taskId: props.taskId,
    projectId: projectId.value,
    subDocId: docId,
    hasUnsavedChanges: false,
    regenerationType: 'overall',
  })
}

onMounted(loadData)
watch(() => props.taskId, loadData)
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
        <!-- 项目概要 -->
        <section class="home-section">
          <div class="section-header">
            <FolderIcon class="w-4 h-4" />
            <span>{{ t('report.projectSummary') }}</span>
          </div>
          <div class="summary-cards">
            <div class="summary-card">
              <span class="card-label">{{ t('project.projectName') }}</span>
              <span class="card-value">{{ project?.name || '-' }}</span>
            </div>
            <div class="summary-card">
              <span class="card-label">{{ t('project.projectLanguage') }}</span>
              <span class="card-value">{{ project?.language || '-' }}</span>
            </div>
            <div class="summary-card">
              <span class="card-label">{{ t('project.fileCount') }}</span>
              <span class="card-value">{{ project?.fileCount || 0 }}</span>
            </div>
            <div class="summary-card">
              <span class="card-label">{{ t('project.projectPath') }}</span>
              <span
                class="card-value card-path"
                :title="project?.rootPath || project?.path || ''"
              >{{ truncatePath(project?.rootPath || project?.path) }}</span>
            </div>
          </div>
        </section>

        <!-- 任务概要 -->
        <section class="home-section">
          <div class="section-header">
            <ChartBarIcon class="w-4 h-4" />
            <span>{{ t('report.taskSummary') }}</span>
          </div>
          <div class="summary-cards">
            <div class="summary-card">
              <span class="card-label">{{ t('analysis.taskName') }}</span>
              <span class="card-value">{{ task?.name || '-' }}</span>
            </div>
            <div class="summary-card">
              <span class="card-label">{{ t('analysis.taskType') }}</span>
              <span class="card-value">{{ task?.type || '-' }}</span>
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
          </div>

          <div class="file-distribution">
            <div class="dist-title">
              {{ t('report.analysisScope') }}
            </div>
            <div class="scope-content">
              <div class="scope-row">
                <span class="scope-label">{{ t('analysis.fileType') }}</span>
                <div class="scope-tags">
                  <span
                    v-if="!taskDetail?.extensions?.length"
                    class="scope-tag scope-tag-all"
                  >{{ t('analysis.allFiles') }}</span>
                  <span
                    v-for="ext in (taskDetail?.extensions || [])"
                    :key="ext"
                    class="scope-tag"
                  >{{ ext }}</span>
                </div>
              </div>
              <div class="scope-row">
                <span class="scope-label">{{ t('analysis.directoryScope') }}</span>
                <div class="scope-tags">
                  <span
                    v-if="!taskDetail?.scopes?.length"
                    class="scope-tag scope-tag-all"
                  >{{ t('analysis.allDirectories') }}</span>
                  <span
                    v-for="s in (taskDetail?.scopes || [])"
                    :key="s"
                    class="scope-tag"
                  >{{ s }}</span>
                </div>
              </div>
            </div>
          </div>
        </section>

        <!-- 社区概要 -->
        <section
          v-if="runtimeCommunities.length > 0"
          class="home-section"
        >
          <div class="section-header">
            <RectangleGroupIcon class="w-4 h-4" />
            <span>{{ t('report.communitySummary') }}</span>
          </div>
          <!-- 边类型切换 -->
          <div class="comm-et-tabs">
            <button
              :class="['comm-et-tab', { active: commEdgeType === 'INCLUDE' }]"
              @click="commEdgeType = 'INCLUDE'"
            >
              {{ t('report.pipeline.edgeInclude') }}
            </button>
            <button
              :class="['comm-et-tab', { active: commEdgeType === 'CALL' }]"
              @click="commEdgeType = 'CALL'"
            >
              {{ t('report.pipeline.edgeCall') }}
            </button>
          </div>
          <!-- L0统计 -->
          <div class="comm-stats">
            <span class="comm-stat">
              <HashtagIcon class="w-3 h-3" /> {{ commStats.count }}
            </span>
            <span class="comm-stat">{{ t('report.communityMaxNodes') }}: {{ commStats.maxNodes }}</span>
            <span class="comm-stat">{{ t('report.communityMinNodes') }}: {{ commStats.minNodes }}</span>
            <span
              class="comm-stat quality-stat"
              :title="'质量分反映社区内聚度，分值越高组件间区分度越好。平均约 ' + (commStats.avgQuality ? commStats.avgQuality.toFixed(3) : '-')"
            >
              {{ t('report.communityAvgQuality') }}: {{ commStats.avgQuality ? commStats.avgQuality.toFixed(3) : '-' }}
              <span class="quality-hint">ⓘ</span>
            </span>
          </div>
          <!-- 社区搜索 -->
          <div class="comm-search">
            <input
              v-model="communitySearch"
              type="text"
              placeholder="搜索组件名称/ID..."
              class="comm-search-input"
            >
          </div>
          <!-- L0 社区列表 -->
          <div class="community-items">
            <template v-if="pagedCommunityItems.length > 0">
              <div
                v-for="item in pagedCommunityItems"
                :key="item.id"
                class="community-chip"
                :class="{ 'has-result': item.status === 'completed' && !!(item.name) && item.name !== item.communityId }"
                :title="`${item.communityId} (${item.nodeCount} 节点, 质量: ${item.qualityScore ?? '-'})`"
                @click="openCommunityDoc(item)"
              >
                <span class="chip-name">{{ commName(item) }}</span>
                <span class="chip-count">{{ item.nodeCount }}</span>
              </div>
            </template>
            <div
              v-else
              class="comm-empty"
            >
              {{ t('report.pipeline.noCommunities') }}
            </div>
          </div>
          <!-- 组件分页 -->
          <div
            v-if="communityTotalPages > 1"
            class="comm-pagination"
          >
            <button
              class="btn btn-ghost btn-xs"
              :disabled="communityPage <= 1"
              @click="communityPage--"
            >
              上一页
            </button>
            <span class="comm-page-info">{{ communityPage }} / {{ communityTotalPages }}</span>
            <button
              class="btn btn-ghost btn-xs"
              :disabled="communityPage >= communityTotalPages"
              @click="communityPage++"
            >
              下一页
            </button>
          </div>
        </section>

        <!-- 操作区 -->
        <section class="home-section actions-section">
          <div class="section-header">
            <SparklesIcon class="w-4 h-4" />
            <span>{{ t('report.generateReport') }}</span>
          </div>

          <!-- LLM API 校验提示 -->
          <div
            v-if="!hasModel"
            class="model-warning"
          >
            <ExclamationTriangleIcon class="w-4 h-4" />
            <span>{{ t('report.llmNotConfigured') }}</span>
          </div>

          <div class="actions-row">
            <button
              class="btn btn-primary"
              @click="openTaskList"
            >
              <ListBulletIcon class="w-4 h-4" />
              <span>{{ t('report.openTaskList') }}</span>
            </button>
            <button
              class="btn btn-secondary comp-analysis-btn"
              @click="openCommunityAnalysis"
            >
              <span
                class="comp-analysis-progress"
                :style="{ width: communityAnalysisProgress + '%' }"
              />
              <SparklesIcon class="w-4 h-4" />
              <span>{{ t('report.pipeline.communityAnalysis') }}</span>
              <span
                v-if="communityAnalysisProgress > 0"
                class="comp-analysis-pct"
              >{{ communityAnalysisProgress }}%</span>
            </button>
            <button
              :class="['btn', hasArchitectureReport ? 'btn-has-result' : 'btn-secondary']"
              @click="openOverallArchitecture"
            >
              <DocumentTextIcon class="w-4 h-4" />
              <span>{{ t('report.viewOverallArchitecture') }}</span>
            </button>

          </div>

          <!-- 生成流水线（隐藏，后台同步） -->
          <div style="display:none">
            <ReportGenerationPipeline
              :task-id="props.taskId"
              :project-id="props.projectId"
              @generated="handleReportGenerated"
              @view-community-md="handleCommunityMD"
            />
          </div>
        </section>
      </div>

      <!-- 生成报告提示弹窗 -->
      <div
        v-if="showNoReportDialog"
        class="dialog-overlay"
        @click.self="showNoReportDialog = false"
      >
        <div class="dialog-content">
          <ExclamationTriangleIcon class="w-5 h-5 dialog-warning-icon" />
          <p class="dialog-message">{{ t('report.noArchitectureReport') }}</p>
          <div class="dialog-actions">
            <button
              class="btn btn-primary btn-sm"
              @click="showNoReportDialog = false"
            >
              {{ t('common.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.report-home {
  height: 100%;
  overflow: hidden;
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
  flex: 1;
  overflow-y: auto;
  padding: 16px 20px;
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
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
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

.file-distribution {
  margin-top: 12px;
}

.dist-title {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.scope-content {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.scope-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 11px;
}

.scope-label {
  flex-shrink: 0;
  width: 56px;
  color: var(--text-muted);
  padding-top: 2px;
}

.scope-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

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
</style>
