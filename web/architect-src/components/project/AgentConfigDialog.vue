<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  ArrowPathIcon, BoltIcon, CheckCircleIcon, ExclamationTriangleIcon,
  ServerIcon, StarIcon, XMarkIcon,
} from '@heroicons/vue/24/outline'
import type { AgentAdapterInfo, AgentProbeResult } from '@/types'
import { listAgentAdapters, previewAgentConfig, createAgentConfig } from '@/services/agent-service'

const emit = defineEmits<{ close: []; saved: [] }>()

const { t } = useI18n()

const adapters = ref<AgentAdapterInfo[]>([])
const form = ref({
  adapter: 'opencode',
  name: '',
  mode: 'server',
  host: '127.0.0.1',
  port: 4096,
  username: 'opencode',
  url: '',
  models: [] as string[],
  default_model: '',
})

const probing = ref(false)
const saving = ref(false)
const probe = ref<AgentProbeResult | null>(null)
const error = ref('')

const modelOptions = computed(() => probe.value?.models ?? [])
const connectedCount = computed(() => probe.value?.connected?.length ?? 0)
const supported = (id: string) => id === 'opencode'

async function loadAdapters() {
  try {
    adapters.value = await listAgentAdapters()
  } catch {
    adapters.value = [
      { id: 'opencode', name: 'OpenCode' },
      { id: 'codex', name: 'OpenAI Codex' },
      { id: 'claude', name: 'Claude Code' },
      { id: 'cursor', name: 'Cursor' },
      { id: 'copilot', name: 'GitHub Copilot' },
      { id: 'gemini', name: 'Gemini CLI' },
      { id: 'windsurf', name: 'Windsurf' },
    ]
  }
}

function selectAdapter(id: string) {
  if (!supported(id)) return
  form.value.adapter = id
}

async function runProbe() {
  probing.value = true
  error.value = ''
  try {
    probe.value = await previewAgentConfig({
      adapter: form.value.adapter,
      host: form.value.host,
      port: Number(form.value.port),
      username: form.value.username,
      url: form.value.url,
    })
    // 探测成功后，把未选中的已连通模型补齐为候选；保留已选。
    const ids = new Set((probe.value?.models ?? []).map((m) => m.id))
    form.value.models = form.value.models.filter((m) => ids.has(m))
    if (form.value.default_model && !ids.has(form.value.default_model)) {
      form.value.default_model = ''
    }
  } catch (e) {
    error.value = e instanceof Error && e.message ? e.message : t('agent.dialog.testFailed')
    probe.value = null
  } finally {
    probing.value = false
  }
}

function toggleModel(id: string) {
  const idx = form.value.models.indexOf(id)
  if (idx >= 0) {
    form.value.models.splice(idx, 1)
    if (form.value.default_model === id) form.value.default_model = ''
  } else {
    form.value.models.push(id)
    if (!form.value.default_model) form.value.default_model = id
  }
}

function setDefault(id: string) {
  form.value.default_model = id
}

async function save() {
  saving.value = true
  error.value = ''
  const payload = {
    adapter: form.value.adapter,
    name: form.value.name || form.value.adapter,
    mode: form.value.mode as 'server' | 'cli',
    host: form.value.host,
    port: Number(form.value.port),
    username: form.value.username,
    url: form.value.url,
    models: form.value.models,
    defaultModel: form.value.default_model,
  }
  try {
    await createAgentConfig(payload)
    emit('saved')
    emit('close')
  } catch (e) {
    error.value = e instanceof Error && e.message ? e.message : t('agent.dialog.saveFailed')
  } finally {
    saving.value = false
  }
}

onMounted(() => {
  loadAdapters()
})
</script>

