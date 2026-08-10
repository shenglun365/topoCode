<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CpuChipIcon, Cog6ToothIcon, ArrowDownTrayIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import PageHeader from '@/components/PageHeader.vue'
import { useArchAgentStore } from '@/stores/agent-store'
import { useArchSpecStore } from '@/stores/spec-store'
import { useArchCollabStore } from '@/stores/collaboration-store'
import { useArchProjectStore } from '@/stores/project-store'
import { apiGet, apiPost, apiPut, apiDelete } from '@/services/api-client'
import { backendUp } from '@/services/backend'
import type { ArchLlmModel, ArchLlmModelsResult, ArchLlmImportResult } from '@/types'

const { t } = useI18n()
const agent = useArchAgentStore()
const spec = useArchSpecStore()
const collab = useArchCollabStore()
const project = useArchProjectStore()
spec.load()
agent.load()

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

// ==================== LLM 模型配置 ====================
const llmModels = ref<ArchLlmModel[]>([])
const llmModelId = ref('')
const importing = ref(false)
const importMsg = ref('')
const importError = ref('')
const showAddManual = ref(false)
const manualForm = reactive({ name: '', provider: '', model: '', url: '' })
const addingManual = ref(false)

async function loadLlm() {
  if (!(await backendUp())) return
  try {
    const data = await apiGet<ArchLlmModelsResult>('/llm/models')
    llmModels.value = data.models ?? []
    llmModelId.value = data.modelId ?? ''
  } catch {
    // backend not ready → show nothing
  }
}

async function importModels() {
  if (!(await backendUp())) return
  importing.value = true
  importMsg.value = ''
  importError.value = ''
  try {
    const data = await apiPost<ArchLlmImportResult>('/llm/models/import')
    llmModels.value = data.models ?? []
    importMsg.value = t('config.llm.importDone', {
      added: data.added,
      updated: data.updated,
      preserved: data.preserved,
    })
  } catch (e: any) {
    importError.value = e?.message || t('config.llm.importFail')
  } finally {
    importing.value = false
  }
}

async function selectActiveModel(id: string) {
  llmModelId.value = id
  if (await backendUp()) {
    apiPut<{ modelId: string }>('/llm/model', { modelId: id }).catch(() => {})
  }
}

async function addManual() {
  if (!manualForm.name.trim() || !manualForm.model.trim()) return
  addingManual.value = true
  try {
    if (await backendUp()) {
      const row = await apiPost<ArchLlmModel>('/llm/models/manual', {
        name: manualForm.name.trim(),
        provider: manualForm.provider.trim() || 'custom',
        model: manualForm.model.trim(),
        url: manualForm.url.trim(),
      })
      llmModels.value = [row, ...llmModels.value]
    } else {
      llmModels.value.unshift({
        source: 'manual',
        id: `man-${Date.now()}`,
        name: manualForm.name.trim(),
        provider: manualForm.provider.trim() || 'custom',
        model: manualForm.model.trim(),
        url: manualForm.url.trim(),
      })
    }
    manualForm.name = ''
    manualForm.provider = ''
    manualForm.model = ''
    manualForm.url = ''
    showAddManual.value = false
  } finally {
    addingManual.value = false
  }
}

async function removeManualModel(id: string) {
  if (await backendUp()) {
    await apiDelete<{ id: string }>(`/llm/models/${id}`).catch(() => {})
  }
  llmModels.value = llmModels.value.filter((m) => m.id !== id)
}

