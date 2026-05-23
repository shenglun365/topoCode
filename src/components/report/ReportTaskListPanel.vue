<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  PlayIcon,
  PauseIcon,
  StopIcon,
  ArrowPathIcon,
  TrashIcon,
  CheckCircleIcon,
  XCircleIcon,
  ClockIcon,
  SparklesIcon,
} from '@heroicons/vue/24/outline'
import { usePipelineStore } from '@/stores/pipeline'
import type { PipelineTaskNode } from '@/types/ipc'
import { useComponentId } from '@/composables/useComponentId'

const { t } = useI18n()
const store = usePipelineStore()
const containerRef = ref<HTMLElement | null>(null)

const containerWidth = ref(320)

const { showId, componentId } = useComponentId('RP-005')

function updateWidth() {
  if (containerRef.value) {
    containerWidth.value = containerRef.value.clientWidth
  }
}

onMounted(() => {
  updateWidth()
  window.addEventListener('resize', updateWidth)
})
onUnmounted(() => {
  window.removeEventListener('resize', updateWidth)
})

const maxNameLen = computed(() => {
  const w = containerWidth.value
  if (w < 250) return 10
  if (w < 300) return 14
  if (w < 350) return 18
  if (w < 400) return 24
  return 30
})

const leafTasks = computed(() => {
  const result: { node: PipelineTaskNode; depth: number }[] = []
  function walk(nodes: PipelineTaskNode[] | undefined, depth: number) {
    if (!nodes) return
    for (const n of nodes) {
      if (n.children && n.children.length > 0) {
        walk(n.children, depth + 1)
      } else {
        result.push({ node: n, depth })
      }
    }
  }
  if (store.rootTask?.children) walk(store.rootTask.children, 0)
  return result
})

function truncate(name: string): string {
  if (name.length <= maxNameLen.value) return name
  return name.slice(0, maxNameLen.value) + '…'
}

function statusIcon(status: string) {
  switch (status) {
    case 'completed': return CheckCircleIcon
    case 'running': case 'queued': return ClockIcon
    case 'error': return XCircleIcon
    default: return ClockIcon
  }
}

function statusClass(status: string): string {
  switch (status) {
    case 'completed': return 'task-completed'
    case 'running': case 'queued': return 'task-running'
    case 'error': return 'task-error'
    default: return 'task-pending'
  }
}

const ctrl = computed(() => store.controls)

function handleRunAll() { ctrl.value?.runAll() }
function handlePause() { ctrl.value?.pause() }
function handleResume() { ctrl.value?.resume() }
function handleStop() { ctrl.value?.stop() }
function handleReset() { ctrl.value?.reset() }
function handleRetryTask(nodeId: string) {
  const update = (node: PipelineTaskNode): boolean => {
    if (node.id === nodeId) {
      node.status = 'pending'
      node.error = undefined
      return true
    }
    if (node.children) for (const c of node.children) if (update(c)) return true
    return false
  }
  if (store.rootTask) update(store.rootTask)
}
function handleCancelTask(nodeId: string) {
  const update = (node: PipelineTaskNode): boolean => {
    if (node.id === nodeId) {
      if (node.status === 'running' || node.status === 'queued') {
        node.status = 'skipped'
      }
      return true
    }
    if (node.children) for (const c of node.children) if (update(c)) return true
    return false
  }
  if (store.rootTask) update(store.rootTask)
}
</script>

