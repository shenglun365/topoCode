<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { useArchWorkflowStore } from '@/stores/workflow-store'
import { useRoute } from 'vue-router'
import { watch } from 'vue'

const { t } = useI18n()
const workflow = useArchWorkflowStore()
const route = useRoute()

watch(
  () => route.fullPath,
  () => workflow.syncFromRoute(route.path, route.query),
  { immediate: true },
)
</script>

<template>
  <div class="shrink-0 flex items-center gap-1 px-4 py-2 bg-ctp-mantle border-b border-ctp-surface0 overflow-x-auto">
    <span class="text-[11px] uppercase tracking-wider text-ctp-overlay1 mr-2 shrink-0">{{ t('workflow.title') }}</span>
    <template
      v-for="(step, i) in workflow.stages"
      :key="step.key"
    >
      <span
        class="flex items-center gap-1.5 px-2 py-1 rounded-md text-xs whitespace-nowrap shrink-0"
        :class="step.status === 'active' ? 'text-ctp-blue bg-ctp-blue/10 ring-1 ring-ctp-blue/30' : 'text-ctp-subtext0'"
      >
        <span
          class="w-4 h-4 inline-flex items-center justify-center rounded-full text-[10px] font-bold"
          :class="step.status === 'active' ? 'bg-ctp-blue text-ctp-crust' : 'bg-ctp-surface1 text-ctp-overlay1'"
        >{{ i + 1 }}</span>
        {{ t(`workflow.steps.${step.labelKey}`) }}
      </span>
      <div
        v-if="i < workflow.stages.length - 1"
        class="w-3 h-px bg-ctp-surface1 shrink-0"
      />
    </template>
  </div>
</template>
