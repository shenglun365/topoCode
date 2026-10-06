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
import { useAppDialog } from '@/composables/useAppDialog'
import { useArchProjectStore } from '@/stores/project-store'

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
const dialog = useAppDialog()
const project = useArchProjectStore()
const entries = ref<ExecEntry[]>([])
const runtime = ref<any>(null)
const loading = ref(false)
const saving = ref(false)
const savedMsg = ref('')
const probing = ref<Record<string, string>>({})
// 展开状态绑对象身份 + v-for 用稳定 key(非 e.id):
// 输入 id 时不触发行重建/详情收起(页面状态精准控制)
const expandedEntry = ref<ExecEntry | null>(null)
const entryKeys = new WeakMap<ExecEntry, number>()
let keySeq = 0
const keyOf = (e: ExecEntry): number => {
  let k = entryKeys.get(e)
  if (!k) { k = ++keySeq; entryKeys.set(e, k) }
  return k
}

/** ── 环境检测 + 一键安装 ── */
const envInfo = ref<Record<string, any> | null>(null)
const envDetecting = ref(false)
const installing = ref('')
const installMsg = ref<Record<string, string>>({})
const AGENT_META: Record<string, { label: string; doc: string }> = {
  opencode: { label: 'opencode', doc: 'npm install -g opencode-ai' },
  codex: { label: 'codex', doc: 'npm install -g @openai/codex' },
  cline: { label: 'cline SDK (自主模式)', doc: 'npm run build -w packages/cline-sidecar' },
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
interface DetectedModel {
  name: string; model: string; url: string; kind: string
  /** opencode 探测面元数据(source: builtin|config|env|custom|api) */
  source?: string; authed?: boolean; connected?: boolean
  context?: number; output?: number
}
interface DetectedAgent { name: string; mode: string; builtIn: boolean; description: string; model: string }
const modelProbing = ref<Record<string, string>>({})   // key: `${execId}/${modelName}`
const detected = ref<Record<string, DetectedModel[]>>({})
const detectedAgents = ref<Record<string, DetectedAgent[]>>({})
const showDetected = ref<Record<string, boolean>>({})
const detecting = ref('')

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
    for (const e of entries.value) {
      if (!Array.isArray(e.config.models)) e.config.models = []   // 快照形状稳定
    }
    runtime.value = d.runtime
    // 重载后按 id 找回展开中的条目(id 未变则保持展开)
    if (expandedEntry.value) {
      expandedEntry.value = entries.value.find((x) => x.id === expandedEntry.value?.id) ?? null
    }
  } catch {
    entries.value = []
  } finally {
    loading.value = false
    // 成功/失败均以当前视图为新基线(失败=空视图 → dirty=false 防误点全量覆盖)
    takeSnapshot()
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
  expandedEntry.value = entries.value[entries.value.length - 1]
}

async function removeEntry(i: number) {
  // 删除即持久化(全量覆盖保存), 避免"看起来删了实际没发请求"的误解
  entries.value.splice(i, 1)
  await save()
}

function setDefault(idx: number) {
  entries.value.forEach((e, i) => { e.default = i === idx })
}

function toggleExpand(e: ExecEntry) {
  expandedEntry.value = expandedEntry.value === e ? null : e
  // cline-sdk 展开时拉取引擎版本面(检测/默认/可装清单)
  if (expandedEntry.value?.type === 'cline-sdk' && !enginesInfo.value) loadEngines()
}

