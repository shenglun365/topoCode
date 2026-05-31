<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, ClockIcon, DocumentTextIcon } from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import type { AnalysisTask, TaskLogEntry, TaskRun } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('AN-003')
const props = defineProps<{
  task: AnalysisTask
  visible?: boolean
}>()

const emit = defineEmits<{
  close: []
}>()

const { t } = useI18n()
const analysisStore = useAnalysisStore()

const logs = ref<TaskLogEntry[]>([])
const loadingLogs = ref(false)
const taskRuns = ref<TaskRun[]>([])
const selectedRunId = ref<string>('')
let pollTimer: ReturnType<typeof setInterval> | null = null

// 状态颜色
const statusColor = computed(() => {
  const map: Record<string, string> = {
    running: 'var(--accent)',
    done: 'var(--success)',
    error: 'var(--error)',
    cancelled: 'var(--warning)',
    pending: 'var(--text-muted)',
  }
  return map[props.task.status] || 'var(--text-muted)'
})

// 安全解析数组字段（后端可能返回 JSON 字符串）
const safeExtensions = computed(() => {
  const data = props.task.extensions
  if (!data) return []
  return Array.isArray(data) ? data : JSON.parse(data)
})
const safeReportTypes = computed(() => {
  const data = props.task.reportTypes || props.task.report_types
  if (!data) return []
  return Array.isArray(data) ? data : JSON.parse(data)
})
const safeExcludeDirs = computed(() => {
  const data = props.task.excludeDirs || props.task.exclude_dirs
  if (!data) return []
  return Array.isArray(data) ? data : JSON.parse(data)
})
const safeScopes = computed(() => {
  const data = props.task.scopes
  if (!data) return []
  return Array.isArray(data) ? data : (data.split?.(',') || [])
})

// 文件分布数据
const fileDistribution = ref<Record<string, number>>({})
const totalFiles = ref(0)
const loadingDistribution = ref(false)

async function loadFileDistribution() {
  if (!props.task.projectId) return
  loadingDistribution.value = true
  try {
    const options: any = { patternType: 'all' }
    if (safeScopes.value.length > 0) {
      options.scopes = safeScopes.value
    }
    if (safeExtensions.value.length > 0) {
      options.selectedExtensions = safeExtensions.value
    }
    if (safeExcludeDirs.value.length > 0) {
      options.excludeDirs = safeExcludeDirs.value
    }
    const result = await analysisStore.scanFileStats(props.task.projectId, options)
    fileDistribution.value = result.extensions || {}
    totalFiles.value = result.totalFiles || 0
  } catch (err) {
    console.error('Failed to load file distribution:', err)
    fileDistribution.value = {}
    totalFiles.value = 0
  } finally {
    loadingDistribution.value = false
  }
}

// 格式化扩展名显示
function formatExtension(key: string): string {
  if (!key || key === '') {
    return t('analysis.noExtension')
  }
  return `.${key}`
}

// 按文件数降序排列
const sortedDistribution = computed(() => {
  return Object.entries(fileDistribution.value)
    .sort((a, b) => b[1] - a[1])
})

const statusLabel = computed(() => {
  const map: Record<string, string> = {
    running: t('analysis.running'),
    done: t('analysis.done'),
    error: t('analysis.error'),
    cancelled: t('analysis.cancelled'),
    pending: t('analysis.pending'),
  }
  return map[props.task.status] || props.task.status
})

// 加载运行历史
async function loadRuns() {
  if (!props.task.id) return
  try {
    taskRuns.value = await analysisStore.getTaskRuns(props.task.id)
    // 默认选中最新的运行
    if (taskRuns.value.length > 0) {
      selectedRunId.value = taskRuns.value[0].id
    }
  } catch (err) {
    console.error('Failed to load runs:', err)
  }
}

// 加载日志
async function loadLogs(runId?: string) {
  if (!props.task.id) return
  loadingLogs.value = true
  try {
    const result = await analysisStore.getTaskLogs(props.task.id, runId || undefined)
    logs.value = result.logs || []
  } catch (err) {
    console.error('Failed to load logs:', err)
  } finally {
    loadingLogs.value = false
  }
}

