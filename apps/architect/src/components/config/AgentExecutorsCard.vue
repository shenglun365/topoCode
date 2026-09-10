<script setup lang="ts">
/**
 * 三方 Coding Agent 执行器注册表管理（S1 执行通道）。
 *
 * 数据面：arch_collab_config["agent.executors"]（architect PUT /agent/executors）
 * 运行面：runner :3458 /api/executors（保存后热刷新，executor_id 路由执行）。
 * 类型：opencode（会话化 serve）/ cline-sdk（自主模式 sidecar）/ cli / mock。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, PlusIcon, TrashIcon, CheckCircleIcon, XCircleIcon, SignalIcon,
} from '@heroicons/vue/24/outline'
import { apiGet, apiPut, apiPost } from '@/services/api-client'

interface ExecModel { id: string; name: string; model: string; url: string; apiKey: string; maxTokens: number }
interface ExecEntry {
  id: string
  type: string
  /** 本机 | 远程(连接层按 host 路由) */
  host: 'local' | 'remote'
  enabled: boolean
  default: boolean
  config: Record<string, any> & { models?: ExecModel[] }
}

const { t } = useI18n()
const entries = ref<ExecEntry[]>([])
const runtime = ref<any>(null)
const loading = ref(false)
const saving = ref(false)
const savedMsg = ref('')
const probing = ref<Record<string, string>>({})
const modelProbing = ref<Record<string, string>>({})   // key: `${execId}/${modelName}`

const TYPES = [
  { value: 'opencode', label: 'opencode (serve 会话)' },
  { value: 'cline-sdk', label: 'cline SDK (自主模式)' },
  { value: 'codex-server', label: 'codex app-server (会话)' },
  { value: 'remote-agent', label: '远端 agent (共享git同步)' },
  { value: 'cli', label: 'CLI 命令 (兜底)' },
  { value: 'serve-generic', label: 'serve 一次性 (/run)' },
  { value: 'mock', label: 'mock (测试)' },
]

async function load() {
  loading.value = true
  try {
    const d = await apiGet<{ executors: ExecEntry[]; runtime: any }>('/agent/executors')
    entries.value = d.executors ?? []
    runtime.value = d.runtime
  } catch {
    entries.value = []
  } finally {
    loading.value = false
  }
}
onMounted(load)

function healthOf(id: string): boolean | null {
  const h = runtime.value?.health?.[id]
  return h === undefined ? null : !!h
}

function addEntry() {
  const used = new Set(entries.value.map(e => e.id))
  let n = 1
  while (used.has(`agent-${n}`)) n++
  entries.value.push({
    id: `agent-${n}`, type: 'opencode', host: 'local', enabled: true, default: false,
    config: { auto_start: true, base_port: 3478, permission: 'auto', timeout: 1800, models: [] },
  })
}

function removeEntry(i: number) {
  entries.value.splice(i, 1)
}

function setDefault(idx: number) {
  entries.value.forEach((e, i) => { e.default = i === idx })
}

function onTypeChange(e: ExecEntry) {
  const defaults: Record<string, Record<string, any>> = {
    opencode: { auto_start: true, base_port: 3478, permission: 'auto', timeout: 1800, models: [] },
    'remote-agent': { agent_url: '', api_key: '', git_remote: 'auto', timeout: 3600, models: [] },
    'codex-server': { codex_bin: 'codex', approval_policy: 'never', sandbox_mode: 'workspace-write', timeout: 3600, models: [] },
    'cline-sdk': { node_bin: 'node', sidecar_script: '', provider_id: 'openai-compatible', model_id: '', base_url: '', api_key: '', max_iterations: 40, models: [] },
    cli: { command: '', timeout: 600 },
    'serve-generic': { base_url: '', api_key: '' },
    mock: {},
  }
  e.config = { ...(defaults[e.type] || {}) }
}

/** ── 实例内模型(模型完全下沉进连接实例, 角色经 modelId 引用) ── */
function addModel(e: ExecEntry) {
  if (!Array.isArray(e.config.models)) e.config.models = []
  e.config.models.push({ id: `m${e.config.models.length + 1}`, name: '', model: '', url: '', apiKey: '', maxTokens: 0 })
}
function removeModel(e: ExecEntry, i: number) {
  e.config.models?.splice(i, 1)
}
async function probeModel(e: ExecEntry, m: ExecModel) {
  const key = `${e.id}/${m.name || m.model || '?'}`
  modelProbing.value[key] = '…'
  try {
    const d = await apiPost<{ status: string; detail: string }>('/agent/executors/model-probe',
      { url: m.url, model: m.model, apiKey: m.apiKey })
    modelProbing.value[key] = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
  } catch (err: any) {
    modelProbing.value[key] = `✗ ${err?.message || err}`
  }
}

