<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PlusIcon,
  EyeIcon,
  StopIcon,
  ArrowPathIcon,
  PencilIcon,
  TrashIcon,
  ExclamationTriangleIcon,
  PlayIcon,
  DocumentTextIcon,
  ClockIcon,
} from '@heroicons/vue/24/outline'
import { useRouter } from 'vue-router'
import { useAnalysisStore } from '@/stores/analysis'
import { useProjectStore } from '@/stores/project'
import { useNavigationStore } from '@/stores/navigation'
import TaskDetailDialog from './TaskDetailDialog.vue'
import TimelineDialog from './TimelineDialog.vue'
import type { AnalysisTask } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'
import { displayDispatcher } from '@/services/display-dispatcher'
import { createLogger } from '@/utils/logger'

const { showId, componentId } = useComponentId('AN-002')
const logger = createLogger('TaskListPanel')
const props = defineProps<{
  projectId: string
}>()

const emit = defineEmits<{
  createTask: [taskId?: string]
}>()

const { t } = useI18n()
const router = useRouter()
const analysisStore = useAnalysisStore()
const projectStore = useProjectStore()
const navigation = useNavigationStore()

const detailTask = ref<AnalysisTask | null>(null)
const deleteConfirm = ref<string | null>(null)
const timelineDialogVisible = ref(false)
const timelineDialogTask = ref<AnalysisTask | null>(null)
function openTimeline(task: AnalysisTask) {
  timelineDialogTask.value = task
  timelineDialogVisible.value = true
}

// 加载任务列表
async function loadTasks() {
  if (props.projectId) {
    await analysisStore.loadTasks(props.projectId)
  }
}

// 运行中任务轮询（3 秒刷新）
function startPolling() {
  const key = `task-list:${props.projectId}`
  if (displayDispatcher.has(key)) return
  displayDispatcher.register(key, {
    interval: 3000,
    fetcher: async () => {
      const hasRunning = analysisStore.tasks.some(t => t.status === 'running')
      if (hasRunning && props.projectId) {
        await analysisStore.loadTasks(props.projectId)
      }
      return hasRunning
    },
    onData: (hasRunning) => {
      if (!hasRunning) displayDispatcher.unregister(`task-list:${props.projectId}`)
    },
  })
}

function stopPolling() {
  if (!props.projectId) return
  displayDispatcher.unregister(`task-list:${props.projectId}`)
}

// 监听任务列表变化，有 running 任务时启动轮询
watch(() => analysisStore.tasks, (tasks) => {
  const hasRunning = tasks.some(t => t.status === 'running')
  if (hasRunning) {
    startPolling()
  }
}, { deep: true })

onMounted(() => {
  loadTasks()
})

onUnmounted(() => {
  stopPolling()
})

// 状态颜色
function getStatusColor(status: string): string {
  const map: Record<string, string> = {
    running: 'var(--accent)',
    done: 'var(--success)',
    error: 'var(--error)',
    cancelled: 'var(--warning)',
    pending: 'var(--text-muted)',
    modified: 'var(--warning)',
  }
  return map[status] || 'var(--text-muted)'
}

function getStatusLabel(status: string): string {
  const map: Record<string, string> = {
    running: t('analysis.running'),
    done: t('analysis.done'),
    error: t('analysis.error'),
    cancelled: t('analysis.cancelled'),
    pending: t('analysis.pending'),
    modified: t('analysis.modified'),
  }
  return map[status] || status
}

// Computed task stats
const taskStats = computed(() => {
  const tasks = analysisStore.tasks
  return {
    total: tasks.length,
    running: tasks.filter(t => t.status === 'running').length,
    done: tasks.filter(t => t.status === 'done').length,
    error: tasks.filter(t => t.status === 'error').length,
    modified: tasks.filter(t => t.status === 'modified').length,
    pending: tasks.filter(t => t.status === 'pending').length,
  }
})

