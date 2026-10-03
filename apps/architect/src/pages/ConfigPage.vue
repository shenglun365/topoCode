<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { CpuChipIcon, Cog6ToothIcon, ArrowDownTrayIcon, PlusIcon, TrashIcon, AdjustmentsHorizontalIcon, PencilSquareIcon, BoltIcon } from '@heroicons/vue/24/outline'
import PageHeader from '@/components/PageHeader.vue'
import { useArchSpecStore } from '@/stores/spec-store'
import { useArchProjectStore } from '@/stores/project-store'
import { apiGet, apiPost, apiPut, apiDelete, apiBaseUrl, getToken } from '@/services/api-client'
import { backendUp } from '@/services/backend'
import { useAppDialog } from '@/composables/useAppDialog'
import { semanticAssetService, type CodegraphStatus } from '@/services/semantic-asset-service'
import AgentExecutorsCard from '@/components/config/AgentExecutorsCard.vue'
import type { ArchLlmModel, ArchLlmModelsResult, ArchLlmImportResult } from '@/types'

const { t, te } = useI18n()
const dialog = useAppDialog()

// ── 设置页子 tab ──
const TABS = [
  { key: 'instance', label: 'config.tabs.instance' },
  { key: 'executors', label: 'config.tabs.executors' },
  { key: 'roleModels', label: 'config.tabs.roleModels' },
  { key: 'other', label: 'config.tabs.other' },
] as const
const activeTab = ref<string>('instance')
const spec = useArchSpecStore()

const project = useArchProjectStore()
spec.load()


// ── 资产助理（数据资产·语义分析管线工种；per-call 生效，不写全局 llm 配置） ──
interface AgentRole { name: string; label: string; modelId: string; note?: string }
const roles = ref<AgentRole[]>([])
const rolesSaving = ref(false)
const rolesSavedAt = ref(0)

async function loadRoles() {
  try {
    const r = await apiGet<{ roles: AgentRole[] }>('/agent/roles')
    roles.value = r.roles ?? []
  } catch {
    roles.value = []
  }
}

// 角色文案走 i18n(按 name), 后端兜底
const roleLabel = (r: AgentRole) =>
  te(`config.roles.items.${r.name}.label`) ? t(`config.roles.items.${r.name}.label`) : r.label
const roleNote = (r: AgentRole) =>
  te(`config.roles.items.${r.name}.note`) ? t(`config.roles.items.${r.name}.note`) : (r.note || '')
const roleTrigger = (r: AgentRole) =>
  te(`config.roles.items.${r.name}.trigger`) ? t(`config.roles.items.${r.name}.trigger`) : ''

async function saveRoles() {
  rolesSaving.value = true
  try {
    const r = await apiPut<{ roles: AgentRole[] }>('/agent/roles', { roles: roles.value })
    roles.value = r.roles ?? []
    rolesSavedAt.value = Date.now()
    setTimeout(() => { rolesSavedAt.value = 0 }, 2000)
  } finally {
    rolesSaving.value = false
  }
}

loadRoles()

// ── 轻任务模型（编码编排侧：标题摘要/范围探针；与资产助理分属两域） ──
interface LightTask { key: string; label: string; note: string; modelId: string }
const lightTasks = ref<LightTask[]>([])
const lightSaving = ref(false)
const lightSavedAt = ref(0)

async function loadLightTasks() {
  try {
    const r = await apiGet<{ lightTasks: Record<string, string> }>('/agent/light-tasks')
    const cfg = r.lightTasks || {}
    lightTasks.value = ['summary', 'probe'].map((k) => ({
      key: k,
      label: te(`config.lightTasks.items.${k}.label`)
        ? t(`config.lightTasks.items.${k}.label`) : k,
      note: te(`config.lightTasks.items.${k}.note`)
        ? t(`config.lightTasks.items.${k}.note`) : '',
      modelId: cfg[k] || '',
    }))
  } catch {
    lightTasks.value = []
  }
}

async function saveLightTasks() {
  lightSaving.value = true
  try {
    const payload = Object.fromEntries(lightTasks.value.map((x) => [x.key, x.modelId]))
    const r = await apiPut<{ lightTasks: Record<string, string> }>(
      '/agent/light-tasks', { lightTasks: payload })
    const cfg = r.lightTasks || {}
    lightTasks.value = lightTasks.value.map((x) => ({ ...x, modelId: cfg[x.key] || '' }))
    lightSavedAt.value = Date.now()
    setTimeout(() => { lightSavedAt.value = 0 }, 2000)
  } finally {
    lightSaving.value = false
  }
}

loadLightTasks()



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
// 编辑手动模型条目: 就地在条目位置切换编辑框(不跳顶部表单)
const editingManualId = ref('')
function startEditManual(m: ArchLlmModel) {
  editingManualId.value = m.id
  showAddManual.value = false
  manualForm.name = m.name
  manualForm.provider = m.provider || ''
  manualForm.model = m.model
  manualForm.url = m.url || ''
}
function toggleAddManual() {
  showAddManual.value = !showAddManual.value
  if (showAddManual.value) resetManualForm()
}
function resetManualForm() {
  editingManualId.value = ''
  manualForm.name = ''
  manualForm.provider = ''
  manualForm.model = ''
  manualForm.url = ''
}

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
    if (editingManualId.value) {
      // 编辑态: 修改既有 manual 条目
      if (await backendUp()) {
        const row = await apiPut<ArchLlmModel>(`/llm/models/manual/${editingManualId.value}`, {
          name: manualForm.name.trim(),
          provider: manualForm.provider.trim() || 'custom',
          model: manualForm.model.trim(),
          url: manualForm.url.trim(),
        })
        const i = llmModels.value.findIndex((x) => x.id === editingManualId.value)
        if (i >= 0) llmModels.value[i] = row
      } else {
        const i = llmModels.value.findIndex((x) => x.id === editingManualId.value)
        if (i >= 0) {
          llmModels.value[i] = {
            ...llmModels.value[i],
            name: manualForm.name.trim(),
            provider: manualForm.provider.trim() || 'custom',
            model: manualForm.model.trim(),
            url: manualForm.url.trim(),
          }
        }
      }
      resetManualForm()
      showAddManual.value = false
      return
    }
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
    resetManualForm()
    showAddManual.value = false
  } finally {
    addingManual.value = false
  }
}

