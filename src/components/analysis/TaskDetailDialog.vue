<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, ClockIcon, DocumentTextIcon } from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import type { AnalysisTask, TaskLogEntry, TaskRun } from '@/types/ipc'

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
    stopped: 'var(--warning)',
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

const statusLabel = computed(() => {
  const map: Record<string, string> = {
    running: t('analysis.running'),
    done: t('analysis.done'),
    error: t('analysis.error'),
    stopped: t('analysis.stopped'),
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
    stopped: t('analysis.stopped'),
  }
  return map[status] || status
}

function formatRunStatusColor(status: string): string {
  const map: Record<string, string> = {
    running: 'var(--accent)',
    done: 'var(--success)',
    error: 'var(--error)',
    stopped: 'var(--warning)',
  }
  return map[status] || 'var(--text-muted)'
}
</script>

<template>
  <Teleport to="body">
    <div v-if="visible" class="dialog-overlay" @click.self="handleClose">
      <div class="task-detail-dialog">
        <!-- 标题栏 -->
        <div class="dialog-header">
          <div class="dialog-title">
            <span class="status-dot" :style="{ background: statusColor }"></span>
            <span>{{ task.name }}</span>
            <span class="status-badge" :style="{ background: statusColor + '22', color: statusColor }">
              {{ statusLabel }}
            </span>
          </div>
          <button class="dialog-close-btn" @click="handleClose">
            <XMarkIcon class="w-4 h-4" />
          </button>
        </div>

        <!-- 内容区 -->
        <div class="dialog-body">
          <!-- 基本信息 -->
          <div class="detail-section">
            <h3 class="section-title">{{ t('analysis.basicInfo') }}</h3>
            <div class="info-grid">
              <div class="info-row">
                <span class="info-label">{{ t('analysis.taskId') }}</span>
                <span class="info-value">{{ task.id }}</span>
              </div>
              <div class="info-row">
                <span class="info-label">{{ t('analysis.status') }}</span>
                <span class="info-value">
                  <span class="status-dot" :style="{ background: statusColor }"></span>
                  {{ statusLabel }}
                </span>
              </div>
              <div class="info-row" v-if="task.progress != null">
                <span class="info-label">{{ t('analysis.progress') }}</span>
                <span class="info-value">
                  <div class="progress-bar-inline">
                    <div class="progress-fill" :style="{ width: `${task.progress}%` }"></div>
                  </div>
                  {{ task.progress }}% ({{ task.current || 0 }}/{{ task.total || 0 }})
                </span>
              </div>
              <div class="info-row" v-if="task.createdAt">
                <span class="info-label">{{ t('analysis.createdAt') }}</span>
                <span class="info-value">{{ task.createdAt }}</span>
              </div>
              <div class="info-row" v-if="task.updatedAt">
                <span class="info-label">{{ t('analysis.updatedAt') }}</span>
                <span class="info-value">{{ task.updatedAt }}</span>
              </div>
            </div>
          </div>

          <!-- 分析配置 -->
          <div class="detail-section" v-if="task.scope || safeExtensions.length || safeExcludeDirs.length || safeReportTypes.length">
            <h3 class="section-title">{{ t('analysis.taskConfig') }}</h3>
            <div class="info-grid">
              <div class="info-row" v-if="safeReportTypes.length">
                <span class="info-label">{{ t('analysis.reportTypes') }}</span>
                <span class="info-value">{{ safeReportTypes.join(', ') }}</span>
              </div>
              <div class="info-row" v-if="task.scope">
                <span class="info-label">{{ t('analysis.analysisRoot') }}</span>
                <span class="info-value">{{ task.scope }}</span>
              </div>
              <div class="info-row" v-if="safeExtensions.length">
                <span class="info-label">{{ t('analysis.fileExtensions') }}</span>
                <span class="info-value">{{ safeExtensions.join(', ') }}</span>
              </div>
              <div class="info-row" v-if="safeExcludeDirs.length">
                <span class="info-label">{{ t('analysis.excludeDirs') }}</span>
                <span class="info-value">{{ safeExcludeDirs.join(', ') }}</span>
              </div>
            </div>
          </div>

          <!-- 运行历史 -->
          <div class="detail-section" v-if="taskRuns.length > 0">
            <h3 class="section-title">{{ t('analysis.runHistory') }}</h3>
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
                  <span class="status-dot" :style="{ background: formatRunStatusColor(run.status) }"></span>
                  {{ formatRunStatus(run.status) }}
                </span>
                <span class="runs-col">{{ run.startedAt }}</span>
                <span class="runs-col">{{ run.finishedAt || '--' }}</span>
                <span class="runs-col">{{ formatDurationMs(run.durationMs) }}</span>
              </div>
            </div>
          </div>

          <!-- 错误信息 -->
          <div class="detail-section" v-if="task.error">
            <h3 class="section-title">{{ t('analysis.error') }}</h3>
            <div class="error-message">{{ task.error }}</div>
          </div>

          <!-- 执行日志 -->
          <div class="detail-section">
            <div class="logs-header">
              <h3 class="section-title">{{ t('analysis.executionLogs') }}</h3>
              <select
                v-if="taskRuns.length > 1"
                v-model="selectedRunId"
                @change="handleSelectRun(($event.target as HTMLSelectElement).value)"
                class="run-select"
              >
                <option v-for="run in taskRuns" :key="run.id" :value="run.id">
                  Run #{{ run.runNumber }} ({{ formatRunStatus(run.status) }})
                </option>
              </select>
            </div>
            <div v-if="loadingLogs" class="logs-loading">
              <div class="loading-spinner"></div>
            </div>
            <div v-else-if="logs.length === 0" class="logs-empty">
              <ClockIcon class="w-4 h-4" />
              <span>{{ t('analysis.noLogs') }}</span>
            </div>
            <div v-else class="logs-container">
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
          <button class="btn btn-ghost" @click="handleClose">
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