// 任务操作
function onViewDetail(task: AnalysisTask) {
  detailTask.value = task
}

async function onStopTask(taskId: string) {
  try {
    await analysisStore.stopTask(taskId)
    await loadTasks()
  } catch (err) {
    console.error('Failed to stop task:', err)
  }
}

// 首次运行（pending 状态，从未执行过）
async function onRunTask(taskId: string) {
  const task = analysisStore.tasks.find(t => t.id === taskId)
  if (task && !(await validateFileCount(task))) return
  try {
    await analysisStore.runTask(taskId)
    await loadTasks()
  } catch (err) {
    console.error('Failed to run task:', err)
  }
}

// 重跑（已有运行历史）
async function onRerunTask(taskId: string) {
  const task = analysisStore.tasks.find(t => t.id === taskId)
  if (task && !(await validateFileCount(task))) return
  try {
    await analysisStore.reRunTask(taskId)
    await loadTasks()
  } catch (err) {
    console.error('Failed to rerun task:', err)
  }
}

const FILE_LIMIT_WARN = 5000
const FILE_LIMIT_BLOCK = 10000
const taskFileCounts = ref<Record<string, { count: number; loading: boolean }>>({})

const showFileCountExceedDialog = ref(false)
const fileCountExceedMessage = ref('')

function parseTaskArray(field: unknown): string[] {
  if (!field) return []
  if (Array.isArray(field)) return field
  if (typeof field === 'string') {
    try { return JSON.parse(field) } catch { return [] }
  }
  return []
}

async function validateFileCount(task: AnalysisTask): Promise<boolean> {
  const key = task.id
  const cached = taskFileCounts.value[key]
  if (cached && cached.count > 0) {
    if (cached.count > FILE_LIMIT_BLOCK) {
      fileCountExceedMessage.value = `文件数 ${cached.count} 超过 ${FILE_LIMIT_BLOCK}，请先削减解析范围`
      showFileCountExceedDialog.value = true
      return false
    }
    return true
  }
  taskFileCounts.value[key] = { count: 0, loading: true }
  try {
    const scopes = parseTaskArray(task.scopes)
    const exts = parseTaskArray(task.extensions)
    const result = await analysisStore.scanFileStats(task.projectId, {
      scopes: scopes.length > 0 ? scopes : undefined,
      selectedExtensions: exts.length > 0 ? exts : undefined,
    })
    const count = result.totalFiles
    taskFileCounts.value[key] = { count, loading: false }
    if (count > FILE_LIMIT_BLOCK) {
      fileCountExceedMessage.value = `文件数 ${count} 超过 ${FILE_LIMIT_BLOCK}，请先削减解析范围`
      showFileCountExceedDialog.value = true
      return false
    }
    if (count > FILE_LIMIT_WARN) {
      logger.warn(`File count ${count} exceeds ${FILE_LIMIT_WARN} for task ${task.name}`)
    }
    return true
  } catch {
    taskFileCounts.value[key] = { count: 0, loading: false }
    return true
  }
}

function onEditTask(taskId: string) {
  emit('createTask', taskId)
}

function onDeleteTask(taskId: string) {
  deleteConfirm.value = taskId
}

function onOpenAnalysis(task: AnalysisTask) {
  projectStore.selectProject(task.projectId)
  router.push('/analysis')
  navigation.navigateTo('analysis')
  projectStore.openReportHomeTab({
    taskId: task.id,
    taskName: task.name,
    projectId: task.projectId,
    projectName: projectStore.selectedProject?.name,
  })
}

async function confirmDelete() {
  if (!deleteConfirm.value) return
  try {
    await analysisStore.deleteTask(deleteConfirm.value)
    deleteConfirm.value = null
    await loadTasks()
  } catch (err) {
    console.error('Failed to delete task:', err)
  }
}

function cancelDelete() {
  deleteConfirm.value = null
}

const reportTypeLabels: Record<string, string> = {
  dependency: 'analysis.dependencyAnalysis',
  callChain: 'analysis.callChainAnalysis',
}

