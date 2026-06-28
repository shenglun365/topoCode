<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore } from '@/stores/community-store'
import { useProjectStore } from '@/stores/project'
import { PauseIcon, PlayIcon, StopIcon, ClockIcon } from '@heroicons/vue/24/outline'

const { t } = useI18n()
const communityStore = useCommunityStore()
const projectStore = useProjectStore()

const taskId = computed(() => projectStore.activeTab?.taskId || '')
const projectName = computed(() => projectStore.selectedProject?.name || '')
const taskName = computed(() => projectStore.activeTab?.title || taskId.value || '')

const cancellingTaskId = ref<string | null>(null)
const cancelFeedback = ref('')

function onCancelTask(taskIdVal: string, agentId: string) {
  if (cancellingTaskId.value === agentId) return
  cancellingTaskId.value = agentId
  cancelFeedback.value = '正在停止，等待当前 LLM 请求结束后完全终止'
  communityStore.cancelAgentTask(taskIdVal, agentId)
    .catch(() => { cancelFeedback.value = '停止失败，请重试' })
    .finally(() => { setTimeout(() => { cancellingTaskId.value = null }, 1000) })
  setTimeout(() => { cancelFeedback.value = '' }, 5000)
}

function onPauseTask(taskIdVal: string, agentId: string) {
  communityStore.pauseAgentTask(taskIdVal, agentId)
    .catch(() => {})
}

function onResumeTask(taskIdVal: string, agentId: string) {
  communityStore.resumeAgentTask(taskIdVal, agentId)
    .catch(() => {})
}

const historyTasks = ref<any[]>([])
const historyLoaded = ref(false)
const pageSize = ref(10)

function _historySame(a: any[], b: any[]): boolean {
  if (a.length !== b.length) return false
  return a.every((item, i) => {
    const o = b[i]
    return item.agent_id === o.agent_id && item.status === o.status
  })
}

const liveTasks = computed(() => {
  if (!taskId.value) return []
  return communityStore.tasks[taskId.value]?.agentTasks || []
})

// 合并 live + history，按 agent_id 去重（live 优先）
const allTasks = computed(() => {
  const live = liveTasks.value
  const history = historyTasks.value
  const seen = new Set<string>()
  const merged: any[] = []
  // live 优先
  for (const t of live) {
    seen.add(t.id)
    merged.push(t)
  }
  for (const t of history) {
    if (!seen.has(t.agent_id || t.id)) {
      // 跳过历史中 stale 的 running/queued 记录（无对应 live entry 说明是旧管线的残留）
      // 但 presummary_files 管线除外：后续批次会创建新 agent 且无 live placeholder
      if ((t.status === 'running' || t.status === 'queued') && !live.some(lt => lt.id === (t.agent_id || t.id))) {
        if (t.action !== 'presummary_files') continue
      }
      seen.add(t.agent_id || t.id)
      merged.push(transformHistory(t))
    }
  }
  // 按 created_at 倒序（最近在前）
  merged.sort((a, b) => (b.createdAt || '').localeCompare(a.createdAt || ''))
  return merged
})

const displayedTasks = computed(() => allTasks.value.slice(0, pageSize.value))
const hasMore = computed(() => pageSize.value < allTasks.value.length)

function transformHistory(h: any) {
  let steps: any[] = []
  try { steps = h.steps ? JSON.parse(h.steps) : [] } catch {}
  const task = {
    id: h.agent_id,
    action: h.action,
    status: h.status,
    progress: h.status === 'completed' ? 100 : h.status === 'failed' ? 0 : 0,
    message: h.message || '',
    steps,
    createdAt: h.created_at || '',
  }
  console.log('[transformHistory] agent=%s action=%s status=%s steps=%d', h.agent_id, h.action, h.status, steps.length)
  return task
}

async function loadHistory(cursor: number) {
  if (!taskId.value) return
  const results = await communityStore.loadAgentTaskHistory(taskId.value, cursor, 10)
  if (cursor === 0) {
    if (!_historySame(results, historyTasks.value)) {
      historyTasks.value = results
    }
  } else {
    for (const r of results) {
      if (!historyTasks.value.find(h => h.agent_id === r.agent_id)) {
        historyTasks.value.push(r)
      }
    }
  }
  historyLoaded.value = true
}

async function loadMore() {
  const before = historyTasks.value.length
  await loadHistory(before)
  pageSize.value += 10
}