loadLlm()
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
          <Cog6ToothIcon class="w-4 h-4 text-ctp-sapphire" />{{ t('config.llm.title') }}
        </span>
        <span class="flex items-center gap-2">
          <span class="text-[11px] text-ctp-overlay1">
            {{ llmModels.length }}
          </span>
          <button
            class="btn btn-primary !py-1 !px-3 !text-xs"
            :disabled="importing"
            @click="importModels"
          >
            <ArrowDownTrayIcon class="w-3.5 h-3.5" />
            {{ importing ? t('config.llm.importing') : t('config.llm.import') }}
          </button>
          <button
            class="btn !py-1 !px-3 !text-xs"
            @click="showAddManual = !showAddManual"
          >
            <PlusIcon class="w-3.5 h-3.5" />{{ t('config.llm.addManual') }}
          </button>
        </span>
      </div>
      <div class="p-3 text-xs space-y-2">
        <div class="text-[11px] text-ctp-overlay0">{{ t('config.llm.desc') }}</div>
        <div v-if="importMsg" class="chip bg-ctp-green/15 text-ctp-green">{{ importMsg }}</div>
        <div v-if="importError" class="chip bg-ctp-red/15 text-ctp-red">{{ importError }}</div>

        <form
          v-if="showAddManual"
          class="border border-ctp-surface0 rounded-lg p-2.5 space-y-2"
          @submit.prevent="addManual"
        >
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
            <label class="flex flex-col gap-0.5">
              <span class="text-[11px] text-ctp-overlay1">{{ t('config.llm.manualName') }}</span>
              <input v-model="manualForm.name" class="input !py-1 !text-xs">
            </label>
            <label class="flex flex-col gap-0.5">
              <span class="text-[11px] text-ctp-overlay1">{{ t('config.llm.manualProvider') }}</span>
              <input v-model="manualForm.provider" class="input !py-1 !text-xs" placeholder="custom">
            </label>
            <label class="flex flex-col gap-0.5">
              <span class="text-[11px] text-ctp-overlay1">{{ t('config.llm.manualModel') }}</span>
              <input v-model="manualForm.model" class="input !py-1 !text-xs">
            </label>
            <label class="flex flex-col gap-0.5">
              <span class="text-[11px] text-ctp-overlay1">{{ t('config.llm.manualUrl') }}</span>
              <input v-model="manualForm.url" class="input !py-1 !text-xs">
            </label>
          </div>
          <button
            type="submit"
            class="btn btn-primary !px-3 !py-1 !text-xs"
            :disabled="addingManual || !manualForm.name || !manualForm.model"
          >{{ t('config.llm.addManual') }}</button>
        </form>

        <div
          v-if="!llmModels.length"
          class="text-[11px] text-ctp-overlay0 py-3 text-center"
        >{{ t('config.llm.noModels') }}</div>

        <div class="divide-y divide-ctp-surface0">
          <div
            v-for="m in llmModels"
            :key="m.id"
            class="flex items-center gap-3 py-2"
          >
            <input
              type="radio"
              :name="'llm-active'"
              class="accent-ctp-sapphire"
              :checked="llmModelId === m.id"
              :value="m.id"
              @change="selectActiveModel(m.id)"
            >
            <div class="min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-mono text-ctp-text truncate">{{ m.name }}</span>
                <span
                  class="chip"
                  :class="m.source === 'manual' ? 'bg-ctp-yellow/15 text-ctp-yellow' : 'bg-ctp-blue/15 text-ctp-blue'"
                >{{ t(`config.llm.source.${m.source}`) }}</span>
                <span v-if="m.isDefault" class="chip bg-ctp-green/15 text-ctp-green">default</span>
              </div>
              <div class="text-[11px] text-ctp-subtext0 truncate">
                <span class="font-mono text-ctp-overlay1">{{ m.provider }}</span>
                <span class="mx-1">·</span>
                <span class="font-mono"> {{ m.model }}</span>
                <span v-if="m.url" class="text-ctp-overlay0"> · {{ m.url }}</span>
              </div>
            </div>
            <div class="flex-1" />
            <button
              v-if="m.source === 'manual'"
              class="btn !py-0.5 !px-2 !text-[11px] text-ctp-red"
              :title="t('config.llm.deleteManual')"
              @click="removeManualModel(m.id)"
            >
              <TrashIcon class="w-3 h-3" />{{ t('config.llm.delete') }}
            </button>
          </div>
        </div>
        <div class="flex gap-4 text-[10px] text-ctp-overlay0">
          <span class="flex items-center gap-1">
            <span class="text-ctp-blue">{{ t('config.llm.source.imported') }}</span>
            : {{ t('config.llm.importedNote') }}
          </span>
          <span class="flex items-center gap-1">
            <span class="text-ctp-yellow">{{ t('config.llm.source.manual') }}</span>
            : {{ t('config.llm.manualNote') }}
          </span>
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