// 格式化配置摘要
function getConfigSummary(task: AnalysisTask): string {
  const parts: string[] = []
  if (task.reportTypes?.length) {
    parts.push(task.reportTypes.map(r => t(reportTypeLabels[r] || r)).join(', '))
  }
  if (task.scope) {
    parts.push(task.scope)
  }
  if (task.extensions?.length) {
    const exts = Array.isArray(task.extensions) ? task.extensions : JSON.parse(task.extensions)
    parts.push(exts.join(', '))
  }
  return parts.join('  ')
}
</script>

<template>
  <div class="task-list-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 标题栏 -->
    <div class="panel-header">
      <h2 class="panel-title">
        {{ t('analysis.taskList') }}
      </h2>
      <button
        class="btn btn-primary btn-sm"
        @click="emit('createTask')"
      >
        <PlusIcon class="w-4 h-4" />
        <span>{{ t('analysis.newTask') }}</span>
      </button>
    </div>

    <!-- 统计摘要 -->
    <div class="task-stats">
      <span class="stat-item">
        <span class="stat-label">{{ t('analysis.total') }}</span>
        <span class="stat-value">{{ analysisStore.tasks.length }}</span>
      </span>
      <span class="stat-divider" />
      <span class="stat-item">
        <span
          class="stat-dot"
          style="background: var(--accent)"
        />
        <span class="stat-label">{{ t('analysis.running') }}</span>
        <span class="stat-value">{{ analysisStore.taskStats.running }}</span>
      </span>
      <span class="stat-divider" />
      <span class="stat-item">
        <span
          class="stat-dot"
          style="background: var(--success)"
        />
        <span class="stat-label">{{ t('analysis.done') }}</span>
        <span class="stat-value">{{ analysisStore.taskStats.done }}</span>
      </span>
      <span class="stat-divider" />
      <span class="stat-item">
        <span
          class="stat-dot"
          style="background: var(--error)"
        />
        <span class="stat-label">{{ t('analysis.error') }}</span>
        <span class="stat-value">{{ analysisStore.taskStats.error }}</span>
      </span>
    </div>

    <!-- 任务列表 -->
    <div
      v-if="analysisStore.tasks.length === 0"
      class="empty-state"
    >
      <span>{{ t('analysis.noTasks') }}</span>
    </div>

    <div
      v-else
      class="task-cards"
    >
      <div
        v-for="task in analysisStore.filteredTasks"
        :key="task.id"
        class="task-card"
      >
        <!-- 第一行: 名称/状态/进度 -->
        <div class="task-card-header">
          <div class="task-name-group">
            <span
              class="status-dot"
              :style="{ background: getStatusColor(task.status) }"
            />
            <span class="task-name">{{ task.name }}</span>
            <span class="task-type-badge">{{ task.type }}</span>
            <button
              v-if="task.status === 'done'"
              class="btn btn-ghost btn-xs task-name-btn"
              title="查看历史快照"
              @click.stop="openTimeline(task)"
            >
              <ClockIcon class="w-3 h-3" />
              <span class="task-name-btn-text">时间线</span>
            </button>
          </div>
          <div class="task-progress-group">
            <span
              class="task-status"
              :style="{ color: getStatusColor(task.status) }"
            >
              {{ getStatusLabel(task.status) }}
            </span>
            <div
              v-if="task.status === 'running'"
              class="task-progress-bar"
            >
              <div
                class="task-progress-fill"
                :style="{ width: `${task.progress || 0}%` }"
              />
            </div>
            <span
              v-if="task.progress != null"
              class="task-progress-text"
            >{{ task.progress }}%</span>
          </div>
        </div>

        <!-- 第二行: 配置摘要 -->
        <div class="task-card-body">
          <span class="task-config">{{ getConfigSummary(task) }}</span>
        </div>

        <!-- 错误信息 -->
        <div
          v-if="task.error"
          class="task-error"
        >
          <ExclamationTriangleIcon class="w-3.5 h-3.5" />
          <span>{{ task.error }}</span>
        </div>

        <!-- 第三行: 操作按钮 -->
        <div class="task-card-actions">
          <button
            class="btn btn-ghost btn-xs"
            :title="t('analysis.viewDetail')"
            @click="onViewDetail(task)"
          >
            <EyeIcon class="w-3.5 h-3.5" />
            <span>{{ t('analysis.viewDetail') }}</span>
          </button>

          <button
            v-if="task.status === 'running'"
            class="btn btn-ghost btn-xs btn-warning"
            :title="t('analysis.stopTask')"
            @click="onStopTask(task.id)"
          >
            <StopIcon class="w-3.5 h-3.5" />
            <span>{{ t('analysis.stopTask') }}</span>
          </button>

          <button
            v-if="task.status === 'error'"
            class="btn btn-ghost btn-xs"
            :title="t('analysis.retryTask')"
            :disabled="analysisStore.isTaskLoading(task.id)"
            @click="onRerunTask(task.id)"
          >
            <ArrowPathIcon class="w-3.5 h-3.5" />
            <span>{{ t('analysis.retryTask') }}</span>
          </button>

          <button
            v-if="task.status === 'pending'"
            class="btn btn-ghost btn-xs btn-primary"
            :title="t('analysis.runTask')"
            :disabled="analysisStore.isTaskLoading(task.id)"
            @click="onRunTask(task.id)"
          >
            <PlayIcon class="w-3.5 h-3.5" />
            <span>{{ t('analysis.runTask') }}</span>
          </button>

          <button
            v-if="task.status !== 'running' && task.status !== 'pending'"
            class="btn btn-ghost btn-xs"
            :title="t('analysis.rerunTask')"
            :disabled="analysisStore.isTaskLoading(task.id)"
            @click="onRerunTask(task.id)"
          >
            <ArrowPathIcon class="w-3.5 h-3.5" />
            <span>{{ t('analysis.rerunTask') }}</span>
          </button>

          <button
            v-if="task.status !== 'running'"
            class="btn btn-ghost btn-xs"
            :title="t('analysis.editTask')"
            @click="onEditTask(task.id)"
          >
            <PencilIcon class="w-3.5 h-3.5" />
            <span>{{ t('analysis.editTask') }}</span>
          </button>

          <button
            v-if="task.status !== 'running'"
            class="btn btn-ghost btn-xs btn-danger"
            :title="t('analysis.deleteTask')"
            @click="onDeleteTask(task.id)"
          >
            <TrashIcon class="w-3.5 h-3.5" />
            <span>{{ t('analysis.deleteTask') }}</span>
          </button>

          <div class="actions-spacer" />

          <button
            v-if="task.status === 'done'"
            class="btn btn-primary btn-xs"
            :title="t('report.structuralReport', '结构分析')"
            @click="onOpenAnalysis(task)"
          >
            <DocumentTextIcon class="w-3.5 h-3.5" />
            <span>结构分析</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 任务详情对话框 -->
    <TaskDetailDialog
      v-if="detailTask"
      :task="detailTask"
      :visible="!!detailTask"
      @close="detailTask = null"
    />

    <!-- 删除确认对话框 -->
    <Teleport to="body">
      <div
        v-if="deleteConfirm"
        class="dialog-overlay"
        @click.self="cancelDelete"
      >
        <div class="confirm-dialog">
          <div class="confirm-title">
            <ExclamationTriangleIcon class="w-5 h-5 text-warning" />
            <span>{{ t('analysis.confirmDelete') }}</span>
          </div>
          <div class="confirm-actions">
            <button
              class="btn btn-ghost"
              @click="cancelDelete"
            >
              {{ t('analysis.deleteCancelled') }}
            </button>
            <button
              class="btn btn-danger"
              @click="confirmDelete"
            >
              {{ t('analysis.deleteConfirmed') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

    <TimelineDialog
      :visible="timelineDialogVisible"
      :task-id="timelineDialogTask?.id || ''"
      :task-name="timelineDialogTask?.name || ''"
      :project-id="props.projectId"
      @close="timelineDialogVisible = false"
    />

    <!-- 文件数超限警告对话框 -->
    <Teleport to="body">
      <div
        v-if="showFileCountExceedDialog"
        class="dialog-overlay"
        @click.self="showFileCountExceedDialog = false"
      >
        <div class="confirm-dialog">
          <div class="confirm-title">
            <ExclamationTriangleIcon class="w-5 h-5 text-warning" />
            <span>{{ t('import.fileCountExceed', '文件数量过多') }}</span>
          </div>
          <div class="confirm-body">
            {{ fileCountExceedMessage }}
          </div>
          <div class="confirm-actions">
            <button
              class="btn btn-primary"
              @click="showFileCountExceedDialog = false"
            >
              {{ t('common.ok', '确定') }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>

<style scoped>
.task-list-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 16px;
}

.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
  margin: 0;
}

.task-stats {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 12px;
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-secondary);
}