// 运行中任务轮询日志
function startPolling() {
  if (props.task.status === 'running') {
    pollTimer = setInterval(() => loadLogs(selectedRunId.value), 2000)
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

// 初始化
async function init() {
  await loadRuns()
  await loadLogs(selectedRunId.value)
  await loadFileDistribution()
  startPolling()
}
init()

onUnmounted(() => {
  stopPolling()
})

function handleClose() {
  stopPolling()
  emit('close')
}

function handleSelectRun(runId: string) {
  selectedRunId.value = runId
  loadLogs(runId)
}

// 格式化时间
function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}s`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${seconds % 60}s`
  return `${Math.floor(seconds / 3600)}h ${Math.floor((seconds % 3600) / 60)}m`
}

function formatDurationMs(ms?: number): string {
  if (ms == null) return '--'
  return formatDuration(Math.floor(ms / 1000))
}

function formatRunStatus(status: string): string {
  const map: Record<string, string> = {
    running: t('analysis.running'),
    done: t('analysis.done'),
    error: t('analysis.error'),
    cancelled: t('analysis.cancelled'),
  }
  return map[status] || status
}

function formatRunStatusColor(status: string): string {
  const map: Record<string, string> = {
    running: 'var(--accent)',
    done: 'var(--success)',
    error: 'var(--error)',
    cancelled: 'var(--warning)',
  }
  return map[status] || 'var(--text-muted)'
}
</script>