async function removeModel(m: ArchLlmModel) {
  const tip = m.source === 'imported'
    ? t('config.llm.unlinkImportedTip')
    : t('config.llm.deleteManualTip')
  if (!(await dialog.confirm(tip, { danger: true }))) return
  if (await backendUp()) {
    await apiDelete<{ id: string }>(`/llm/models/${m.id}`).catch(() => {})
  }
  llmModels.value = llmModels.value.filter((x) => x.id !== m.id)
}

// 清空全部测评档案(旧套件/旧刻度残留清理): 各模型回到未测评态, 重探生成新档案
async function clearAllProfiles() {
  if (!(await dialog.confirm(t('config.llm.clearProfilesConfirm'), { danger: true }))) return
  try {
    await apiDelete<{ cleared: number }>('/llm/model-profiles')
    capProfiles.value = {}
  } catch { /* api 层提示 */ }
}

loadLlm()

// ── architect 实例模型连通性测试(模型下沉实例, 逐条可测) ──
const llmProbing = ref<Record<string, string>>({})
async function probeLlm(m: ArchLlmModel) {
  llmProbing.value[m.id] = '…'
  try {
    const { apiPost } = await import('@/services/api-client')
    const d = await apiPost<{ status: string; detail: string }>('/llm/models/probe', { modelId: m.id })
    llmProbing.value[m.id] = `${d.status === 'ok' ? '✓' : '✗'} ${d.detail}`
  } catch (e: any) {
    llmProbing.value[m.id] = `✗ ${e?.message || e}`
  }
}

// ── 模型能力探测(分级适配 T0-T2): 工具协议/结构化输出/指令边界 → 档案 ──
function tierLabel(t: number): string {
  return ({ 0: 'T0 强', 1: 'T1 中', 2: 'T2 弱' } as Record<number, string>)[t] ?? `T${t}`
}
// 准入三档投影: insufficient(模型能力不足, 补偿复核未通过) / weak(T2 补偿可运行) /
// 无档案 admission 字段(手工档/启发式)时退回 tier===2 判 weak(维持原语义)
function admissionLevel(m: ArchLlmModel): string {
  const p: any = capProfiles.value[m.id]
  if (p?.admission?.level) return String(p.admission.level)
  return Number(p?.tier) === 2 ? 'weak' : ''
}
function admissionNote(m: ArchLlmModel): string {
  const p: any = capProfiles.value[m.id]
  return String(p?.admission?.note
    || (admissionLevel(m) === 'weak' ? 'T2 档——按全面补偿模式运行(未做补偿复核)' : ''))
}

// 测评详情 chip(恒渲染定宽, 状态吸收 Q3A): 未测评/测评中…/排队中…/T0-T2/能力不足/测评失败
// 注意: 「进行中」判据用 capActive(瞬时态); capProbing 是结果回执(✗/⏳ 常驻展示,
// ✓ 成功即清除)——若拿它判进行中, 完成后 chip 会永远停在「测评中…」
function evalChipState(m: ArchLlmModel): { text: string; cls: string; title: string } {
  if (capActive.value[m.id]) {
    const msg = capProbing.value[m.id] || ''
    return {
      text: msg.startsWith('排队') ? '排队中…' : '测评中…',
      cls: 'bg-ctp-yellow/15 text-ctp-yellow',
      title: msg || '探测闸门串行执行中',
    }
  }
  const receipt = capProbing.value[m.id] || ''
  if (receipt.startsWith('✗')) {
    return { text: '测评失败', cls: 'bg-ctp-red/20 text-ctp-red', title: receipt }
  }
  if (receipt.startsWith('⏳')) {
    return { text: '测评中…', cls: 'bg-ctp-yellow/15 text-ctp-yellow', title: receipt }
  }
  const p: any = capProfiles.value[m.id]
  if (!p) {
    return { text: '未测评', cls: 'bg-ctp-surface0/60 text-ctp-overlay0',
             title: '尚未探测——点「能力探测」开始' }
  }
  if (admissionLevel(m) === 'insufficient') {
    return { text: '能力不足', cls: 'bg-ctp-red/20 text-ctp-red', title: admissionNote(m) }
  }
  // 综合分直显 + 四档配色(评分与策略解耦——策略档位在浮层内查看/调整):
  // ≥0.90 强(绿) / ≥0.75 良(青) / ≥0.60 中(黄) / <0.60 弱(橙)
  const score = Number(p.caps?.probeScore)
  if (!Number.isFinite(score)) {
    return { text: `T${Number(p.tier)}·未评分`, cls: 'bg-ctp-surface0/60 text-ctp-overlay0',
             title: '手工策略档位(无探测分数)' }
  }
  return {
    text: `${score.toFixed(2)} ${score >= 0.90 ? '强' : score >= 0.75 ? '良' : score >= 0.60 ? '中' : '弱'}`,
    cls: score >= 0.90 ? 'bg-ctp-green/15 text-ctp-green'
       : score >= 0.75 ? 'bg-ctp-teal/15 text-ctp-teal'
       : score >= 0.60 ? 'bg-ctp-yellow/15 text-ctp-yellow'
       : 'bg-ctp-peach/20 text-ctp-peach',
    title: `综合 ${score}（≥0.90 强 / ≥0.75 良 / ≥0.60 中 / <0.60 弱）——执行策略悬停面板内查看/调整`,
  }
}