function onTypeChange(e: ExecEntry) {
  const defaults: Record<string, Record<string, any>> = {
    opencode: { auto_start: true, base_port: 3478, permission: 'auto', timeout: 1800, capability: '', models: [] },
    'remote-agent': { agent_url: '', api_key: '', git_remote: 'auto', timeout: 3600, models: [] },
    'codex-server': { codex_bin: 'codex', approval_policy: 'never', sandbox_mode: 'workspace-write', timeout: 3600, models: [] },
    'cline-sdk': { node_bin: 'node', sidecar_script: '', provider_id: 'openai-compatible', model_id: '', base_url: '', api_key: '', max_iterations: 2000, capability: '', system_prompt: '', tool_policies: {}, models: [] },
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
    const d = await apiPost<{ status: string; models?: DetectedModel[]; agents?: DetectedAgent[]; note?: string; detail?: string }>(
      '/agent/executors/models/detect', { entry: e, cwd: project.project?.rootPath || '' })
    if (d.status !== 'ok' || !d.models) {
      probing.value[e.id] = `✗ ${d.detail || 'fail'}`
      return
    }
    const k = keyOf(e)
    detected.value[k] = d.models
    detectedAgents.value[k] = d.agents ?? []
    showDetected.value[k] = true
    if (!Array.isArray(e.config.models)) e.config.models = []
    probing.value[e.id] = `✓ ${t('config.executors.modelsDetected', { n: d.models.length })}`
      + (d.note ? ` · ${d.note}` : '')
  } catch (err: any) {
    probing.value[e.id] = `✗ ${err?.message || err}`
  } finally { detecting.value = '' }
}

/** 代理绑定(单选): 空=执行器默认(build); 点击已绑定项=取消绑定。均自动保存 */
function bindAgent(e: ExecEntry, name: string) {
  e.config.agent = e.config.agent === name ? '' : name
  schedulePersist()
}
function unbindAgent(e: ExecEntry) {
  e.config.agent = ''
  schedulePersist()
}
/** 检测到的代理名清单(绑定代理下拉选项源)。 */
function agentNames(e: ExecEntry): string[] {
  return (detectedAgents.value[keyOf(e)] || []).map((a) => a.name)
}

/** 检测面板三态: 未检测=检测模型 → 成功后=隐藏列表 ⇄ 显示列表 */
function toggleDetectPanel(e: ExecEntry) {
  const k = keyOf(e)
  if (!detected.value[k]?.length) { detectModels(e); return }
  showDetected.value[k] = !showDetected.value[k]
}
function detectBtnLabel(e: ExecEntry): string {
  const k = keyOf(e)
  if (!detected.value[k]?.length) return t('config.executors.detectModels')
  return showDetected.value[k] ? t('config.executors.hideList') : t('config.executors.showList')
}

/** 执行器白名单模型 id 清单(默认模型下拉选项源)。
 * 全名优先(m.model="服务商/模型id"): 展示名跨 provider 可重复, 全名唯一可辨;
 * 去重防同 id 重复渲染。存量落盘的展示名经「白名单外」兜底选项仍可选。 */
function modelNames(e: ExecEntry): string[] {
  return Array.from(new Set(((e.config as any)?.models || [])
    .map((m: any) => m?.model || m?.name || '')
    .filter(Boolean)))
}

function isChecked(e: ExecEntry, model: string): boolean {
  return (e.config.models ?? []).some((m) => m.model === model)
}
function toggleModel(e: ExecEntry, dm: { name: string; model: string; url: string }) {
  if (!Array.isArray(e.config.models)) e.config.models = []
  const i = e.config.models.findIndex((m) => m.model === dm.model)
  if (i >= 0) { e.config.models.splice(i, 1); schedulePersist(); return }
  // name 存全名(=model): 展示名跨 provider 可重复(同 bare id),
  // 重名校验会误伤多 provider 同 id 勾选, 运行期 name 引用亦歧义
  e.config.models.push({
    id: `m${Date.now()}${e.config.models.length}`,
    name: dm.model, model: dm.model, url: dm.url, apiKey: '', maxTokens: 0,
  })
  schedulePersist()
}

/** 表单字段: 内置 cline 模型面只剩默认模型选择(实例实时投影)——
 * 白名单/provider/base_url/api_key/sidecar_script 全部退役(引擎面板管 sidecar) */
function fieldsOf(e: ExecEntry) {
  const fields = typeFields[e.type] || []
  if (!isBuiltinExec(e)) return fields
  const hidden = new Set(['sidecar_script', 'provider_id', 'base_url', 'api_key'])
  return fields.filter((f) => !hidden.has(f.key))
}

/** ── cline SDK 引擎版本管理(多版本共存隔离) ──
 * 每版本自包含目录(engines/<ver>: dist+node_modules+data)——进程/存储按版本隔离;
 * 默认版本随任务下发(cline_data_dir 隔离会话); 显式 sidecar_script 优先。 */