async function refresh() {
  pageSize.value = 10
  historyLoaded.value = false
  await loadHistory(0)
  // 将 history 中新发现的 running presummary_files agent 注入 store，启动轮询
  const t = communityStore.tasks[taskId.value]
  if (t) {
    for (const h of historyTasks.value) {
      if (h.action === 'presummary_files' && (h.status === 'running' || h.status === 'queued')) {
        const existing = t.agentTasks.some(at => at.id === h.agent_id)
        if (!existing) {
          const idx = t.agentTasks.length
          t.agentTasks.push({
            id: h.agent_id, action: 'presummary_files', status: h.status || 'running',
            progress: 0, step: 0, total: 0, message: h.message || '',
            steps: [],
            createdAt: h.created_at || '',
          })
          communityStore.ensureAgentPolling(taskId.value)
          console.log('[refresh] injected history agent into store: %s', h.agent_id)
        }
      }
    }
  }
  const liveLen = liveTasks.value.length
  const historyLen = historyTasks.value.length
  console.log('[AgentTaskList] refreshed: live=%d history=%d all=%d', liveLen, historyLen, liveLen + historyLen)
}

async function clearHistory() {
  if (!taskId.value) return
  await communityStore.clearAgentTaskHistory(taskId.value)
  // 同时清理 store 中非 running 的 live agent
  const t = communityStore.tasks[taskId.value]
  if (t) {
    t.agentTasks = t.agentTasks.filter(at => at.status === 'running' || at.status === 'queued')
  }
  historyTasks.value = []
  pageSize.value = 10
}

onMounted(() => {
  refresh()
})

let historyPollTimer: ReturnType<typeof setInterval> | null = null

watch(liveTasks, (tasks) => {
  const hasPresummary = tasks.some(t => t.action === 'presummary_files')
  const hasRunning = tasks.some(t => t.status === 'running' || t.status === 'queued')
  console.log('[watchLive] hasRunning=%s hasPresummary=%s timer=%s tasks=%d', hasRunning, hasPresummary, historyPollTimer ? 'active' : 'none', tasks.length)
  if ((hasRunning || hasPresummary) && !historyPollTimer) {
    console.log('[watchLive] starting 3s history poll')
    historyPollTimer = setInterval(() => { refresh() }, 3000)
  } else if (!hasRunning && !hasPresummary && historyPollTimer) {
    console.log('[watchLive] stopping history poll')
    clearInterval(historyPollTimer)
    historyPollTimer = null
  }
}, { deep: true })

onUnmounted(() => {
  if (historyPollTimer) { clearInterval(historyPollTimer); historyPollTimer = null }
})

watch(taskId, (newId, oldId) => {
  if (newId && newId !== oldId) {
    refresh()
  }
})

function sumFileCount(steps: any[], statuses: string[]): number {
  return steps
    .filter(s => statuses.includes(s.status))
    .reduce((sum, s) => sum + (s.file_count || 1), 0)
}

const statusLabel = (status: string) => {
  const map: Record<string, string> = {
    queued: '排队中', running: '运行中', paused: '已暂停', completed: '已完成',
    partial: '部分完成', failed: '已失败', cancelled: '已取消',
    skipped: '已跳过', unknown: '未知',
  }
  return map[status] || '未知'
}

const actionLabel = (action: string) => {
  const map: Record<string, string> = {
    analyze_components: '组件分析',
    agentic_analyze_components: '智能组件分析',
    overview: '架构概览',
    analyze_all: '全量分析',
    analyzeCommFiles: '文件分析',
    presummary_files: '文件预摘要',
    pipeline: '流水线',
  }
  return map[action] || action
}

</script>