// 探测历史时间线(悬停面板用)
function historyText(p: any): string {
  const hist = (p.probes ?? []).map((h: any) => {
    const d = new Date(h.ts || 0)
    return `${d.getMonth() + 1}/${d.getDate()} T${h.tier}`
  })
  return hist.length ? `历史: ${hist.join(' → ')}` : '首次探测'
}

// 测评浮层开关: 500ms 延迟关闭(短暂移出不闪断) + 主动关闭按钮兜底
const openEvalId = ref('')
const openEvalUp = ref(false)   // 视口下半部 → 浮层向上展开(底行防溢出可视区)
let evalCloseTimer: ReturnType<typeof setTimeout> | null = null
function cancelEvalClose() {
  if (evalCloseTimer) { clearTimeout(evalCloseTimer); evalCloseTimer = null }
}
function openEvalPanel(id: string, e?: MouseEvent) {
  cancelEvalClose()
  openEvalId.value = id
  if (e) {
    const rect = (e.currentTarget as HTMLElement | undefined)?.getBoundingClientRect()
    // 浮层高约 240px: 触发元素底部距视口底不足此高度 → 向上展开
    openEvalUp.value = !!rect && rect.bottom + 240 > window.innerHeight
  }
}

/** 面板内悬停: 只续期防关闭, 不重算位置(用面板 rect 重算会与 chip 首算不一致 → 跳位) */
function keepEvalPanel(id: string) {
  cancelEvalClose()
  openEvalId.value = id
}
function scheduleEvalClose() {
  cancelEvalClose()
  evalCloseTimer = setTimeout(() => {
    evalCloseTimer = null
    openEvalId.value = ''
  }, 500)
}
function closeEvalPanel() {
  cancelEvalClose()
  openEvalId.value = ''
}
const capProfiles = ref<Record<string, any>>({})
async function loadProfiles() {
  try {
    const d = await apiGet<{ profiles: any[] }>('/llm/model-profiles')
    capProfiles.value = Object.fromEntries((d.profiles ?? []).map((p: any) => [p.modelId, p]))
  } catch { /* 后端未就绪静默 */ }
}
loadProfiles()
const capProbing = ref<Record<string, string>>({})
// 探测并发治理联动(后端互斥串行+FIFO 排队+滤重): 任一探测进行中,
// 其余模型按钮禁用并提示排队; 同模型重复点击前端滤重早退。
// capActive 仅"在跑"瞬时态(结束即清); capProbing 存结果回执(持续展示)
const capActive = ref<Record<string, boolean>>({})
// 注意 .value: 对 RefImpl 本体做 Object.values 会枚举内部字段 → 恒真(按钮永久禁用)
const capBusy = computed(() => Object.values(capActive.value).some(Boolean))
const capAbort: Record<string, AbortController> = {}
async function capabilityProbe(m: ArchLlmModel) {
  if (capActive.value[m.id]) return
  const wasBusy = capBusy.value
  capActive.value = { ...capActive.value, [m.id]: true }
  const ac = new AbortController()
  capAbort[m.id] = ac
  capProbing.value[m.id] = wasBusy
    ? '排队中…(后端串行探测, 等待前置完成)'
    : '探测中…(~10 次小调用)'
  try {
    const { apiPost } = await import('@/services/api-client')
    // 兜底超时: 探测请求悬挂(模型服务无响应等)时恢复按钮可用, 不无限置灰
    // 15 分钟: 六维用例 16 次(T2 补偿复核 18 次)大模型慢推理场景
    const d = await Promise.race([
      apiPost<any>(`/llm/models/${m.id}/capability-probe`, {}, ac.signal),
      new Promise<never>((_, rej) => setTimeout(() => rej(new Error('探测超时(15 分钟)')), 900000)),
    ])
    if (d?.reachable === false) {
      capProbing.value[m.id] = `✗ ${d.summary || '模型不可达'}`
    } else if (d?.dedup) {
      capProbing.value[m.id] = `⏳ ${d.summary || '已在探测中(滤重)'}`
    } else {
      capProfiles.value = { ...capProfiles.value, [m.id]: d }
      // 成功即档案生效 → chip 由档案驱动实时刷新; ✗/⏳ 回执保留展示
      delete capProbing.value[m.id]
    }
  } catch (e: any) {
    if (e?.name === 'AbortError') return   // 服务端真值对账主动放弃, 提示已由对账写入
    capProbing.value[m.id] = `✗ ${e?.message || e}`
  } finally {
    delete capAbort[m.id]
    const next = { ...capActive.value }
    delete next[m.id]
    capActive.value = next
  }
}