<template>
  <Teleport to="body">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div
      v-if="visible"
      class="dialog-overlay"
      role="dialog"
      aria-modal="true"
      @click.self="handleClose"
    >
      <div class="task-detail-dialog">
        <!-- 标题栏 -->
        <div class="dialog-header">
          <div class="dialog-title">
            <span
              class="status-dot"
              :style="{ background: statusColor }"
            />
            <span>{{ task.name }}</span>
            <span
              class="status-badge"
              :style="{ background: statusColor + '22', color: statusColor }"
            >
              {{ statusLabel }}
            </span>
          </div>
          <button
            class="dialog-close-btn"
            @click="handleClose"
          >
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>

        <!-- 内容区 -->
        <div class="dialog-body">
          <!-- 基本信息 -->
          <div class="detail-section">
            <h3 class="section-title">
              {{ t('analysis.basicInfo') }}
            </h3>
            <div class="info-grid">
              <div class="info-row">
                <span class="info-label">{{ t('analysis.taskId') }}</span>
                <span class="info-value">{{ task.id }}</span>
              </div>
              <div class="info-row">
                <span class="info-label">{{ t('analysis.status') }}</span>
                <span class="info-value">
                  <span
                    class="status-dot"
                    :style="{ background: statusColor }"
                  />
                  {{ statusLabel }}
                </span>
              </div>
              <div
                v-if="task.progress != null"
                class="info-row"
              >
                <span class="info-label">{{ t('analysis.progress') }}</span>
                <span class="info-value">
                  <div class="progress-bar-inline">
                    <div
                      class="progress-fill"
                      :style="{ width: `${task.progress}%` }"
                    />
                  </div>
                  {{ task.progress }}% ({{ task.current || 0 }}/{{ task.total || 0 }})
                </span>
              </div>
              <div
                v-if="task.createdAt"
                class="info-row"
              >
                <span class="info-label">{{ t('analysis.createdAt') }}</span>
                <span class="info-value">{{ task.createdAt }}</span>
              </div>
              <div
                v-if="task.updatedAt"
                class="info-row"
              >
                <span class="info-label">{{ t('analysis.updatedAt') }}</span>
                <span class="info-value">{{ task.updatedAt }}</span>
              </div>
            </div>
          </div>

          <!-- 分析配置 -->
          <div
            v-if="task.scope || safeScopes.length || safeExtensions.length || safeExcludeDirs.length || safeReportTypes.length"
            class="detail-section"
          >
            <h3 class="section-title">
              {{ t('analysis.taskConfig') }}
            </h3>
            <div class="info-grid">
              <div
                v-if="safeReportTypes.length"
                class="info-row"
              >
                <span class="info-label">{{ t('analysis.reportTypes') }}</span>
                <span class="info-value">{{ safeReportTypes.join(', ') }}</span>
              </div>
              <div
                v-if="safeScopes.length"
                class="info-row"
              >
                <span class="info-label">{{ t('analysis.directoryScopes') }}</span>
                <span class="info-value scopes-list">
                  <span
                    v-for="s in safeScopes"
                    :key="s"
                    class="scope-tag"
                  >{{ s }}</span>
                </span>
              </div>
              <div
                v-if="task.scope"
                class="info-row"
              >
                <span class="info-label">{{ t('analysis.analysisRoot') }}</span>
                <span class="info-value">{{ task.scope }}</span>
              </div>
              <div
                v-if="safeExtensions.length"
                class="info-row"
              >
                <span class="info-label">{{ t('analysis.fileExtensions') }}</span>
                <span class="info-value">{{ safeExtensions.join(', ') }}</span>
              </div>
              <div
                v-if="safeExcludeDirs.length"
                class="info-row"
              >
                <span class="info-label">{{ t('analysis.excludeDirs') }}</span>
                <span class="info-value">{{ safeExcludeDirs.join(', ') }}</span>
              </div>
            </div>
          </div>

          <!-- 文件分布 -->
          <div
            v-if="totalFiles > 0"
            class="detail-section"
          >
            <h3 class="section-title">
              {{ t('analysis.fileDistribution') }}
              <span
                v-if="loadingDistribution"
                class="distribution-loading"
              >{{ t('common.loading') }}...</span>
            </h3>
            <div class="distribution-summary">
              <span class="distribution-total">{{ t('analysis.totalFilesCount', { count: totalFiles }) }}</span>
            </div>
            <div class="distribution-bars">
              <div
                v-for="[ext, count] in sortedDistribution"
                :key="ext"
                class="distribution-row"
              >
                <span class="distribution-ext">{{ formatExtension(ext) }}</span>
                <div class="distribution-bar-bg">
                  <div
                    class="distribution-bar-fill"
                    :style="{ width: `${(count / totalFiles) * 100}%` }"
                  />
                </div>
                <span class="distribution-count">{{ count }}</span>
              </div>
            </div>
          </div>

          <!-- 运行历史 -->
          <div
            v-if="taskRuns.length > 0"
            class="detail-section"
          >
            <h3 class="section-title">
              {{ t('analysis.runHistory') }}
            </h3>
            <div class="runs-table">
              <div class="runs-table-header">
                <span class="runs-col">#</span>
                <span class="runs-col">{{ t('analysis.status') }}</span>
                <span class="runs-col">{{ t('analysis.startTime') }}</span>
                <span class="runs-col">{{ t('analysis.endTime') }}</span>
                <span class="runs-col">{{ t('analysis.duration') }}</span>
              </div>
              <div
                v-for="run in taskRuns"
                :key="run.id"
                class="runs-table-row"
                :class="{ 'runs-table-row--selected': run.id === selectedRunId }"
                @click="handleSelectRun(run.id)"
              >
                <span class="runs-col">{{ run.runNumber }}</span>
                <span class="runs-col">
                  <span
                    class="status-dot"
                    :style="{ background: formatRunStatusColor(run.status) }"
                  />
                  {{ formatRunStatus(run.status) }}
                </span>
                <span class="runs-col">{{ run.startedAt }}</span>
                <span class="runs-col">{{ run.finishedAt || '--' }}</span>
                <span class="runs-col">{{ formatDurationMs(run.durationMs) }}</span>
              </div>
            </div>
          </div>

          <!-- 错误信息 -->
          <div
            v-if="task.error"
            class="detail-section"
          >
            <h3 class="section-title">
              {{ t('analysis.error') }}
            </h3>
            <div class="error-message">
              {{ task.error }}
            </div>
          </div>

          <!-- 执行日志 -->
          <div class="detail-section">
            <div class="logs-header">
              <h3 class="section-title">
                {{ t('analysis.executionLogs') }}
              </h3>
              <select
                v-if="taskRuns.length > 1"
                v-model="selectedRunId"
                class="run-select"
                @change="handleSelectRun(($event.target as HTMLSelectElement).value)"
              >
                <option
                  v-for="run in taskRuns"
                  :key="run.id"
                  :value="run.id"
                >
                  Run #{{ run.runNumber }} ({{ formatRunStatus(run.status) }})
                </option>
              </select>
            </div>
            <div
              v-if="loadingLogs"
              class="logs-loading"
            >
              <div class="loading-spinner" />
            </div>
            <div
              v-else-if="logs.length === 0"
              class="logs-empty"
            >
              <ClockIcon class="w-4 h-4" />
              <span>{{ t('analysis.noLogs') }}</span>
            </div>
            <div
              v-else
              class="logs-container"
            >
              <div
                v-for="(log, idx) in logs"
                :key="idx"
                class="log-entry"
              >
                <span class="log-time">{{ log.timestamp }}</span>
                <span class="log-message">{{ log.message }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 底部按钮 -->
        <div class="dialog-footer">
          <button
            class="btn btn-ghost"
            @click="handleClose"
          >
            {{ t('common.close') }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
.dialog-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.task-detail-dialog {
  width: 600px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.dialog-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  font-weight: 600;
  color: var(--text-primary);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.status-badge {
  padding: 2px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
}

.dialog-close-btn {
  width: 24px;
  height: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 4px;
  background: transparent;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
}

.dialog-close-btn:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.dialog-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0;
}

.info-grid {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: 8px 16px;
}

.info-row {
  display: contents;
}

.info-label {
  font-size: 12px;
  color: var(--text-muted);
}

.info-value {
  font-size: 12px;
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.scopes-list {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.scope-tag {
  padding: 1px 6px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  font-size: 11px;
  font-family: monospace;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* File distribution */
.distribution-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.distribution-total {
  font-size: 12px;
  color: var(--text-muted);
}

.distribution-loading {
  font-size: 11px;
  color: var(--accent);
}

.distribution-bars {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.distribution-row {
  display: grid;
  grid-template-columns: 70px 1fr 40px;
  gap: 8px;
  align-items: center;
  font-size: 11px;
}

.distribution-ext {
  color: var(--text-secondary);
  font-family: monospace;
  text-align: right;
  white-space: nowrap;
}

.distribution-bar-bg {
  height: 14px;
  background: var(--bg-tertiary);
  border-radius: 3px;
  overflow: hidden;
}

.distribution-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 3px;
  transition: width 0.3s;
  min-width: 2px;
}

.distribution-count {
  color: var(--text-muted);
  text-align: right;
}

.progress-bar-inline {
  width: 80px;
  height: 8px;
  background: var(--bg-tertiary);
  border-radius: 4px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.3s;
  border-radius: 4px;
}

.error-message {
  padding: 8px 12px;
  background: var(--error)11;
  border: 1px solid var(--error)33;
  border-radius: 4px;
  font-size: 12px;
  color: var(--error);
  font-family: monospace;
}

.logs-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.logs-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 20px;
  font-size: 12px;
  color: var(--text-muted);
}

.logs-container {
  max-height: 200px;
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 8px;
  font-family: monospace;
  font-size: 11px;
}

.log-entry {
  display: flex;
  gap: 8px;
  padding: 2px 0;
  line-height: 1.5;
}

.log-time {
  color: var(--text-muted);
  flex-shrink: 0;
}

.log-message {
  color: var(--text-secondary);
}

.dialog-footer {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
  border-top: 1px solid var(--border);
}

.logs-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.run-select {
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text-primary);
  font-size: 11px;
  padding: 2px 6px;
  outline: none;
  cursor: pointer;
}

.run-select:focus {
  border-color: var(--accent);
}

.runs-table {
  border: 1px solid var(--border);
  border-radius: 4px;
  overflow: hidden;
}

.runs-table-header {
  display: grid;
  grid-template-columns: 40px 100px 1fr 1fr 80px;
  gap: 8px;
  padding: 6px 8px;
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);
  font-size: 11px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.runs-table-row {
  display: grid;
  grid-template-columns: 40px 100px 1fr 1fr 80px;
  gap: 8px;
  padding: 6px 8px;
  font-size: 12px;
  color: var(--text-secondary);
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  align-items: center;
}

.runs-table-row:last-child {
  border-bottom: none;
}

.runs-table-row:hover {
  background: var(--bg-hover);
}

.runs-table-row--selected {
  background: var(--accent)11;
}

.runs-col {
  display: flex;
  align-items: center;
  gap: 4px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