.stat-value {
  font-weight: 600;
  color: var(--text-primary);
}

.stat-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
}

.stat-divider {
  width: 1px;
  height: 16px;
  background: var(--border);
}

.empty-state {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--text-muted);
}

.task-cards {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-card {
  padding: 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.task-card:hover {
  border-color: var(--border-light);
}

.task-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.task-name-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.task-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-primary);
}

.task-type-badge {
  padding: 1px 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  font-size: 10px;
  color: var(--text-muted);
  font-family: monospace;
}

.task-name-btn {
  padding: 2px 4px;
  margin-left: 2px;
  color: var(--text-muted);
  gap: 2px;
}
.task-name-btn:hover {
  color: var(--accent);
}
.task-name-btn-text {
  font-size: 10px;
}

.task-progress-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-status {
  font-size: 11px;
  font-weight: 500;
}

.task-progress-bar {
  width: 60px;
  height: 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
}

.task-progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.3s;
  border-radius: 3px;
}

.task-progress-text {
  font-size: 11px;
  color: var(--text-muted);
  min-width: 32px;
  text-align: right;
}

.task-card-body {
  font-size: 11px;
  color: var(--text-muted);
  font-family: monospace;
}

.task-error {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 6px 8px;
  background: var(--error)11;
  border: 1px solid var(--error)33;
  border-radius: 4px;
  font-size: 11px;
  color: var(--error);
}

