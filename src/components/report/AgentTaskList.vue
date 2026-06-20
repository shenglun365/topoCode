<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore } from '@/stores/community-store'
import { useProjectStore } from '@/stores/project'

const { t } = useI18n()
const communityStore = useCommunityStore()
const projectStore = useProjectStore()

const taskId = computed(() => projectStore.activeTab?.taskId || '')
const projectName = computed(() => projectStore.selectedProject?.name || '')
const taskName = computed(() => projectStore.activeTab?.title || taskId.value || '')

const historyTasks = ref<any[]>([])
const historyLoaded = ref(false)
const pageSize = ref(10)

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
  return {
    id: h.agent_id,
    action: h.action,
    status: h.status,
    progress: h.status === 'completed' ? 100 : h.status === 'failed' ? 0 : 0,
    message: h.message || '',
    steps,
    createdAt: h.created_at || '',
  }
}

async function loadHistory(cursor: number) {
  if (!taskId.value) return
  const results = await communityStore.loadAgentTaskHistory(taskId.value, cursor, 10)
  if (cursor === 0) {
    historyTasks.value = results
  } else {
    // append
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
  historyTasks.value = []
  pageSize.value = 10
  historyLoaded.value = false
  await loadHistory(0)
}

async function clearHistory() {
  if (!taskId.value) return
  await communityStore.clearAgentTaskHistory(taskId.value)
  historyTasks.value = []
  pageSize.value = 10
}

onMounted(() => {
  refresh()
})

const statusLabel = (status: string) => {
  const map: Record<string, string> = {
    queued: '排队中', running: '运行中', completed: '已完成',
    partial: '部分完成', failed: '已失败', cancelled: '已取消',
    unknown: '未知',
  }
  return map[status] || '未知'
}

const actionLabel = (action: string) => {
  const map: Record<string, string> = {
    analyze_components: '组件分析',
    agentic_analyze_components: '智能组件分析',
    startArchAnalysis: '架构分析',
    analyze_all: '全量分析',
    analyzeCommFiles: '文件分析',
    presummary_files: '文件预摘要',
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
        'atl-task-fail': task.status === 'failed' || task.status === 'partial'
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
          class="atl-stop-btn"
          title="停止此任务"
          @click="communityStore.cancelAgentTask(taskId, task.id)"
        >
          ✕
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
          <span class="atl-compact-count">{{ task.steps.filter(s => s.status === 'done').length }}</span>
          <span>/{{ task.steps.length }}</span>
          <span class="atl-compact-detail">
            （完成{{ task.steps.filter(s => s.status === 'done').length }}
            / 失败{{ task.steps.filter(s => s.status === 'failed').length }}
            / 剩余{{ task.steps.filter(s => s.status === 'pending' || s.status === 'running').length }}）
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
.atl-action { font-weight: 600; color: var(--text-primary); }
.atl-status-text { font-size: 0.6rem; color: var(--text-muted); font-family: var(--font-mono); }
.atl-task-success .atl-status-text { color: var(--success, #22c55e); }
.atl-task-fail .atl-status-text { color: var(--danger, #ef4444); }
.atl-stop-btn {
  margin-left: auto;
  width: 18px; height: 18px;
  display: flex; align-items: center; justify-content: center;
  border-radius: 3px; border: 1px solid var(--danger, #ef4444);
  background: transparent; color: var(--danger, #ef4444);
  font-size: 10px; cursor: pointer; line-height: 1;
}
.atl-stop-btn:hover { background: var(--danger, #ef4444); color: #fff; }
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
  align-items: center;
  gap: 0.25rem;
  font-size: 0.65rem;
  color: var(--accent);
  margin-top: 0.15rem;
  padding: 0.1rem 0.35rem;
  background: color-mix(in srgb, var(--accent) 8%, transparent);
  border-radius: 3px;
}
.atl-more { text-align: center; padding: 0.25rem; }
.atl-more-btn { font-size: 0.65rem; color: var(--accent); background: none; border: 1px solid var(--accent); border-radius: 3px; padding: 0.1rem 0.6rem; cursor: pointer; }
.atl-more-btn:hover { background: var(--accent); color: #fff; }
</style>