<template>
  <div class="atl-container">
    <div
      v-if="projectName || taskName"
      class="atl-header"
    >
      <span
        v-if="projectName"
        class="atl-project"
      >{{ projectName }}</span>
      <span
        v-if="taskName"
        class="atl-task-badge"
      >{{ taskName }}</span>
      <button
        v-if="allTasks.length > 0"
        class="atl-clear-btn"
        :title="t('report.clearHistory', '清除历史')"
        @click="clearHistory"
      >
        清除
      </button>
    </div>
    <div
      v-if="allTasks.length === 0 && historyLoaded"
      class="atl-empty"
    >
      {{ t('report.noAgentTasks', '暂无 Agent 任务') }}
    </div>
    <div
      v-if="!historyLoaded"
      class="atl-loading"
    >
      <span class="text-muted">{{ t('common.loading') }}</span>
    </div>
    <div
      v-for="(task, idx) in displayedTasks"
      :key="task.id"
      class="atl-task"
      :class="{
        'atl-task-success': task.status === 'completed',
        'atl-task-fail': task.status === 'failed' || task.status === 'partial',
        'atl-task-skipped': task.status === 'skipped',
        'atl-task-paused': task.status === 'paused',
      }"
    >
      <div class="atl-task-header">
        <span class="atl-status-label">{{ statusLabel(task.status) }}</span>
        <span class="atl-action">{{ actionLabel(task.action) }}</span>
        <span class="atl-status-text">{{ task.status }}</span>
        <span
          v-if="task.progress !== undefined"
          class="atl-progress"
        >{{ task.progress }}%</span>
        <button
          v-if="task.status === 'running' || task.status === 'queued'"
          class="atl-pause-btn"
          title="暂停此任务"
          @click="onPauseTask(taskId, task.id)"
        >
          <PauseIcon class="w-3 h-3" />
        </button>
        <button
          v-if="task.status === 'paused'"
          class="atl-resume-btn"
          title="恢复此任务"
          @click="onResumeTask(taskId, task.id)"
        >
          <PlayIcon class="w-3 h-3" />
        </button>
        <button
          v-if="task.status === 'running' || task.status === 'queued'"
          class="atl-stop-btn"
          :class="{ 'atl-stopping': cancellingTaskId === task.id }"
          :title="cancellingTaskId === task.id ? '正在停止...' : '停止此任务（等待当前 LLM 请求结束后完全终止）'"
          :disabled="cancellingTaskId === task.id"
          @click="onCancelTask(taskId, task.id)"
        >
          <ClockIcon v-if="cancellingTaskId === task.id" class="w-3 h-3" />
          <StopIcon v-else class="w-3 h-3" />
        </button>
      </div>
      <div
        v-if="task.status === 'running'"
        class="atl-progress-bar"
      >
        <div
          class="atl-progress-fill"
          :style="{ width: task.progress + '%' }"
        />
      </div>
      <div
        v-if="task.steps && task.steps.length > 0"
        class="atl-steps"
      >
        <div class="atl-step-compact">
          <span>已完成 </span>
          <span class="atl-compact-count">{{ sumFileCount(task.steps, ['done']) }}</span>
          <span>/{{ sumFileCount(task.steps, ['done','failed','pending','running']) }}</span>
          <span class="atl-compact-detail">
            （完成{{ sumFileCount(task.steps, ['done']) }}
            / 失败{{ sumFileCount(task.steps, ['failed']) }}
            / 剩余{{ sumFileCount(task.steps, ['pending','running']) }}）
          </span>
        </div>
        <div
          v-if="task.steps.find(s => s.status === 'running')"
          class="atl-step-current"
        >
          <span>当前: </span>
          <span>{{ task.steps.find(s => s.status === 'running')?.description }}</span>
        </div>
      </div>
    </div>
    <div
      v-if="hasMore"
      class="atl-more"
    >
      <button
        class="atl-more-btn"
        @click="loadMore"
      >
        加载更多
      </button>
    </div>
    <div
      v-if="cancelFeedback"
      class="atl-toast"
    >
      {{ cancelFeedback }}
    </div>
  </div>
</template>

