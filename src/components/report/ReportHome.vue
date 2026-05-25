<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextIcon,
  ChartBarIcon,
  FolderIcon,
  RectangleGroupIcon,
  SparklesIcon,
  ArrowPathIcon,
  ExclamationTriangleIcon,
  Cog6ToothIcon,
  HashtagIcon,
  ListBulletIcon,
} from '@heroicons/vue/24/outline'
import { usePanelStore } from '@/stores/panel'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import { useSettingsStore } from '@/stores/settings'
import { ipc } from '@/services/ipc'
import ReportGenerationPipeline from './ReportGenerationPipeline.vue'
import ReportMDViewer from './ReportMDViewer.vue'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const panelStore = usePanelStore()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()
const settingsStore = useSettingsStore()

const props = defineProps<{
  taskId: string
}>()

const projectId = computed(() => projectStore.selectedProjectId || taskDetail.value?.projectId || '')

const emit = defineEmits<{
  'open-md': [params: { taskId: string; content: string; title: string }]
}>()

const loading = ref(true)
const loadError = ref<string | null>(null)
const projectSummary = ref<any>(null)
const taskDetail = ref<any>(null)
const communityDataCall = ref<any>(null)
const communityDataInclude = ref<any>(null)
const communityResultsCall = ref<Record<string, any>>({})
const communityResultsInclude = ref<Record<string, any>>({})
const fileStats = ref<any>(null)
const generatedReport = ref<string | null>(null)
const commEdgeType = ref<'INCLUDE' | 'CALL'>('INCLUDE')
const communitySearch = ref('')
const communityPage = ref(1)
const communityPageSize = 100

const hasModel = computed(() => settingsStore.models.some(m => m.isDefault))
const project = computed(() => projectSummary.value || projectStore.selectedProject)
const task = computed(() => taskDetail.value)

const commData = computed(() => commEdgeType.value === 'INCLUDE' ? communityDataInclude.value : communityDataCall.value)
const commResults = computed(() => (commEdgeType.value === 'INCLUDE' ? communityResultsInclude : communityResultsCall).value)

interface CommStats { count: number; maxNodes: number; minNodes: number; avgQuality: number }
const commStats = computed<CommStats>(() => {
  const levels = commData.value?.levels
  if (!levels) return { count: 0, maxNodes: 0, minNodes: 0, avgQuality: 0 }
  const all = levels.flatMap((lv: any) => lv.items || [])
  const nodes = all.map((i: any) => i.nodeCount || 0)
  const quals = all.filter((i: any) => i.qualityScore != null).map((i: any) => i.qualityScore)
  return {
    count: all.length,
    maxNodes: nodes.length ? Math.max(...nodes) : 0,
    minNodes: nodes.length ? Math.min(...nodes) : 0,
    avgQuality: quals.length ? (quals.reduce((a: number, b: number) => a + b, 0) / quals.length) : 0,
  }
})

