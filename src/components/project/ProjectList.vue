<script setup lang="ts">
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  FolderIcon,
  MagnifyingGlassIcon,
  DocumentTextIcon,
  ChevronRightIcon,
  ChevronDownIcon,
  StarIcon,
  SparklesIcon,
  ExclamationTriangleIcon,
} from '@heroicons/vue/24/outline'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import type { Project, AnalysisTask } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('PR-001')
const { t } = useI18n()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()

const emit = defineEmits<{
  selectReport: [item: ReportItem, projectId: string]
  importProject: []
  createTaskForProject: [project: Project]
}>()

const searchQuery = ref('')
const expandedProjects = ref<Set<string>>(new Set())
const loadingProjects = ref<Set<string>>(new Set())

// 报告项：每个报告类型单独一行
export interface ReportItem {
  taskId: string
  type: string
  typeName: string
  taskName: string
  updatedAt?: string
}

// 报告项（按项目分组）
const reportItemsByProject = ref<Map<string, ReportItem[]>>(new Map())

// 报告类型映射
const typeMap: Record<string, string> = {
  dependency: '依赖分析',
  callChain: '调用分析',
  dataFlow: '数据流分析',
  architecture: '架构分析',
}

  // 加载项目的已完成报告
  async function loadCompletedTasks(projectId: string) {
    if (loadingProjects.value.has(projectId)) return
    loadingProjects.value.add(projectId)
    try {
      await analysisStore.loadTasks(projectId)
      const completed = analysisStore.tasks.filter(task => task.status === 'done')

      // 每个已完成任务显示一个"分析报告"入口
      const items: ReportItem[] = []
      for (const task of completed) {
        const taskName = task.name || `Task ${task.id.slice(0, 8)}`
        items.push({
          taskId: task.id,
          type: 'analysisReport',
          typeName: '结构分析',
          taskName,
          updatedAt: task.updatedAt,
        })
      }

    reportItemsByProject.value.set(projectId, items)
  } catch (err) {
    console.error(`Failed to load tasks for project ${projectId}:`, err)
  } finally {
    loadingProjects.value.delete(projectId)
  }
}

// 切换项目展开/折叠
function toggleProject(project: Project) {
  const id = project.id
  if (expandedProjects.value.has(id)) {
    expandedProjects.value.delete(id)
  } else {
    expandedProjects.value.add(id)
    // 首次展开时加载任务
    if (!reportItemsByProject.value.has(id)) {
      loadCompletedTasks(id)
    }
  }
}

// 格式化报告名称：类型 · 任务名（过长截断）
function formatReportName(item: ReportItem): string {
  const maxLen = 24
  const full = `${item.typeName} · ${item.taskName}`
  return full.length > maxLen ? full.slice(0, maxLen) + '…' : full
}

