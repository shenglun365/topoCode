<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useArchWorkflowStore } from '@/stores/workflow-store'
import { useArchTaskStore } from '@/stores/task-store'
import { useArchAgentStore } from '@/stores/agent-store'
import { useArchMcpStore } from '@/stores/mcp-store'
import { useArchCollabStore } from '@/stores/collaboration-store'
import type { CollabMode } from '@/types'

const { t } = useI18n()
const workflow = useArchWorkflowStore()
const task = useArchTaskStore()
const agent = useArchAgentStore()
const mcp = useArchMcpStore()
const collab = useArchCollabStore()
mcp.load()
agent.load()

const phase = computed(() => t(`workflow.steps.${workflow.currentLabelKey}`))

const taskStat = computed(() => `${task.doneCount}/${task.totalCount}`)
const activeSessions = computed(() => agent.sessions.filter((s) => s.status === 'working' || s.status === 'planning' || s.status === 'testing').length)
const orchestrating = computed(() => agent.running || activeSessions.value > 0)

const collabModes: CollabMode[] = ['main-agent', 'mcp-server', 'spec-assist', 'migration']

function cycleMode() {
  const idx = collabModes.indexOf(collab.mode)
  collab.setMode(collabModes[(idx + 1) % collabModes.length])
}
</script>

<template>
  <footer class="h-7 shrink-0 flex items-center gap-4 px-4 bg-ctp-crust border-t border-ctp-surface0 text-[11px] text-ctp-overlay1">
    <span class="flex items-center gap-1.5">
      <span
        class="w-2 h-2 rounded-full"
        :class="workflow.executionDone ? 'bg-ctp-green' : 'bg-ctp-blue animate-pulse'"
      />
      {{ t('workflow.title') }}: <span class="text-ctp-text">{{ phase }}</span>
    </span>
    <span>{{ t('coding.tasks') }}: <span class="text-ctp-text">{{ taskStat }}</span></span>
    <span>{{ t('coding.session') }}: <span class="text-ctp-text">{{ activeSessions }}</span></span>
    <span
      class="chip"
      :class="orchestrating ? 'bg-ctp-peach/15 text-ctp-peach' : 'bg-ctp-surface0 text-ctp-subtext1'"
      :title="t('workflow.roleHint')"
    >
      {{ t(orchestrating ? 'workflow.orchestrating' : 'workflow.viewing') }}
    </span>
    <span
      class="chip cursor-pointer select-none bg-ctp-mauve/15 text-ctp-mauve hover:bg-ctp-mauve/25 transition-colors"
      :title="t('execute.modeToggle')"
      @click="cycleMode"
    >
      {{ t('execute.modeLabel') }}: {{ t(`execute.mode.${collab.mode}`) }}
      <template v-if="collab.pendingCount"> · {{ collab.pendingCount }}</template>
    </span>
    <div class="flex-1" />
    <span
      v-if="mcp.calls.length"
      class="chip bg-ctp-surface0 text-ctp-sky"
      :title="t('overview.externalCalls')"
    >
      {{ t('overview.externalCalls') }}: {{ mcp.calls.length }}<template v-if="mcp.pendingCount"> · {{ mcp.pendingCount }} 待处理</template>
    </span>
    <span>{{ t('app.name') }} · prototype v0.1</span>
  </footer>
</template>
