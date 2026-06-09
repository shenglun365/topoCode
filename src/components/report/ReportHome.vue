<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextIcon,
  DocumentMagnifyingGlassIcon,
  ChartBarIcon,
  FolderIcon,
  RectangleGroupIcon,
  SparklesIcon,
  ExclamationTriangleIcon,
  HashtagIcon,
  ListBulletIcon,
  XMarkIcon,
} from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import { useModelConfigStore } from '@/stores/model-config-store'
import { useFuncGroupStore } from '@/stores/funcGroup'

import { useReportStore } from '@/stores/report-store'
import { useCommunityStore, type CommunityItem } from '@/stores/community-store'
import { ipc } from '@/services/ipc'
import ProjectSummaryCard from '@/components/home/ProjectSummaryCard.vue'
import TaskSummaryCard from '@/components/home/TaskSummaryCard.vue'
import ActionsBar from '@/components/home/ActionsBar.vue'
import CommunitySection from '@/components/report/CommunitySection.vue'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const panelStore = usePanelStore()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()
const modelConfigStore = useModelConfigStore()
const funcGroup = useFuncGroupStore()
const communityStore = useCommunityStore()
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
const expandedComms = ref<Set<string>>(new Set())

const depCommunityCount = computed(() =>
  (communityStore.tasks[props.taskId]?.communities || []).filter(c => c.level === 'L0' && c.edgeType === 'INCLUDE').length
)
const callCommunityCount = computed(() =>
  (communityStore.tasks[props.taskId]?.communities || []).filter(c => c.level === 'L0' && c.edgeType === 'CALL').length
)

function toggleArchComm(id: string) {
  if (expandedComms.value.has(id)) {
    expandedComms.value.delete(id)
  } else {
    expandedComms.value.add(id)
  }
}

function getArchChildren(communityId: string): CommunityItem[] {
  const all = communityStore.tasks[props.taskId]?.communities || []
  return all.filter(c => c.parentId === communityId)
}
const projectSummaryText = ref('')
const projectSummaryDate = ref('')
const showSummaryModal = ref(false)
const editingSummary = ref(false)
const editSummaryText = ref('')

const hasModel = computed(() => modelConfigStore.models.some(m => m.isDefault))
const project = computed(() => projectSummary.value || projectStore.selectedProject)
const task = computed(() => taskDetail.value)

