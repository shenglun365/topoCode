<script setup lang="ts">
import { ref, computed, onMounted, watch } from 'vue'
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
import ProjectSummaryCard from '@/components/home/ProjectSummaryCard.vue'
import TaskSummaryCard from '@/components/home/TaskSummaryCard.vue'
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
}>()

const projectId = computed(() => projectStore.selectedProjectId || taskDetail.value?.projectId || '')

const emit = defineEmits<{
  'open-md': [params: { taskId: string; content: string; title: string; parentLevel?: string; parentCommId?: string; parentEdgeType?: string; regenerationType?: 'community' | 'overall' }]
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

const project = computed(() => projectSummary.value || projectStore.selectedProject)
const task = computed(() => taskDetail.value)

const hasAnyCommunity = computed(() => {
  const coms = communityStore.tasks[props.taskId]?.communities || []
  return coms.length > 0
})

const depCommunityCount = computed(() =>
  (communityStore.tasks[props.taskId]?.communities || []).filter(c => c.level === 'L0' && c.edgeType === 'INCLUDE').length
)
const callCommunityCount = computed(() =>
  (communityStore.tasks[props.taskId]?.communities || []).filter(c => c.level === 'L0' && c.edgeType === 'CALL').length
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
    regenerationType: 'community',
  })
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
      const ps = await reportStore.getProjectSummary(pid).catch(() => null)
      if (ps?.summary) {
        projectSummaryText.value = ps.summary
        projectSummaryDate.value = ps.generated_at || ''
      }
    }

    // 合并查询：一次 RPC 获取 community + fileStats（替代 5 次独立调用）
    if (pid) {
      try {
        const dash = await ipc.analysis.getReportDashboard(props.taskId).catch(() => null)
        if (dash) {
          // 文件统计
          fileStats.value = dash.fileStats?.extensions || {}
          const taskExtensions = (taskDetail.value as any)?.extensions || []
          if (taskExtensions.length > 0 && dash.fileStats?.extensions) {
            totalScopeFiles.value = taskExtensions.reduce(
              (sum: number, ext: string) => sum + (dash.fileStats.extensions[ext] || 0),
              0
            )
          } else {
            totalScopeFiles.value = dash.fileStats?.totalFiles || 0
          }
          // 社区数据注入 store
          await communityStore.loadCommunitiesFromDashboard(props.taskId, dash)
        }
        // 加载外部依赖/调用统计
        await communityStore.loadExternalStats(props.taskId).catch(() => {})
      } catch {
        // fallback: 原始独立调用
        await communityStore.loadCommunities(props.taskId, pid)
        // 加载外部依赖/调用统计
        await communityStore.loadExternalStats(props.taskId).catch(() => {})
        const fs = await analysisStore.scanFileStats(pid).catch(() => null)
        if (fs) {
          fileStats.value = fs.extensions || {}
          const taskExtensions = (taskDetail.value as any)?.extensions || []
          if (taskExtensions.length > 0 && fs.extensions) {
            totalScopeFiles.value = taskExtensions.reduce(
              (sum: number, ext: string) => sum + (fs.extensions[ext] || 0),
              0
            )
          } else {
            totalScopeFiles.value = fs.totalFiles || 0
          }
        }
      }
    }
    await reportStore.checkReportExists(props.taskId)
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
            <span>{{ t('report.taskSummary') }}: {{ task?.name || '-' }}</span>
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

        <!-- 任务概要 -->
        <section
          v-if="!collapsed.task"
          class="home-section"
        >
          <div class="section-header">
            <ChartBarIcon class="w-4 h-4" />
            <span>{{ t('report.taskSummary') }}</span>
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
                  >{{ ext }} <span class="scope-tag-count">{{ fileStats[ext] ?? '-' }}</span></span>
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
      </div>

      <!-- 组件架构 — Tag/Graph 双模式 — 填充剩余空间 -->
      <div class="report-arch-panel">
        <CommunityArchitecturePanel
          :task-id="props.taskId"
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
  flex: 0 1 auto;
  overflow-y: auto;
  padding: 16px 20px;
  min-height: 0;
}
.report-arch-panel {
  flex: 1;
  min-height: 0;
  padding: 16px 20px;
  display: flex;
  flex-direction: column;
  overflow-y: auto;
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

.scope-tag-count {
  margin-left: 4px;
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
