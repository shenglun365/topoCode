<script setup lang="ts">
/**
 * 三方 Coding Agent 执行器注册表管理（S1 执行通道）。
 *
 * 数据面：arch_collab_config["agent.executors"]（architect PUT /agent/executors）
 * 运行面：runner :3458 /api/executors（保存后热刷新，executor_id 路由执行）。
 * 类型：opencode（会话化 serve）/ cline-sdk（自主模式 sidecar）/ codex-server。
 *
 * 交互模型：
 * - 概要条目 + 点击展开详情；
 * - 环境检测（已适配类型）+ 一键辅助安装；
 * - 实例模型 = 运行时白名单（opencode 从服务检测勾选、cline 同步 architect 实例模型、
 *   codex 手动维护），运行时只在白名单内调用模型；
 * - 工作目录一律绑定项目源码目录，不可修改。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  BoltIcon, PlusIcon, TrashIcon, CheckCircleIcon, XCircleIcon, SignalIcon,
  ChevronDownIcon, ChevronRightIcon, WrenchScrewdriverIcon,
} from '@heroicons/vue/24/outline'
import { apiGet, apiPut, apiPost } from '@/services/api-client'
import { useArchProjectStore } from '@/stores/project-store'
import type { ArchLlmModel } from '@/types'

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
const project = useArchProjectStore()
const entries = ref<ExecEntry[]>([])
const runtime = ref<any>(null)
const loading = ref(false)
const saving = ref(false)
const savedMsg = ref('')
const probing = ref<Record<string, string>>({})
const expandedId = ref('')

/** ── 环境检测 + 一键安装 ── */
const envInfo = ref<Record<string, any> | null>(null)
const envDetecting = ref(false)
const installing = ref('')
const installMsg = ref<Record<string, string>>({})
const AGENT_META: Record<string, { label: string; doc: string }> = {
  opencode: { label: 'opencode', doc: 'npm install -g opencode-ai' },
  codex: { label: 'codex', doc: 'npm install -g @openai/codex' },
  cline: { label: 'cline SDK (自主模式)', doc: 'npm run build -w packages/agent-sidecar' },
}
async function detectEnv() {
  envDetecting.value = true
  try {
    envInfo.value = await apiGet<Record<string, any>>('/agent/executors/env')
  } catch { envInfo.value = null } finally { envDetecting.value = false }
}
async function installAgent(name: string) {
  installing.value = name
  installMsg.value[name] = t('config.executors.installing')
  try {
    const d = await apiPost<{ status: string; detail: string }>('/agent/executors/install', { agent: name })
    installMsg.value[name] = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
    await detectEnv()
  } catch (e: any) {
    installMsg.value[name] = `✗ ${e?.message || e}`
  } finally { installing.value = '' }
}

/** ── 实例模型(白名单)检测/同步 ── */
const modelProbing = ref<Record<string, string>>({})   // key: `${execId}/${modelName}`
const detected = ref<Record<string, { name: string; model: string; url: string; kind: string }[]>>({})
const detecting = ref('')
const llmModels = ref<ArchLlmModel[]>([])

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
    const [d, llm] = await Promise.all([
      apiGet<{ executors: ExecEntry[]; runtime: any }>('/agent/executors'),
      apiGet<{ models: ArchLlmModel[] }>('/llm/models').catch(() => ({ models: [] })),
    ])
    entries.value = d.executors ?? []
    runtime.value = d.runtime
    llmModels.value = llm.models ?? []
  } catch {
    entries.value = []
  } finally {
    loading.value = false
  }
}
onMounted(() => { load(); detectEnv() })

function healthOf(id: string): boolean | null {
  const h = runtime.value?.health?.[id]
  return h === undefined ? null : !!h
}

function typeLabelOf(v: string): string {
  return TYPES.find((x) => x.value === v)?.label ?? v
}

function addEntry() {
  const used = new Set(entries.value.map(e => e.id))
  let n = 1
  while (used.has(`agent-${n}`)) n++
  entries.value.push({
    id: `agent-${n}`, type: 'opencode', host: 'local', enabled: true, default: false,
    config: { auto_start: true, base_port: 3478, permission: 'auto', timeout: 1800, models: [] },
  })
  expandedId.value = `agent-${n}`
}

function removeEntry(i: number) {
  entries.value.splice(i, 1)
}

function setDefault(idx: number) {
  entries.value.forEach((e, i) => { e.default = i === idx })
}