interface EngineRow { version: string; ok: boolean; missing?: string[]; installedAt?: string; node?: string; dataDir?: string }
const enginesInfo = ref<{ installed: EngineRow[]; defaultVersion: string; available: any; node: string; repoSidecar: any } | null>(null)
const enginesLoading = ref(false)
const engineInstalling = ref('')
const engineVer = ref('')
const engineMsg = ref('')
async function loadEngines() {
  enginesLoading.value = true
  try { enginesInfo.value = await apiGet<any>('/agent/executors/cline/engines') } catch { /* 保持旧数据 */ } finally { enginesLoading.value = false }
}
async function installEngine(v: string) {
  if (!v) return
  engineInstalling.value = v
  engineMsg.value = `安装 ${v} 中（仓库 sidecar 构建 + npm 依赖安装，可能需要几分钟）…`
  try {
    const d = await apiPost<{ status: string; detail: string }>('/agent/executors/cline/engines/install', { version: v })
    engineMsg.value = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
    await loadEngines()
  } catch (e: any) { engineMsg.value = `✗ ${e?.message || e}` } finally { engineInstalling.value = '' }
}
async function removeEngine(v: string) {
  if (!(await dialog.confirm(`移除引擎 ${v}？该版本的会话数据将一并删除。`, { danger: true }))) return
  try {
    const d = await apiPost<{ status: string; detail: string }>('/agent/executors/cline/engines/remove', { version: v })
    engineMsg.value = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
    await loadEngines()
  } catch (e: any) { engineMsg.value = `✗ ${e?.message || e}` }
}
async function setEngineDefault(v: string) {
  try {
    await apiPost('/agent/executors/cline/engines/default', { version: v })
    await loadEngines()
  } catch (e: any) { engineMsg.value = `✗ ${e?.message || e}` }
}

function addModel(e: ExecEntry) {
  if (!Array.isArray(e.config.models)) e.config.models = []
  e.config.models.push({ id: `m${e.config.models.length + 1}`, name: '', model: '', url: '', apiKey: '', maxTokens: 0 })
}
function removeModel(e: ExecEntry, i: number) {
  e.config.models?.splice(i, 1)
}
/** 白名单 chip 移除(opencode 常显区): 反选 + 自动保存 */
function removeWhitelist(e: ExecEntry, i: number) {
  e.config.models?.splice(i, 1)
  schedulePersist()
}
async function probeModel(e: ExecEntry, m: ExecModel) {
  const key = `${e.id}/${m.name || m.model || '?'}`
  modelProbing.value[key] = '…'
  try {
    // entry 供路由分派: opencode 且 url 空 → opencode 侧静态探活(目录+凭据)
    const d = await apiPost<{ status: string; detail: string }>('/agent/executors/model-probe',
      { url: m.url, model: m.model, apiKey: m.apiKey, entry: e,
        cwd: project.project?.rootPath || '' })
    modelProbing.value[key] = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
  } catch (err: any) {
    modelProbing.value[key] = `✗ ${err?.message || err}`
  }
}

/** ── 未保存变更跟踪 ──
 * 快照 = 最近一次成功加载/持久化的注册表; JSON 序列化比对(键序稳定:
 * 条目仅经 load 赋值与响应式字段写入, 无键重排)。dirty=新增/变化 → 保存按钮可点;
 * 勾选模型/代理绑定走自动保存, 按钮态只补陈"其它编辑"(连接参数/白名单表格等)。 */
const savedSnapshot = ref('[]')
function takeSnapshot() {
  savedSnapshot.value = JSON.stringify(entries.value)
}
const dirty = computed(() => JSON.stringify(entries.value) !== savedSnapshot.value)

/** ── 持久化: 手动保存(保存注册表按钮) + 勾选/绑定自动保存(800ms 防抖) ──
 * persist 默认不触发 load: entries 身份重建会让检测面板(keyOf 对象身份)塌陷;
 * 自动保存失败时 reload 回服务器真值——勾选态弹回, 所见即所存。 */