async function save() {
  saving.value = true
  savedMsg.value = ''
  try {
    const d = await apiPut<{ runnerRefreshed: boolean }>('/agent/executors',
      { executors: entries.value })
    savedMsg.value = d.runnerRefreshed
      ? t('config.executors.savedRefreshed')
      : t('config.executors.savedNoRunner')
    await load()
  } catch (e: any) {
    savedMsg.value = e?.message || String(e)
  } finally {
    saving.value = false
    setTimeout(() => { savedMsg.value = '' }, 4000)
  }
}

async function probe(e: ExecEntry) {
  probing.value[e.id] = '…'
  try {
    const d = await apiPost<{ status: string; detail: string }>('/agent/executors/probe',
      { entry: e })
    probing.value[e.id] = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
  } catch (err: any) {
    probing.value[e.id] = `✗ ${err?.message || err}`
  }
}

const runnerReachable = computed(() => !!runtime.value?.executors)

const typeFields: Record<string, { key: string; label: string; kind?: 'num' | 'bool' | 'select'; options?: string[] }[]> = {
  opencode: [
    { key: 'base_port', label: 'serve 端口', kind: 'num' },
    { key: 'auto_start', label: '自动拉起', kind: 'bool' },
    { key: 'permission', label: '权限策略', kind: 'select', options: ['auto', 'ask'] },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
    { key: 'model', label: '模型(可选)' },
  ],
  'remote-agent': [
    { key: 'agent_url', label: '远端 serve URL' },
    { key: 'api_key', label: 'API Key' },
    { key: 'git_remote', label: '共享仓库(auto=内置)' },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
  ],
  'codex-server': [
    { key: 'codex_bin', label: 'codex 路径' },
    { key: 'model', label: '模型名' },
    { key: 'codex_home', label: 'CODEX_HOME(隔离)' },
    { key: 'approval_policy', label: '审批策略', kind: 'select', options: ['never', 'on-request', 'on-failure', 'untrusted'] },
    { key: 'sandbox_mode', label: '沙箱', kind: 'select', options: ['workspace-write', 'read-only', 'danger-full-access'] },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
  ],
  'cline-sdk': [
    { key: 'provider_id', label: 'Provider' },
    { key: 'model_id', label: '模型' },
    { key: 'base_url', label: '端点(本地必填, /v1)' },
    { key: 'api_key', label: 'API Key', },
    { key: 'max_iterations', label: '最大迭代', kind: 'num' },
    { key: 'node_bin', label: 'node 路径' },
    { key: 'sidecar_script', label: 'sidecar 路径' },
  ],
  cli: [
    { key: 'command', label: '命令模板 ({prompt})' },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
  ],
  'serve-generic': [
    { key: 'base_url', label: 'serve URL' },
    { key: 'api_key', label: 'API Key' },
  ],
  mock: [],
}
</script>