<style scoped>
.atl-container { padding: 0.5rem; display: flex; flex-direction: column; gap: 0.5rem; }
.atl-header { display: flex; align-items: center; gap: 0.4rem; padding-bottom: 0.3rem; border-bottom: 1px solid var(--border); }
.atl-project { font-size: 0.7rem; font-weight: 600; color: var(--text-primary); }
.atl-task-badge { font-size: 0.65rem; color: var(--text-muted); background: var(--bg-tertiary); padding: 0.1rem 0.4rem; border-radius: 3px; }
.atl-clear-btn { margin-left: auto; font-size: 0.6rem; color: var(--text-muted); background: none; border: 1px solid var(--border); border-radius: 3px; padding: 0.05rem 0.4rem; cursor: pointer; }
.atl-clear-btn:hover { color: var(--danger, #ef4444); border-color: var(--danger, #ef4444); }
.atl-empty { font-size: 0.75rem; color: var(--text-muted); text-align: center; padding: 1rem; font-style: italic; }
.atl-loading { font-size: 0.7rem; text-align: center; padding: 1rem; }
.atl-task { background: var(--bg-primary); border: 1px solid var(--border); border-radius: 0.375rem; padding: 0.5rem; }
.atl-task-success { border-color: var(--success, #22c55e); background: color-mix(in srgb, var(--success, #22c55e) 5%, transparent); }
.atl-task-fail { border-color: var(--danger, #ef4444); background: color-mix(in srgb, var(--danger, #ef4444) 5%, transparent); }
.atl-task-skipped { border-color: var(--warning, #f59e0b); background: color-mix(in srgb, var(--warning, #f59e0b) 5%, transparent); }
.atl-task-header { display: flex; align-items: center; gap: 0.35rem; font-size: 0.75rem; }
.atl-status-label {
  font-size: 0.65rem;
  padding: 0.05rem 0.35rem;
  border-radius: 3px;
  background: var(--bg-tertiary);
  color: var(--text-muted);
  border: 1px solid var(--border);
}
.atl-task-success .atl-status-label {
  background: color-mix(in srgb, var(--success, #22c55e) 12%, transparent);
  color: var(--success, #22c55e);
  border-color: color-mix(in srgb, var(--success, #22c55e) 30%, transparent);
}
.atl-task-fail .atl-status-label {
  background: color-mix(in srgb, var(--danger, #ef4444) 12%, transparent);
  color: var(--danger, #ef4444);
  border-color: color-mix(in srgb, var(--danger, #ef4444) 30%, transparent);
}
.atl-task-skipped .atl-status-label {
  background: color-mix(in srgb, var(--warning, #f59e0b) 12%, transparent);
  color: var(--warning, #f59e0b);
  border-color: color-mix(in srgb, var(--warning, #f59e0b) 30%, transparent);
}
.atl-action { font-weight: 600; color: var(--text-primary); }
.atl-status-text { font-size: 0.6rem; color: var(--text-muted); font-family: var(--font-mono); }
.atl-task-success .atl-status-text { color: var(--success, #22c55e); }
.atl-task-fail .atl-status-text { color: var(--danger, #ef4444); }
.atl-task-skipped .atl-status-text { color: var(--warning, #f59e0b); }
.atl-stopping { opacity: 0.5; cursor: not-allowed; }
.atl-stopping:hover { background: transparent; color: var(--danger, #ef4444); }
.atl-toast {
  position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
  background: var(--bg-primary); border: 1px solid var(--warning, #f59e0b);
  border-radius: 0.5rem; padding: 0.8rem 1.2rem; font-size: 0.85rem;
  color: var(--text-primary); z-index: 9999; white-space: nowrap;
  box-shadow: 0 8px 32px rgba(0,0,0,0.35);
  animation: atl-toast-in 0.2s ease;
}
@keyframes atl-toast-in { from { opacity: 0; transform: translate(-50%, -50%) translateY(-8px); } to { opacity: 1; transform: translate(-50%, -50%) translateY(0); } }
.atl-stop-btn {
  margin-left: auto;
  width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 3px; border: 1px solid var(--danger, #ef4444);
  background: transparent; color: var(--danger, #ef4444);
  font-size: 10px; cursor: pointer; line-height: 1;
}
.atl-stop-btn:hover { background: var(--danger, #ef4444); color: #fff; }
.atl-pause-btn {
  margin-left: auto;
  width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 3px; border: 1px solid var(--warning, #f59e0b);
  background: transparent; color: var(--warning, #f59e0b);
  font-size: 10px; cursor: pointer; line-height: 1;
}
.atl-pause-btn:hover { background: var(--warning, #f59e0b); color: #fff; }
.atl-resume-btn {
  margin-left: auto;
  width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 3px; border: 1px solid var(--success, #22c55e);
  background: transparent; color: var(--success, #22c55e);
  font-size: 10px; cursor: pointer; line-height: 1;
}
.atl-resume-btn:hover { background: var(--success, #22c55e); color: #fff; }
.atl-progress { margin-left: auto; font-size: 0.65rem; color: var(--text-muted); font-family: var(--font-mono); }
.atl-progress-bar { height: 3px; background: var(--bg-secondary); border-radius: 2px; margin: 0.25rem 0; }
.atl-progress-fill { height: 100%; background: var(--accent, #7c3aed); border-radius: 2px; transition: width 0.3s; }
.atl-steps { display: flex; flex-direction: column; gap: 0.15rem; margin-top: 0.25rem; }
.atl-step-compact {
  display: flex;
  align-items: center;
  gap: 0.2rem;
  font-size: 0.7rem;
  color: var(--text-secondary);
  padding: 0.15rem 0;
}
.atl-compact-count {
  font-weight: 600;
  font-family: var(--font-mono);
  color: var(--text-primary);
}
.atl-compact-detail {
  font-size: 0.6rem;
  color: var(--text-muted);
  margin-left: 0.25rem;
}
.atl-step-current {
  display: flex;
  align-items: flex-start;
  gap: 0.25rem;
  font-size: 0.65rem;
  color: var(--accent);
  margin-top: 0.15rem;
  padding: 0.1rem 0.35rem;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border-radius: 3px;
  overflow: hidden;
}
.atl-step-current span:last-child {
  word-break: break-all;
  overflow-wrap: break-word;
  min-width: 0;
}
.atl-more { text-align: center; padding: 0.25rem; }
.atl-more-btn { font-size: 0.65rem; color: var(--accent); background: none; border: 1px solid var(--accent); border-radius: 3px; padding: 0.1rem 0.6rem; cursor: pointer; }
.atl-more-btn:hover { background: var(--accent); color: #fff; }
</style>
