<script setup lang="ts">
/**
 * ReportTaskListPanel — Agent 分析任务执行状态。
 *
 * 显示请求层面的运行信息：状态、耗时、成功/失败、失败原因。
 * 数据不持久化，来自 ZMQ PUB task.progress / task.complete 事件。
 */

import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { PlayIcon, ArrowPathIcon, CheckCircleIcon, XCircleIcon, ClockIcon } from '@heroicons/vue/24/outline'
import { useSettingsStore } from '@/stores/settings-store'
import { useProjectStore } from '@/stores/project'
import { useAnalysisStore } from '@/stores/analysis'
import { ipc } from '@/services/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('RP-TL')
const { t } = useI18n()
const settingsStore = useSettingsStore()
const projectStore = useProjectStore()
const analysisStore = useAnalysisStore()

const props = defineProps<{ taskId: string; taskName?: string }>()

const projectId = computed(() => projectStore.selectedProjectId || '')

interface TaskRun {
  id: string
  taskId: string
  runNumber: number
  status: 'running' | 'done' | 'error' | 'stopped'
  progress: number
  total: number
  current: number
  startedAt: string
  finishedAt?: string
  durationMs?: number
  error?: string
}

const runs = ref<TaskRun[]>([])
const loading = ref(false)

function loadRuns() {
  loading.value = true
  analysisStore.getTaskRuns(props.taskId).then((rows: any[]) => {
    runs.value = (rows || []).map((r: any) => ({
      id: r.id,
      taskId: r.taskId || r.task_id,
      runNumber: r.runNumber || r.run_number,
      status: r.status,
      progress: r.progress || 0,
      total: r.total || 100,
      current: r.current || 0,
      startedAt: r.startedAt || r.started_at,
      finishedAt: r.finishedAt || r.finished_at,
      durationMs: r.durationMs || r.duration_ms,
      error: r.error,
    }))
  }).catch(() => {}).finally(() => {
    loading.value = false
  })
}

function formatDuration(ms: number | undefined): string {
  if (!ms) return '-'
  if (ms < 1000) return `${ms}ms`
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`
  return `${Math.floor(ms / 60000)}m${Math.round((ms % 60000) / 1000)}s`
}

function formatTime(iso: string | undefined): string {
  if (!iso) return '-'
  return iso.slice(11, 19)
}

function statusIcon(status: string) {
  switch (status) {
    case 'done': return CheckCircleIcon
    case 'error': return XCircleIcon
    case 'running': return ArrowPathIcon
    case 'stopped': return XCircleIcon
    default: return ClockIcon
  }
}

onMounted(() => loadRuns())
</script>

<template>
  <div class="task-run-panel">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <div class="panel-header">
      <PlayIcon class="hdr-icon" />
      <span>{{ t('report.taskRuns', '分析任务执行') }}</span>
      <button
        class="refresh-btn"
        :disabled="loading"
        @click="loadRuns"
      >
        <ArrowPathIcon
          class="refresh-icon"
          :class="{ spin: loading }"
        />
      </button>
    </div>
    <div class="panel-body">
      <div
        v-if="runs.length === 0"
        class="empty-state"
      >
        <p>{{ t('report.noRuns', '暂无执行记录') }}</p>
      </div>
      <div
        v-for="run in runs"
        :key="run.id"
        class="run-item"
      >
        <component
          :is="statusIcon(run.status)"
          class="run-icon"
          :class="`status-${run.status}`"
        />
        <div class="run-info">
          <div class="run-header">
            <span class="run-number">#{{ run.runNumber }}</span>
            <span
              class="run-status"
              :class="`status-${run.status}`"
            >
              {{ run.status === 'done' ? '成功' : run.status === 'error' ? '失败' : run.status === 'running' ? '运行中' : '停止' }}
            </span>
          </div>
          <div class="run-meta">
            <span class="run-time">{{ formatTime(run.startedAt) }}</span>
            <span class="run-duration"> · {{ formatDuration(run.durationMs) }}</span>
          </div>
          <div
            v-if="run.error"
            class="run-error"
          >
            {{ run.error }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-run-panel { background: var(--bg-primary, #1a1a2e); border-radius: 0.5rem; overflow: hidden; }
.panel-header { display: flex; align-items: center; gap: 0.5rem; padding: 0.6rem 0.9rem; border-bottom: 1px solid var(--border); font-size: 0.8rem; font-weight: 600; color: var(--text-primary); }
.hdr-icon { width: 0.9rem; height: 0.9rem; }
.refresh-btn { margin-left: auto; background: none; border: none; cursor: pointer; }
.refresh-icon { width: 0.8rem; height: 0.8rem; color: var(--text-muted); }
.refresh-icon.spin { animation: spin 0.8s linear infinite; }
@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
.panel-body { padding: 0.25rem; max-height: 300px; overflow-y: auto; }
.empty-state { padding: 2rem 1rem; text-align: center; color: var(--text-secondary); font-size: 0.8rem; }
.run-item { display: flex; gap: 0.5rem; padding: 0.4rem 0.6rem; border-radius: 0.375rem; }
.run-item:hover { background: var(--bg-secondary); }
.run-icon { width: 1rem; height: 1rem; flex-shrink: 0; margin-top: 0.15rem; }
.status-done { color: #22c55e; }
.status-error { color: #ef4444; }
.status-running { color: var(--accent, #7c3aed); animation: pulse 1.2s infinite; }
.status-stopped { color: #f59e0b; }
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.4} }
.run-info { flex: 1; min-width: 0; }
.run-header { display: flex; justify-content: space-between; align-items: center; }
.run-number { font-size: 0.75rem; color: var(--text-muted); }
.run-status { font-size: 0.7rem; font-weight: 500; }
.run-meta { font-size: 0.65rem; color: var(--text-muted); margin-top: 0.1rem; }
.run-error { font-size: 0.7rem; color: #ef4444; margin-top: 0.2rem; background: #3b1111; padding: 0.2rem 0.4rem; border-radius: 0.25rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
</style>
