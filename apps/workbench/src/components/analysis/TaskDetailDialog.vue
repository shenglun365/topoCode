<script setup lang="ts">
import { ref, computed, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { XMarkIcon, ClockIcon, DocumentTextIcon } from '@heroicons/vue/24/outline'
import { useAnalysisStore } from '@/stores/analysis'
import type { AnalysisTask, TaskLogEntry, TaskRun } from '@topo/web-core/types/ipc'
import { useComponentId } from '@topo/web-core/composables/useComponentId'
import { displayDispatcher } from '@/services/display-dispatcher'

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
  const data = props.task.reportTypes || props.task.reportTypes
  if (!data) return []
  return Array.isArray(data) ? data : JSON.parse(data)
})
const safeExcludeDirs = computed(() => {
  const data = props.task.excludeDirs || props.task.excludeDirs
  if (!data) return []
  return Array.isArray(data) ? data : JSON.parse(data)
})
const safeScopes = computed(() => {
  const data = props.task.scopes
  if (!data) return []
  return Array.isArray(data) ? data : ((data as string).split?.(',') || [])
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
  if (props.task.status !== 'running') return
  const key = `task-logs:${props.task.id}:${selectedRunId.value || 'latest'}`
  if (displayDispatcher.has(key)) return
  displayDispatcher.register(key, {
    interval: 2000,
    fetcher: () => loadLogs(selectedRunId.value).then(() => undefined),
  })
}

function stopPolling() {
  displayDispatcher.unregister(`task-logs:${props.task.id}:${selectedRunId.value || 'latest'}`)
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
  stopPolling()
  selectedRunId.value = runId
  loadLogs(runId)
  startPolling()
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
                v-show="task.progress != null"
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
                  {{ typeof task.progress === 'number' ? task.progress.toFixed(2) : task.progress }}%
                  ({{ task.current || 0 }}/{{ task.total || 0 }})
                  <span
                    v-if="task.eta"
                    style="margin-left:calc(6px * var(--ui-scale, 1)); opacity:0.7; font-size:calc(10px * var(--ui-scale, 1));"
                  >
                    {{ t('analysis.etaRemaining', { eta: task.eta }) }}
                  </span>
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
              v-show="loadingLogs"
              class="logs-loading"
            >
              <div class="loading-spinner" />
            </div>
            <div
              v-show="!loadingLogs && logs.length === 0"
              class="logs-empty"
            >
              <ClockIcon class="w-4 h-4" />
              <span>{{ t('analysis.noLogs') }}</span>
            </div>
            <div
              v-show="!loadingLogs && logs.length > 0"
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
  width: calc(600px * var(--ui-scale, 1));
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: calc(8px * var(--ui-scale, 1));
  overflow: hidden;
}

.dialog-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1));
  border-bottom: 1px solid var(--border);
}

.dialog-title {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  font-size: calc(14px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-primary);
}

.status-dot {
  width: calc(8px * var(--ui-scale, 1));
  height: calc(8px * var(--ui-scale, 1));
  border-radius: 50%;
  flex-shrink: 0;
}

.status-badge {
  padding: calc(2px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  border-radius: calc(10px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  font-weight: 500;
}

.dialog-close-btn {
  width: calc(24px * var(--ui-scale, 1));
  height: calc(24px * var(--ui-scale, 1));
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: calc(4px * var(--ui-scale, 1));
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
  padding: calc(16px * var(--ui-scale, 1));
  display: flex;
  flex-direction: column;
  gap: calc(20px * var(--ui-scale, 1));
}

.detail-section {
  display: flex;
  flex-direction: column;
  gap: calc(8px * var(--ui-scale, 1));
}

.section-title {
  font-size: calc(12px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin: 0;
}

.info-grid {
  display: grid;
  grid-template-columns: 120px 1fr;
  gap: calc(8px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1));
}

.info-row {
  display: contents;
}

.info-label {
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-muted);
}

.info-value {
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-primary);
  display: flex;
  align-items: center;
  gap: calc(6px * var(--ui-scale, 1));
  flex-wrap: wrap;
}

.scopes-list {
  display: flex;
  flex-wrap: wrap;
  gap: calc(4px * var(--ui-scale, 1));
}