<template>
  <div ref="containerRef" class="task-list-panel">
    <span v-if="showId" class="cmp-id">{{ componentId }}</span>
    <!-- 空状态 -->
    <div v-if="!store.rootTask" class="tl-empty">
      <SparklesIcon class="w-8 h-8" />
      <span>{{ t('report.taskList.empty') }}</span>
    </div>

    <template v-else>
      <!-- 全局进度 -->
      <div class="tl-header">
        <div class="tl-progress-row">
          <span class="tl-progress-label">{{ t('report.taskList.progress') }}:</span>
          <span class="tl-progress-text">{{ store.completedCount }}/{{ store.totalCount }}</span>
        </div>
        <div class="tl-progress-bar">
          <div class="tl-progress-fill" :style="{ width: store.progress + '%' }"></div>
        </div>
      </div>

      <!-- 全局操作 -->
      <div class="tl-global-actions">
        <button v-if="!store.running && store.progress === 0" class="btn btn-primary btn-xs" @click="handleRunAll">
          <PlayIcon class="w-3 h-3" /> {{ t('report.taskList.startAll') }}
        </button>
        <template v-if="store.running">
          <button v-if="!store.paused" class="btn btn-warning btn-xs" @click="handlePause">
            <PauseIcon class="w-3 h-3" /> {{ t('common.pause') }}
          </button>
          <button v-else class="btn btn-primary btn-xs" @click="handleResume">
            <PlayIcon class="w-3 h-3" /> {{ t('common.resume') }}
          </button>
          <button class="btn btn-ghost btn-xs" @click="handleStop">
            <StopIcon class="w-3 h-3" /> {{ t('report.taskList.stop') }}
          </button>
        </template>
        <template v-if="store.progress > 0 && !store.running">
          <button class="btn btn-ghost btn-xs" @click="handleReset">
            <ArrowPathIcon class="w-3 h-3" /> {{ t('common.reset') }}
          </button>
        </template>
      </div>

      <!-- 任务列表 -->
      <div class="tl-tasks">
        <div
          v-for="{ node, depth } in leafTasks"
          :key="node.id"
          :class="['tl-task-row', statusClass(node.status)]"
          :style="{ paddingLeft: (8 + depth * 12) + 'px' }"
        >
          <Component :is="statusIcon(node.status)" class="tl-task-icon" />
          <span class="tl-task-name" :title="node.label">
            {{ truncate(node.label) }}
          </span>
          <span v-if="node.status === 'running' && node.progress > 0" class="tl-task-progress">
            {{ node.progress }}%
          </span>
          <div class="tl-task-actions">
            <button
              v-if="node.status === 'error'"
              class="btn btn-ghost btn-xs"
              @click.stop="handleRetryTask(node.id)"
              :title="t('common.retry')"
            >
              <ArrowPathIcon class="w-2.5 h-2.5" />
            </button>
            <button
              v-if="node.status === 'running' || node.status === 'queued'"
              class="btn btn-ghost btn-xs"
              @click.stop="handleCancelTask(node.id)"
              :title="t('report.taskList.cancel')"
            >
              <StopIcon class="w-2.5 h-2.5" />
            </button>
          </div>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.task-list-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
  font-size: 11px;
  overflow: hidden;
}

.tl-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-muted);
  font-size: 11px;
}

.tl-header {
  padding: 8px 10px 4px;
  border-bottom: 1px solid var(--border);
}

.tl-progress-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 4px;
}

.tl-progress-label { color: var(--text-muted); font-size: 10px; }
.tl-progress-text { color: var(--text-secondary); font-family: var(--font-mono); font-size: 10px; }

.tl-progress-bar {
  height: 4px;
  background: var(--bg-primary);
  border-radius: 2px;
  overflow: hidden;
}

.tl-progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.3s;
}

.tl-global-actions {
  display: flex;
  gap: 4px;
  padding: 6px 10px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}

.tl-tasks {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.tl-task-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  cursor: default;
  transition: background 0.1s;
}

.tl-task-row:hover { background: var(--bg-tertiary); }

.tl-task-icon { width: 12px; height: 12px; flex-shrink: 0; }
.task-completed .tl-task-icon { color: var(--success); }
.task-running .tl-task-icon { color: var(--accent); animation: pulse 1.5s infinite; }
.task-error .tl-task-icon { color: var(--error); }
.task-pending .tl-task-icon { color: var(--text-muted); }

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

.tl-task-name {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-primary);
  font-size: 10px;
  min-width: 0;
}

.tl-task-progress {
  font-size: 9px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  flex-shrink: 0;
}

.tl-task-actions {
  display: flex;
  gap: 2px;
  flex-shrink: 0;
  opacity: 0;
  transition: opacity 0.15s;
}

.tl-task-row:hover .tl-task-actions { opacity: 1; }
</style>