// 格式化完成时间
function formatCompletedTime(updatedAt?: string): string {
  if (!updatedAt) return ''
  const d = new Date(updatedAt)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return t('datetime.justNow')
  if (mins < 60) return `${mins}${t('datetime.minutesAgo')}`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}${t('datetime.hoursAgo')}`
  const days = Math.floor(hours / 24)
  return `${days}${t('datetime.daysAgo')}`
}

// 过滤后的项目列表
const filteredProjects = computed(() => {
  const query = searchQuery.value.toLowerCase().trim()
  if (!query) return projectStore.projects
  return projectStore.projects.filter(p =>
    p.name.toLowerCase().includes(query) ||
    p.path.toLowerCase().includes(query)
  )
})

// 监听项目列表变化，清空缓存
watch(() => projectStore.projects, () => {
  reportItemsByProject.value.clear()
  expandedProjects.value.clear()
})

// 点击"无报告"，弹出确认框
const pendingCreateProject = ref<Project | null>(null)

function handleNoReports(project: Project) {
  pendingCreateProject.value = project
}

function confirmCreateTask() {
  if (pendingCreateProject.value) {
    emit('createTaskForProject', pendingCreateProject.value)
  }
  pendingCreateProject.value = null
}

function cancelCreateTask() {
  pendingCreateProject.value = null
}
</script>

<template>
  <div class="project-list">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 搜索框 -->
    <div class="project-list-search">
      <MagnifyingGlassIcon class="w-3.5 h-3.5 search-icon" />
      <input
        v-model="searchQuery"
        type="text"
        :placeholder="t('project.searchProjects')"
        class="search-input"
      >
    </div>

    <!-- 空状态 -->
    <div
      v-if="projectStore.projects.length === 0"
      class="empty-state"
    >
      <FolderIcon class="w-8 h-8 empty-icon" />
      <div class="empty-title">
        {{ t('project.noProjects') }}
      </div>
      <div class="empty-desc">
        {{ t('project.importFirst') }}
      </div>
      <button
        class="btn btn-primary btn-sm"
        @click="emit('importProject')"
      >
        <SparklesIcon class="w-4 h-4" />
        <span>{{ t('project.importProject') }}</span>
      </button>
    </div>

    <!-- 项目列表 -->
    <div
      v-else
      class="project-items"
    >
      <div
        v-for="project in filteredProjects"
        :key="project.id"
        class="project-item"
      >
        <!-- 项目行 -->
        <div
          class="project-row"
          @click="toggleProject(project)"
        >
          <span
            class="expand-icon"
            :class="{ expanded: expandedProjects.has(project.id) }"
          >
            <ChevronRightIcon class="w-3 h-3" />
          </span>
          <FolderIcon class="w-4 h-4 project-icon" />
          <span class="project-name">{{ project.name }}</span>
          <span class="project-count">
            {{ reportItemsByProject.get(project.id)?.length || 0 }}
          </span>
        </div>

        <!-- 子菜单：已完成报告 -->
        <div
          v-if="expandedProjects.has(project.id)"
          class="project-reports"
        >
          <div
            v-if="loadingProjects.has(project.id)"
            class="report-loading"
          >
            <div class="loading-spinner" />
          </div>
          <div
            v-else-if="(reportItemsByProject.get(project.id) || []).length === 0"
            class="report-empty report-item"
            @click="handleNoReports(project)"
          >
            <DocumentTextIcon class="w-3.5 h-3.5 report-icon" />
            <span class="report-name">{{ t('project.noCompletedReports') }}</span>
          </div>
          <div
            v-for="item in reportItemsByProject.get(project.id)"
            v-else
            :key="`${item.taskId}-${item.type}`"
            class="report-item"
            @click="emit('selectReport', item, project.id)"
          >
            <DocumentTextIcon class="w-3.5 h-3.5 report-icon" />
            <span
              class="report-name"
              :title="formatReportName(item)"
            >{{ formatReportName(item) }}</span>
            <span class="report-time">{{ formatCompletedTime(item.updatedAt) }}</span>
          </div>
        </div>
      </div>

      <!-- 无匹配结果 -->
      <div
        v-if="filteredProjects.length === 0"
        class="no-match"
      >
        {{ t('project.noMatch') }}
      </div>
    </div>

    <!-- 确认创建任务对话框 -->
    <Teleport to="body">
      <div
        v-if="pendingCreateProject"
        class="dialog-overlay"
        @click.self="cancelCreateTask"
      >
        <div class="confirm-dialog">
          <div class="confirm-title">
            <ExclamationTriangleIcon class="w-5 h-5 text-warning" />
            <span>{{ t('project.confirmCreateTask', { name: pendingCreateProject.name }) }}</span>
          </div>
          <div class="confirm-actions">
            <button
              class="btn btn-ghost"
              @click="cancelCreateTask"
            >
              {{ t('common.cancel') }}
            </button>
            <button
              class="btn btn-primary"
              @click="confirmCreateTask"
            >
              {{ t('common.confirm') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.project-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.project-list-search {
  position: relative;
  padding: 6px 8px;
  border-bottom: 1px solid var(--border);
}

.search-icon {
  position: absolute;
  left: 12px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-muted);
  pointer-events: none;
}

.search-input {
  width: 100%;
  padding: 4px 8px 4px 24px;
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--bg-input);
  color: var(--text-primary);
  font-size: 11px;
  outline: none;
}

.search-input:focus {
  border-color: var(--accent);
}

.project-items {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.project-item {
  user-select: none;
}

.project-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 8px;
  cursor: pointer;
  font-size: 12px;
  color: var(--text-primary);
}

.project-row:hover {
  background: var(--bg-hover);
}

.expand-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  color: var(--text-muted);
  transition: transform 0.15s ease;
}

.expand-icon.expanded {
  transform: rotate(90deg);
}

.project-icon {
  color: var(--accent);
  flex-shrink: 0;
}

.project-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.project-count {
  font-size: 10px;
  color: var(--text-muted);
  background: var(--bg-secondary);
  padding: 1px 5px;
  border-radius: 8px;
}

.project-reports {
  padding-left: 16px;
}

.report-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 8px;
}

.report-empty {
  padding: 4px 8px 4px 28px;
  font-size: 11px;
  color: var(--text-muted);
}

.report-item {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px 3px 28px;
  cursor: pointer;
  font-size: 11px;
  color: var(--text-secondary);
}

.report-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.report-icon {
  color: var(--text-muted);
  flex-shrink: 0;
}

.report-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.report-time {
  font-size: 10px;
  color: var(--text-muted);
  flex-shrink: 0;
}

.no-match {
  padding: 12px;
  text-align: center;
  font-size: 11px;
  color: var(--text-muted);
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 24px 16px;
  text-align: center;
}

.empty-icon {
  color: var(--text-muted);
}

.empty-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.empty-desc {
  font-size: 11px;
  color: var(--text-muted);
}

/* 确认对话框 */
.confirm-dialog {
  width: 360px;
  padding: 20px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.confirm-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