// 闸门自省(置灰期间可视化 + 服务端真值对账): 忙时每 2s 轮询
// /llm/capability-probe/status——闸门空闲而前端仍有在途请求 = 孤儿请求
// (响应丢失/后端重启), 连续 2 次空闲即主动 abort 回收, 不再无限置灰。
const capGateStatus = ref<{ running: string; queue: string[] } | null>(null)
const capGateLastError = ref('')
const capGateTicked = ref(false)   // 首帧竞态防护: 首次 tick 落地前不判「不可达」
const gateModelName = (mid: string) => llmModels.value.find((x) => x.id === mid)?.name || mid
let capGateTimer: ReturnType<typeof setInterval> | null = null
let capGateIdleTicks = 0
function stopGatePoll() {
  if (capGateTimer) { clearInterval(capGateTimer); capGateTimer = null }
  capGateStatus.value = null
  capGateLastError.value = ''
  capGateTicked.value = false
  capGateIdleTicks = 0
}
async function recoverOrphans() {
  const mids = Object.keys(capActive.value)
  for (const ac of Object.values(capAbort)) { try { ac.abort() } catch { /* 已闭合 */ } }
  for (const mid of mids) {
    capProbing.value[mid] = '✗ 与后端探测闸门失联(响应丢失或后端重启), 请重试'
  }
}
watch(capBusy, (busy) => {
  if (!busy) { stopGatePoll(); return }
  const tick = async () => {
    const url = `${apiBaseUrl()}/llm/capability-probe/status`
    const ac = new AbortController()
    const killer = setTimeout(() => ac.abort(), 8000)   // 悬挂防护: 8s 未返回即显式失败
    try {
      const tok = getToken()
      const resp = await fetch(url, {
        headers: tok ? { Authorization: `Bearer ${tok}` } : {},
        signal: ac.signal,
      })
      const raw = await resp.text()
      let d: any = null
      try { d = JSON.parse(raw)?.data } catch { /* 非 JSON 包体 */ }
      capGateLastError.value = ''
      capGateTicked.value = true
      capGateStatus.value = { running: d?.running || '', queue: d?.queue || [] }
      const idle = !(d?.running || '').trim() && !(d?.queue || []).length
      capGateIdleTicks = idle ? capGateIdleTicks + 1 : 0
      if (idle && capGateIdleTicks >= 2 && capBusy.value) {
        capGateIdleTicks = 0
        await recoverOrphans()
      }
    } catch (e) {
      capGateLastError.value = ac.signal.aborted
        ? '状态查询悬挂超时(8s)——该请求被浏览器挂起未返回'
        : String((e as Error)?.message || e)
      capGateTicked.value = true
      capGateStatus.value = null
    } finally {
      clearTimeout(killer)
    }
  }
  void tick()
  capGateTimer = setInterval(() => {
    if (!capBusy.value) stopGatePoll()
    else void tick()
  }, 2000)
})
onUnmounted(() => {
  stopGatePoll()
  cancelEvalClose()
})
// ── 语义资产解析能力(独立探测独立参数, 与综合档分离) ──────────────
const assetProbing = ref<Record<string, string>>({})
const assetActive = ref<Record<string, boolean>>({})
async function assetProbe(m: ArchLlmModel) {
  if (assetActive.value[m.id]) return
  assetActive.value = { ...assetActive.value, [m.id]: true }
  assetProbing.value[m.id] = '探测中…(10 次调用测稳定性)'
  try {
    const { apiPost } = await import('@/services/api-client')
    const d = await Promise.race([
      apiPost<any>(`/llm/models/${m.id}/asset-capability-probe`, { force: true }),
      new Promise<never>((_, rej) => setTimeout(() => rej(new Error('探测超时(15 分钟)')), 900000)),
    ])
    if (d?.skipped) {
      assetProbing.value[m.id] = '⏳ 已有探测档案(未强制)'
    } else if (d?.profile) {
      capProfiles.value = {
        ...capProfiles.value,
        [m.id]: { ...(capProfiles.value[m.id] || { modelId: m.id }), asset: { ...d.profile, evidence: d.evidence } },
      }
      delete assetProbing.value[m.id]
    } else {
      assetProbing.value[m.id] = '✗ 探测未返回档案'
    }
  } catch (e: any) {
    assetProbing.value[m.id] = `✗ ${e?.message || e}`
  } finally {
    const next = { ...assetActive.value }
    delete next[m.id]
    assetActive.value = next
  }
}

async function setAssetPolicy(m: ArchLlmModel, mode: string) {
  try {
    const { apiPut } = await import('@/services/api-client')
    await apiPut(`/llm/model-profiles/${m.id}`, mode ? { asset: { mode } } : { asset: null })
    await loadProfiles()   // 档案重载(手动覆盖 source=manual / 清除回缺省)
  } catch (e: any) {
    assetProbing.value[m.id] = `✗ ${e?.message || e}`
  }
}

function assetPolicyText(asset: any): string {
  const mode = { numbered: '编号引用', free: '自由归纳', structural: '结构化构链' }[asset.mode as string] || asset.mode
  const cap = asset.listCap ? ` · 清单≤${asset.listCap}` : ''
  const src = asset.source === 'manual' ? ' · 手动' : asset.source === 'probed' ? ' · 已探测' : ''
  const ev = asset.evidence
  const evTxt = ev ? ` · name@100:${_evMin(ev['name@100'])} num@200:${_evMin(ev['num@200'])}` : ''
  return `${mode}${cap}${src}${evTxt}`
}
function _evMin(v?: number[]): string {
  return v?.length ? Math.round(Math.min(...v) * 100) + '%' : '—'
}

async function setManualTier(m: ArchLlmModel, tier: number) {
  try {
    const { apiPut } = await import('@/services/api-client')
    const d = await apiPut<any>(`/llm/model-profiles/${m.id}`, { tier })
    capProfiles.value = { ...capProfiles.value, [m.id]: d }
  } catch { /* 静默 */ }
}
// ── 符号源(CodeGraph)开关：三档 + 状态(KV 持久化) ──
const cgStatus = ref<CodegraphStatus | null>(null)
const cgSaving = ref(false)
const cgSyncing = ref(false)
async function loadCgStatus() {
  cgStatus.value = await semanticAssetService.codegraphStatus() ?? null
}
async function runCgSync() {
  cgSyncing.value = true
  try {
    await semanticAssetService.symbolSync()
    void loadCgStatus()
  } catch { /* 失败提示由 api 层处理 */ } finally {
    cgSyncing.value = false
  }
}
const cgColdStarting = ref(false)
const cgColdStartMsg = ref('')
async function runCgColdStart() {
  cgColdStarting.value = true
  cgColdStartMsg.value = ''
  try {
    // 驱动就绪状态机直至 ready(共享 driveBaselineReady; initGit=true 按钮点击
    // 即授权: 非 git 工作目录自动初始化)。实时状态经 onProgress 显示。
    const r = await semanticAssetService.driveBaselineReady((s) => {
      const st = s?.state ?? ''
      const extra = s?.taskId ? ` (任务 ${s.taskId}${s.taskType ? '/' + s.taskType : ''})` : ''
      cgColdStartMsg.value = `状态: ${st}${extra} …`
    })
    if (r?.state === 'ready') {
      cgColdStartMsg.value = `状态: ready (任务 ${(r?.mountedTaskIds ?? []).join(',') || r?.taskId})`
    }
    void loadCgStatus()
  } catch (e: any) {
    cgColdStartMsg.value = e?.message || String(e)
  } finally {
    cgColdStarting.value = false
  }
}
async function setCgMode(m: 'on' | 'off' | 'auto') {
  cgSaving.value = true
  try {
    if (await semanticAssetService.setCodegraphMode(m)) void loadCgStatus()
  } finally {
    cgSaving.value = false
  }
}
onMounted(() => { void loadCgStatus() })
</script>

