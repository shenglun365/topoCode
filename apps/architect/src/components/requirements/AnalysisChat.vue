<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { kindChipClass } from '@/services/semantic-kind-style'
import { useI18n } from 'vue-i18n'
import { DocumentTextIcon, ArrowPathIcon, PaperAirplaneIcon, ChatBubbleLeftRightIcon, PencilSquareIcon, SparklesIcon, BookOpenIcon, CheckIcon, QuestionMarkCircleIcon, ClipboardDocumentCheckIcon, ClipboardDocumentIcon, TrashIcon, CubeTransparentIcon, BoltIcon, AdjustmentsHorizontalIcon, ChevronDownIcon, ChevronRightIcon, StopIcon, ArrowTopRightOnSquareIcon, WrenchScrewdriverIcon, XMarkIcon, ExclamationCircleIcon } from '@heroicons/vue/24/outline'
import type { KbAnalysisTurn } from '@/services/kb-analysis-agent'
import type { AcceptanceFact, AcceptanceReportDetail, ContractItem } from '@/services/contract-service'
import type { NamingConvention } from '@/services/naming-service'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import TaskCard from '@/components/chat/TaskCard.vue'
import { apiPost } from '@/services/api-client'
import type { SemanticAsset } from '@/types'
import type { ToolTrailItem } from '@/composables/useChatProgress'
import { copyText } from '@/utils/clipboard'

const props = defineProps<{
  turns: KbAnalysisTurn[]
  busy: boolean
  /** 忙碌态动态文案(如「正在调用工具 kb.asset.search…」)；缺省用静态「知识库检索中…」。 */
  busyLabel?: string
  /** 本轮工具轨迹(tool_call/tool_result 驱动，useChatProgress 维护)；浮层展示。 */
  toolTrail?: ToolTrailItem[]
  /** 外部引用预填(组件「引用名称+ID」快捷按钮)：nonce 变化即把 text 追加进输入框。 */
  insertDraft?: { text: string; nonce: number } | null
  /** 对话标题(缺省「需求分析对话」；资产管理等复用场景可覆盖)。 */
  title?: string
  /** 头部标题可编辑: 悬停显示 手动修改/自动摘要 按钮(宿主接线保存/摘要)。 */
  editable?: boolean
  /** 自动摘要进行中(按钮转圈)。 */
  titleSummarizing?: boolean
  /** 绘图增强(IR→代码)：开启后 agent 经 diagram.build 工具生成语法正确的图。 */
  diagramSkill?: boolean
  /** 归档只读: 禁用输入与发送(读取/复制/提炼仍可用)。 */
  readOnly?: boolean
  /** 期望固化(🧾)：开启后 agent 把可验证期望固化为契约条目草稿。 */
  contractSkill?: boolean
  /** 是否显示 🧾 开关(仅需求方案对话显示；资产管理/工作台不显示)。 */
  showContractSkill?: boolean
  /** running 归属(S2): {role:'coding', executorId, status} 有活跃作业时非空。 */
  jobState?: { role: string; executorId?: string; status?: string; progress?: { toolCount?: number; msgCount?: number; at?: number } } | null
  /** 已绑定执行器 id(S2/S3): 空=未绑定——Coding 切换钮首击触发分配(bind-coding)。 */
  boundExecutorId?: string
  /** 执行器白名单模型名列表(≥2 时显示模型 chip)。 */
  executorModels?: string[]
  /** 当前会话模型(空=默认)。 */
  executorModel?: string
  /** v2 发送方向: ''=architect(缺省) | 'cline'(显式指派 subagent)。 */
  sendAgent?: string
  /** v2 agent 过滤器(all/architect/coding)。 */
  agentFilter?: 'all' | 'architect' | 'coding'
  /** v2 coding subagent 任务清单(arch_tasks, 倒序; TaskCard 渲染用)。 */
  tasks?: Array<Record<string, any>>
}>()

const emit = defineEmits<{
  send: [text: string]
  'set-agent': [id: string]
  'agent-filter': [v: 'all' | 'architect' | 'coding']
  'task-confirm': [taskId: string]
  'task-cancel': [taskId: string]
  'task-executor': [p: { taskId: string; executorType: string }]
  'local-cmd': [name: string]
  'bind-coding': []
  'set-model': [model: string]
  rename: [title: string]
  'summarize-title': []
  answers: [answers: Record<string, string>]
  'confirm-draft': []
  'delete-turn': [index: number]
  'feed-turn': [p: { index: number; id?: string; summarize?: boolean }]
  'refresh-asset': [assetId: string]
  'toggle-diagram-skill': [enabled: boolean]
  'toggle-contract-skill': [enabled: boolean]
  'contract-confirm': [id: string]
  'contract-delete': [id: string]
  'contract-edit-save': [id: string, patch: Record<string, unknown>]
  'job-accept': [meta: Record<string, any>]
  'job-resume': []
  'guard-repair': [p: { index: number; meta: Record<string, any>; action: string }]
  'spec-apply': [p: { index: number; payload: Record<string, unknown> }]
  'convention-confirm': [id: string]
  'convention-ignore': [id: string]
  'goto-acceptance': []
  stop: []
}>()

// ── 头部标题行内编辑 ──
const editingTitle = ref(false)
const titleDraft = ref('')

/** 资产引用点击 → 联动资产地图(图谱节点/资产卡)。宿主页面监听 arch:open-asset。 */
function openAssetRef(id: string) {
  window.dispatchEvent(new CustomEvent('arch:open-asset', { detail: id }))
}

// ── 系统守卫卡: 指令点击上抛(修复执行/本地渲染由宿主 dock 完成) ──
const guardBusyIdx = ref(-1)
function onGuardAction(index: number, s: { action: string; label: string }) {
  if (guardBusyIdx.value >= 0) return
  guardBusyIdx.value = index
  try {
    emit('guard-repair', {
      index,
      meta: props.turns[index]?.meta || {},
      action: s.action,
    })
  } finally {
    setTimeout(() => { guardBusyIdx.value = -1 }, 800)
  }
}

// ── S3 投喂门: 消息级「转达 coding」(dock 执行 POST /feed, 结果本地消息) ──
const feedBusyIdx = ref(-1)

// ── 指令符号 chips: 本地提示/守卫/系统消息中出现的 /指令 渲染为标签, 点击填入对话框 ──
const CMD_TOKENS = ['/执行', '/确认执行', '/定稿', '/继续', '/diff', '/调整']
function cmdChipsOf(text: string): string[] {
  return CMD_TOKENS.filter((c) => (text || '').includes(c))
}

// ── 规约 JSON 识别(字段签名): 「写入需求」按钮的显示条件与载荷提取 ──
const SPEC_FIELDS = [
  'title', 'requirementMd', 'designMd', 'allowedScope', 'allowedScopeMd',
  'forbiddenScope', 'forbiddenScopeMd', 'acceptance', 'acceptanceMd',
  'assessmentMd', 'estMin', 'priority',
]
function parseSpecPayload(content: string): Record<string, unknown> | null {
  if (!content) return null
  const fences = [...content.matchAll(/```json\s*(\{[\s\S]*?})\s*```/g)]
  for (const f of fences) {
    try {
      const obj = JSON.parse(f[1])
      if (obj && typeof obj === 'object') {
        const hits = SPEC_FIELDS.filter((k) => k in obj).length
        if (hits >= 3) return obj
      }
    } catch { /* 下一个围栏 */ }
  }
  return null
}
function specPayloadOf(index: number): Record<string, unknown> | null {
  // 草稿卡(meta.specDraft, 系统确定性提取)优先于正文围栏识别
  const meta = props.turns[index]?.meta as any
  if (meta?.kind === 'specDraft' && meta?.payload && typeof meta.payload === 'object') {
    return meta.payload
  }
  return parseSpecPayload(props.turns[index]?.content || '')
}
const specBusyIdx = ref(-1)
function onSpecApply(index: number) {
  if (specBusyIdx.value >= 0) return
  const payload = specPayloadOf(index)
  if (!payload) return
  specBusyIdx.value = index
  try {
    emit('spec-apply', { index, payload })
  } finally {
    setTimeout(() => { specBusyIdx.value = -1 }, 800)
  }
}

/** 阶段标注配色(设计/实现/评估/验收——消息级工具推导, 非会话分类)。 */
function stageClass(stage: string) {
  if (stage === 'design') return 'bg-ctp-peach/15 text-ctp-peach'
  if (stage === 'implement') return 'bg-ctp-sky/15 text-ctp-sky'
  if (stage === 'evaluate') return 'bg-ctp-yellow/15 text-ctp-yellow'
  return 'bg-ctp-green/15 text-ctp-green'
}
function startTitleEdit() {
  titleDraft.value = props.title || ''
  editingTitle.value = true
}
function onTitleInput(e: Event) { titleDraft.value = (e.target as HTMLInputElement).value }
function commitTitleEdit() {
  if (!editingTitle.value) return
  editingTitle.value = false
  const t = titleDraft.value.trim()
  if (t && t !== props.title) emit('rename', t)
}

const { t } = useI18n()
const input = ref('')
const inputRef = ref<HTMLTextAreaElement | null>(null)