<template>
  <div class="panel overflow-hidden">
    <div class="panel-header">
      <span class="flex items-center gap-2">
        <BoltIcon class="w-4 h-4 text-ctp-yellow" />{{ t('config.executors.title') }}
      </span>
      <span class="flex items-center gap-2">
        <span
          class="chip"
          :class="runnerReachable ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
          :title="t('config.executors.runnerHint')"
        >
          <SignalIcon class="w-3 h-3" /> runner {{ runnerReachable ? '✓' : '✗' }}
        </span>
        <button class="btn !py-1 !px-3 !text-xs" @click="addEntry">
          <PlusIcon class="w-3.5 h-3.5" />{{ t('config.executors.add') }}
        </button>
        <button class="btn btn-primary !py-1 !px-3 !text-xs" :disabled="saving" @click="save">
          {{ saving ? t('config.executors.saving') : t('config.executors.save') }}
        </button>
      </span>
    </div>
    <div class="p-3 text-xs space-y-2">
      <div class="text-[11px] text-ctp-overlay0">{{ t('config.executors.desc') }}</div>
      <div v-if="savedMsg" class="chip bg-ctp-blue/15 text-ctp-blue">{{ savedMsg }}</div>

      <div
        v-for="(e, i) in entries"
        :key="e.id"
        class="border border-ctp-surface0 rounded-lg p-2.5 space-y-2"
        :class="{ 'opacity-50': !e.enabled }"
      >
        <div class="flex items-center gap-2 flex-wrap">
          <input
            v-model="e.id"
            class="input !py-0.5 !text-xs font-mono w-32"
            :title="t('config.executors.idHint')"
          >
          <select
            v-model="e.type"
            class="input !py-0.5 !text-xs w-52"
            @change="onTypeChange(e)"
          >
            <option v-for="ty in TYPES" :key="ty.value" :value="ty.value">
              {{ ty.label }}
            </option>
          </select>
          <select v-model="e.host" class="input !py-0.5 !text-xs w-20" :title="t('config.executors.hostHint')">
            <option value="local">{{ t('config.executors.hostLocal') }}</option>
            <option value="remote">{{ t('config.executors.hostRemote') }}</option>
          </select>
          <label class="flex items-center gap-1 text-[11px] text-ctp-subtext1">
            <input v-model="e.enabled" type="checkbox" class="accent-ctp-blue">{{ t('config.executors.enabled') }}
          </label>
          <label class="flex items-center gap-1 text-[11px]" :title="t('config.executors.defaultHint')">
            <input
              type="radio"
              name="exec-default"
              :checked="e.default"
              @change="setDefault(i)"
            >{{ t('config.executors.default') }}
          </label>
          <span
            v-if="healthOf(e.id) !== null"
            class="chip"
            :class="healthOf(e.id) ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-surface0 text-ctp-overlay1'"
          >
            <component :is="healthOf(e.id) ? CheckCircleIcon : XCircleIcon" class="w-3 h-3" />
            {{ t('config.executors.health') }}
          </span>
          <div class="flex-1" />
          <button class="btn !py-0.5 !px-2 !text-[11px]" @click="probe(e)">
            {{ t('config.executors.probe') }}
          </button>
          <button
            class="btn !py-0.5 !px-2 !text-[11px] text-ctp-red"
            @click="removeEntry(i)"
          >
            <TrashIcon class="w-3 h-3" />
          </button>
        </div>

        <div v-if="typeFields[e.type]?.length" class="grid grid-cols-2 sm:grid-cols-3 gap-2">
          <label
            v-for="f in typeFields[e.type]"
            :key="f.key"
            class="flex flex-col gap-0.5"
          >
            <span class="text-[10px] text-ctp-overlay1">{{ f.label }}</span>
            <select
              v-if="f.kind === 'select'"
              v-model="e.config[f.key]"
              class="input !py-0.5 !text-[11px]"
            >
              <option v-for="o in f.options" :key="o" :value="o">{{ o }}</option>
            </select>
            <input
              v-else-if="f.kind === 'bool'"
              v-model="e.config[f.key]"
              type="checkbox"
              class="accent-ctp-blue self-start mt-1"
            >
            <input
              v-else
              v-model="e.config[f.key]"
              :type="f.kind === 'num' ? 'number' : 'text'"
              class="input !py-0.5 !text-[11px] font-mono"
              :class="{ 'w-24': f.kind === 'num' }"
            >
          </label>
        </div>
        <!-- 实例内模型(下沉配置: 连通性可测) -->
        <div v-if="e.config.models" class="border-t border-ctp-surface0/70 pt-2 space-y-1.5">
          <div class="flex items-center gap-2">
            <span class="text-[10px] text-ctp-overlay1">{{ t('config.executors.modelsTitle') }}</span>
            <button class="btn !py-0 !px-2 !text-[10px]" @click="addModel(e)">
              <PlusIcon class="w-3 h-3" />{{ t('config.executors.addModel') }}
            </button>
          </div>
          <div
            v-for="(m, mi) in e.config.models"
            :key="m.id || mi"
            class="flex flex-wrap items-center gap-1.5"
          >
            <input v-model="m.name" class="input !py-0.5 !text-[11px] w-24" :placeholder="t('config.executors.mName')">
            <input v-model="m.model" class="input !py-0.5 !text-[11px] font-mono w-36" :placeholder="t('config.executors.mModel')">
            <input v-model="m.url" class="input !py-0.5 !text-[11px] font-mono flex-1 min-w-40" :placeholder="t('config.executors.mUrl')">
            <input v-model="m.apiKey" type="password" class="input !py-0.5 !text-[11px] font-mono w-28" :placeholder="t('config.executors.mKey')" autocomplete="off">
            <input v-model.number="m.maxTokens" type="number" class="input !py-0.5 !text-[11px] w-20" :placeholder="t('config.executors.mMaxTokens')">
            <button class="btn !py-0 !px-2 !text-[10px]" @click="probeModel(e, m)">
              {{ t('config.executors.modelProbe') }}
            </button>
            <button class="btn !py-0 !px-1.5 !text-[10px] text-ctp-red" @click="removeModel(e, mi)">
              <TrashIcon class="w-3 h-3" />
            </button>
            <div v-if="modelProbing[`${e.id}/${m.name || m.model || '?'}`]" class="w-full text-[10px] text-ctp-overlay0 font-mono break-all">
              {{ modelProbing[`${e.id}/${m.name || m.model || '?'}`] }}
            </div>
          </div>
        </div>
        <div v-if="probing[e.id]" class="text-[10px] text-ctp-overlay0 font-mono break-all">
          {{ probing[e.id] }}
        </div>
      </div>

      <div v-if="!entries.length && !loading" class="text-ctp-overlay1">
        {{ t('config.executors.empty') }}
      </div>
    </div>
  </div>
</template>