function toggleExpand(id: string) {
  expandedId.value = expandedId.value === id ? '' : id
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

/** ── opencode: 拉起/关闭服务 + 模型检测勾选(白名单) ── */
async function startServe(e: ExecEntry) {
  probing.value[e.id] = t('config.executors.starting')
  try {
    const d = await apiPost<{ status: string; port?: number; url?: string; note?: string; detail?: string }>(
      '/agent/executors/start', { entry: e, cwd: project.project?.rootPath || '' })
    probing.value[e.id] = d.status === 'ok'
      ? `✓ ${d.url} —— ${d.note}`
      : `✗ ${d.detail || 'fail'}`
    await load()
  } catch (err: any) {
    probing.value[e.id] = `✗ ${err?.message || err}`
  }
}

/** 关闭手动拉起的 serve(后端按 opencode serve --port 特征精确匹配)。 */
async function stopServe(e: ExecEntry) {
  probing.value[e.id] = t('config.executors.stopping')
  try {
    const d = await apiPost<{ status: string; detail: string }>('/agent/executors/stop', { entry: e })
    probing.value[e.id] = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
    await load()
  } catch (err: any) {
    probing.value[e.id] = `✗ ${err?.message || err}`
  }
}

async function detectModels(e: ExecEntry) {
  detecting.value = e.id
  try {
    const d = await apiPost<{ status: string; models?: { name: string; model: string; url: string; kind: string }[]; note?: string; detail?: string }>(
      '/agent/executors/models/detect', { entry: e, cwd: project.project?.rootPath || '' })
    if (d.status !== 'ok' || !d.models) {
      probing.value[e.id] = `✗ ${d.detail || 'fail'}`
      return
    }
    detected.value[e.id] = d.models
    if (!Array.isArray(e.config.models)) e.config.models = []
    probing.value[e.id] = `✓ ${t('config.executors.modelsDetected', { n: d.models.length })}`
  } catch (err: any) {
    probing.value[e.id] = `✗ ${err?.message || err}`
  } finally { detecting.value = '' }
}

function isChecked(e: ExecEntry, model: string): boolean {
  return (e.config.models ?? []).some((m) => m.model === model)
}
function toggleModel(e: ExecEntry, dm: { name: string; model: string; url: string }) {
  if (!Array.isArray(e.config.models)) e.config.models = []
  const i = e.config.models.findIndex((m) => m.model === dm.model)
  if (i >= 0) { e.config.models.splice(i, 1); return }
  e.config.models.push({
    id: `m${Date.now()}${e.config.models.length}`,
    name: dm.name, model: dm.model, url: dm.url, apiKey: '', maxTokens: 0,
  })
}

/** ── cline: 模型与 architect 实例模型保持一致(一键同步) ── */
function syncInstanceModels(e: ExecEntry) {
  if (!llmModels.value.length) return
  e.config.models = llmModels.value.map((m, i) => ({
    id: `m${Date.now()}${i}`, name: m.name, model: m.model,
    url: m.url || '', apiKey: '', maxTokens: 0,
  }))
  if (!e.config.base_url && llmModels.value[0]?.url) e.config.base_url = llmModels.value[0].url
}

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
    const d = await apiPost<{ status: string; detail: string; note?: string }>('/agent/executors/probe',
      { entry: e })
    // ok=✓ / stopped=未运行但 auto_start 属预期 / fail=✗
    const mark = d.status === 'ok' ? '✓' : d.status === 'stopped' ? '○' : '✗'
    probing.value[e.id] = `${mark} ${d.detail}${d.note ? ` —— ${d.note}` : ''}`
  } catch (err: any) {
    probing.value[e.id] = `✗ ${err?.message || err}`
  }
}

const runnerReachable = computed(() => !!runtime.value?.executors)
const srcDir = computed(() => project.project?.rootPath || '')