// ---- 工具轨迹浮层（防信息过载：默认收起，点击展开；回合结束/busy 清空自动关闭）----
const trailOpen = ref(false)
watch(() => props.busy, (b) => { if (!b) trailOpen.value = false })

// ---- 外部引用预填：nonce 变化 → 追加进输入框并聚焦(用户可补充问题后再发送) ----
watch(() => props.insertDraft?.nonce ?? 0, (n) => {
  if (!n) return
  const text = props.insertDraft?.text ?? ''
  if (!text) return
  input.value = input.value ? `${input.value} ${text}` : text
  void nextTick(() => {
    inputRef.value?.focus()
    manualHeight = false
    autoResize()
    const el = inputRef.value
    if (el) el.selectionStart = el.selectionEnd = el.value.length
  })
})
const scrollRef = ref<HTMLElement | null>(null)
const answers = reactive<Record<string, string>>({})

watch(
  () => props.turns.length,
  async () => {
    await nextTick()
    scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' })
  },
)
watch(
  () => props.turns,
  (turns) => {
    const q = turns[turns.length - 1]?.questions
    if (q) q.forEach((item) => { if (!(item.key in answers)) answers[item.key] = item.answer ?? '' })
  },
  { deep: true },
)

// ── v2 统一会话: agent 过滤 tab(纯 UI 过滤, 不切数据源) ──
const AGENT_TABS: Array<{ id: 'all' | 'architect' | 'coding'; label: string }> = [
  { id: 'all', label: '全部' },
  { id: 'architect', label: 'architect' },
  { id: 'coding', label: 'coding' },
]
function setAgentTab(v: 'all' | 'architect' | 'coding') {
  emit('agent-filter', v)
}
/** v2 发送方向选择(@architect/@cline): 菜单本地, 值上抛宿主。 */
const agentMenuOpen = ref(false)
const AGENT_PICKS: Array<{ id: string; label: string; desc: string }> = [
  { id: '', label: '@architect', desc: '外循环对话(缺省)' },
  { id: 'cline', label: '@cline', desc: '指派 coding subagent(无活跃任务时由 architect 出任务卡)' },
]
function pickSendAgent(id: string) {
  agentMenuOpen.value = false
  emit('set-agent', id)
}

/** 任务卡定位: meta.taskId → 最新任务行(状态实时)。 */
function taskById(id?: string) {
  if (!id) return null
  return (props.tasks || []).find((t) => t.id === id) || null
}

// ── 模型 chip: 随选随生效(下次执行; 进行中作业模型已固化) ──
const modelMenuOpen = ref(false)
function onModelClick() {
  modelMenuOpen.value = !modelMenuOpen.value
}
function pickModel(m: string) {
  modelMenuOpen.value = false
  if (m !== (props.executorModel || '')) emit('set-model', m)
}

