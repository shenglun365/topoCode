<script setup lang="ts">
import { computed, reactive, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CpuChipIcon, Cog6ToothIcon } from '@heroicons/vue/24/outline'
import PageHeader from '@/components/PageHeader.vue'
import { useArchAgentStore } from '@/stores/agent-store'
import { useArchSpecStore } from '@/stores/spec-store'
import { useArchCollabStore } from '@/stores/collaboration-store'
import { useArchProjectStore } from '@/stores/project-store'

const { t } = useI18n()
const agent = useArchAgentStore()
const spec = useArchSpecStore()
const collab = useArchCollabStore()
const project = useArchProjectStore()
spec.load()

const adapters = computed(() => agent.adapters)
const sessions = computed(() => agent.sessions)

const statusColor: Record<string, string> = {
  idle: 'bg-ctp-surface0 text-ctp-subtext1',
  planning: 'bg-ctp-peach/15 text-ctp-peach',
  working: 'bg-ctp-blue/15 text-ctp-blue',
  testing: 'bg-ctp-yellow/15 text-ctp-yellow',
  done: 'bg-ctp-green/15 text-ctp-green',
  failed: 'bg-ctp-red/15 text-ctp-red',
}

const collabModes = computed(() => {
  const keys = ['main-agent', 'mcp-server', 'spec-assist', 'migration'] as const
  return keys.map((k) => ({ key: k, label: t(`execute.mode.${k}`) }))
})

const granularityFields = [
  { key: 'estMinMin' as const },
  { key: 'estMinMax' as const },
  { key: 'acceptanceMax' as const },
  { key: 'p0SubsetMax' as const },
]
const granularity = reactive({
  estMinMin: 0,
  estMinMax: 0,
  acceptanceMax: 0,
  p0SubsetMax: 0,
})
watch(
  () => project.project?.config,
  (cfg) => {
    if (!cfg) return
    granularity.estMinMin = cfg.estMinMin
    granularity.estMinMax = cfg.estMinMax
    granularity.acceptanceMax = cfg.acceptanceMax
    granularity.p0SubsetMax = cfg.p0SubsetMax
  },
  { immediate: true },
)
function applyGranularity(key: keyof typeof granularity) {
  project.updateConfig({ [key]: granularity[key] })
}
</script>

<template>
  <div class="p-5 space-y-4">
    <PageHeader
      :title="t('config.title')"
      :desc="t('config.desc')"
    />

    <div class="grid grid-cols-1 xl:grid-cols-2 gap-4">
      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <CpuChipIcon class="w-4 h-4 text-ctp-green" />{{ t('config.externalAgents') }}
          </span>
          <span class="text-[11px] text-ctp-overlay1">{{ adapters.length }} {{ t('config.adapters') }}</span>
        </div>
        <div class="p-3 space-y-2">
          <div
            v-for="a in adapters"
            :key="a.id"
            class="border border-ctp-surface0 rounded-lg px-3 py-2.5"
          >
            <div class="flex items-center gap-2">
              <span class="font-mono text-sm text-ctp-text">{{ a.name }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ a.id }}</span>
              <div class="flex-1" />
              <span
                v-if="a.keepContext"
                class="chip bg-ctp-teal/15 text-ctp-teal"
              >{{ t('coding.keepContext') }}</span>
            </div>
            <p class="text-[11px] text-ctp-subtext0 mt-1">
              {{ a.note }}
            </p>
          </div>
        </div>
      </div>

      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <Cog6ToothIcon class="w-4 h-4 text-ctp-lavender" />{{ t('config.otherConfig') }}
          </span>
        </div>
        <div class="p-3 space-y-3 text-xs">
          <div class="border border-ctp-surface0 rounded-lg p-3">
            <div class="text-ctp-overlay1 mb-1.5">
              {{ t('config.collabDefault') }}
            </div>
            <div class="flex flex-wrap gap-1.5">
              <span
                v-for="m in collabModes"
                :key="m.key"
                class="chip"
                :class="collab.mode === m.key ? 'bg-ctp-mauve/15 text-ctp-mauve ring-1 ring-ctp-mauve/40' : 'bg-ctp-surface0 text-ctp-subtext0'"
              >{{ m.label }}</span>
            </div>
          </div>
          <div class="border border-ctp-surface0 rounded-lg p-3">
            <div class="flex items-center gap-2">
              <span class="text-ctp-overlay1">{{ t('config.specVersion') }}</span>
              <span class="chip bg-ctp-mauve/15 text-ctp-mauve font-mono">{{ spec.spec?.version ?? '—' }}</span>
              <span class="text-ctp-overlay1 ml-2">{{ t('config.rulesCount') }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ spec.ruleCount }}</span>
            </div>
          </div>
          <div class="border border-ctp-surface0 rounded-lg p-3">
            <div class="flex items-center justify-between mb-2">
              <div class="text-ctp-overlay1">
                {{ t('config.granularity') }}
              </div>
              <span class="text-[10px] text-ctp-overlay0">{{ t('config.granularityHint') }}</span>
            </div>
            <div class="grid grid-cols-2 gap-2">
              <label
                v-for="f in granularityFields"
                :key="f.key"
                class="flex items-center justify-between gap-2"
              >
                <span class="text-ctp-subtext0 text-[11px]">{{ t(`config.${f.key}`) }}</span>
                <input
                  v-model.number="granularity[f.key]"
                  type="number"
                  class="input !w-20 !py-1 !text-xs text-right"
                  @change="applyGranularity(f.key)"
                >
              </label>
            </div>
          </div>
          <div class="border border-ctp-surface0 rounded-lg p-3">
            <div class="text-ctp-overlay1 mb-1">
              {{ t('config.project') }}
            </div>
            <div class="font-mono text-ctp-sapphire truncate">
              {{ project.project?.rootPath ?? '—' }}
            </div>
            <div class="flex items-center gap-2 mt-1">
              <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ project.project?.branch ?? '—' }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1 font-mono">{{ project.project?.baselineId ?? '—' }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <CpuChipIcon class="w-4 h-4 text-ctp-blue" />{{ t('config.activeSessions') }}
        </span>
        <span class="text-[11px] text-ctp-overlay1">{{ sessions.length }}</span>
      </div>
      <div class="divide-y divide-ctp-surface0">
        <div
          v-for="s in sessions"
          :key="s.id"
          class="flex items-center gap-2 px-4 py-2.5 text-xs"
        >
          <span class="font-mono text-ctp-subtext1">{{ s.adapter }}</span>
          <span class="font-mono text-[10px] text-ctp-overlay1">{{ s.taskId }}</span>
          <div class="flex-1" />
          <span
            class="chip"
            :class="statusColor[s.status]"
          >{{ t(`coding.status.${s.status}`) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>