const typeFields: Record<string, { key: string; label: string; kind?: 'num' | 'bool' | 'select'; options?: string[] }[]> = {
  opencode: [
    { key: 'base_port', label: 'serve 端口', kind: 'num' },
    { key: 'auto_start', label: '自动拉起', kind: 'bool' },
    { key: 'permission', label: '权限策略', kind: 'select', options: ['auto', 'ask'] },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
    { key: 'model', label: '默认模型(须在白名单内)' },
  ],
  'remote-agent': [
    { key: 'agent_url', label: '远端 serve URL' },
    { key: 'api_key', label: 'API Key' },
    { key: 'git_remote', label: '共享仓库(auto=内置)' },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
  ],
  'codex-server': [
    { key: 'codex_bin', label: 'codex 路径' },
    { key: 'model', label: '默认模型(须在白名单内)' },
    { key: 'codex_home', label: 'CODEX_HOME(隔离)' },
    { key: 'approval_policy', label: '审批策略', kind: 'select', options: ['never', 'on-request', 'on-failure', 'untrusted'] },
    { key: 'sandbox_mode', label: '沙箱', kind: 'select', options: ['workspace-write', 'read-only', 'danger-full-access'] },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
  ],
  'cline-sdk': [
    { key: 'provider_id', label: 'Provider' },
    { key: 'model_id', label: '默认模型(须在白名单内)' },
    { key: 'base_url', label: '端点(本地必填, /v1)' },
    { key: 'api_key', label: 'API Key' },
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

      <!-- 环境检测 + 一键安装(仅已适配类型) -->
      <div class="border border-ctp-surface0 rounded-lg p-2.5 space-y-1.5">
        <div class="flex items-center gap-2">
          <WrenchScrewdriverIcon class="w-3.5 h-3.5 text-ctp-overlay1" />
          <span class="text-[11px] text-ctp-overlay1">{{ t('config.executors.envTitle') }}</span>
          <div class="flex-1" />
          <button class="btn !py-0 !px-2 !text-[10px]" :disabled="envDetecting" @click="detectEnv">
            {{ envDetecting ? t('config.executors.detecting') : t('config.executors.envDetect') }}
          </button>
        </div>
        <div v-for="(meta, name) in AGENT_META" :key="name" class="flex items-center gap-2 text-[11px]">
          <span
            class="chip shrink-0"
            :class="envInfo?.[name]?.installed ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
          >
            <component :is="envInfo?.[name]?.installed ? CheckCircleIcon : XCircleIcon" class="w-3 h-3" />
            {{ meta.label }} {{ envInfo?.[name]?.installed ? envInfo[name].version || '✓' : t('config.executors.notInstalled') }}
          </span>
          <span class="font-mono text-[10px] text-ctp-overlay0 truncate" :title="meta.doc">{{ meta.doc }}</span>
          <div class="flex-1" />
          <!-- 一键安装与检测联动: 仅在「已检测且未安装」时出现, 避免误点击 -->
          <button
            v-if="envInfo?.[name] && !envInfo[name].installed"
            class="btn !py-0 !px-2 !text-[10px]"
            :disabled="installing === name"
            @click="installAgent(name)"
          >{{ installing === name ? t('config.executors.installing') : t('config.executors.install') }}</button>
        </div>
        <div v-for="(msg, name) in installMsg" :key="name" class="text-[10px] font-mono text-ctp-overlay0 break-all whitespace-pre-wrap">
          {{ msg }}
        </div>
      </div>

      <!-- 执行器概要条目(点击展开详情) -->
      <div
        v-for="(e, i) in entries"
        :key="e.id"
        class="border border-ctp-surface0 rounded-lg overflow-hidden"
        :class="{ 'opacity-50': !e.enabled }"
      >
        <!-- 概要行 -->
        <div
          class="flex items-center gap-2 px-2.5 py-2 cursor-pointer hover:bg-ctp-surface0/40"
          @click="toggleExpand(e.id)"
        >
          <component :is="expandedId === e.id ? ChevronDownIcon : ChevronRightIcon" class="w-3.5 h-3.5 text-ctp-overlay1 shrink-0" />
          <span class="font-mono font-semibold text-ctp-text">{{ e.id }}</span>
          <span class="text-[11px] text-ctp-subtext0 truncate">{{ typeLabelOf(e.type) }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ e.host === 'remote' ? t('config.executors.hostRemote') : t('config.executors.hostLocal') }}</span>
          <span
            v-if="healthOf(e.id) !== null"
            class="chip"
            :class="healthOf(e.id) ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-surface0 text-ctp-overlay1'"
          >
            <component :is="healthOf(e.id) ? CheckCircleIcon : XCircleIcon" class="w-3 h-3" />
            {{ t('config.executors.health') }}
          </span>
          <span v-if="(e.config.models ?? []).length" class="chip bg-ctp-blue/15 text-ctp-blue">
            {{ (e.config.models ?? []).length }} {{ t('config.executors.modelsCount') }}
          </span>
          <span v-if="e.default" class="chip bg-ctp-mauve/15 text-ctp-mauve">{{ t('config.executors.default') }}</span>
          <div class="flex-1" />
          <label class="flex items-center gap-1 text-[11px] text-ctp-subtext1" @click.stop>
            <input v-model="e.enabled" type="checkbox" class="accent-ctp-blue">{{ t('config.executors.enabled') }}
          </label>
        </div>

        <!-- 详情(展开) -->
        <div v-if="expandedId === e.id" class="border-t border-ctp-surface0/60">
          <!-- 身份编辑行 -->
          <div class="flex items-center gap-2 px-2.5 py-2 bg-ctp-surface0/40">
            <input
              v-model="e.id"
              class="input !py-0.5 !text-xs font-mono w-28"
              :title="t('config.executors.idHint')"
            >
            <select
              v-model="e.type"
              class="input !py-0.5 !text-xs w-48"
              @change="onTypeChange(e)"
            >
              <option v-for="ty in TYPES" :key="ty.value" :value="ty.value">
                {{ ty.label }}
              </option>
            </select>
            <select v-model="e.host" class="input !py-0.5 !text-xs w-16" :title="t('config.executors.hostHint')">
              <option value="local">{{ t('config.executors.hostLocal') }}</option>
              <option value="remote">{{ t('config.executors.hostRemote') }}</option>
            </select>
            <div class="flex-1" />
            <button
              v-if="e.type === 'opencode'"
              class="btn !py-0.5 !px-2 !text-[11px]"
              @click="startServe(e)"
            >{{ t('config.executors.startServe') }}</button>
            <button
              v-if="e.type === 'opencode'"
              class="btn !py-0.5 !px-2 !text-[11px]"
              @click="stopServe(e)"
            >{{ t('config.executors.stopServe') }}</button>
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

          <!-- 开关行: 默认 / 状态信息 -->
          <div class="flex items-center gap-4 px-2.5 py-1.5 text-[11px] text-ctp-subtext1 border-t border-ctp-surface0/60">
            <label class="flex items-center gap-1" :title="t('config.executors.defaultHint')">
              <input
                type="radio"
                name="exec-default"
                :checked="e.default"
                @change="setDefault(i)"
              >{{ t('config.executors.default') }}
            </label>
            <div class="flex-1" />
            <div class="flex items-center gap-3 text-[10px] text-ctp-overlay0 font-mono min-w-0">
              <span v-if="probing[e.id]" class="truncate" :title="probing[e.id]">{{ probing[e.id] }}</span>
            </div>
          </div>

          <!-- 项目源码目录(绑定, 不可改) -->
          <div class="flex items-center gap-2 px-2.5 py-1.5 text-[11px] border-t border-ctp-surface0/60">
            <span class="text-ctp-overlay1">{{ t('config.executors.srcDir') }}</span>
            <span class="font-mono text-ctp-sapphire truncate">{{ srcDir || '—' }}</span>
            <span class="text-[10px] text-ctp-overlay0">{{ t('config.executors.srcDirHint') }}</span>
          </div>

          <!-- 连接参数(随类型) -->
          <div v-if="typeFields[e.type]?.length" class="px-2.5 py-2 border-t border-ctp-surface0/60">
            <div class="text-[10px] text-ctp-overlay1 mb-1.5">{{ t('config.executors.connTitle') }}</div>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
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
                >
              </label>
            </div>
          </div>

          <!-- ══ opencode 专属: 服务内模型检测 → 勾选白名单 ══ -->
          <div v-if="e.type === 'opencode'" class="px-2.5 py-2 border-t border-ctp-surface0/60 space-y-1.5">
            <div class="flex items-center gap-2">
              <span class="text-[10px] text-ctp-overlay1">{{ t('config.executors.modelsTitle') }}</span>
              <span class="text-[10px] text-ctp-overlay0">{{ t('config.executors.whitelistHint') }}</span>
              <div class="flex-1" />
              <button class="btn !py-0 !px-2 !text-[10px]" :disabled="detecting === e.id" @click="detectModels(e)">
                {{ detecting === e.id ? t('config.executors.detecting') : t('config.executors.detectModels') }}
              </button>
            </div>
            <div v-if="detected[e.id]?.length" class="grid grid-cols-1 sm:grid-cols-2 gap-1">
              <label
                v-for="dm in detected[e.id]"
                :key="dm.model"
                class="flex items-center gap-1.5 text-[11px] cursor-pointer"
                :title="`${dm.url} · ${dm.kind}`"
              >
                <input
                  type="checkbox"
                  class="accent-ctp-blue"
                  :checked="isChecked(e, dm.model)"
                  @change="toggleModel(e, dm)"
                >
                <span class="font-mono truncate" :class="isChecked(e, dm.model) ? 'text-ctp-text' : 'text-ctp-overlay1'">{{ dm.model }}</span>
                <span
                  class="chip shrink-0 !text-[9px]"
                  :class="dm.kind === 'local' ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-yellow/15 text-ctp-yellow'"
                >{{ dm.kind }}</span>
              </label>
            </div>
            <div v-else class="text-[10px] text-ctp-overlay0">{{ t('config.executors.detectHint') }}</div>
          </div>

          <!-- ══ cline 专属: 与 architect 实例模型保持一致 ══ -->
          <div v-if="e.type === 'cline-sdk'" class="px-2.5 py-2 border-t border-ctp-surface0/60 space-y-1.5">
            <div class="flex items-center gap-2">
              <span class="text-[10px] text-ctp-overlay1">{{ t('config.executors.modelsTitle') }}</span>
              <span class="text-[10px] text-ctp-overlay0">{{ t('config.executors.clineHint') }}</span>
              <div class="flex-1" />
              <button class="btn !py-0 !px-2 !text-[10px]" @click="syncInstanceModels(e)">
                {{ t('config.executors.syncInstanceModels') }} ({{ llmModels.length }})
              </button>
            </div>
          </div>

          <!-- 模型白名单表(各类型通用, opencode 由勾选生成/cline 由同步生成/codex 手动) -->
          <div v-if="e.config.models" class="px-2.5 py-2 border-t border-ctp-surface0/60 space-y-1.5">
            <div class="flex items-center gap-2">
              <span class="text-[10px] text-ctp-overlay0">
                {{ t('config.executors.whitelistCount', { n: (e.config.models ?? []).length }) }}
              </span>
              <div class="flex-1" />
              <button
                v-if="e.type !== 'opencode' && e.type !== 'cline-sdk'"
                class="btn !py-0 !px-2 !text-[10px]"
                @click="addModel(e)"
              >
                <PlusIcon class="w-3 h-3" />{{ t('config.executors.addModel') }}
              </button>
            </div>
            <div class="hidden lg:grid grid-cols-[7rem_10rem_minmax(0,1fr)_8rem_5rem_4.5rem] gap-1.5 text-[10px] text-ctp-overlay0">
              <span>{{ t('config.executors.mName') }}</span>
              <span>{{ t('config.executors.mModel') }}</span>
              <span>{{ t('config.executors.mUrl') }}</span>
              <span>{{ t('config.executors.mKey') }}</span>
              <span>{{ t('config.executors.mMaxTokens') }}</span>
              <span />
            </div>
            <div
              v-for="(m, mi) in e.config.models"
              :key="m.id || mi"
              class="grid grid-cols-2 lg:grid-cols-[7rem_10rem_minmax(0,1fr)_8rem_5rem_4.5rem] gap-1.5 items-center"
            >
              <input v-model="m.name" class="input !py-0.5 !text-[11px]" :placeholder="t('config.executors.mName')">
              <input v-model="m.model" class="input !py-0.5 !text-[11px] font-mono" :placeholder="t('config.executors.mModel')">
              <input v-model="m.url" class="input !py-0.5 !text-[11px] font-mono col-span-2 lg:col-span-1" :placeholder="t('config.executors.mUrl')">
              <input v-model="m.apiKey" type="password" class="input !py-0.5 !text-[11px] font-mono" :placeholder="t('config.executors.mKey')" autocomplete="off">
              <input v-model.number="m.maxTokens" type="number" class="input !py-0.5 !text-[11px]" :placeholder="t('config.executors.mMaxTokens')">
              <div class="flex items-center gap-1 justify-end">
                <button class="btn !py-0 !px-2 !text-[10px]" :title="t('config.executors.modelProbe')" @click="probeModel(e, m)">
                  {{ t('config.executors.modelProbe') }}
                </button>
                <button class="btn !py-0 !px-1.5 !text-[10px] text-ctp-red" @click="removeModel(e, mi)">
                  <TrashIcon class="w-3 h-3" />
                </button>
              </div>
              <div class="col-span-full text-[10px] text-ctp-overlay0 font-mono break-all">
                {{ modelProbing[`${e.id}/${m.name || m.model || '?'}`] }}
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!entries.length && !loading" class="text-ctp-overlay1">
        {{ t('config.executors.empty') }}
      </div>
    </div>
  </div>
</template>