const communityItems = computed(() => {
  const items = commData.value?.levels?.[0]?.items || []
  const q = communitySearch.value.trim().toLowerCase()
  if (!q) return items
  return items.filter((item: any) => {
    const id = item.id.toLowerCase()
    const name = (commResults.value[item.id]?.name || '').toLowerCase()
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

function commName(item: { id: string }): string {
  const result = commResults.value[item.id]
  const raw = result?.name || result?.name_manual || ''
  const name = raw && raw !== item.id ? raw : ''
  if (name) return name.length > 10 ? name.slice(0, 10) + '…' : name
  return formatCommId(item)
}

async function openCommunityDoc(item: any) {
  try {
    const result = commResults.value[item.id]
    if (result?.name || result?.summary) {
      handleCommunityMD({ communityId: item.id, name: result.name || result.name_manual || formatCommId(item), summary: result.summary || '', mermaid: result.mermaid, plantuml: result.plantuml })
      return
    }
    const pid = projectStore.selectedProjectId || taskDetail.value?.projectId
    if (!pid) return
    const detail = await window.api.report.getLevelCommunityDetail({
      projectId: pid, taskId: props.taskId,
      level: item.level || 'L0', edgeType: commEdgeType.value,
    })
    const community = detail.communities.find((c: any) => c.communityId === item.id)
    if (!community) return
    const nodeLines = community.nodes.map((n: any) => `- ${n.name} (${n.filePath})`).join('\n')
    const edgeLines = community.edges.map((e: any) => `- ${e.source} → ${e.target} [${e.type}]`).join('\n')
    const md = [
      `# 社区: ${item.id}`,
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
    })
  } catch (e) {
    console.error('[ReportHome] openCommunityDoc error:', e)
  }
}

function handleCommunityMD(params: { communityId: string; name: string; summary: string; mermaid?: string; plantuml?: string }) {
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
  })
}

async function reloadCommunityResults() {
  const [resCall, resInclude] = await Promise.all([
    window.api.analysis.listCommunityResults(props.taskId, 'CALL').catch(() => ({ results: [] })),
    window.api.analysis.listCommunityResults(props.taskId, 'INCLUDE').catch(() => ({ results: [] })),
  ])
  communityResultsCall.value = Object.fromEntries((resCall?.results || []).map((r: any) => [r.comm_id, r]))
  communityResultsInclude.value = Object.fromEntries((resInclude?.results || []).map((r: any) => [r.comm_id, r]))
}

async function loadData() {
  loading.value = true
  loadError.value = null
  projectSummary.value = projectStore.selectedProject
  try {
    taskDetail.value = await analysisStore.getTask(props.taskId)
    if (!taskDetail.value) {
      loadError.value = t('report.taskNotFound')
      return
    }
    const pid = projectStore.selectedProjectId || taskDetail.value?.projectId
    if (pid) {
      projectSummary.value = await ipc.project.get(pid).catch(() => projectStore.selectedProject || null)
      fileStats.value = await analysisStore.scanFileStats(pid)
    }
    const [call, include, resCall, resInclude] = await Promise.all([
      window.api.analysis.getCascadeLevels(props.taskId, 'CALL').catch(() => null),
      window.api.analysis.getCascadeLevels(props.taskId, 'INCLUDE').catch(() => null),
      window.api.analysis.listCommunityResults(props.taskId, 'CALL').catch(() => ({ results: [] })),
      window.api.analysis.listCommunityResults(props.taskId, 'INCLUDE').catch(() => ({ results: [] })),
    ])
    communityDataCall.value = call
    communityDataInclude.value = include
    communityResultsCall.value = Object.fromEntries((resCall?.results || []).map((r: any) => [r.comm_id, r]))
    communityResultsInclude.value = Object.fromEntries((resInclude?.results || []).map((r: any) => [r.comm_id, r]))
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

function handleReportGenerated(content: string) {
  generatedReport.value = content
  emit('open-md', {
    taskId: props.taskId,
    content,
    title: `${taskDetail.value?.name || '报告'} · 完整架构分析`,
  })
}

function handleViewReport() {
  if (generatedReport.value) {
    emit('open-md', {
      taskId: props.taskId,
      content: generatedReport.value,
      title: `${taskDetail.value?.name || '报告'} · 完整架构分析`,
    })
  }
}

function fileExtLabel(ext: string): string {
  if (!ext) return t('analysis.noExtension')
  const labels: Record<string, string> = {
    typescript: 'TypeScript',
    javascript: 'JavaScript',
    python: 'Python',
    go: 'Go',
    rust: 'Rust',
    java: 'Java',
    vue: 'Vue',
    html: 'HTML',
    css: 'CSS',
    json: 'JSON',
    markdown: 'Markdown',
    yaml: 'YAML',
  }
  return labels[ext] || ext
}

onMounted(loadData)
watch(() => props.taskId, loadData)
</script>

<template>
  <div class="report-home">
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <template v-if="loading">
      <div class="loading-state">
        <div class="loading-spinner"></div>
        <span>{{ t('common.loading') }}</span>
      </div>
    </template>

    <div v-else-if="loadError" class="load-error">
      <ExclamationTriangleIcon class="w-4 h-4" />
      <span>{{ loadError }}</span>
      <button class="btn btn-ghost btn-xs" @click="loadData">{{ t('common.retry') }}</button>
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
              <span class="card-value card-path" :title="project?.rootPath || project?.path || ''">{{ truncatePath(project?.rootPath || project?.path) }}</span>
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
              <span class="card-value status-badge" :class="task?.status">{{ task?.status }}</span>
            </div>
            <div class="summary-card">
              <span class="card-label">{{ t('analysis.createdAt') }}</span>
              <span class="card-value">{{ task?.createdAt ? new Date(task.createdAt).toLocaleString() : '-' }}</span>
            </div>
          </div>

          <div v-if="fileStats" class="file-distribution">
            <div class="dist-title">{{ t('report.fileDistribution') }}</div>
            <div class="dist-bars">
              <div
                v-for="(count, ext) in fileStats.extensions"
                :key="ext"
                class="dist-bar-row"
              >
                <span class="dist-label">{{ fileExtLabel(ext) }}</span>
                <div class="dist-bar-track">
                  <div
                    class="dist-bar-fill"
                    :style="{ width: (count / fileStats.totalFiles * 100) + '%' }"
                  ></div>
                </div>
                <span class="dist-count">{{ count }}</span>
              </div>
            </div>
          </div>
        </section>

        <!-- 社区概要 -->
        <section v-if="commData" class="home-section">
          <div class="section-header">
            <RectangleGroupIcon class="w-4 h-4" />
            <span>{{ t('report.communitySummary') }}</span>
          </div>
          <!-- 边类型切换 -->
          <div class="comm-et-tabs">
            <button
              :class="['comm-et-tab', { active: commEdgeType === 'INCLUDE' }]"
              @click="commEdgeType = 'INCLUDE'"
            >{{ t('report.pipeline.edgeInclude') }}</button>
            <button
              :class="['comm-et-tab', { active: commEdgeType === 'CALL' }]"
              @click="commEdgeType = 'CALL'"
            >{{ t('report.pipeline.edgeCall') }}</button>
          </div>
          <!-- L0统计 -->
          <div class="comm-stats">
            <span class="comm-stat">
              <HashtagIcon class="w-3 h-3" /> {{ commStats.count }}
            </span>
            <span class="comm-stat">{{ t('report.communityMaxNodes') }}: {{ commStats.maxNodes }}</span>
            <span class="comm-stat">{{ t('report.communityMinNodes') }}: {{ commStats.minNodes }}</span>
            <span class="comm-stat quality-stat" :title="'质量分反映社区内聚度，分值越高组件间区分度越好。平均约 ' + (commStats.avgQuality ? commStats.avgQuality.toFixed(3) : '-')">
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
            />
          </div>
          <!-- L0 社区列表 -->
          <div class="community-items">
            <template v-if="pagedCommunityItems.length > 0">
              <div
                v-for="item in pagedCommunityItems"
                :key="item.id"
                class="community-chip"
                :class="{ 'has-result': !!(commResults[item.id]?.name) && commResults[item.id]?.name !== item.id }"
                :title="`${item.id} (${item.nodeCount} 节点, 质量: ${item.qualityScore ?? '-'})`"
                @click="openCommunityDoc(item)"
              >
                <span class="chip-name">{{ commName(item) }}</span>
                <span class="chip-count">{{ item.nodeCount }}</span>
              </div>
            </template>
            <div v-else class="comm-empty">{{ t('report.pipeline.noCommunities') }}</div>
          </div>
          <!-- 组件分页 -->
          <div v-if="communityTotalPages > 1" class="comm-pagination">
            <button class="btn btn-ghost btn-xs" :disabled="communityPage <= 1" @click="communityPage--">上一页</button>
            <span class="comm-page-info">{{ communityPage }} / {{ communityTotalPages }}</span>
            <button class="btn btn-ghost btn-xs" :disabled="communityPage >= communityTotalPages" @click="communityPage++">下一页</button>
          </div>
        </section>

        <!-- 操作区 -->
        <section class="home-section actions-section">
          <div class="section-header">
            <SparklesIcon class="w-4 h-4" />
            <span>{{ t('report.generateReport') }}</span>
          </div>

          <!-- LLM API 校验提示 -->
          <div v-if="!hasModel" class="model-warning">
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
              v-if="generatedReport"
              class="btn btn-secondary"
              @click="handleViewReport"
            >
              <DocumentTextIcon class="w-4 h-4" />
              <span>{{ t('report.viewReport') }}</span>
            </button>
          </div>

          <!-- 生成流水线（隐藏，后台同步） -->
          <div style="display:none">
            <ReportGenerationPipeline
              :task-id="taskId"
              :project-id="projectId"
              @generated="handleReportGenerated"
              @close="() => {}"
              @community-results="reloadCommunityResults"
              @view-community-md="handleCommunityMD"
            />
          </div>
        </section>
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
  margin-bottom: 6px;
}

.dist-bars {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.dist-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.dist-label {
  width: 80px;
  flex-shrink: 0;
  color: var(--text-secondary);
  text-align: right;
}

.dist-bar-track {
  flex: 1;
  height: 14px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
}

.dist-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.3s ease;
}

.dist-count {
  width: 40px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  font-size: 10px;
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
</style>
