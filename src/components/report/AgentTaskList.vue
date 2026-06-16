<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useCommunityStore } from '@/stores/community-store'
import { useProjectStore } from '@/stores/project'

const { t } = useI18n()
const communityStore = useCommunityStore()
const projectStore = useProjectStore()

const taskId = computed(() => projectStore.activeTab?.taskId || '')
const projectName = computed(() => projectStore.selectedProject?.name || '')
const taskName = computed(() => projectStore.activeTab?.title || taskId.value || '')

const tasks = computed(() => {
  if (!taskId.value) return []
  return communityStore.tasks[taskId.value]?.agentTasks || []
})

const statusIcon = (status: string) => {
  const map: Record<string, string> = {
    queued: '\u2B1C', running: '\uD83D\uDD04', completed: '\u2705',
    partial: '\u26A0\uFE0F', failed: '\u274C', cancelled: '\u25FC\uFE0F',
  }
  return map[status] || '\u2B1C'
}

const stepIcon = (status: string) => {
  const map: Record<string, string> = {
    pending: '\u2B1C', running: '\u23F3', done: '\u2705', failed: '\u274C',
  }
  return map[status] || '\u2B1C'
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
    </div>
    <div v-if="tasks.length === 0" class="atl-empty">
      {{ t('report.noAgentTasks', '暂无 Agent 任务') }}
    </div>
    <div
      v-for="(task, idx) in tasks"
      :key="task.id"
      class="atl-task"
    >
      <div class="atl-task-header">
        <span class="atl-status">{{ statusIcon(task.status) }}</span>
        <span class="atl-action">{{ task.action }}</span>
        <span
          v-if="task.status === 'running' || task.status === 'completed'"
          class="atl-progress"
        >{{ task.progress }}%</span>
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
        v-if="task.message"
        class="atl-message"
      >{{ task.message }}</div>
      <div class="atl-steps">
        <div
          v-for="(step, si) in task.steps"
          :key="si"
          class="atl-step"
        >
          <span class="atl-step-icon">{{ stepIcon(step.status) }}</span>
          <span class="atl-step-desc">{{ step.description }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.atl-container { padding: 0.5rem; display: flex; flex-direction: column; gap: 0.5rem; }
.atl-header { display: flex; align-items: center; gap: 0.4rem; padding-bottom: 0.3rem; border-bottom: 1px solid var(--border); }
.atl-project { font-size: 0.7rem; font-weight: 600; color: var(--text-primary); }
.atl-task-badge { font-size: 0.65rem; color: var(--text-muted); background: var(--bg-tertiary); padding: 0.1rem 0.4rem; border-radius: 3px; }
.atl-empty { font-size: 0.75rem; color: var(--text-muted); text-align: center; padding: 1rem; font-style: italic; }
.atl-task { background: var(--bg-primary); border: 1px solid var(--border); border-radius: 0.375rem; padding: 0.5rem; }
.atl-task-header { display: flex; align-items: center; gap: 0.35rem; font-size: 0.75rem; }
.atl-status { font-size: 0.85rem; }
.atl-action { font-weight: 600; color: var(--text-primary); }
.atl-progress { margin-left: auto; font-size: 0.65rem; color: var(--text-muted); font-family: var(--font-mono); }
.atl-progress-bar { height: 3px; background: var(--bg-secondary); border-radius: 2px; margin: 0.25rem 0; }
.atl-progress-fill { height: 100%; background: var(--accent, #7c3aed); border-radius: 2px; transition: width 0.3s; }
.atl-message { font-size: 0.65rem; color: var(--text-muted); margin-bottom: 0.25rem; }
.atl-steps { display: flex; flex-direction: column; gap: 0.15rem; margin-top: 0.25rem; }
.atl-step { display: flex; align-items: center; gap: 0.25rem; font-size: 0.65rem; }
.atl-step-icon { font-size: 0.7rem; flex-shrink: 0; }
.atl-step-desc { color: var(--text-muted); }
</style>