.scope-tag {
  padding: 1px calc(6px * var(--ui-scale, 1));
  background: var(--bg-tertiary);
  border-radius: calc(3px * var(--ui-scale, 1));
  font-size: calc(11px * var(--ui-scale, 1));
  font-family: monospace;
  color: var(--text-secondary);
  white-space: nowrap;
}

/* File distribution */
.distribution-summary {
  display: flex;
  align-items: center;
  gap: calc(8px * var(--ui-scale, 1));
  margin-bottom: calc(8px * var(--ui-scale, 1));
}

.distribution-total {
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-muted);
}

.distribution-loading {
  font-size: calc(11px * var(--ui-scale, 1));
  color: var(--accent);
}

.distribution-bars {
  display: flex;
  flex-direction: column;
  gap: calc(4px * var(--ui-scale, 1));
}

.distribution-row {
  display: grid;
  grid-template-columns: 70px 1fr 40px;
  gap: calc(8px * var(--ui-scale, 1));
  align-items: center;
  font-size: calc(11px * var(--ui-scale, 1));
}

.distribution-ext {
  color: var(--text-secondary);
  font-family: monospace;
  text-align: right;
  white-space: nowrap;
}

.distribution-bar-bg {
  height: calc(14px * var(--ui-scale, 1));
  background: var(--bg-tertiary);
  border-radius: calc(3px * var(--ui-scale, 1));
  overflow: hidden;
}

.distribution-bar-fill {
  height: 100%;
  background: var(--accent);
  border-radius: calc(3px * var(--ui-scale, 1));
  transition: width 0.3s;
  min-width: calc(2px * var(--ui-scale, 1));
}

.distribution-count {
  color: var(--text-muted);
  text-align: right;
}

.progress-bar-inline {
  width: calc(80px * var(--ui-scale, 1));
  height: calc(8px * var(--ui-scale, 1));
  background: var(--bg-tertiary);
  border-radius: calc(4px * var(--ui-scale, 1));
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  background: var(--accent);
  transition: width 0.3s;
  border-radius: calc(4px * var(--ui-scale, 1));
}

.error-message {
  padding: calc(8px * var(--ui-scale, 1)) calc(12px * var(--ui-scale, 1));
  background: var(--error)11;
  border: 1px solid var(--error)33;
  border-radius: calc(4px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--error);
  font-family: monospace;
}

.logs-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: calc(20px * var(--ui-scale, 1));
}

.loading-spinner {
  width: calc(24px * var(--ui-scale, 1));
  height: calc(24px * var(--ui-scale, 1));
  border: 2px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: task-detail-spin 0.6s linear infinite;
}

@keyframes task-detail-spin {
  to { transform: rotate(360deg); }
}

.logs-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(20px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
  color: var(--text-muted);
}

.logs-container {
  max-height: calc(200px * var(--ui-scale, 1));
  overflow-y: auto;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: calc(4px * var(--ui-scale, 1));
  padding: calc(8px * var(--ui-scale, 1));
  font-family: monospace;
  font-size: calc(11px * var(--ui-scale, 1));
}

.log-entry {
  display: flex;
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(2px * var(--ui-scale, 1)) 0;
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
  padding: calc(12px * var(--ui-scale, 1)) calc(16px * var(--ui-scale, 1));
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
  border-radius: calc(4px * var(--ui-scale, 1));
  color: var(--text-primary);
  font-size: calc(11px * var(--ui-scale, 1));
  padding: calc(2px * var(--ui-scale, 1)) calc(6px * var(--ui-scale, 1));
  outline: none;
  cursor: pointer;
}

.run-select:focus {
  border-color: var(--accent);
}

.runs-table {
  border: 1px solid var(--border);
  border-radius: calc(4px * var(--ui-scale, 1));
  overflow: hidden;
}

.runs-table-header {
  display: grid;
  grid-template-columns: 40px 100px 1fr 1fr 80px;
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(6px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  background: var(--bg-tertiary);
  border-bottom: 1px solid var(--border);
  font-size: calc(11px * var(--ui-scale, 1));
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.runs-table-row {
  display: grid;
  grid-template-columns: 40px 100px 1fr 1fr 80px;
  gap: calc(8px * var(--ui-scale, 1));
  padding: calc(6px * var(--ui-scale, 1)) calc(8px * var(--ui-scale, 1));
  font-size: calc(12px * var(--ui-scale, 1));
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
  gap: calc(4px * var(--ui-scale, 1));
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
