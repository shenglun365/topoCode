<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { BoltIcon, CheckIcon, RocketLaunchIcon, ShieldCheckIcon, ArrowRightIcon } from '@heroicons/vue/24/outline'
import { useArchWorkflowStore } from '@/stores/workflow-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { useArchTaskStore } from '@/stores/task-store'

const { t } = useI18n()
const router = useRouter()
const workflow = useArchWorkflowStore()
const requirement = useArchRequirementStore()
const task = useArchTaskStore()

interface NextStep {
  text: string
  tone: 'blue' | 'green' | 'peach' | 'yellow'
  cta?: { label: string; to: string }
}

const next = computed<NextStep>(() => {
  const stage = workflow.current
  const proposalCount = requirement.proposals.length
  const poolCount = requirement.poolItems.length
  const activeCount = task.activeTasks.length
  const acceptingCount = task.executionTasks.filter((x) => x.status === 'accepting').length
  const doneCount = task.executionTasks.filter((x) => x.status === 'done').length
  switch (stage) {
    case 'pool':
      if (proposalCount) return { text: t('assistant.pool.next', { n: proposalCount }), tone: 'blue' }
      return { text: t('assistant.pool.empty'), tone: 'blue' }
    case 'design':
      if (poolCount) return { text: t('assistant.design.next', { n: poolCount }), tone: 'green', cta: { label: t('assistant.design.cta'), to: '/workbench/execute' } }
      return { text: t('assistant.design.empty'), tone: 'green' }
    case 'execute':
      if (activeCount) return { text: t('assistant.execute.running', { n: activeCount }), tone: 'peach' }
      if (poolCount) return { text: t('assistant.execute.ready', { n: poolCount }), tone: 'peach' }
      return { text: t('assistant.execute.empty'), tone: 'peach' }
    case 'accept':
      if (acceptingCount) return { text: t('assistant.accept.accepting', { n: acceptingCount }), tone: 'yellow' }
      if (doneCount) return { text: t('assistant.accept.done', { n: doneCount }), tone: 'green' }
      return { text: t('assistant.accept.empty'), tone: 'yellow' }
    default:
      return { text: '', tone: 'blue' }
  }
})

const toneClass: Record<NextStep['tone'], string> = {
  blue: 'text-ctp-blue border-ctp-blue/30 bg-ctp-blue/5',
  green: 'text-ctp-green border-ctp-green/30 bg-ctp-green/5',
  peach: 'text-ctp-peach border-ctp-peach/30 bg-ctp-peach/5',
  yellow: 'text-ctp-yellow border-ctp-yellow/30 bg-ctp-yellow/5',
}
</script>

<template>
  <div
    v-if="next.text"
    class="shrink-0 flex items-center gap-2 px-3 py-2 rounded-lg border text-xs"
    :class="toneClass[next.tone]"
  >
    <span class="flex items-center gap-1.5">
      <CheckIcon
        v-if="next.tone === 'green'"
        class="w-3.5 h-3.5"
      />
      <BoltIcon
        v-else-if="next.tone === 'blue'"
        class="w-3.5 h-3.5"
      />
      <RocketLaunchIcon
        v-else-if="next.tone === 'peach'"
        class="w-3.5 h-3.5"
      />
      <ShieldCheckIcon
        v-else
        class="w-3.5 h-3.5"
      />
      {{ next.text }}
    </span>
    <button
      v-if="next.cta"
      class="btn btn-sm btn-ghost !py-0.5 ml-auto"
      @click="router.push(next.cta!.to)"
    >
      <ArrowRightIcon class="w-3 h-3" />{{ next.cta.label }}
    </button>
  </div>
</template>