function send() {
  if (!input.value.trim()) return
  if (props.busy) return
  // 本地命令拦截(绘图/方案/摘要/提炼/归档): 组件内或上抛宿主执行, 不发后端
  const local = matchLocalCmd(input.value)
  if (local) {
    runLocalCmd(local)
    input.value = ''
    cmdMenuOpen.value = false
    resetInputHeight()
    return
  }
  emit('send', input.value.trim())
  input.value = ''
  cmdMenuOpen.value = false
  resetInputHeight()
  nextTick(() => scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' }))
}

/** 本地命令(前端拦截, 不发后端): 会话操作/状态切换——与工具条按钮同动作。 */
const LOCAL_CMD_LIST = [
  { name: '绘图', desc: '切换绘图增强(IR→代码)' },
  { name: '方案', desc: '预填方案生成指令' },
  { name: '摘要', desc: '生成会话标题与摘要' },
  { name: '提炼', desc: '提炼会话为数据资产' },
  { name: '归档', desc: '结束会话(有可提炼内容时提示)' },
  { name: '引导', desc: '显示会话使用引导(本地提示)' },
]
const cmdMenuOpen = ref(false)
const cmdFilter = computed(() => {
  const v = input.value.trim()
  if (!v.startsWith('/')) return []
  const q = v.slice(1).toLowerCase()
  return LOCAL_CMD_LIST.filter((c) => c.name.toLowerCase().startsWith(q))
})
/** 精确命中本地命令(拦截: 本地执行, 不发后端)。 */
function matchLocalCmd(v: string): string | null {
  const t = v.trim()
  if (!t.startsWith('/')) return null
  const name = t.slice(1)
  return LOCAL_CMD_LIST.some((c) => c.name === name) ? name : null
}
watch(cmdFilter, (list) => { cmdMenuOpen.value = list.length > 0 && input.value.trim().startsWith('/') })
function pickCmd(name: string) {
  input.value = `/${name}`
  cmdMenuOpen.value = false
  inputRef.value?.focus()
}
function onCmdMenuKeydown(e: KeyboardEvent) {
  if (!cmdMenuOpen.value) return
  if (e.key === 'Escape') { cmdMenuOpen.value = false; e.preventDefault() }
  else if (e.key === 'Enter' && cmdFilter.value.length === 1) {
    input.value = `/${cmdFilter.value[0].name}`
    cmdMenuOpen.value = false
    e.preventDefault()
  }
}
/** 本地命令分发: 绘图/方案在组件内执行; 摘要/提炼/归档上抛宿主(与工具条同动作)。 */
function runLocalCmd(name: string) {
  if (name === '绘图') {
    emit('toggle-diagram-skill', !props.diagramSkill)
  } else if (name === '方案') {
    fillExtractPlan()
  } else {
    emit('local-cmd', name)
  }
}

const MIN_ROWS = 2
const MAX_ROWS = 6
/** 读取行高与上下 padding(用于行数↔像素换算)。 */
function inputMetrics(el: HTMLTextAreaElement) {
  const cs = getComputedStyle(el)
  return {
    lineH: parseFloat(cs.lineHeight) || 16,
    pad: (parseFloat(cs.paddingTop) || 0) + (parseFloat(cs.paddingBottom) || 0),
  }
}
/** 用户拖拽把手进入手动高度模式(暂停自动伸缩)，发送后恢复。 */
let manualHeight = false
/** autoResize 施加高度时抑制 RO 回调(避免把自己的改动误判为手动拖拽)。 */
let roSuppress = false
let lastAppliedHeight = ''
/** 自适应高度：随内容行数伸缩，默认/最矮 2 行、最高 6 行，超出滚动；手动拖拽后交由用户控制(仍限 2~6 行)。 */
function autoResize() {
  const el = inputRef.value
  if (!el) return
  if (manualHeight) {
    // 手动模式：不改动用户拖出的高度，只维护滚动条
    el.style.overflowY = el.scrollHeight > el.clientHeight + 1 ? 'auto' : 'hidden'
    return
  }
  roSuppress = true
  const { lineH, pad } = inputMetrics(el)
  const min = lineH * MIN_ROWS + pad
  const max = lineH * MAX_ROWS + pad
  el.style.height = 'auto'
  const h = Math.min(Math.max(el.scrollHeight, min), max)
  el.style.height = `${h}px`
  lastAppliedHeight = `${h}px`
  el.style.overflowY = el.scrollHeight > max + 1 ? 'auto' : 'hidden'
}
/** 手动拖拽检测：高度变化非 autoResize 所施加 → 进入手动模式(越界钳制回 2~6 行)。 */
const inputResizeObserver = new ResizeObserver(() => {
  const el = inputRef.value
  if (!el) return
  if (roSuppress) { roSuppress = false; return }
  if (el.style.height === lastAppliedHeight) return
  manualHeight = true
  const { lineH, pad } = inputMetrics(el)
  const min = lineH * MIN_ROWS + pad
  const max = lineH * MAX_ROWS + pad
  const h = parseFloat(el.style.height) || 0
  if (h && (h < min || h > max)) {
    roSuppress = true
    lastAppliedHeight = `${Math.min(Math.max(h, min), max)}px`
    el.style.height = lastAppliedHeight
  }
  el.style.overflowY = el.scrollHeight > el.clientHeight + 1 ? 'auto' : 'hidden'
})
onMounted(() => {
  if (inputRef.value) {
    inputResizeObserver.observe(inputRef.value)
    autoResize()
  }
})
onUnmounted(() => inputResizeObserver.disconnect())
/** 发送后清空并回到默认两行高度(同时退出手动模式)。 */
function resetInputHeight() {
  manualHeight = false
  autoResize()
}
/** Enter 发送；Ctrl/Cmd+Enter 手动插入换行(保证各浏览器一致)。 */
function onInputKeydown(e: KeyboardEvent) {
  onCmdMenuKeydown(e)
  if (e.key !== 'Enter') return
  if (e.ctrlKey || e.metaKey) {
    e.preventDefault()
    const el = e.target as HTMLTextAreaElement
    const start = el.selectionStart
    const end = el.selectionEnd
    input.value = input.value.slice(0, start) + '\n' + input.value.slice(end)
    nextTick(() => {
      el.selectionStart = el.selectionEnd = start + 1
      autoResize()
    })
    return
  }
  e.preventDefault()
  send()
}

function submitAnswers() {
  emit('answers', { ...answers })
  Object.keys(answers).forEach((k) => delete answers[k])
}

/** 单条消息删除：DOM 弹窗确认后移除本地 turn(持久化删除由 workspace 处理)。 */
const deletePending = ref<number | null>(null)

function removeTurn(i: number) {
  if (props.busy) return
  const m = props.turns[i]
  if (!m) return
  deletePending.value = i
}

function confirmDeleteTurn() {
  const i = deletePending.value
  deletePending.value = null
  if (i === null) return
  emit('delete-turn', i)
}

function cancelDeleteTurn() {
  deletePending.value = null
}

// ---- 复制：整条消息按钮 + 选中即复制(监听 copy 事件) + 轻提示 ----
const copiedTurn = ref<number | null>(null)
const copiedTimer = ref<ReturnType<typeof setTimeout> | null>(null)
const toastVisible = ref(false)
const toastText = ref('')
let toastTimer: ReturnType<typeof setTimeout> | null = null

/** 一键复制整条消息(纯文本内容)。 */
async function copyTurn(i: number) {
  const m = props.turns[i]
  if (!m) return
  const ok = await copyText(m.content)
  if (ok) {
    copiedTurn.value = i
    if (copiedTimer.value) clearTimeout(copiedTimer.value)
    copiedTimer.value = setTimeout(() => { copiedTurn.value = null }, 1600)
    showToast(t('requirement.chat.copySuccess'))
  } else {
    showToast(t('requirement.chat.copyFailed'))
  }
}

/** 选中即复制：消息区内发生 copy 事件(快捷键/右键)时，提示已复制。 */
function onMsgCopy() {
  const sel = window.getSelection()
  const text = sel?.toString().trim() ?? ''
  if (text) showToast(t('requirement.chat.copySuccess'))
}


function showToast(text: string) {
  toastText.value = text
  toastVisible.value = true
  if (toastTimer) clearTimeout(toastTimer)
  toastTimer = setTimeout(() => { toastVisible.value = false }, 2000)
}

// ── 方案生成：预填指令进输入框(用户可补充后自行发送；与对话指令同路径) ──
const extractPlanPrompt = t('assetChat.extractPlan.prompt')
function fillExtractPlan() {
  input.value = input.value ? `${input.value} ${extractPlanPrompt}` : extractPlanPrompt
  void nextTick(() => {
    inputRef.value?.focus()
    const el = inputRef.value
    if (el) el.selectionStart = el.selectionEnd = el.value.length
  })
}

// ── 提案卡确认存入：finalize 入池(待执行)；按钮自带 reqId, 多提案各自独立确认 ──
const confirmingProposalId = ref('')
async function confirmProposal(m: KbAnalysisTurn) {
  const p = m.proposal
  if (!p || p.confirmed || confirmingProposalId.value) return
  confirmingProposalId.value = p.id
  try {
    const analysis = {
      ...(p.analysis ?? {}),
      implementationPath: p.analysis?.implementationPath || p.analysis?.designMd || '',
    }
    const row = await apiPost<Record<string, unknown>>(`/requirements/${p.id}/finalize`, { analysis })
    if (row && (row as any).id) {
      p.confirmed = true
      showToast(t('assetChat.extractPlan.confirmed'))
    } else {
      showToast(t('assetChat.extractPlan.confirmFailed'))
    }
  } catch (e: any) {
    // 透出门禁原因(如"方案为空, 请 /调整 补全")而非笼统失败
    const msg = e?.response?.data?.message || e?.message || ''
    showToast(msg ? `${t('assetChat.extractPlan.confirmFailed')}：${String(msg).slice(0, 120)}` : t('assetChat.extractPlan.confirmFailed'))
  } finally {
    confirmingProposalId.value = ''
  }
}

// ---- 推理内容(thinking)折叠展示 ----
const reasoningOpen = reactive<Record<number, boolean>>({})

function toggleReasoning(i: number) {
  reasoningOpen[i] = !reasoningOpen[i]
}

// ---- 语义数据资产卡片 ----
const expandedAssets = reactive<Record<string, boolean>>({})

function assetKey(turnIdx: number, assetIdx: number) {
  return `${turnIdx}-${assetIdx}`
}

function toggleAsset(i: number, ai: number) {
  const k = assetKey(i, ai)
  expandedAssets[k] = !expandedAssets[k]
}

function assetKindIcon(kind?: SemanticAsset['kind']) {
  if (kind === 'process') return BoltIcon
  if (kind === 'decision' || kind === 'state') return AdjustmentsHorizontalIcon
  if (kind === 'contract') return CubeTransparentIcon
  return CubeTransparentIcon
}

function assetKindLabel(kind?: SemanticAsset['kind']): string {
  return t(`requirement.chat.assetKind.${kind ?? 'asset'}`)
}

function assetSummary(a: SemanticAsset): string {
  const d = a.detail
  if (!d) return ''
  const parts: string[] = []
  if (d.fields?.length) parts.push(`${t('requirement.chat.assetFields')} ${d.fields.length}`)
  if (d.steps?.length) parts.push(`${t('requirement.chat.assetSteps')} ${d.steps.length}`)
  if (d.branches?.length) parts.push(`${t('requirement.chat.assetBranches')} ${d.branches.length}`)
  if (a.astRefs?.length) parts.push(`${a.astRefs.length} AST`)
  return parts.join(' · ')
}

function copyAsset(a: SemanticAsset) {
  const lines = [`${a.name} (${assetKindLabel(a.kind)})`, `ID: ${a.id}`, a.desc]
  if (a.astRefs?.length) {
    lines.push('')
    lines.push(...a.astRefs.slice(0, 10).map((r) => `${r.file}:L${r.startLine}-L${r.endLine} ${r.symbol}`))
  }
  void copyText(lines.join('\n')).then((ok) => showToast(ok ? t('requirement.chat.copySuccess') : t('requirement.chat.copyFailed')))
}

/** 资产是否可引用(active 且未标记需更新)。 */
function assetUsable(a: SemanticAsset): boolean {
  return a.status !== 'stale' && a.status !== 'deleted' && !a.needsUpdate
}

function onRefreshAsset(a: SemanticAsset) {
  if (props.busy) return
  emit('refresh-asset', a.id)
}

// ── 契约条目固化卡（🧾 期望固化） ─────────────────────────────

const contractEditOpen = reactive<Record<string, boolean>>({})
const contractEditText = reactive<Record<string, string>>({})

function contractStatusLabel(s?: string): string {
  return t(`requirement.chat.contractStatus.${s ?? 'draft'}`)
}

function contractStatusCls(s?: string): string {
  const map: Record<string, string> = {
    draft: 'bg-ctp-yellow/15 text-ctp-yellow',
    confirmed: 'bg-ctp-blue/15 text-ctp-blue',
    injected: 'bg-ctp-sky/15 text-ctp-sky',
    verifying: 'bg-ctp-mauve/15 text-ctp-mauve',
    accepted: 'bg-ctp-green/15 text-ctp-green',
    rejected: 'bg-ctp-red/15 text-ctp-red',
  }
  return map[s ?? 'draft'] ?? map.draft
}

function contractTargetText(c: ContractItem): string {
  const tgt = c.target ?? {}
  const t2 = [tgt.file, tgt.symbol].filter(Boolean).join('::')
  return t2 || t('requirement.chat.contractIntentOnly')
}

function contractBehaviorText(c: ContractItem): string {
  const b = c.behavior ?? {}
  const parts: string[] = []
  if (b.steps?.length) parts.push(`${t('requirement.chat.assetSteps')} ${b.steps.length}`)
  if (b.branches?.length) parts.push(`${t('requirement.chat.assetBranches')} ${b.branches.length}`)
  if (b.fields?.length) parts.push(`${t('requirement.chat.assetFields')} ${b.fields.length}`)
  if (c.zAxis?.length) parts.push(`Z ${c.zAxis.length}`)
  return parts.join(' · ')
}

/** 展开「修改」：把可编辑期望字段序列化为 JSON 供设计者调整。 */
function openContractEdit(c: ContractItem) {
  if (contractEditOpen[c.id]) { contractEditOpen[c.id] = false; return }
  const editable = {
    target: c.target ?? {},
    behavior: c.behavior ?? {},
    zAxis: c.zAxis ?? [],
    acceptance: c.acceptance ?? {},
  }
  contractEditText[c.id] = JSON.stringify(editable, null, 2)
  contractEditOpen[c.id] = true
}

function saveContractEdit(c: ContractItem) {
  let parsed: Record<string, unknown>
  try {
    parsed = JSON.parse(contractEditText[c.id] || '{}')
  } catch {
    showToast(t('requirement.chat.contractEditInvalid'))
    return
  }
  contractEditOpen[c.id] = false
  emit('contract-edit-save', c.id, parsed)
}

function onContractConfirm(c: ContractItem) {
  if (props.busy) return
  emit('contract-confirm', c.id)
}

function onContractDelete(c: ContractItem) {
  if (props.busy) return
  emit('contract-delete', c.id)
}

function onConventionConfirm(c: NamingConvention) {
  if (props.busy) return
  emit('convention-confirm', c.id)
}

function onConventionIgnore(c: NamingConvention) {
  if (props.busy) return
  emit('convention-ignore', c.id)
}

function onGotoAcceptance() {
  if (props.busy) return
  emit('goto-acceptance')
}

/** 差异报告卡：L1/L2 通过率 + 待人工数 + 前三差异事实（事实/意见分区，判定在验收区块）。 */
function diffSummary(detail: AcceptanceReportDetail): { rate: string; awaiting: number; top: AcceptanceFact[] } {
  const facts = detail.facts ?? []
  const pass = facts.filter((f) => f.verdict === 'pass').length
  const rate = facts.length ? `${Math.round((pass / facts.length) * 100)}%` : '—'
  const awaiting = (detail.report?.summary?.awaitingHuman ?? 0)
    + facts.filter((f) => f.verdict === 'fail' || f.verdict === 'partial').length
  const top = facts
    .filter((f) => f.verdict !== 'pass')
    .slice(0, 3)
  return { rate, awaiting, top }
}

onUnmounted(() => {
  if (copiedTimer.value) clearTimeout(copiedTimer.value)
  if (toastTimer) clearTimeout(toastTimer)
})
</script>

<template>
  <div class="relative flex flex-col h-full min-h-0 border border-ctp-surface0 rounded-lg overflow-hidden bg-ctp-crust/30">
    <!-- 布局: 标题+状态区靠左(状态类动态增长只向右扩); 收件人组(ml-auto)恒靠右,
         位置不随会话生命周期变化 -->
    <div class="panel-header relative shrink-0">
      <span class="flex min-w-0 items-center gap-2">
        <ChatBubbleLeftRightIcon class="w-4 h-4 shrink-0 text-ctp-blue" />
        <input
          v-if="editingTitle"
          v-model="titleDraft"
          class="input w-full min-w-0 max-w-72 !px-1.5 !py-0.5 text-xs"
          @keydown.enter.prevent="commitTitleEdit"
          @keydown.esc="editingTitle = false"
          @blur="commitTitleEdit"
        >
        <span
          v-else
          class="group/t flex min-w-0 items-center gap-1"
        >
          <span class="min-w-0 truncate">{{ title ?? t('requirement.chat.title') }}</span>
          <span
            v-if="editable"
            class="hidden shrink-0 items-center gap-0.5 group-hover/t:flex"
          >
            <button
              class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface0 hover:text-ctp-blue"
              :title="t('session.actions.rename')"
              @click="startTitleEdit"
            >
              <PencilSquareIcon class="h-3 w-3" />
            </button>
            <button
              class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface0 hover:text-ctp-blue"
              :title="t('session.actions.summarize')"
              @click="emit('summarize-title')"
            >
              <SparklesIcon class="h-3 w-3" :class="titleSummarizing ? 'animate-pulse' : ''" />
            </button>
          </span>
        </span>
        <!-- 状态类(reqId/运行中/停止): 跟随标题向右增长, 不影响收件人组 -->
        <slot name="header-extra" />
      </span>
      <!-- v2 agent 过滤 tab(纯 UI 过滤, 不切数据源) + 模型 chip -->
      <span class="ml-auto flex shrink-0 items-center gap-1">
        <slot name="header-inline" />
        <span
          v-for="tab in AGENT_TABS"
          :key="tab.id"
          class="chip cursor-pointer select-none !text-[10px] transition-colors"
          :class="(props.agentFilter || 'all') === tab.id
            ? 'bg-ctp-sky/15 text-ctp-sky' : 'bg-ctp-surface0/60 text-ctp-overlay0 hover:text-ctp-subtext1'"
          :title="tab.id === 'coding' ? '只看 coding subagent 产出(任务回执/进展)' : tab.id === 'architect' ? '只看 architect 外循环对话' : '全部消息'"
          @click="setAgentTab(tab.id)"
        >{{ tab.label }}</span>
        <span
          v-if="props.boundExecutorId && (props.executorModels?.length ?? 0) >= 2"
          class="chip cursor-pointer select-none !text-[10px] font-mono transition-colors"
          :class="props.executorModel
            ? 'bg-ctp-green/15 text-ctp-green' : 'bg-ctp-surface0/60 text-ctp-overlay0 hover:text-ctp-subtext1'"
          :title="t('session.target.modelHint')"
          @click="onModelClick"
        >{{ props.executorModel || t('session.target.modelDefault') }}</span>
        <span
          v-if="modelMenuOpen && (props.executorModels?.length ?? 0) >= 2"
          class="absolute right-0 top-full z-50 mt-1 flex w-44 flex-col gap-0.5 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1 shadow-lg"
        >
          <button
            v-for="m in ['', ...(props.executorModels || [])]"
            :key="m || '__default__'"
            class="rounded px-2 py-1 text-left text-[11px] font-mono transition-colors"
            :class="m === (props.executorModel || '')
              ? 'bg-ctp-blue/15 text-ctp-blue' : 'text-ctp-subtext1 hover:bg-ctp-surface0'"
            @click="pickModel(m)"
          >{{ m || t('session.target.modelDefault') }}</button>
        </span>
      </span>
    </div>

    <!-- coding 视图执行进展行(SSE 实时, 不落库): 工具调用/消息计数 + 状态 -->
    <div
      v-if="props.jobState?.role === 'coding'"
      class="flex items-center gap-2 border-b border-ctp-surface0 bg-ctp-mantle/40 px-3 py-1 text-[10px] shrink-0"
    >
      <span
        class="inline-flex items-center gap-1"
        :class="props.jobState.status === 'waiting_input' ? 'text-ctp-peach' : 'text-ctp-blue animate-pulse'"
      >▶ {{ props.jobState.executorId || 'coding' }} · {{ props.jobState.status === 'waiting_input' ? '等待回复' : '执行中' }}</span>
      <span v-if="(props.jobState as any).progress" class="font-mono text-ctp-subtext0">
        ⚙ 工具 ×{{ (props.jobState as any).progress.toolCount ?? 0 }} · 消息 ×{{ (props.jobState as any).progress.msgCount ?? 0 }}
      </span>
      <span v-else class="text-ctp-overlay0">暂无进展数据(回合级事件到达时更新)</span>
      <span class="flex-1" />
      <span v-if="(props.jobState as any).progress?.at" class="text-ctp-overlay0 font-mono">{{ new Date((props.jobState as any).progress.at).toLocaleTimeString() }}</span>
    </div>

    <div
      ref="scrollRef"
      class="flex-1 min-h-[320px] overflow-auto p-3 space-y-2.5"
    >
        <div
          v-for="(m, i) in turns"
          :key="i"
          class="animate-fade-up flex items-start gap-2"
          @copy="onMsgCopy"
        >
        <div
          class="flex-1 min-w-0 rounded-lg rounded-tl-none px-3 py-2 text-xs bg-ctp-surface0/80"
          :class="m.role === 'user' ? 'ring-1 ring-ctp-sky/20' : ''"
        >
          <TaskCard
            v-if="m.meta?.kind === 'task_card' && taskById(m.meta.taskId)"
            :task="taskById(m.meta.taskId)!"
            class="mb-2"
            @confirm="(id: string) => emit('task-confirm', id)"
            @cancel="(id: string) => emit('task-cancel', id)"
            @set-executor="(id: string, ex: string) => emit('task-executor', { taskId: id, executorType: ex })"
          />
          <div class="flex items-center gap-1.5 mb-1">
            <svg
              v-if="m.role === 'user'"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              stroke-linejoin="round"
              class="w-4 h-4 text-ctp-sky"
            >
              <circle
                cx="12"
                cy="8"
                r="4"
              />
              <path d="M4.5 20a7.5 7.5 0 0 1 15 0" />
            </svg>
            <span
              v-else-if="(m as any).agent"
              class="chip !text-[9px] bg-ctp-peach/15 text-ctp-peach font-mono"
              :title="`coding subagent(${(m as any).agent})产出`"
            >⚙ {{ (m as any).agent }}</span>
            <span
              v-else
              class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve"
            >
              <BookOpenIcon class="w-2.5 h-2.5 inline" />{{ t('requirement.chat.kb') }}
            </span>
            <span
              v-if="m.stage"
              class="chip !text-[9px]"
              :class="stageClass(m.stage)"
            >{{ t(`session.stage.${m.stage}`) }}</span>
            <span class="flex-1" />
            <button
              v-if="m.reasoning"
              class="text-ctp-overlay0 hover:text-ctp-sky transition-colors p-0.5 flex items-center gap-1 text-[10px]"
              :title="t('requirement.chat.toggleReasoning')"
              @click="toggleReasoning(i)"
            >
              <svg
                class="w-3 h-3"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.8"
                stroke-linecap="round"
                stroke-linejoin="round"
              ><path d="M12 3a3 3 0 0 0-3 3v12a3 3 0 0 0 6 0V6a3 3 0 0 0-3-3z" /><path d="M19 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" /><path d="M5 14a2 2 0 1 0 0-4 2 2 0 0 0 0 4z" /></svg>
              <ChevronDownIcon
                v-if="reasoningOpen[i]"
                class="w-3 h-3"
              />
              <ChevronRightIcon
                v-else
                class="w-3 h-3"
              />
              {{ t('requirement.chat.reasoning') }}
            </button>
            <button
              class="text-ctp-overlay0 hover:text-ctp-blue transition-colors p-0.5"
              :title="t('requirement.chat.copyTurn')"
              :disabled="busy"
              @click="copyTurn(i)"
            >
              <ClipboardDocumentIcon
                v-if="copiedTurn !== i"
                class="w-3 h-3"
              />
              <CheckIcon
                v-else
                class="w-3 h-3 text-ctp-green"
              />
            </button>
            <button
              v-if="m.role === 'assistant' && !(m.meta?.kind)"
              class="text-ctp-overlay0 hover:text-ctp-mauve transition-colors p-0.5"
              :title="t('session.subs.feedHint')"
              :disabled="feedBusyIdx === i"
              @click="emit('feed-turn', { index: i, id: (m as any).id })"
            >
              <PaperAirplaneIcon class="w-3 h-3 rotate-90" />
            </button>
            <button
              v-if="m.role === 'assistant' && !(m.meta?.kind)"
              class="text-ctp-overlay0 hover:text-ctp-yellow transition-colors p-0.5"
              :title="t('session.subs.feedSummaryHint')"
              :disabled="feedBusyIdx === i"
              @click="emit('feed-turn', { index: i, id: (m as any).id, summarize: true })"
            >
              <SparklesIcon class="w-3 h-3" />
            </button>
            <button
              class="text-ctp-overlay0 hover:text-ctp-red transition-colors p-0.5"
              :title="t('requirement.chat.deleteTurn')"
              :disabled="busy"
              @click="removeTurn(i)"
            >
              <TrashIcon class="w-3 h-3" />
            </button>
          </div>

          <div
            v-if="m.reasoning && reasoningOpen[i]"
            class="mb-2 rounded-md border border-ctp-sky/20 bg-ctp-sky/5 px-2.5 py-2 text-[11px] text-ctp-subtext0 whitespace-pre-wrap max-h-64 overflow-auto"
          >
            <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-ctp-sky mb-1">
              <BookOpenIcon class="w-3 h-3" />{{ t('requirement.chat.reasoning') }}
            </div>
            {{ m.reasoning }}
          </div>
          <ChatMessageBlocks :content="m.content" />

          <!-- 指令符号 chips: 消息中出现的 /指令 → 点击填入对话框(所有助手消息,
               含系统回执「发送 /执行 …」等引导) -->
          <!-- 作业事件卡操作(生命周期重构): done→验收 / waiting_input→继续执行快捷 -->
          <div
            v-if="m.meta?.kind === 'job_done'"
            class="mt-2 flex items-center gap-2"
          >
            <button
              class="btn btn-xs btn-primary"
              @click="emit('job-accept', m.meta)"
            >{{ t('session.job.accept') }}</button>
            <span class="text-[10px] text-ctp-overlay0">{{ t('session.job.acceptHint') }}</span>
          </div>
          <div
            v-else-if="m.meta?.kind === 'job_input'"
            class="mt-2 flex items-center gap-2"
          >
            <button
              class="btn btn-xs"
              @click="emit('job-resume')"
            >{{ t('session.job.resume') }}</button>
            <span class="text-[10px] text-ctp-overlay0">{{ t('session.job.resumeHint') }}</span>
          </div>

          <!-- 规约 JSON 落库按钮(字段签名识别, 任何含载荷的助手消息) -->
          <div
            v-if="!m.meta?.kind && specPayloadOf(i)"
            class="mt-2 flex items-center gap-2"
          >
            <button
              class="btn btn-xs btn-primary"
              :disabled="specBusyIdx === i"
              title="按原文确定性落库为需求(零模型转写)"
              @click="onSpecApply(i)"
            >{{ specBusyIdx === i ? '…' : t('session.actions.applySpec') }}</button>
            <span class="text-[10px] text-ctp-overlay0">{{ t('session.actions.applySpecHint') }}</span>
          </div>

          <!-- 规约草稿卡(分级适配): 模型把规约写进正文未调工具 → 系统提取暂存;
               用户裁决: 写入需求(一键落库) / 继续对话调整(草稿自动注入下轮合并) -->
          <div
            v-else-if="m.meta?.kind === 'specDraft'"
            class="mt-2 rounded-lg border border-ctp-mauve/30 bg-ctp-mauve/5 px-2.5 py-2"
          >
            <div class="flex items-start gap-1.5 text-[11px] leading-relaxed text-ctp-subtext1">
              <DocumentTextIcon class="mt-0.5 h-3.5 w-3.5 shrink-0 text-ctp-mauve" />
              <div class="min-w-0 flex-1">
                <p>
                  📝 系统从回复中提取了完整规约草稿<code class="rounded bg-ctp-surface0 px-1 text-ctp-text">「{{ (m.meta.payload?.title as string) || '未命名' }}」</code>（尚未落库）。
                </p>
                <p class="mt-1 text-[10px] text-ctp-overlay0">
                  两选一：点「写入需求」确定性落库（零模型转写，编号由系统生成）；或继续对话补充调整——草稿会自动带入下一轮合并完善。
                </p>
              </div>
            </div>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <button
                class="btn btn-xs btn-primary"
                :disabled="specBusyIdx === i"
                title="按草稿确定性落库为需求(零模型转写)"
                @click="onSpecApply(i)"
              >{{ specBusyIdx === i ? '…' : t('session.actions.applySpec') }}</button>
              <span class="text-[10px] text-ctp-overlay0">落库后可 /定稿 → /执行</span>
            </div>
          </div>

          <!-- 系统守卫卡: 可点击指令(点击 → guard-repair 独立外循环), 说明在文字区 -->
          <div
            v-else-if="m.meta?.kind === 'guard'"
            :class="m.meta.resolved
              ? 'mt-2 rounded-lg border border-ctp-green/30 bg-ctp-green/5 px-2.5 py-2'
              : 'mt-2 rounded-lg border border-ctp-yellow/30 bg-ctp-yellow/5 px-2.5 py-2'"
          >
            <div class="flex items-start gap-1.5 text-[11px] leading-relaxed text-ctp-subtext1">
              <ExclamationCircleIcon
                class="mt-0.5 h-3.5 w-3.5 shrink-0"
                :class="m.meta.resolved ? 'text-ctp-green' : 'text-ctp-yellow'"
              />
              <div class="min-w-0 flex-1">
                <p v-if="m.meta.resolved">
                  ✅ 守卫拦截：回复中「{{ m.meta.claim }}」未经实际工具调用——系统已从正文规约<strong>代为落库</strong>，以下方回执编号为准。
                </p>
                <p v-else>
                  守卫拦截：回复中「{{ m.meta.claim }}」未经实际工具调用（需要
                  <code class="rounded bg-ctp-surface0 px-1 text-ctp-text">{{ m.meta.need }}</code> 佐证），该表述不成立。
                </p>
                <p v-if="m.meta.failedTry" class="mt-1 text-ctp-yellow/90">
                  该工具本回合已尝试但执行失败：{{ m.meta.toolError }}
                </p>
                <p class="mt-1 text-[10px] text-ctp-overlay0">
                  点击指令将走独立修复通道从原文提取真实内容落库；过程与结果仅本地展示，不进入对话上下文。
                </p>
                <p
                  v-if="m.meta.hasSpecJson || specPayloadOf(i)"
                  class="mt-1 text-[11px] text-ctp-blue/90"
                >
                  💡 检测到本条回复包含结构化的规约 JSON。若其内容符合你的预期，可直接点「{{
                    (m.meta.suggestions || []).find((x: any) => x.action === 'apply_json')?.label || '按原文落库'
                  }}」将其写入需求约束（确定性代码路径，不经模型转写）；若内容有偏差，请先在对话中指出修正点。
                </p>
              </div>
            </div>
            <div class="mt-1.5 flex flex-wrap items-center gap-1.5">
              <button
                v-for="s in (m.meta.suggestions || [])"
                :key="s.action"
                class="btn btn-xs"
                :class="s.action === 'correct' ? 'btn-ghost' : 'btn-primary'"
                :disabled="guardBusyIdx === i"
                :title="`点击执行：${s.label}`"
                @click="onGuardAction(i, s)"
              >{{ guardBusyIdx === i ? '…' : s.label }}</button>
            </div>
          </div>

          <div
            v-if="m.assets?.length"
            class="mt-2 space-y-1.5"
          >
            <div
              v-for="(a, ai) in m.assets"
              :key="a.id"
              class="border border-ctp-mauve/25 bg-ctp-mauve/5 rounded-lg overflow-hidden"
            >
              <div class="flex items-center gap-1.5 px-2 py-1.5">
                <component
                  :is="assetKindIcon(a.kind)"
                  class="w-3.5 h-3.5 text-ctp-mauve shrink-0"
                />
                <span class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve shrink-0">
                  {{ assetKindLabel(a.kind) }}
                </span>
                <span
                  class="text-[11px] font-medium text-ctp-text truncate cursor-pointer hover:text-ctp-blue"
                  :title="t('requirement.chat.assetOpen')"
                  @click="openAssetRef(a.id)"
                >{{ a.name }}</span>
                <span
                  v-if="a.needsUpdate || a.status === 'stale'"
                  class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                >{{ t('requirement.chat.assetNeedsUpdate') }}</span>
                <span
                  v-else-if="a.status === 'deleted'"
                  class="chip !text-[9px] bg-ctp-red/15 text-ctp-red shrink-0"
                >{{ t('requirement.chat.assetDeleted') }}</span>
                <span
                  v-else-if="a.change === 'modified'"
                  class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                >{{ t('requirement.chat.assetModified') }}</span>
                <span
                  v-else-if="a.change === 'added'"
                  class="chip !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0"
                >{{ t('requirement.chat.assetAdded') }}</span>
                <span class="flex-1" />
                <span class="text-[9px] text-ctp-overlay0 whitespace-nowrap">{{ assetSummary(a) }}</span>
                <button
                  v-if="!assetUsable(a)"
                  class="text-ctp-yellow hover:text-ctp-peach transition-colors p-0.5"
                  :title="t('requirement.chat.assetRefresh')"
                  :disabled="busy"
                  @click="onRefreshAsset(a)"
                >
                  <ArrowPathIcon class="w-3 h-3" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve transition-colors p-0.5"
                  :title="t('requirement.chat.assetCopy')"
                  @click="copyAsset(a)"
                >
                  <ClipboardDocumentIcon class="w-3 h-3" />
                </button>
                <button
                  class="text-ctp-overlay0 hover:text-ctp-mauve transition-colors p-0.5"
                  :title="t('requirement.chat.assetExpand')"
                  @click="toggleAsset(i, ai)"
                >
                  <ChevronDownIcon
                    v-if="expandedAssets[assetKey(i, ai)]"
                    class="w-3.5 h-3.5"
                  />
                  <ChevronRightIcon
                    v-else
                    class="w-3.5 h-3.5"
                  />
                </button>
              </div>
              <p class="px-2 pb-1.5 text-[10px] text-ctp-subtext0 line-clamp-2 whitespace-pre-wrap">
                {{ a.desc }}
              </p>
              <div
                v-if="expandedAssets[assetKey(i, ai)]"
                class="border-t border-ctp-mauve/15 px-2 py-1.5 space-y-1.5"
              >
                <div
                  v-if="a.detail?.fields?.length"
                  class="text-[10px] text-ctp-subtext0"
                >
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('requirement.chat.assetFields') }}</div>
                  <div
                    v-for="f in a.detail.fields"
                    :key="f.name"
                    class="pl-2"
                  ><span class="font-mono text-ctp-text">{{ f.name }}</span><span class="text-ctp-overlay0">: {{ f.type ?? '—' }}</span> {{ f.semantic ? `— ${f.semantic}` : '' }}</div>
                </div>
                <div
                  v-if="a.detail?.steps?.length"
                  class="text-[10px] text-ctp-subtext0"
                >
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('requirement.chat.assetSteps') }}</div>
                  <div
                    v-for="(s, si) in a.detail.steps"
                    :key="si"
                    class="pl-2"
                  >{{ s.order ?? si + 1 }}. {{ s.semantic }} <span v-if="s.astRefs?.length" class="text-ctp-overlay0">(@{{ s.astRefs[0].file }}:L{{ s.astRefs[0].startLine }})</span></div>
                </div>
                <div
                  v-if="a.detail?.branches?.length"
                  class="text-[10px] text-ctp-subtext0"
                >
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('requirement.chat.assetBranches') }}</div>
                  <div
                    v-for="(b, bi) in a.detail.branches"
                    :key="bi"
                    class="pl-2"
                  ><span class="font-mono text-ctp-text">if {{ b.condition ?? '?' }}</span> → {{ b.then ?? '—' }}<span v-if="b.else"> / else {{ b.else }}</span></div>
                </div>
                <div
                  v-if="a.astRefs?.length"
                  class="text-[10px] text-ctp-overlay0"
                >
                  <div class="font-medium text-ctp-mauve mb-0.5">{{ t('requirement.chat.astAnchor') }}</div>
                  <div
                    v-for="(r, ri) in a.astRefs.slice(0, 8)"
                    :key="ri"
                    class="pl-2 font-mono"
                  >{{ r.file }}:L{{ r.startLine }}-L{{ r.endLine }} <span class="text-ctp-subtext0">{{ r.symbol }}</span></div>
                </div>
              </div>
            </div>
          </div>

          <!-- 契约条目固化卡（🧾 期望固化：逐条确认/修改/删；判定动作在验收区块） -->
          <div
            v-if="m.contracts?.length"
            class="mt-2 space-y-1.5"
          >
            <div
              v-for="c in m.contracts"
              :key="c.id"
              class="border border-ctp-teal/25 bg-ctp-teal/5 rounded-lg overflow-hidden"
            >
              <div class="flex items-center gap-1.5 px-2 py-1.5">
                <span class="chip !text-[9px] shrink-0" :class="kindChipClass(c.kind)">
                  {{ t(`assetMgmt.kind.${c.kind}`) }} · {{ c.level }}
                </span>
                <span class="font-mono text-[10px] text-ctp-subtext0 shrink-0">{{ c.id }}</span>
                <span
                  v-if="c.intentOnly"
                  class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0"
                >{{ t('requirement.chat.contractIntentOnly') }}</span>
                <span
                  v-if="c.staleByFramework"
                  class="chip !text-[9px] bg-ctp-peach/15 text-ctp-peach shrink-0"
                >{{ t('requirement.chat.contractStale') }}</span>
                <span class="flex-1" />
                <span class="chip !text-[9px] shrink-0" :class="contractStatusCls(c.status)">
                  {{ contractStatusLabel(c.status) }}
                </span>
              </div>
              <div class="px-2 pb-1.5 space-y-1 text-[11px]">
                <div class="text-ctp-text">
                  <span class="text-[9px] uppercase tracking-wide text-ctp-overlay0">{{ t('requirement.chat.contractTarget') }}</span>
                  <span class="font-mono">{{ contractTargetText(c) }}</span>
                </div>
                <div v-if="contractBehaviorText(c)" class="text-ctp-subtext0">{{ contractBehaviorText(c) }}</div>
                <div
                  v-if="c.origin?.quote"
                  class="text-[10px] text-ctp-overlay0 border-l-2 border-ctp-teal/30 pl-1.5 italic"
                >「{{ c.origin.quote }}」
                </div>
                <div
                  v-for="(z, zi) in c.zAxis ?? []"
                  :key="zi"
                  class="text-[10px] text-ctp-subtext0"
                >Z[{{ z.category }}] {{ z.text }}
                </div>
                <div
                  v-if="c.acceptance?.criteria"
                  class="text-[10px] text-ctp-subtext0"
                >
                  <span class="text-ctp-overlay0">{{ t('requirement.chat.contractAcceptance') }}</span> {{ c.acceptance.criteria }}
                </div>
                <!-- 修改模式（仅 draft） -->
                <div v-if="contractEditOpen[c.id]" class="pt-1">
                  <textarea
                    v-model="contractEditText[c.id]"
                    rows="8"
                    class="input !text-[10px] font-mono"
                    :placeholder="t('requirement.chat.contractEditHint')"
                  />
                  <div class="flex gap-1.5 mt-1">
                    <button class="btn btn-xs btn-green" @click="saveContractEdit(c)">{{ t('common.save') }}</button>
                    <button class="btn btn-xs btn-ghost" @click="contractEditOpen[c.id] = false">{{ t('common.cancel') }}</button>
                  </div>
                </div>
                <!-- 操作（仅 draft：确认/修改/删——判定统一在验收区块） -->
                <div v-else-if="c.status === 'draft' && !busy" class="flex gap-1.5 pt-0.5">
                  <button class="btn btn-xs btn-green" @click="onContractConfirm(c)">
                    <CheckIcon class="w-3 h-3" />{{ t('requirement.chat.contractConfirm') }}
                  </button>
                  <button class="btn btn-xs btn-ghost" @click="openContractEdit(c)">{{ t('requirement.chat.contractEdit') }}</button>
                  <button class="btn btn-xs btn-ghost text-ctp-red" @click="onContractDelete(c)">
                    <TrashIcon class="w-3 h-3" />{{ t('requirement.chat.contractDelete') }}
                  </button>
                </div>
              </div>
            </div>
          </div>

          <!-- 命名规约归纳提议卡（agent 检测命名模式 → pending 提案；确认固化/忽略） -->
          <div
            v-if="m.conventions?.length"
            class="mt-2 space-y-1.5"
          >
            <div
              v-for="cv in m.conventions"
              :key="cv.id"
              class="border border-ctp-mauve/25 bg-ctp-mauve/5 rounded-lg overflow-hidden"
            >
              <div class="flex items-center gap-1.5 px-2 py-1.5">
                <BookOpenIcon class="w-3.5 h-3.5 text-ctp-mauve shrink-0" />
                <span class="chip !text-[9px] bg-ctp-mauve/15 text-ctp-mauve shrink-0">
                  {{ t('naming.tabConventions') }}
                </span>
                <span class="font-mono text-[10px] text-ctp-subtext0 shrink-0">{{ cv.id }}</span>
                <span class="flex-1" />
                <span class="chip !text-[9px] bg-ctp-yellow/15 text-ctp-yellow shrink-0">
                  {{ t('naming.status.pending') }}
                </span>
              </div>
              <div class="px-2 pb-1.5 space-y-1 text-[11px]">
                <div class="text-ctp-text">{{ cv.ruleText }}</div>
                <div class="flex flex-wrap items-center gap-1.5">
                  <span
                    v-for="s in cv.scenarios"
                    :key="s"
                    class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1"
                  >{{ t(`naming.scenario.${s}`) }}</span>
                </div>
                <p class="text-[10px] text-ctp-overlay0">{{ t('naming.proposeHint') }}</p>
                <div v-if="cv.status === 'pending' && !busy" class="flex gap-1.5 pt-0.5">
                  <button class="btn btn-xs btn-green" @click="onConventionConfirm(cv)">
                    <CheckIcon class="w-3 h-3" />{{ t('naming.confirmRule') }}
                  </button>
                  <button class="btn btn-xs btn-ghost" @click="onConventionIgnore(cv)">{{ t('naming.ignoreRule') }}</button>
                </div>
              </div>
            </div>
          </div>

          <!-- S5 需求提案卡（req.propose 产出：需求+方案+评估 → 前往需求方案） -->
          <div
            v-if="m.proposal"
            class="mt-2 border border-ctp-green/30 bg-ctp-green/5 rounded-lg overflow-hidden"
          >
            <div class="flex items-center gap-1.5 px-2 py-1.5">
              <SparklesIcon class="w-3.5 h-3.5 text-ctp-green shrink-0" />
              <span class="chip !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0">
                {{ t('assetChat.proposal.title') }}
              </span>
              <span class="font-mono text-[10px] text-ctp-subtext0 shrink-0">{{ m.proposal.id }}</span>
              <span class="text-xs font-medium truncate">{{ m.proposal.title }}</span>
              <span
                class="chip !px-1.5 !text-[9px] bg-ctp-surface0 text-ctp-subtext0 shrink-0"
              >{{ m.proposal.priority }}</span>
              <span class="flex-1" />
              <span
                v-if="m.proposal.confirmed"
                class="chip !px-1.5 !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0"
              >
                <CheckIcon class="w-3 h-3" />{{ t('assetChat.extractPlan.confirmedChip') }}
              </span>
              <button
                v-else
                class="btn btn-xs btn-green"
                :disabled="confirmingProposalId === m.proposal.id"
                :title="t('assetChat.extractPlan.confirmHint')"
                @click="confirmProposal(m)"
              >
                <CheckIcon class="w-3 h-3" />{{ confirmingProposalId === m.proposal.id ? t('assetChat.extractPlan.confirming') : t('assetChat.extractPlan.confirm') }}
              </button>
            </div>
            <div
              class="px-2 pb-2 text-[11px] text-ctp-subtext1 max-h-40 overflow-auto markdown-body"
              style="white-space: pre-wrap"
            >{{ (m.proposal.desc || '').slice(0, 600) }}{{ (m.proposal.desc || '').length > 600 ? '…' : '' }}</div>
          </div>

          <!-- A5 差异报告通知卡（验收触发后：摘要 + 前往验收；判定统一在验收区块） -->
          <div
            v-if="m.acceptance"
            class="mt-2 border border-ctp-sky/25 bg-ctp-sky/5 rounded-lg overflow-hidden"
          >
            <div class="flex items-center gap-1.5 px-2 py-1.5">
              <ClipboardDocumentCheckIcon class="w-3.5 h-3.5 text-ctp-sky shrink-0" />
              <span class="chip !text-[9px] bg-ctp-sky/15 text-ctp-sky shrink-0">
                {{ t('localAcceptance.tabTitle') }}
              </span>
              <span class="font-mono text-[10px] text-ctp-subtext0 shrink-0">{{ m.acceptance.report.id }}</span>
              <span
                v-if="m.acceptance.report.packageId"
                class="font-mono text-[10px] text-ctp-overlay0 shrink-0"
              >{{ m.acceptance.report.packageId }}</span>
              <span class="flex-1" />
              <button class="btn btn-xs btn-blue" @click="onGotoAcceptance">
                <ArrowTopRightOnSquareIcon class="w-3 h-3" />{{ t('requirement.chat.gotoAcceptance') }}
              </button>
            </div>
            <div class="px-2 pb-2 space-y-1.5 text-[11px]">
              <div class="flex items-center gap-3">
                <span class="text-ctp-subtext0">
                  L1/L2 {{ t('requirement.chat.passRate') }}:
                  <span class="font-medium text-ctp-text">{{ diffSummary(m.acceptance).rate }}</span>
                </span>
                <span class="text-ctp-subtext0">
                  {{ t('requirement.chat.awaitingHuman') }}:
                  <span class="font-medium" :class="diffSummary(m.acceptance).awaiting > 0 ? 'text-ctp-yellow' : 'text-ctp-green'">
                    {{ diffSummary(m.acceptance).awaiting }}
                  </span>
                </span>
              </div>
              <template v-if="diffSummary(m.acceptance).top.length">
                <div class="text-[10px] uppercase tracking-wide text-ctp-sky">{{ t('requirement.chat.topDiffs') }}</div>
                <div
                  v-for="(f, fi) in diffSummary(m.acceptance).top"
                  :key="f.id"
                  class="flex items-start gap-1.5"
                >
                  <span class="chip !text-[9px] bg-ctp-surface0 text-ctp-subtext1 shrink-0">{{ f.checkLayer }}</span>
                  <span
                    class="chip !text-[9px] shrink-0"
                    :class="f.verdict === 'fail' ? 'bg-ctp-red/15 text-ctp-red' : 'bg-ctp-yellow/15 text-ctp-yellow'"
                  >{{ t(`localAcceptance.${f.verdict}`) }}</span>
                  <span class="text-ctp-subtext0 break-all">{{ f.evidence?.detail || '—' }}</span>
                </div>
              </template>
              <p class="text-[10px] text-ctp-overlay0">{{ t('requirement.chat.acceptanceCardHint') }}</p>
            </div>
          </div>

          <div
            v-if="m.questions"
            class="mt-2 border border-ctp-blue/25 bg-ctp-blue/5 rounded-lg p-2 space-y-2"
          >
            <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-ctp-blue">
              <QuestionMarkCircleIcon class="w-3 h-3" />{{ t('requirement.chat.questions') }}
            </div>
            <div
              v-for="(q, qi) in m.questions"
              :key="q.key"
              class="space-y-1"
            >
              <label class="text-[11px] font-medium text-ctp-text">{{ qi + 1 }}. {{ q.label }}</label>
              <input
                v-if="q.type === 'text'"
                v-model="answers[q.key]"
                class="input !py-1 !text-xs"
                :placeholder="q.hint"
              >
              <div
                v-else-if="q.type === 'select' && q.options?.length"
                class="flex flex-wrap gap-1"
              >
                <button
                  v-for="o in q.options"
                  :key="o"
                  class="btn btn-xs"
                  :class="answers[q.key] === o ? 'btn-blue' : 'btn-ghost'"
                  @click="answers[q.key] = o"
                >
                  {{ o }}
                </button>
              </div>
              <p
                v-if="q.hint && q.type !== 'text'"
                class="text-[10px] text-ctp-overlay0"
              >
                {{ q.hint }}
              </p>
            </div>
            <button
              class="btn btn-sm btn-blue !py-1"
              :disabled="busy"
              @click="submitAnswers"
            >
              <CheckIcon class="w-3 h-3" />{{ t('requirement.chat.submitAnswers') }}
            </button>
          </div>

          <div
            v-if="m.formDraft"
            class="mt-2 border border-ctp-green/30 bg-ctp-green/5 rounded-lg p-2 space-y-1.5"
          >
            <div class="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-ctp-green">
              <ClipboardDocumentCheckIcon class="w-3 h-3" />{{ t('requirement.chat.draftTitle') }}
            </div>
            <p class="text-[11px] text-ctp-text font-medium">
              {{ m.formDraft.title }}
            </p>
            <div class="flex flex-wrap gap-1">
              <span class="chip bg-ctp-surface0 text-ctp-subtext1 text-[10px]">{{ t('requirement.assetScope') }}: {{ m.formDraft.assetScope.length }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1 text-[10px]">{{ t('requirement.basicMd') }}: {{ m.formDraft.basicMd.trim() ? '✓' : '—' }}</span>
              <span class="chip bg-ctp-surface0 text-ctp-subtext1 text-[10px]">{{ t('requirement.estMin') }}: {{ m.formDraft.estMin }}m</span>
            </div>
            <p
              v-if="m.formDraft.assessmentSummary"
              class="text-[10px] text-ctp-subtext1 line-clamp-2"
            >
              {{ m.formDraft.assessmentSummary }}
            </p>
            <p class="text-[10px] text-ctp-overlay0 line-clamp-2">
              {{ m.formDraft.implementationPath }}
            </p>
            <button
              class="btn btn-sm btn-green !py-1"
              :disabled="busy"
              @click="emit('confirm-draft')"
            >
              <CheckIcon class="w-3 h-3" />{{ t('requirement.chat.confirmDraft') }}
            </button>
          </div>
        </div>
      </div>

      <div
        v-if="busy"
        class="flex items-center gap-2 text-xs text-ctp-blue animate-pulse"
      >
        <ArrowPathIcon class="w-3.5 h-3.5 animate-spin" />{{ props.busyLabel || t('requirement.chat.thinking') }}
        <button
          v-if="toolTrail && toolTrail.length"
          class="chip bg-ctp-surface0 text-ctp-subtext0 !text-[10px] shrink-0 animate-none cursor-pointer"
          :title="t('requirement.chat.trail')"
          @click="trailOpen = true"
        >
          <WrenchScrewdriverIcon class="w-3 h-3 inline -mt-0.5" />
          {{ t('requirement.chat.trail') }} ×{{ toolTrail.length }}
        </button>
      </div>
    </div>

    <transition
      enter-active-class="transition-opacity duration-200"
      leave-active-class="transition-opacity duration-200"
      enter-from-class="opacity-0"
      leave-to-class="opacity-0"
    >
      <div
        v-if="toastVisible"
        class="absolute left-1/2 -translate-x-1/2 bottom-20 z-30 flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-ctp-base border border-ctp-green/40 text-xs text-ctp-green shadow-lg"
      >
        <CheckIcon class="w-3.5 h-3.5" />{{ toastText }}
      </div>
    </transition>

    <div class="flex items-center gap-1 border-t border-ctp-surface0 px-2.5 py-1.5 shrink-0">
      <!-- 工具条: 纯 icon(悬停 title 提示); 动作均可用 /命令 触达(见命令浮层) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="props.diagramSkill ? 'btn-blue' : 'btn-ghost'"
        :disabled="busy"
        :title="`${t('requirement.chat.diagramSkill')} — /绘图`"
        @click="emit('toggle-diagram-skill', !props.diagramSkill)"
      >
        <svg
          class="w-3.5 h-3.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        ><path d="M3 3h18v18H3z" /><path d="M3 9h18" /><path d="M3 15h18" /><path d="M9 3v18" /></svg>
      </button>
      <button
        class="btn btn-xs btn-ghost !px-1.5"
        :disabled="busy"
        :title="`${t('assetChat.extractPlan.button')} — /方案`"
        @click="fillExtractPlan"
      >
        <SparklesIcon class="w-3.5 h-3.5" />
      </button>
      <slot name="toolbar-extra" />
      <button
        v-if="props.showContractSkill"
        class="btn btn-xs !px-1.5"
        :class="props.contractSkill ? 'btn-green' : 'btn-ghost'"
        :disabled="busy"
        :title="t('requirement.chat.contractSkillHint')"
        @click="emit('toggle-contract-skill', !props.contractSkill)"
      >
        <svg
          class="w-3.5 h-3.5"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.8"
          stroke-linecap="round"
          stroke-linejoin="round"
        ><path d="M9 12h6" /><path d="M9 16h6" /><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><path d="M14 2v6h6" /></svg>
      </button>
    </div>

    <div class="relative flex items-end gap-2 border-t border-ctp-surface0 p-2.5 shrink-0">
      <!-- `/` 命令提示浮层(会话指令发后端 + 会话操作本地执行) -->
      <div
        v-if="cmdMenuOpen"
        class="absolute bottom-full left-2 z-50 mb-1 w-72 flex-col gap-0.5 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1 shadow-lg flex"
      >
        <span class="px-2 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">会话操作(本地)</span>
        <button
          v-for="c in cmdFilter.filter((x) => LOCAL_CMD_LIST.includes(x))"
          :key="c.name"
          class="rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
          @click="pickCmd(c.name)"
        >
          <span class="font-mono text-ctp-mauve">/{{ c.name }}</span>
          <span class="ml-1.5 text-ctp-subtext0">{{ c.desc }}</span>
        </button>
      </div>
      <textarea
        ref="inputRef"
        v-model="input"
        rows="2"
        class="input !py-2.5 text-xs resize-y min-h-0"
        :disabled="props.readOnly"
        :placeholder="props.readOnly ? t('session.readOnlyHint')
          : t('requirement.chat.placeholder')"
        @input="autoResize"
        @keydown="onInputKeydown"
      />
      <!-- v2 发送方向选择(@architect/@cline) -->
      <div class="relative shrink-0">
        <button
          class="chip !text-[10px] font-mono transition-colors"
          :class="props.sendAgent ? 'bg-ctp-peach/15 text-ctp-peach' : 'bg-ctp-surface0/60 text-ctp-overlay0 hover:text-ctp-subtext1'"
          :title="props.sendAgent ? `指派 ${props.sendAgent}(点击切回 architect)` : '对话方向: architect 外循环(缺省)'"
          @click="agentMenuOpen = !agentMenuOpen"
        >{{ props.sendAgent ? `@${props.sendAgent}` : '@architect' }}<ChevronDownIcon class="w-2.5 h-2.5 inline ml-0.5" /></button>
        <div
          v-if="agentMenuOpen"
          class="absolute bottom-full right-0 z-50 mb-1 w-64 flex-col gap-0.5 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1 shadow-lg flex"
          @mouseleave="agentMenuOpen = false"
        >
          <button
            v-for="a in AGENT_PICKS"
            :key="a.id || 'arch'"
            class="rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
            @click="pickSendAgent(a.id)"
          >
            <span class="font-mono" :class="a.id ? 'text-ctp-peach' : 'text-ctp-sky'">{{ a.label }}</span>
            <span class="ml-1.5 text-ctp-subtext0">{{ a.desc }}</span>
          </button>
        </div>
      </div>
      <button
        v-if="busy"
        class="btn btn-red !py-2.5 shrink-0 whitespace-nowrap"
        :title="t('requirement.chat.stop')"
        @click="emit('stop')"
      >
        <StopIcon class="w-4 h-4" />{{ t('requirement.chat.stop') }}
      </button>
      <button
        v-else
        class="btn btn-primary !py-2.5 shrink-0 whitespace-nowrap"
        :disabled="!input.trim() || props.readOnly"
        @click="send"
      >
        <PaperAirplaneIcon class="w-4 h-4" />{{ t('coding.send') }}
      </button>
    </div>

    <!-- 删除消息确认弹窗(DOM) -->
    <div
      v-if="deletePending !== null"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
      @click.self="cancelDeleteTurn"
    >
      <div class="panel w-full max-w-xs">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <TrashIcon class="w-4 h-4 text-ctp-red" />{{ t('requirement.chat.deleteTurn') }}
          </span>
        </div>
        <div class="p-4 text-xs text-ctp-subtext1">
          {{ t('requirement.chat.deleteTurnConfirm') }}
        </div>
        <div class="flex items-center justify-end gap-2 px-4 pb-4">
          <button
            class="btn btn-sm btn-ghost"
            @click="cancelDeleteTurn"
          >
            {{ t('requirement.chat.deleteTurnCancel') }}
          </button>
          <button
            class="btn btn-sm btn-red"
            @click="confirmDeleteTurn"
          >
            {{ t('requirement.chat.deleteTurnOk') }}
          </button>
        </div>
      </div>
    </div>

    <!-- 工具轨迹浮层：防信息过载，默认收起；Teleport+fixed 避免被对话区 overflow 裁剪 -->
    <Teleport to="body">
      <div
        v-if="trailOpen"
        class="fixed inset-0 z-50 bg-black/40"
        @click="trailOpen = false"
      >
        <div
          class="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[min(520px,92vw)] max-h-[70vh] flex flex-col rounded-xl bg-ctp-base border border-ctp-surface1 shadow-2xl overflow-hidden"
          @click.stop
        >
          <div class="flex items-center gap-2 px-4 py-3 border-b border-ctp-surface0 shrink-0">
            <WrenchScrewdriverIcon class="w-4 h-4 text-ctp-blue" />
            <span class="text-sm font-semibold text-ctp-text">{{ t('requirement.chat.trail') }}</span>
            <span class="chip bg-ctp-surface0 text-ctp-subtext0 font-mono text-[10px]">{{ toolTrail?.length ?? 0 }}</span>
            <span class="flex-1" />
            <button
              class="text-ctp-overlay0 hover:text-ctp-text p-0.5"
              @click="trailOpen = false"
            >
              <XMarkIcon class="w-4 h-4" />
            </button>
          </div>
          <div class="p-3 space-y-1 overflow-y-auto">
            <div
              v-for="(it, i) in toolTrail"
              :key="`${it.tool}-${i}`"
              class="flex items-start gap-2 px-2 py-1.5 rounded-lg bg-ctp-mantle"
            >
              <span class="shrink-0 mt-0.5">
                <CheckIcon
                  v-if="it.ok === true"
                  class="w-3.5 h-3.5 text-ctp-green"
                />
                <XMarkIcon
                  v-else-if="it.ok === false"
                  class="w-3.5 h-3.5 text-ctp-red"
                />
                <ArrowPathIcon
                  v-else
                  class="w-3.5 h-3.5 text-ctp-yellow animate-spin"
                />
              </span>
              <span class="min-w-0">
                <span class="font-mono text-[11px] text-ctp-text">{{ it.tool }}</span>
                <span
                  v-if="it.summary"
                  class="block text-[10px] text-ctp-subtext0 truncate"
                  :title="it.summary"
                >{{ it.summary }}</span>
              </span>
            </div>
            <div
              v-if="!toolTrail || !toolTrail.length"
              class="text-[11px] text-ctp-overlay0 px-2 py-3"
            >
              {{ t('requirement.chat.trailEmpty') }}
            </div>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
