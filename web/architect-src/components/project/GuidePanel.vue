<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { CheckCircleIcon, ChevronDownIcon, ChevronRightIcon, LightBulbIcon, XMarkIcon, ArrowRightIcon } from '@heroicons/vue/24/outline'
import { useArchProjectStore } from '@/stores/project-store'
import { useArchRequirementStore } from '@/stores/requirement-store'
import { buildGuidedWorkflow, overallCompleteness } from '@/services/guide-service'
import type { WorkflowCtx, WorkflowMission } from '@/types'

defineOptions({ inheritAttrs: false })

const { t } = useI18n()
const router = useRouter()
const project = useArchProjectStore()
const requirement = useArchRequirementStore()

const open = ref(false)
const expandedKey = ref<string | null>(null)

const ctx = computed<WorkflowCtx>(() => ({
  mode: project.mode,
  productForm: project.productForm,
  scaffoldConfigured: !!project.scaffold?.language && !!project.scaffold?.moduleLayout,
  poolCount: requirement.poolItems.length,
  blueprintConfirmed: false,
  execRootInitialized: !!project.project?.baselineId,
  baselineCreated: !!project.project?.baselineId && project.project?.baselineId !== null,
}))

const guided = computed(() => buildGuidedWorkflow(ctx.value))
const completenessPct = computed(() => overallCompleteness(guided.value.missions, ctx.value))

const statusIcon = (m: WorkflowMission) => {
  const c = m.completeness(ctx.value)
  if (c >= 1) return CheckCircleIcon
  return c > 0 ? ChevronDownIcon : ChevronRightIcon
}
const statusClass = (m: WorkflowMission) => {
  const c = m.completeness(ctx.value)
  if (c >= 1) return 'text-ctp-green'
  if (c > 0) return 'text-ctp-blue'
  return 'text-ctp-overlay1'
}
</script>

<template>
  <button
    v-if="!open && project.isGreenfield"
    class="fixed right-4 bottom-4 z-40 flex items-center gap-2 px-3 py-2 rounded-full bg-ctp-mauve text-white text-xs shadow-lg hover:bg-ctp-mauve/90 transition-colors"
    @click="open = true"
  >
    <LightBulbIcon class="w-4 h-4" />
    {{ t('guide.title') }}
    <span class="bg-white/20 rounded-full px-1.5 py-0.5 text-[10px]">{{ completenessPct }}%</span>
  </button>

  <Transition name="slide">
    <div
      v-if="open"
      class="fixed right-0 top-0 bottom-0 z-50 w-80 bg-ctp-base border-l border-ctp-surface0 shadow-2xl flex flex-col"
    >
      <div class="shrink-0 flex items-center justify-between px-4 py-3 border-b border-ctp-surface0">
        <div class="flex items-center gap-2">
          <LightBulbIcon class="w-5 h-5 text-ctp-mauve" />
          <span class="text-sm font-semibold text-ctp-text">{{ t('guide.title') }}</span>
        </div>
        <button class="btn btn-ghost !p-1" @click="open = false">
          <XMarkIcon class="w-4 h-4" />
        </button>
      </div>

      <div class="shrink-0 px-4 py-2 border-b border-ctp-surface0">
        <div class="flex items-center justify-between text-xs text-ctp-overlay1 mb-1">
          <span>{{ t('guide.completeness') }}</span>
          <span>{{ completenessPct }}%</span>
        </div>
        <div class="h-1.5 rounded-full bg-ctp-surface0 overflow-hidden">
          <div class="h-full rounded-full bg-ctp-mauve transition-all duration-500" :style="{ width: completenessPct + '%' }" />
        </div>
      </div>

      <div class="flex-1 overflow-y-auto px-3 py-2 space-y-1">
        <div v-for="m in guided.missions" :key="m.key" class="rounded-lg transition-colors" :class="expandedKey === m.key ? 'bg-ctp-surface0/60' : 'hover:bg-ctp-surface0/30'">
          <button class="w-full flex items-center gap-2 px-2.5 py-2 text-left" @click="expandedKey = expandedKey === m.key ? null : m.key; router.push(m.route)">
            <component :is="statusIcon(m)" class="w-4 h-4 shrink-0" :class="statusClass(m)" />
            <span class="flex-1 min-w-0 text-xs text-ctp-text truncate">{{ t(m.labelKey) }}</span>
            <span class="shrink-0 text-[10px] rounded-full px-1.5 py-0.5" :class="m.completeness(ctx) >= 1 ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-surface0 text-ctp-overlay1'">{{ (m.completeness(ctx) * 100).toFixed(0) }}%</span>
          </button>
          <div v-if="expandedKey === m.key && m.example" class="px-4 pb-3">
            <div class="text-[10px] text-ctp-overlay1 mb-1 flex items-center gap-1"><LightBulbIcon class="w-3 h-3" />{{ m.example.title }}</div>
            <div class="text-[11px] text-ctp-subtext1 bg-ctp-crust rounded-lg p-2.5 whitespace-pre-wrap font-mono leading-relaxed">{{ m.example.content }}</div>
            <button class="mt-2 flex items-center gap-1 text-[11px] text-ctp-blue hover:text-ctp-sapphire" @click="router.push(m.route)">{{ t('guide.goToStep') }}<ArrowRightIcon class="w-3 h-3" /></button>
          </div>
        </div>
      </div>

      <div class="shrink-0 px-4 py-2 border-t border-ctp-surface0 flex justify-between items-center">
        <button v-if="completenessPct < 100" class="btn btn-ghost text-xs text-ctp-overlay1" @click="open = false">{{ t('guide.skip') }}</button>
        <span v-else class="text-xs text-ctp-green flex items-center gap-1"><CheckCircleIcon class="w-3.5 h-3.5" />{{ t('guide.allDone') }}</span>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.slide-enter-active, .slide-leave-active { transition: transform 0.25s ease; }
.slide-enter-from, .slide-leave-to { transform: translateX(100%); }
</style>