const hasAnyCommunity = computed(() => {
  const coms = communityStore.tasks[props.taskId]?.communities || []
  return coms.length > 0
})

  const runtimeCommunities = computed(() => {
    const coms = communityStore.tasks[props.taskId]?.communities || []
    const filtered = coms.filter(c => c.level === 'L0' && c.edgeType === commEdgeType.value)
  console.log(`[RP-001] runtimeCommunities edgeType=${commEdgeType.value} total=${coms.length} filtered=${filtered.length} completed=${filtered.filter(c=>c.status==='completed').length}`)
  return filtered
})

  const communityAnalysisProgress = computed(() => {
    const allL0 = (communityStore.tasks[props.taskId]?.communities || []).filter(c => c.level === 'L0')
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
  } catch (e: any) {
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
      const ps = await reportStore.getProjectSummary(pid).catch(() => null)
      if (ps?.summary) {
        projectSummaryText.value = ps.summary
        projectSummaryDate.value = ps.generated_at || ''
      }
    }
    await communityStore.loadCommunities(props.taskId, pid || '')
    await reportStore.checkReportExists(props.taskId)
    console.log(`[RP-001] loadData DONE communities=${(communityStore.tasks[props.taskId]?.communities || []).length}`)
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
  const pid = projectStore.selectedProjectId || taskDetail.value?.projectId
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

function closeAllSubDocTabs() {
  const ctx = funcGroup.context.analysis
  const toClose = ctx.tabs.filter(t => t.kind === 'subdoc' && (t as any).taskId === props.taskId)
  for (const tab of toClose) {
    funcGroup.closeTab('analysis', tab.id)
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
  } catch (e: any) {
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
  const coms = communityStore.tasks[props.taskId]?.communities || []
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
    } catch (e: any) {
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
  } catch (e: any) {
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
        <ProjectSummaryCard
          :project-name="project?.name || '-'"
          :language="project?.language || '-'"
          :file-count="project?.fileCount || 0"
          :root-path="project?.rootPath || project?.path || '-'"
        />

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

        <!-- 组件架构 — 分视角（依赖/调用）、分层级 -->
        <section v-if="hasAnyCommunity" class="home-section arch-section">
          <div class="section-header">
            <RectangleGroupIcon class="w-4 h-4" />
            <span>{{ t('report.communityArchitecture', '组件架构') }}</span>
            <span class="arch-stats">
              {{ runtimeCommunities.length }} {{ t('report.l0Communities', '个L0社区') }}
            </span>
          </div>

          <!-- INCLUDE / CALL 切换 -->
          <div class="arch-tabs">
            <button
              class="arch-tab" :class="{ active: commEdgeType === 'INCLUDE' }"
              @click="commEdgeType = 'INCLUDE'"
            >
              <FolderIcon class="w-3.5 h-3.5" />
              {{ t('report.dependencyAnalysis', '依赖分析') }} ({{ depCommunityCount }})
            </button>
            <button
              class="arch-tab" :class="{ active: commEdgeType === 'CALL' }"
              @click="commEdgeType = 'CALL'"
            >
              <ChartBarIcon class="w-3.5 h-3.5" />
              {{ t('report.callAnalysis', '调用分析') }} ({{ callCommunityCount }})
            </button>
          </div>

          <!-- 社区层级列表 -->
          <div class="arch-tree">
            <div
              v-for="item in runtimeCommunities"
              :key="item.id"
              class="arch-comm"
            >
              <div
                class="arch-comm-header"
                :class="{ expanded: expandedComms.has(item.id) }"
                @click="toggleArchComm(item.id)"
              >
                <span class="arch-expand">{{ expandedComms.has(item.id) ? '▾' : '▸' }}</span>
                <span class="arch-comm-name">{{ item.name || formatCommId(item) }}</span>
                <span class="arch-comm-meta">
                  {{ item.nodeCount }} nodes
                  <span v-if="item.edgeCount" class="arch-edge-count">{{ item.edgeCount }} edges</span>
                </span>
                <span v-if="item.nodeCount > 20" class="arch-badge arch-badge-hub" title="Hub community">HUB</span>
                <span v-else-if="item.nodeCount < 4" class="arch-badge arch-badge-small">small</span>
                <span v-if="item.qualityScore" class="arch-score" :class="{ high: item.qualityScore > 0.6 }">
                  {{ (item.qualityScore * 100).toFixed(0) }}%
                </span>
              </div>

              <!-- 子社区 (展开时显示) -->
              <div v-if="expandedComms.has(item.id)" class="arch-children">
                <div
                  v-for="child in getArchChildren(item.communityId)"
                  :key="child.id"
                  class="arch-child"
                >
                  <span class="arch-child-name">{{ child.name || child.communityId }}</span>
                  <span class="arch-child-meta">{{ child.nodeCount }}n</span>
                </div>
                <div v-if="getArchChildren(item.communityId).length === 0" class="arch-no-children">
                  {{ t('report.noSubCommunities', '无子社区') }}
                </div>
              </div>
            </div>
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
            <button
              class="btn btn-ghost"
              title="关闭本报告所有文档页"
              @click="closeAllSubDocTabs"
            >
              <XMarkIcon class="w-4 h-4" />
              <span>{{ t('report.closeAllDocs') }}</span>
            </button>

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

/* Architecture section */
.arch-stats { font-size: 0.75rem; color: var(--text-muted); margin-left: auto; font-weight: 400; }
.arch-tabs { display: flex; gap: 0; margin-bottom: 0.75rem; border-bottom: 2px solid var(--border); }
.arch-tab {
  display: flex; align-items: center; gap: 0.35rem;
  padding: 0.4rem 0.9rem; font-size: 0.8rem; color: var(--text-muted);
  border: none; background: none; cursor: pointer;
  border-bottom: 2px solid transparent; margin-bottom: -2px; transition: all 0.15s;
}
.arch-tab:hover { color: var(--text-primary); }
.arch-tab.active { color: var(--accent, #7c3aed); border-bottom-color: var(--accent, #7c3aed); }
.arch-tree { max-height: 400px; overflow-y: auto; }
.arch-comm { border-bottom: 1px solid var(--border); }
.arch-comm:last-child { border-bottom: none; }
.arch-comm-header {
  display: flex; align-items: center; gap: 0.4rem; padding: 0.4rem 0.25rem;
  cursor: pointer; font-size: 0.8rem; transition: background 0.1s;
}
.arch-comm-header:hover { background: var(--bg-secondary); }
.arch-expand { width: 0.75rem; font-size: 0.65rem; color: var(--text-muted); flex-shrink: 0; }
.arch-comm-name { flex: 1; font-weight: 500; color: var(--text-primary); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arch-comm-meta { font-size: 0.7rem; color: var(--text-muted); flex-shrink: 0; }
.arch-edge-count { margin-left: 0.3rem; color: var(--text-muted); }
.arch-badge { font-size: 0.6rem; border-radius: 0.25rem; padding: 0.1rem 0.3rem; font-weight: 600; }
.arch-badge-hub { background: var(--accent, #7c3aed); color: #fff; }
.arch-badge-small { background: var(--bg-secondary); color: var(--text-muted); }
.arch-score { font-size: 0.65rem; color: var(--text-muted); }
.arch-score.high { color: #22c55e; }
.arch-children { padding-left: 1.2rem; border-top: 1px solid var(--border-subtle, #2a2a3e); }
.arch-child { display: flex; justify-content: space-between; padding: 0.2rem 0.5rem; font-size: 0.75rem; color: var(--text-secondary); }
.arch-child:hover { background: var(--bg-secondary); }
.arch-child-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.arch-child-meta { font-size: 0.65rem; color: var(--text-muted); flex-shrink: 0; }
.arch-no-children { padding: 0.3rem 0.5rem; font-size: 0.7rem; color: var(--text-muted); font-style: italic; }
</style>