.task-card-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  align-items: center;
}
.actions-spacer { flex: 1; }

.btn-xs {
  padding: 3px 8px;
  font-size: 11px;
  gap: 4px;
}

.btn-warning {
  color: var(--warning);
}

.btn-warning:hover {
  background: var(--warning)22;
}

.btn-danger {
  color: var(--error);
}

.btn-danger:hover {
  background: var(--error)22;
}

/* 确认对话框 */
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

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
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.confirm-body {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.confirm-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

/* Stats bar */
.task-stats-bar {
  display: flex;
  gap: 12px;
  padding: 8px 12px;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 6px;
  margin-bottom: 12px;
  font-size: 12px;
  color: var(--text-secondary);
}

.stat-item {
  display: flex;
  align-items: center;
  gap: 4px;
}

.stat-running {
  color: var(--accent);
}

.stat-done {
  color: var(--success);
}

.stat-modified {
  color: var(--warning);
}

.stat-error {
  color: var(--error);
}

/* Modified badge */
.task-modified-badge {
  background: var(--warning);
  color: var(--bg-primary);
  padding: 1px 6px;
  border-radius: 8px;
  font-size: 10px;
  font-weight: 600;
}

.task-run-count {
  font-size: 10px;
  color: var(--text-muted);
  margin-left: 4px;
}
</style>