<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-base/70 backdrop-blur-sm"
    @click.self="emit('close')"
  >
    <div class="panel w-full max-w-xl p-5 flex flex-col max-h-[90vh]">
      <div class="flex items-center justify-between mb-1">
        <div class="flex items-center gap-2">
          <ServerIcon class="w-5 h-5 text-ctp-mauve" />
          <h2 class="text-base font-medium text-ctp-text">
            {{ t('agent.dialog.title') }}
          </h2>
        </div>
        <button class="text-ctp-overlay1 hover:text-ctp-text" @click="emit('close')">
          <XMarkIcon class="w-5 h-5" />
        </button>
      </div>
      <p class="text-xs text-ctp-subtext0 mb-3">{{ t('agent.dialog.desc') }}</p>

      <div
        v-if="error"
        class="flex items-center gap-2 text-xs text-ctp-red border border-ctp-red/30 bg-ctp-red/5 rounded-md px-3 py-2 mb-3"
      >
        <ExclamationTriangleIcon class="w-3.5 h-3.5 shrink-0" />
        <span class="flex-1">{{ error }}</span>
      </div>

      <div class="flex-1 overflow-y-auto space-y-4">
        <!-- 适配器选择 -->
        <div>
          <label class="text-xs text-ctp-overlay1 mb-1.5 block">{{ t('agent.dialog.adapter') }}</label>
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-1.5">
            <button
              v-for="a in adapters"
              :key="a.id"
              class="chip text-left"
              :class="[
                supported(a.id)
                  ? form.adapter === a.id ? 'ring-1 ring-ctp-mauve/50 bg-ctp-mauve/10 text-ctp-mauve' : 'bg-ctp-surface0 text-ctp-subtext1'
                  : 'bg-ctp-surface0 text-ctp-overlay0 cursor-not-allowed',
              ]"
              :disabled="!supported(a.id)"
              @click="selectAdapter(a.id)"
            >
              <span class="flex items-center gap-1">
                {{ a.name }}
                <span
                  v-if="!supported(a.id)"
                  class="text-[10px] text-ctp-overlay1"
                >{{ t('agent.dialog.pending') }}</span>
              </span>
            </button>
          </div>
        </div>

        <!-- server 参数 -->
        <div>
          <label class="text-xs text-ctp-overlay1 mb-1.5 block">{{ t('agent.dialog.server') }}</label>
          <div class="grid grid-cols-6 gap-2">
            <div class="col-span-3">
              <input
                v-model="form.host"
                class="input font-mono text-xs"
                :placeholder="t('agent.dialog.host')"
              />
            </div>
            <div class="col-span-1">
              <input
                v-model.number="form.port"
                type="number"
                class="input font-mono text-xs"
                :placeholder="t('agent.dialog.port')"
              />
            </div>
            <div class="col-span-2">
              <input
                v-model="form.username"
                class="input font-mono text-xs"
                :placeholder="t('agent.dialog.username')"
              />
            </div>
          </div>
          <input
            v-model="form.url"
            class="input font-mono text-xs mt-2"
            :placeholder="t('agent.dialog.urlPlaceholder')"
          />
          <p class="text-[10px] text-ctp-overlay1 mt-1">{{ t('agent.dialog.urlHint') }}</p>
        </div>

        <!-- 测试连通性 -->
        <div class="flex items-center gap-2">
          <button class="btn btn-blue text-xs" :disabled="probing" @click="runProbe">
            <ArrowPathIcon :class="['w-3.5 h-3.5', probing ? 'animate-spin' : '']" />
            {{ probing ? t('common.loading') : t('agent.dialog.test') }}
          </button>
          <span v-if="probe" class="flex items-center gap-1.5 text-xs">
            <CheckCircleIcon v-if="probe.status === 'ok'" class="w-4 h-4 text-ctp-green" />
            <ExclamationTriangleIcon v-else class="w-4 h-4 text-ctp-red" />
            <span :class="probe.status === 'ok' ? 'text-ctp-green' : 'text-ctp-red'">
              {{ probe.detail }}{{ probe.version ? ` · v${probe.version}` : '' }}
            </span>
          </span>
        </div>

        <!-- 模型多选 + 默认 -->
        <div v-if="modelOptions.length">
          <div class="flex items-center gap-2 mb-1.5">
            <label class="text-xs text-ctp-overlay1">{{ t('agent.dialog.models') }}</label>
            <span class="text-[10px] text-ctp-subtext0">{{ t('agent.dialog.connectedN', { n: connectedCount }) }}</span>
          </div>
          <div class="border border-ctp-surface0 rounded-lg p-2 max-h-52 overflow-y-auto space-y-1">
            <label
              v-for="m in modelOptions"
              :key="m.id"
              class="flex items-center gap-2 px-2 py-1 rounded-md cursor-pointer hover:bg-ctp-surface0/60 transition-colors"
              :class="form.default_model === m.id ? 'border border-ctp-mauve/50 bg-ctp-mauve/5' : ''"
            >
              <input
                type="checkbox"
                :checked="form.models.includes(m.id)"
                class="accent-ctp-mauve shrink-0"
                @change="toggleModel(m.id)"
              />
              <span class="flex-1 min-w-0 text-xs text-ctp-text truncate">{{ m.name }}</span>
              <button
                v-if="form.models.includes(m.id)"
                class="btn btn-ghost !px-1.5 !py-0.5 text-[10px] shrink-0"
                :class="form.default_model === m.id ? 'text-ctp-mauve' : 'text-ctp-overlay1'"
                :title="t('agent.dialog.setDefault')"
                @click.prevent="setDefault(m.id)"
              >
                <StarIcon class="w-3.5 h-3.5" />
                {{ form.default_model === m.id ? t('agent.dialog.default') : t('agent.dialog.setDefault') }}
              </button>
            </label>
          </div>
        </div>
        <p v-else-if="probe && probe.status === 'ok'" class="text-xs text-ctp-subtext0">
          {{ t('agent.dialog.noModels') }}
        </p>
      </div>

      <div class="flex items-center justify-between mt-4">
        <span class="text-[10px] text-ctp-overlay1">{{ t('agent.dialog.noPassword') }}</span>
        <div class="flex items-center gap-2">
          <button class="btn btn-ghost text-xs" @click="emit('close')">
            {{ t('common.cancel') }}
          </button>
          <button class="btn btn-green text-xs" :disabled="saving" @click="save">
            <BoltIcon class="w-3.5 h-3.5" />
            {{ saving ? t('common.loading') : t('common.save') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>