<template>
  <div class="p-5 space-y-4">
    <PageHeader
      :title="t('config.title')"
      :desc="t('config.desc')"
    />

    <!-- 子 tab 导航 -->
    <div class="flex flex-wrap gap-1.5">
      <button
        v-for="tb in TABS"
        :key="tb.key"
        class="btn !py-1.5 !px-4 !text-xs"
        :class="activeTab === tb.key ? 'btn-primary' : 'btn-ghost'"
        @click="activeTab = tb.key"
      >{{ t(tb.label) }}</button>
    </div>

    <!-- ═══ tab: 其他配置(其他 + 资产锁 + CodeGraph 同属此 tab, 分散两处 v-show) ═══ -->
    <div v-show="activeTab === 'other'" class="space-y-4">
      <div class="panel overflow-hidden">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <Cog6ToothIcon class="w-4 h-4 text-ctp-lavender" />{{ t('config.otherConfig') }}
          </span>
        </div>
        <div class="p-3 space-y-3 text-xs">
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

    <!-- ═══ tab: Architect 实例设置(模型) ═══ -->
    <div v-show="activeTab === 'instance'">
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
            @click="toggleAddManual"
          >
            <PlusIcon class="w-3.5 h-3.5" />{{ t('config.llm.addManual') }}
          </button>
          <button
            v-if="Object.keys(capProfiles).length"
            class="btn !py-1 !px-3 !text-xs text-ctp-red"
            :title="t('config.llm.clearProfilesTip')"
            @click="clearAllProfiles"
          >
            <TrashIcon class="w-3.5 h-3.5" />{{ t('config.llm.clearProfiles') }}
          </button>
        </span>
      </div>
      <div class="p-3 text-xs space-y-2">
        <div class="text-[11px] text-ctp-overlay0">{{ t('config.llm.desc') }}</div>
        <div
          v-if="capBusy"
          class="text-[10px] font-mono"
          :class="!capGateTicked ? 'text-ctp-overlay0'
                  : capGateStatus ? 'text-ctp-yellow' : 'text-ctp-red'"
          title="探测闸门: 全局互斥串行, 完成后按钮自动恢复"
        >
          <template v-if="!capGateTicked">
            ⏳ 正在查询闸门状态…
          </template>
          <template v-else-if="capGateStatus">
            ⏳ 能力探测中: {{ capGateStatus.running ? gateModelName(capGateStatus.running) : '等待闸门…' }}<span
              v-if="capGateStatus.queue.length"
            >(排队 {{ capGateStatus.queue.length }}: {{ capGateStatus.queue.map(gateModelName).join('、') }})</span>
          </template>
          <template v-else>
            ⚠ 闸门状态不可达——{{ capGateLastError || '网络/代理失败' }}
          </template>
        </div>
        <div v-if="importMsg" class="chip bg-ctp-green/15 text-ctp-green">{{ importMsg }}</div>
        <div v-if="importError" class="chip bg-ctp-red/15 text-ctp-red">{{ importError }}</div>

        <form
          v-if="showAddManual && !editingManualId"
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
          <div class="flex justify-end gap-2">
            <button
              type="submit"
              class="btn btn-primary !px-3 !py-1 !text-xs"
              :disabled="addingManual || !manualForm.name || !manualForm.model"
            >{{ t('config.llm.addManual') }}</button>
            <button
              type="button"
              class="btn btn-ghost !px-3 !py-1 !text-xs"
              @click="resetManualForm(); showAddManual = false"
            >{{ t('common.cancel') }}</button>
          </div>
        </form>

        <div
          v-if="!llmModels.length"
          class="text-[11px] text-ctp-overlay0 py-3 text-center"
        >{{ t('config.llm.noModels') }}</div>

        <div class="divide-y divide-ctp-surface0">
          <template v-for="m in llmModels" :key="m.id">
            <!-- 编辑态: 就地切换为编辑框(不跳顶部表单) -->
            <form
              v-if="editingManualId === m.id"
              class="py-2 space-y-2"
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
              <div class="flex justify-end gap-2">
                <button
                  type="submit"
                  class="btn btn-primary !px-3 !py-1 !text-xs"
                  :disabled="addingManual || !manualForm.name || !manualForm.model"
                >{{ t('config.llm.saveManual') }}</button>
                <button
                  type="button"
                  class="btn btn-ghost !px-3 !py-1 !text-xs"
                  @click="resetManualForm"
                >{{ t('common.cancel') }}</button>
              </div>
            </form>
            <div v-else class="flex items-center gap-3 py-2">
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
            <!-- 固定槽位(防 UI 乱动): 测评 chip 恒渲染定宽 / 连通状态格恒渲染定宽 / 按钮组恒在 -->
            <div class="relative shrink-0">
              <span
                class="chip !text-[10px] font-mono w-[96px] justify-center cursor-help"
                :class="evalChipState(m).cls"
                :title="evalChipState(m).title"
                @mouseenter="openEvalPanel(m.id, $event)"
                @mouseleave="scheduleEvalClose"
              >{{ evalChipState(m).text }}</span>
              <!-- 详情浮层(Q1A: 六维分数+准入+档位调整集中一处; absolute 零布局影响;
                   位于测评 chip 左侧; 视口下半部自动向上展开防溢出;
                   500ms 延迟关闭 + × 主动关闭兜底) -->
              <div
                v-if="capProfiles[m.id] && openEvalId === m.id"
                class="absolute right-full mr-1.5 z-30 w-[360px] rounded-md border border-ctp-surface0 bg-ctp-base shadow-md p-2.5 text-[10px] space-y-1.5 text-left"
                :class="openEvalUp ? 'bottom-0' : 'top-0'"
                @mouseenter="keepEvalPanel(m.id)"
                @mouseleave="scheduleEvalClose"
              >
                <div class="flex items-center justify-between gap-2">
                  <span class="font-mono text-ctp-subtext1">测评分数</span>
                  <button
                    type="button"
                    class="w-4 h-4 leading-none rounded text-ctp-overlay1 hover:text-ctp-red hover:bg-ctp-surface0"
                    title="关闭浮层"
                    @click="closeEvalPanel"
                  >×</button>
                </div>
                <div class="font-mono text-ctp-subtext0">
                  综合
                  <span
                    class="font-bold"
                    :class="Number(capProfiles[m.id].caps?.probeScore) >= 0.90 ? 'text-ctp-green'
                            : Number(capProfiles[m.id].caps?.probeScore) >= 0.75 ? 'text-ctp-teal'
                            : Number(capProfiles[m.id].caps?.probeScore) >= 0.60 ? 'text-ctp-yellow'
                            : 'text-ctp-peach'"
                  >{{ capProfiles[m.id].caps?.probeScore ?? '—' }}</span>
                  · 工具 {{ capProfiles[m.id].caps?.toolCallRate ?? '—' }} ·
                  JSON {{ capProfiles[m.id].caps?.jsonRate ?? '—' }} ·
                  指令 {{ capProfiles[m.id].caps?.instructionScore ?? '—' }}
                </div>
                <div class="font-mono text-ctp-subtext0">
                  需求 {{ capProfiles[m.id].caps?.requirementScore ?? '—' }} ·
                  架构 {{ capProfiles[m.id].caps?.archScore ?? '—' }} ·
                  模块 {{ capProfiles[m.id].caps?.moduleScore ?? '—' }}
                </div>
                <div class="font-mono text-ctp-subtext0">
                  问询 {{ capProfiles[m.id].caps?.inquiryScore ?? '—' }} ·
                  路由 {{ capProfiles[m.id].caps?.routingScore ?? '—' }}
                </div>
                <div class="border-t border-ctp-surface0 pt-1 space-y-1">
                  <div class="flex items-center justify-between gap-2">
                    <span class="font-mono text-ctp-subtext1">执行策略（T0 直通车 / T1 预拆 / T2 步骤补偿）</span>
                    <select
                      class="bg-ctp-surface0 text-[10px] rounded px-1 py-0.5 text-ctp-subtext0"
                      :value="capProfiles[m.id].tier"
                      title="执行策略档位——与评分解耦: 默认按映射区间建议, 手动调整优先且不被探测覆盖"
                      @change="setManualTier(m, +($event.target as HTMLSelectElement).value)"
                    >
                      <option v-for="i in 3" :key="i" :value="i - 1">{{ tierLabel(i - 1) }}</option>
                    </select>
                  </div>
                  <div class="text-ctp-overlay0">
                    默认映射: ≥0.90→T0 / ≥0.52→T1 / 其余→T2（非硬性绑定, 手动调整优先）
                  </div>
                </div>
                <!-- 语义资产解析(独立探测独立参数, 2026-10-03: 与综合档分离) -->
                <div class="border-t border-ctp-surface0 pt-1 space-y-1">
                  <div class="flex items-center justify-between gap-2">
                    <span class="font-mono text-ctp-subtext1">资产解析策略（编号/自由/构链 · 独立探测）</span>
                    <div class="flex items-center gap-1">
                      <select
                        class="bg-ctp-surface0 text-[10px] rounded px-1 py-0.5 text-ctp-subtext0"
                        :value="capProfiles[m.id].asset?.mode ?? ''"
                        title="归纳策略参数(手动覆盖优先于探测; 空值=按探测档案)"
                        @change="setAssetPolicy(m, ($event.target as HTMLSelectElement).value)"
                      >
                        <option value="">按探测档案</option>
                        <option value="numbered">编号引用</option>
                        <option value="free">自由归纳</option>
                        <option value="structural">结构化构链</option>
                      </select>
                      <button
                        class="btn !py-0 !px-2 !text-[10px]"
                        :disabled="!!assetProbing[m.id] || capBusy"
                        @click="assetProbe(m)"
                      >{{ assetProbing[m.id] || '探测' }}</button>
                    </div>
                  </div>
                  <div v-if="capProfiles[m.id].asset" class="font-mono text-ctp-subtext0">
                    {{ assetPolicyText(capProfiles[m.id].asset) }}
                  </div>
                </div>
                <div class="font-mono text-ctp-subtext0">
                  <span
                    v-if="capProfiles[m.id].caps?.compensationRate != null"
                  >补偿复核 {{ Math.round(capProfiles[m.id].caps.compensationRate * 100) }}% · </span><span
                    v-if="capProfiles[m.id].structured"
                    class="text-ctp-teal"
                  >structured ✓</span>
                </div>
                <div
                  class="text-ctp-subtext0"
                  :class="admissionLevel(m) === 'insufficient' ? 'text-ctp-red' : ''"
                >{{ admissionNote(m) || '准入: pass' }}</div>
                <div class="text-ctp-overlay0">{{ historyText(capProfiles[m.id]) }}</div>
              </div>
            </div>
            <span
              class="text-[10px] font-mono w-[150px] shrink-0 truncate text-right"
              :class="llmProbing[m.id]?.startsWith('✓') ? 'text-ctp-green'
                      : llmProbing[m.id] ? 'text-ctp-red' : ''"
              :title="llmProbing[m.id] || ''"
            >{{ llmProbing[m.id] || '' }}</span>
            <button
              class="btn !py-0 !px-2 !text-[10px]"
              :class="{ 'opacity-50 cursor-not-allowed': capBusy }"
              :disabled="capBusy"
              :title="t('config.llm.capProbeTip')"
              @click="capabilityProbe(m)"
            >{{ t('config.llm.capProbe') }}</button>
            <button
              class="btn !py-0 !px-2 !text-[10px]"
              @click="probeLlm(m)"
            >{{ t('config.executors.modelProbe') }}</button>
            <button
              class="btn !py-0.5 !px-2 !text-[11px]"
              :title="m.source === 'imported' ? t('config.llm.editImported') : t('config.llm.editManual')"
              @click="startEditManual(m)"
            >
              <PencilSquareIcon class="w-3 h-3" />{{ t('config.llm.editManualBtn') }}
            </button>
            <button
              class="btn !py-0.5 !px-2 !text-[11px] text-ctp-red"
              :title="m.source === 'imported' ? t('config.llm.unlinkImported') : t('config.llm.deleteManual')"
              @click="removeModel(m)"
            >
              <TrashIcon class="w-3 h-3" />{{ m.source === 'imported' ? t('config.llm.unlinkBtn') : t('config.llm.delete') }}
            </button>
            </div>
          </template>
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
    </div>

    <!-- ═══ tab: Coding Agent 执行器 ═══ -->
    <div v-show="activeTab === 'executors'" class="space-y-4">
      <AgentExecutorsCard />

    </div>



    <!-- ═══ tab: 资产助理(数据资产·语义分析) + 轻任务模型(编排侧) ═══ -->
    <div v-show="activeTab === 'roleModels'">
    <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <AdjustmentsHorizontalIcon class="w-4 h-4 text-ctp-mauve" />{{ t('config.roles.title') }}
        </span>
        <button
          class="btn btn-xs btn-blue"
          :disabled="rolesSaving"
          @click="saveRoles"
        >
          {{ rolesSaving ? t('config.roles.saving') : (rolesSavedAt ? t('config.roles.saved') : t('config.roles.save')) }}
        </button>
      </div>
      <div class="divide-y divide-ctp-surface0">
        <div
          v-for="r in roles"
          :key="r.name"
          class="flex items-center gap-3 px-4 py-2.5 text-xs"
        >
          <span class="w-20 font-semibold text-ctp-text shrink-0">{{ roleLabel(r) }}</span>
          <span class="flex-1 text-[10px] leading-snug">
            <span class="text-ctp-overlay1">{{ roleNote(r) }}</span>
            <span
              v-if="roleTrigger(r)"
              class="ml-1 inline-block rounded bg-ctp-peach/15 px-1.5 py-px align-baseline text-ctp-peach"
            >⚡ {{ t('config.roles.triggerLabel') }}{{ roleTrigger(r) }}</span>
          </span>
          <select v-model="r.modelId" class="input !py-1 !px-2 !text-[11px] w-64 font-mono">
            <option value="">{{ t('config.roles.modelPlaceholder') }}</option>
            <option
              v-if="r.modelId && !llmModels.some((m) => m.id === r.modelId)"
              :value="r.modelId"
            >{{ r.modelId }}（{{ t('config.roles.modelMissing') }}）</option>
            <option v-for="m in llmModels" :key="m.id" :value="m.id">
              {{ m.name }}（{{ m.model }}@{{ m.url }}）
            </option>
          </select>
        </div>
      </div>
      <p class="px-4 pb-3 text-[10px] text-ctp-overlay0 leading-relaxed">
        {{ t('config.roles.hint') }}
      </p>
    </div>

    <!-- 轻任务模型(编码编排侧): 与资产助理分属两域 -->
    <div class="panel mt-4 overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <BoltIcon class="w-4 h-4 text-ctp-peach" />{{ t('config.lightTasks.title') }}
        </span>
        <button
          class="btn btn-xs btn-blue"
          :disabled="lightSaving"
          @click="saveLightTasks"
        >
          {{ lightSaving ? t('config.lightTasks.saving') : (lightSavedAt ? t('config.lightTasks.saved') : t('config.lightTasks.save')) }}
        </button>
      </div>
      <div class="divide-y divide-ctp-surface0">
        <div
          v-for="lt in lightTasks"
          :key="lt.key"
          class="flex items-center gap-3 px-4 py-2.5 text-xs"
        >
          <span class="w-20 font-semibold text-ctp-text shrink-0">{{ lt.label }}</span>
          <span class="flex-1 text-[10px] leading-snug text-ctp-overlay1">{{ lt.note }}</span>
          <select v-model="lt.modelId" class="input !py-1 !px-2 !text-[11px] w-64 font-mono">
            <option value="">{{ t('config.lightTasks.modelPlaceholder') }}</option>
            <option
              v-if="lt.modelId && !llmModels.some((m) => m.id === lt.modelId)"
              :value="lt.modelId"
            >{{ lt.modelId }}（{{ t('config.lightTasks.modelMissing') }}）</option>
            <option v-for="m in llmModels" :key="m.id" :value="m.id">
              {{ m.name }}（{{ m.model }}@{{ m.url }}）
            </option>
          </select>
        </div>
      </div>
      <p class="px-4 pb-3 text-[10px] text-ctp-overlay0 leading-relaxed">
        {{ t('config.lightTasks.hint') }}
      </p>
    </div>
    </div>

    <!-- ═══ tab: 其他配置(续)——符号源 ═══ -->
    <div v-show="activeTab === 'other'" class="space-y-4">

      <!-- 符号源(CodeGraph)开关：语义提取的符号数据来源 -->
      <div class="panel overflow-hidden">
      <div class="panel-header">
        <span class="flex items-center gap-2">
          <AdjustmentsHorizontalIcon class="w-4 h-4 text-ctp-teal" />{{ t('config.cg.title') }}
        </span>
        <span v-if="cgStatus" class="text-[11px] text-ctp-overlay1">
          <span :class="cgStatus.cli ? 'text-ctp-green' : 'text-ctp-peach'">{{ cgStatus.cli ? t('config.cg.cliOk') : t('config.cg.cliMissing') }}</span>
          <span v-if="cgStatus.cliPath" class="font-mono" :title="cgStatus.cliPath"> · {{ cgStatus.cliPath.split('/').slice(-1)[0] }}</span>
          <span class="mx-1 text-ctp-overlay0">·</span>
          <span class="text-ctp-overlay0">{{ { env: t('config.cg.srcEnv'), kv: t('config.cg.srcKv'), default: t('config.cg.srcDefault') }[cgStatus.source] }}</span>
          <span v-if="cgStatus.native?.nodes" class="text-ctp-overlay0"> · {{ t('config.cg.nativeNodes') }}: {{ cgStatus.native.nodes.toLocaleString() }}</span>
          <span v-if="cgStatus.mergeStats" class="text-ctp-overlay0 font-mono" :title="t('config.cg.hintAuto')">
            · ∪{{ (cgStatus.mergeStats.cgNodes ?? 0).toLocaleString() }} +{{ Math.max((cgStatus.mergeStats.cgNodes ?? 0) - (cgStatus.mergeStats.cgMapped ?? 0), 0).toLocaleString() }}<template v-if="cgStatus.mergeStats.lineDrift"> ⚠{{ cgStatus.mergeStats.lineDrift }}</template>
          </span>
          <span v-if="cgStatus.state?.stale" class="text-ctp-yellow"> · {{ t('config.cg.stale') }} ({{ cgStatus.state.staleCount }})</span>
        </span>
      </div>
      <div v-if="cgStatus?.state" class="px-4 py-2 flex items-center gap-2 text-[11px] border-t border-ctp-surface0">
        <span v-if="!cgStatus.state.lastHead" class="text-ctp-overlay0">{{ t('config.cg.baselineNone') }}</span>
        <span v-else-if="cgStatus.state.stale" class="text-ctp-yellow">
          {{ t('config.cg.baselineStale') }} <span class="font-mono">{{ cgStatus.state.lastHead.slice(0, 8) }}</span> → <span class="font-mono">{{ cgStatus.state.head.slice(0, 8) }}</span>
          <span v-if="cgStatus.state.staleCount"> ({{ t('config.cg.baselineFiles') }} {{ cgStatus.state.staleCount }})</span>
        </span>
        <span v-else class="text-ctp-green">{{ t('config.cg.baselineFresh') }} <span class="font-mono">{{ cgStatus.state.head.slice(0, 8) }}</span></span>
        <span v-if="cgStatus.state.dirty" class="text-ctp-overlay0"> · {{ t('config.cg.dirty') }} {{ cgStatus.state.dirty }}</span>
        <button
          v-if="cgStatus.state.lastHead && cgStatus.state.stale"
          class="btn !py-1 !px-3 !text-xs ml-auto"
          :disabled="cgSyncing"
          @click="runCgSync"
        >{{ cgSyncing ? t('config.cg.syncing') : t('config.cg.syncNow') }}</button>
      </div>
      <div v-if="cgStatus && !cgStatus.corePid" class="px-4 py-2 flex items-center gap-2 text-[11px] border-t border-ctp-surface0">
        <span class="text-ctp-peach">{{ t('config.cg.noCoreProject') }}</span>
        <button
          class="btn !py-1 !px-3 !text-xs ml-auto"
          :disabled="cgColdStarting"
          @click="runCgColdStart"
        >{{ cgColdStarting ? t('config.cg.coldStarting') : t('config.cg.coldStart') }}</button>
      </div>
      <p v-if="cgColdStartMsg" class="px-4 pb-2 text-[10px] text-ctp-overlay0 leading-relaxed">{{ cgColdStartMsg }}</p>
      <p v-if="cgStatus?.state?.stale" class="px-4 pb-2 text-[10px] text-ctp-overlay0 leading-relaxed">
        {{ t('config.cg.syncHint') }}
      </p>
      <div class="px-4 py-3 flex items-center gap-2">
        <button
          v-for="m in (['on', 'auto', 'off'] as const)" :key="m"
          class="btn !py-1 !px-3 !text-xs"
          :class="cgStatus?.mode === m ? 'btn-primary' : 'btn-ghost'"
          :disabled="cgSaving || cgStatus?.source === 'env'"
          @click="setCgMode(m)"
        >{{ t(`config.cg.mode${m[0].toUpperCase()}${m.slice(1)}`) }}</button>
        <span v-if="cgStatus?.source === 'env'" class="text-[10px] text-ctp-peach">{{ t('config.cg.envLocked') }}</span>
      </div>
      <p class="px-4 pb-3 text-[10px] text-ctp-overlay0 leading-relaxed">
        {{ cgStatus?.mode === 'off' ? t('config.cg.hintOff') : cgStatus?.mode === 'on' ? t('config.cg.hintOn') : t('config.cg.hintAuto') }}
      </p>
      </div>
    </div>
  </div>
</template>
