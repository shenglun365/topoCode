<script setup lang="ts">
import {
  ClockIcon,
  CpuChipIcon,
  DocumentTextIcon,
  CheckCircleIcon,
  XCircleIcon,
} from '@heroicons/vue/24/outline'
import { useI18n } from 'vue-i18n'
import type { TaskStatus } from '@/utils/mock'
import { useComponentId } from '@/composables/useComponentId'

const { showId, componentId } = useComponentId('CD-006')
const { t } = useI18n()

defineProps<{
  task: TaskStatus
}>()

function getStatusBadge(status: string): string {
  switch (status) {
    case 'done': return 'badge-green'
    case 'running': return 'badge-yellow'
    case 'error': return 'badge-red'
    default: return 'badge-gray'
  }
}

function getStatusText(status: string): string {
  switch (status) {
    case 'done': return t('common.completed')
    case 'running': return t('common.running')
    case 'error': return t('common.failed')
    default: return t('common.pending')
  }
}
</script>

<template>
  <div class="task-status-card">
    <span
      v-if="showId"
      class="cmp-id"
    >{{ componentId }}</span>
    <!-- 头部 -->
    <div class="task-header">
      <div class="task-title">
        <ClockIcon class="w-4 h-4" />
        <span>#{{ task.id }} {{ task.name }}</span>
      </div>
      <span :class="`badge ${getStatusBadge(task.status)}`">
        {{ getStatusText(task.status) }}
      </span>
    </div>

    <!-- 任务信息 -->
    <div class="task-info">
      <div class="task-row">
        <span>{{ t('coder.agentName') }}</span>
        <span class="font-mono">{{ task.agent }}</span>
      </div>
      <div class="task-row">
        <span>{{ t('coder.taskDuration') }}</span>
        <span>{{ task.elapsed }}</span>
      </div>
      <div class="task-row">
        <span>{{ t('coder.generatedFiles') }}</span>
        <span>{{ task.filesGenerated }} {{ t('coder.filesCountUnit') }}</span>
      </div>
    </div>

    <!-- 终端输出 -->
    <div class="task-terminal">
      <div
        v-for="(line, idx) in task.terminalLines"
        :key="idx"
        class="terminal-line"
        :class="line.type"
      >
        {{ line.text }}
      </div>
    </div>

    <!-- 校验结果 -->
    <div
      v-if="task.validations.length > 0"
      class="task-validation"
    >
      <div class="validation-title">
        {{ t('coder.designContract') }}
      </div>
      <div
        v-for="(item, idx) in task.validations"
        :key="idx"
        class="validation-row"
      >
        <CheckCircleIcon
          v-if="item.passed"
          class="w-4 h-4 text-success"
        />
        <XCircleIcon
          v-else
          class="w-4 h-4 text-error"
        />
        <span>{{ item.label }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.task-status-card {
  margin-top: 12px;
  padding: 12px;
  background: var(--bg-primary);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
}

.task-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 10px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.task-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 600;
}

.task-info {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 8px;
  margin-bottom: 12px;
}

.task-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.task-row span:first-child {
  font-size: 10px;
  color: var(--text-muted);
}

.task-row span:last-child {
  font-size: 11px;
  color: var(--text-primary);
}

.task-terminal {
  background: var(--bg-secondary);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 10px;
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1.6;
  margin-bottom: 12px;
  max-height: 150px;
  overflow-y: auto;
}

.terminal-line {
  color: var(--text-muted);
}

.terminal-line.success {
  color: var(--success);
}

.terminal-line.error {
  color: var(--error);
}

.task-validation {
  padding-top: 10px;
  border-top: 1px solid var(--border);
}

.validation-title {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-secondary);
  margin-bottom: 8px;
}

.validation-row {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-secondary);
  margin-bottom: 4px;
}
</style>