let persistTimer: ReturnType<typeof setTimeout> | null = null
async function persist(opts: { reload?: boolean; manual?: boolean } = {}) {
  saving.value = true
  savedMsg.value = ''
  try {
    const d = await apiPut<{ runnerRefreshed: boolean }>('/agent/executors',
      { executors: entries.value })
    savedMsg.value = opts.manual
      ? (d.runnerRefreshed
          ? t('config.executors.savedRefreshed')
          : t('config.executors.savedNoRunner'))
      : t('config.executors.autoSaved')
    savedSnapshot.value = JSON.stringify(entries.value)   // 本地态已获服务器接受
    if (opts.reload) await load()
  } catch (e: any) {
    savedMsg.value = e?.message || String(e)
    if (!opts.manual) await load()
  } finally {
    saving.value = false
    setTimeout(() => { savedMsg.value = '' }, 4000)
  }
}
function schedulePersist() {
  if (persistTimer) clearTimeout(persistTimer)
  persistTimer = setTimeout(() => { persistTimer = null; void persist() }, 800)
}

async function save() {
  if (persistTimer) { clearTimeout(persistTimer); persistTimer = null }
  await persist({ reload: true, manual: true })
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

/** 能力探测(十二b): 5 探针标定 → tierProbed; 运行中 4s 轮询直到完成。 */
const capProbing = ref<Record<string, boolean>>({})
const capRunning = ref<Record<string, boolean>>({})
async function startCapProbe(e: ExecEntry) {
  try {
    await apiPost(`/agent/executors/${e.id}/capability-probe`, {})
    capRunning.value[e.id] = true
    capProbing.value[e.id] = true
    const poll = setInterval(async () => {
      try {
        const d = await apiGet<{ running: boolean; tierProbed: string; probeDetail: string }>(
          `/agent/executors/${e.id}/capability-probe`)
        capRunning.value[e.id] = d.running
        if (!d.running) {
          clearInterval(poll)
          capProbing.value[e.id] = false
          await load()
        }
      } catch { clearInterval(poll); capProbing.value[e.id] = false }
    }, 4000)
  } catch (err: any) {
    probing.value[e.id] = `✗ ${err?.message || err}`
    capProbing.value[e.id] = false
  }
}
function capLabel(e: ExecEntry): string {
  const cfg: any = e.config || {}
  if (capRunning.value[e.id]) return '探测中…'
  if (!cfg.tierProbed) return '能力探测'
  const weak = cfg.tierProbed === 'T2'
  return (weak ? '⚠ ' : '') + `实测 ${cfg.tierProbed}（${cfg.probeDetail || ''}）`
}

/** M5 准入标注(C 轴): 实测 T2 = 弱档(全面补偿运行)——提示不拦截。 */
function capTone(e: ExecEntry): string {
  const cfg: any = e.config || {}
  if (cfg.tierProbed === 'T2') return 'text-ctp-peach'
  if (cfg.tierProbed) return 'text-ctp-green'
  return ''
}

/** 内嵌执行器(architect 自主模式): 不可删除、id 锁定。 */
function isBuiltinExec(e: ExecEntry): boolean {
  return e.id === 'cline'
}

const runnerReachable = computed(() => !!runtime.value?.executors)
const srcDir = computed(() => project.project?.rootPath || '')

const typeFields: Record<string, { key: string; label: string; kind?: 'num' | 'bool' | 'select' | 'model-select' | 'agent-select'; options?: string[] }[]> = {
  opencode: [
    { key: 'base_port', label: 'serve 端口', kind: 'num' },
    { key: 'auto_start', label: '自动拉起', kind: 'bool' },
    { key: 'permission', label: '权限策略', kind: 'select', options: ['auto', 'ask'] },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
    { key: 'capability', label: '能力档位(空=未标定)', kind: 'select', options: ['', 'T0', 'T1', 'T2'] },
    { key: 'model', label: '默认模型', kind: 'model-select' },
    { key: 'agent', label: '绑定代理(空=默认)', kind: 'agent-select' },
  ],
  'remote-agent': [
    { key: 'agent_url', label: '远端 serve URL' },
    { key: 'api_key', label: 'API Key' },
    { key: 'git_remote', label: '共享仓库(auto=内置)' },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
  ],
    'codex-server': [
        { key: 'codex_bin', label: 'codex 路径' },
        { key: 'capability', label: '能力档位(空=未标定)', kind: 'select', options: ['', 'T0', 'T1', 'T2'] },
        { key: 'model', label: '默认模型', kind: 'model-select' },
    { key: 'codex_home', label: 'CODEX_HOME(隔离)' },
    { key: 'approval_policy', label: '审批策略', kind: 'select', options: ['never', 'on-request', 'on-failure', 'untrusted'] },
    { key: 'sandbox_mode', label: '沙箱', kind: 'select', options: ['workspace-write', 'read-only', 'danger-full-access'] },
    { key: 'timeout', label: '超时(秒)', kind: 'num' },
  ],
  'cline-sdk': [
    { key: 'provider_id', label: 'Provider(openai-compatible/ollama/deepseek…)' },
    { key: 'model_id', label: '默认模型', kind: 'model-select' },
    { key: 'base_url', label: '端点(本地必填, /v1)' },
    { key: 'api_key', label: 'API Key' },
    { key: 'max_iterations', label: '最大迭代', kind: 'num' },
    { key: 'capability', label: '能力档位(空=未标定)', kind: 'select', options: ['', 'T0', 'T1', 'T2'] },
    { key: 'system_prompt', label: '系统提示(空=默认协议)' },
    { key: 'node_bin', label: 'node 路径(需≥22)' },
    { key: 'sidecar_script', label: 'sidecar 路径' },
    // tool_policies / mcp_servers / teams 为对象/数组配置——经 API 编辑(PUT agent/executors)，表单不展开
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
        <button
          class="btn btn-primary !py-1 !px-3 !text-xs"
          :disabled="saving || !dirty"
          :title="dirty ? '' : t('config.executors.noChanges')"
          @click="save"
        >
          {{ saving
            ? t('config.executors.saving')
            : (dirty ? t('config.executors.save') : t('config.executors.saved')) }}
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
        :key="keyOf(e)"
        class="border border-ctp-surface0 rounded-lg overflow-hidden"
        :class="{ 'opacity-50': !e.enabled }"
      >
        <!-- 概要行 -->
        <div
          class="flex items-center gap-2 px-2.5 py-2 cursor-pointer hover:bg-ctp-surface0/40"
          @click="toggleExpand(e)"
        >
          <component :is="expandedEntry === e ? ChevronDownIcon : ChevronRightIcon" class="w-3.5 h-3.5 text-ctp-overlay1 shrink-0" />
          <span class="font-mono font-semibold text-ctp-text">{{ e.id }}</span>
          <span class="text-[11px] text-ctp-subtext0 truncate">{{ typeLabelOf(e.type) }}</span>
          <span class="chip bg-ctp-surface0 text-ctp-subtext1">{{ e.host === 'remote' ? t('config.executors.hostRemote') : t('config.executors.hostLocal') }}</span>
          <span v-if="isBuiltinExec(e)" class="chip bg-ctp-mauve/15 text-ctp-mauve">{{ t('config.executors.builtin') }}</span>
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
        <div v-if="expandedEntry === e" class="border-t border-ctp-surface0/60">
          <!-- 身份编辑行(内置 cline 免名称/类型配置: 静态标识) -->
          <div class="flex items-center gap-2 px-2.5 py-2 bg-ctp-surface0/40">
            <template v-if="isBuiltinExec(e)">
              <span class="chip bg-ctp-mauve/15 text-ctp-mauve font-mono">cline</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1">内置 · cline SDK（自主模式）</span>
              <span class="text-[10px] text-ctp-overlay0">免配置名称/类型 · 不可删除</span>
            </template>
            <template v-else>
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
            </template>
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
              class="btn !py-0.5 !px-2 !text-[11px]"
              :class="capTone(e)"
              :disabled="capProbing[e.id]"
              :title="capLabel(e) + ' —— 5 探针标定套件(实测挡位写入 tierProbed, 解析链优先于 capability; T2=弱档准入提示, 不拦截)'"
              @click="startCapProbe(e)"
            >
              {{ capLabel(e) }}
            </button>
            <button
              v-if="!isBuiltinExec(e)"
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

          <!-- 连接参数(随类型; 内置 cline 不含 sidecar_script——引擎面板管理) -->
          <div v-if="fieldsOf(e).length" class="px-2.5 py-2 border-t border-ctp-surface0/60">
            <div class="text-[10px] text-ctp-overlay1 mb-1.5">{{ t('config.executors.connTitle') }}</div>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
              <label
                v-for="f in fieldsOf(e)"
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
                <select
                  v-else-if="f.kind === 'model-select' && modelNames(e).length"
                  v-model="e.config[f.key]"
                  class="input !py-0.5 !text-[11px] font-mono"
                >
                  <option value="">{{ t('config.executors.modelDefault') }}</option>
                  <option v-if="e.config[f.key] && !modelNames(e).includes(e.config[f.key])"
                    :value="e.config[f.key]">{{ e.config[f.key] }}(白名单外)</option>
                  <option v-for="m in modelNames(e)" :key="m" :value="m">{{ m }}</option>
                </select>
                <select
                  v-else-if="f.kind === 'agent-select' && (agentNames(e).length || e.config[f.key])"
                  v-model="e.config[f.key]"
                  class="input !py-0.5 !text-[11px] font-mono"
                >
                  <option value="">{{ t('config.executors.agentDefault') }}</option>
                  <option v-if="e.config[f.key] && !agentNames(e).includes(e.config[f.key])"
                    :value="e.config[f.key]">{{ e.config[f.key] }}({{ t('config.executors.notDetected') }})</option>
                  <option v-for="a in agentNames(e)" :key="a" :value="a">{{ a }}</option>
                </select>
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
            <span class="text-[10px] text-ctp-overlay0">{{ t('config.executors.hintOpencode') }}</span>
            <div class="flex items-center gap-2">
              <span class="text-[10px] text-ctp-overlay1">{{ t('config.executors.modelsTitle') }}</span>
              <span class="text-[10px] text-ctp-overlay0">{{ t('config.executors.whitelistHint') }}</span>
              <div class="flex-1" />
              <button class="btn !py-0 !px-2 !text-[10px]" :disabled="detecting === e.id" @click="toggleDetectPanel(e)">
                {{ detecting === e.id ? t('config.executors.detecting') : detectBtnLabel(e) }}
              </button>
            </div>
            <!-- 已选白名单(常显): 刷新/保存后回显, 独立于检测面板; 点 × 移除并自动保存 -->
            <div
              v-if="e.config.models?.length"
              class="flex flex-wrap items-center gap-1"
            >
              <span class="text-[10px] text-ctp-overlay0">{{ t('config.executors.whitelistShort', { n: e.config.models.length }) }}</span>
              <span
                v-for="(m, mi) in e.config.models"
                :key="m.id || m.model"
                class="chip !text-[9px] font-mono bg-ctp-blue/10 text-ctp-sapphire cursor-pointer hover:bg-ctp-blue/20"
                :title="t('config.executors.removeWhitelist')"
                @click="removeWhitelist(e, mi)"
              >{{ m.model }} ×</span>
            </div>
            <div v-if="detected[keyOf(e)]?.length && showDetected[keyOf(e)]" class="grid grid-cols-1 sm:grid-cols-2 gap-1">
              <label
                v-for="dm in detected[keyOf(e)]"
                :key="dm.model"
                class="flex items-center gap-1.5 text-[11px] cursor-pointer"
                :title="`${dm.url || 'opencode 内置目录'} · ${dm.kind}${dm.context ? ` · ctx ${dm.context}` : ''}${dm.source ? ` · ${dm.source}` : ''}`"
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
                <span v-if="dm.connected" class="chip shrink-0 !text-[9px] bg-ctp-blue/15 text-ctp-blue">✓</span>
                <span v-else-if="dm.authed === false" class="chip shrink-0 !text-[9px] bg-ctp-red/15 text-ctp-red">{{ t('config.executors.needsAuth') }}</span>
              </label>
            </div>
            <!-- 检测到的代理(builtIn 置前): 点击绑定, 再点取消; 空=执行器默认 build -->
            <div v-if="detectedAgents[keyOf(e)]?.length && showDetected[keyOf(e)]" class="space-y-1 pt-0.5">
              <div class="text-[10px] text-ctp-overlay1">{{ t('config.executors.agentsTitle') }}</div>
              <div class="flex flex-wrap gap-1">
                <button
                  class="btn !py-0 !px-2 !text-[10px] font-mono"
                  :class="!e.config.agent ? 'bg-ctp-blue/20 text-ctp-blue' : ''"
                  @click="unbindAgent(e)"
                >{{ t('config.executors.agentDefault') }}</button>
                <button
                  v-for="a in detectedAgents[keyOf(e)]"
                  :key="a.name"
                  class="btn !py-0 !px-2 !text-[10px] font-mono"
                  :class="e.config.agent === a.name ? 'bg-ctp-blue/20 text-ctp-blue' : ''"
                  :title="`${a.builtIn ? t('config.executors.agentBuiltIn') : t('config.executors.agentCustom')}${a.description ? ` · ${a.description}` : ''}${a.model ? ` · ${a.model}` : ''}`"
                  @click="bindAgent(e, a.name)"
                >{{ a.name }}</button>
              </div>
            </div>
            <div v-if="!detected[keyOf(e)]?.length && !detectedAgents[keyOf(e)]?.length" class="text-[10px] text-ctp-overlay0">{{ t('config.executors.detectHint') }}</div>
          </div>

          <!-- ══ cline 专属(内置): 模型面=architect 实例实时投影, 仅选默认模型 ══ -->
          <div v-if="e.type === 'cline-sdk' && isBuiltinExec(e)" class="px-2.5 py-1.5 border-t border-ctp-surface0/60">
            <span class="text-[10px] text-ctp-overlay0">
              模型列表随 architect 实例配置实时同步（无需白名单/端点/密钥重复配置）；「默认模型」在列表范围内选定，会话级可临时切换
            </span>
          </div>

          <!-- ══ codex 专属: 模型适配建议(本地中小模型支持弱) ══ -->
          <div
            v-if="e.type === 'codex-server'"
            class="px-2.5 py-1.5 border-t border-ctp-surface0/60"
          >
            <span class="text-[10px] text-ctp-overlay0">{{ t('config.executors.hintCodex') }}</span>
          </div>

          <!-- ══ cline 专属(内置): SDK 引擎版本管理(多版本共存·进程/存储按版本隔离) ══ -->
          <div v-if="e.type === 'cline-sdk' && isBuiltinExec(e)" class="px-2.5 py-2 border-t border-ctp-surface0/60 space-y-1.5">
            <div class="flex items-center gap-2 flex-wrap">
              <span class="text-[10px] text-ctp-overlay1">SDK 引擎版本</span>
              <span class="text-[10px] text-ctp-overlay0">多版本共存，按版本隔离进程与会话存储；默认版本对新会话生效</span>
              <div class="flex-1" />
              <button class="btn !py-0 !px-2 !text-[10px]" :disabled="enginesLoading" @click="loadEngines">
                {{ enginesLoading ? '检测中…' : '检测' }}
              </button>
            </div>
            <div v-if="enginesInfo" class="space-y-1.5">
              <div class="flex items-center gap-1.5 flex-wrap text-[10px]">
                <span class="chip bg-ctp-surface0 text-ctp-subtext1" :title="`node 版本（@cline/core 要求 >=22）: ${enginesInfo.node || '未检测到'}`">
                  node {{ enginesInfo.node || '?' }}
                </span>
                <span
                  v-if="enginesInfo.available?.latest"
                  class="chip bg-ctp-teal/15 text-ctp-teal"
                >npm latest {{ enginesInfo.available.latest }}</span>
                <span
                  v-else-if="enginesInfo.available?.error"
                  class="chip bg-ctp-red/15 text-ctp-red"
                  :title="enginesInfo.available.error"
                >registry 不可达</span>
                <span
                  class="chip"
                  :class="enginesInfo.repoSidecar?.exists ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
                  :title="enginesInfo.repoSidecar?.path"
                >仓库内置 {{ enginesInfo.repoSidecar?.exists ? '✓' : '✗' }}</span>
                <span class="text-ctp-overlay0">
                  默认: <span class="font-mono">{{ enginesInfo.defaultVersion || '未设(回退仓库内置)' }}</span>
                </span>
              </div>
              <div
                v-for="eng in enginesInfo.installed"
                :key="eng.version"
                class="flex items-center gap-2 text-[11px]"
              >
                <input
                  type="radio"
                  name="cline-engine-default"
                  :checked="eng.version === enginesInfo?.defaultVersion"
                  title="设为执行器默认使用的引擎版本"
                  @change="setEngineDefault(eng.version)"
                >
                <span class="font-mono" :class="eng.ok ? 'text-ctp-text' : 'text-ctp-red'">v{{ eng.version }}</span>
                <span
                  class="chip !text-[9px]"
                  :class="eng.ok ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-red/15 text-ctp-red'"
                  :title="(eng.missing || []).join('; ')"
                >{{ eng.ok ? 'ok' : 'broken' }}</span>
                <span class="text-[10px] text-ctp-overlay0 truncate" :title="eng.dataDir">{{ eng.installedAt || '' }}</span>
                <div class="flex-1" />
                <button
                  class="btn !py-0 !px-2 !text-[10px] text-ctp-red"
                  :disabled="(enginesInfo?.installed?.length ?? 0) > 1 && eng.version === enginesInfo?.defaultVersion"
                  :title="(enginesInfo?.installed?.length ?? 0) > 1 && eng.version === enginesInfo?.defaultVersion
                    ? '默认版本不可移除——先切换默认'
                    : '移除该版本（含其会话数据）'"
                  @click="removeEngine(eng.version)"
                >移除</button>
              </div>
              <div class="flex items-center gap-1.5">
                <select
                  v-model="engineVer"
                  class="input !py-0.5 !text-[11px] font-mono w-44"
                  title="npm 稳定版清单(新→旧, 最多 15 个)"
                >
                  <option value="">选择可装版本…</option>
                  <option
                    v-for="v in enginesInfo.available?.versions || []"
                    :key="v"
                    :value="v"
                  >{{ v }}{{ v === enginesInfo.available?.latest ? '（latest）' : '' }}</option>
                </select>
                <input
                  v-model="engineVer"
                  class="input !py-0.5 !text-[11px] font-mono w-32"
                  placeholder="或输入版本号"
                >
                <button
                  class="btn !py-0 !px-2 !text-[10px]"
                  :disabled="!engineVer || !!engineInstalling"
                  @click="installEngine(engineVer)"
                >
                  {{ engineInstalling ? `安装 ${engineInstalling} 中…` : '下载安装' }}
                </button>
              </div>
            </div>
            <div v-else class="text-[10px] text-ctp-overlay0">点击「检测」加载引擎版本面</div>
            <div v-if="engineMsg" class="text-[10px] font-mono text-ctp-overlay0 break-all whitespace-pre-wrap">{{ engineMsg }}</div>
          </div>

          <!-- 模型白名单表(opencode 由检测勾选生成/codex 手动维护; 内置 cline 由直选生成——不可手编) -->
          <div v-if="e.config.models && e.type !== 'cline-sdk'" class="px-2.5 py-2 border-t border-ctp-surface0/60 space-y-1.5">
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
            <!-- 列宽: 模型ID 加宽适配 服务商/模型ID 全名(≥qwen3.8-flash 类长名), URL 弹性下限防挤压 -->
            <div class="hidden lg:grid grid-cols-[8rem_minmax(14rem,22rem)_minmax(10rem,1fr)_8rem_5rem_4.5rem] gap-1.5 text-[10px] text-ctp-overlay0">
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
              class="grid grid-cols-2 lg:grid-cols-[8rem_minmax(14rem,22rem)_minmax(10rem,1fr)_8rem_5rem_4.5rem] gap-1.5 items-center"
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
