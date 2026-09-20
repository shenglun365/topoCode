<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { kindChipClass } from '@/services/semantic-kind-style'
import { useI18n } from 'vue-i18n'
import { DocumentTextIcon, ArrowPathIcon, PaperAirplaneIcon, ChatBubbleLeftRightIcon, PencilSquareIcon, SparklesIcon, BookOpenIcon, CheckIcon, QuestionMarkCircleIcon, ClipboardDocumentCheckIcon, ClipboardDocumentIcon, TrashIcon, CubeTransparentIcon, BoltIcon, AdjustmentsHorizontalIcon, ChevronDownIcon, ChevronRightIcon, StopIcon, ArrowTopRightOnSquareIcon, WrenchScrewdriverIcon, XMarkIcon, ExclamationCircleIcon, AtSymbolIcon, CpuChipIcon } from '@heroicons/vue/24/outline'
import type { KbAnalysisTurn } from '@/services/kb-analysis-agent'
import type { AcceptanceFact, AcceptanceReportDetail, ContractItem } from '@/services/contract-service'
import type { NamingConvention } from '@/services/naming-service'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import TaskCard from '@/components/chat/TaskCard.vue'
import AssetsPanel from '@/components/chat/AssetsPanel.vue'
import { apiPost, apiGet } from '@/services/api-client'
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
  /** running 归属(S2): {role:'coding', executorId, status} 有活跃作业时非空。 */
  jobState?: { role: string; executorId?: string; status?: string; progress?: { toolCount?: number; msgCount?: number; at?: number } } | null
  /** 已绑定执行器 id(S2/S3): 空=未绑定——Coding 切换钮首击触发分配(bind-coding)。 */
  boundExecutorId?: string
  /** 执行器注册表(启用项): 工具栏选择钮清单与完整名称显示。 */
  executors?: Array<{ id: string; type?: string; default?: boolean }>
  /** 执行器白名单模型名列表(≥2 时显示模型 chip)。 */
  executorModels?: string[]
  /** 当前会话模型(空=默认)。 */
  executorModel?: string
  /** v2 分析挡位(strict/quick): 快捷挡直切钮展示并可切换(上抛宿主 → REST 即时生效)。 */
  analysisMode?: 'strict' | 'quick'
  /** 会话是否已存在: false=空白对话(记录未创建)——挡位是会话级字段无处可写, 直切钮禁用+提示。 */
  hasSession?: boolean
  /** 会话 id(语境摘要 REST 用); 空=无会话。 */
  convId?: string
  /** 知识资产面板(输入框上方折叠条): 缺省显示; 会话中心已移至左栏, 传 false 隐藏。 */
  showAssetsPanel?: boolean
  /** v2 coding subagent 任务清单(arch_tasks, 倒序; TaskCard 渲染 + 语境路由用)。 */
  tasks?: Array<Record<string, any>>
}>()

const emit = defineEmits<{
  /** 发送(语境路由): text 已剥离内联 @前缀; attachTo=转达任务卡, agent=一次性指派执行器, digest=语境摘要。 */
  send: [p: { text: string; attachTo?: string; agent?: string; digest?: string }]
  /** 分析挡位切换(strict/quick) → 宿主上抛 REST。 */
  'set-analysis-mode': [mode: 'strict' | 'quick']
  /** 工具栏执行器选择: 上抛宿主执行绑定(未绑=bind; 已绑切换=克隆新会话)。 */
  'bind-executor': [executorId: string]
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
  'rollback-to': [index: number]
  'feed-turn': [p: { index: number; id?: string; summarize?: boolean }]
  'refresh-asset': [assetId: string]
  'toggle-diagram-skill': [enabled: boolean]
  'contract-confirm': [id: string]
  'contract-delete': [id: string]
  'contract-edit-save': [id: string, patch: Record<string, unknown>]
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

// ── S3 投喂门: 消息级「转达 coding」(dock 执行 POST /feed, 结果本地消息) ──
const feedBusyIdx = ref(-1)
const mergeBusyIdx = ref(-1)
const mergedDone = ref<Record<number, boolean>>({})

/** 合并入口检查(环节十五): git 事实 → 轻提示(可否直并/需先 rebase)。 */
async function runMergePrecheck(i: number, taskId: string) {
  mergeBusyIdx.value = i
  try {
    const r = await apiGet<{ fastForward: boolean | null; mainNewCommits: string[]; branchCommits: string[]; advice: string }>(
      `/tasks/${taskId}/merge-precheck`)
    const ff = r.fastForward === true ? '✓ 可直接合并' : r.fastForward === false ? '⚠ 主目录有推进, 需先 rebase' : '— 无基点, 请手工检视'
    showToast(`合并检查: ${ff} — ${r.advice}`)
  } catch (e: any) {
    showToast(`✗ 合并检查失败: ${e?.message || e}`)
  } finally {
    mergeBusyIdx.value = -1
  }
}

/** 确认合并(本地 PR 语义): 门禁通过后执行; 冲突/需 rebase → 提示原文。 */
async function confirmMerge(i: number, taskId: string) {
  mergeBusyIdx.value = i
  try {
    const r = await apiPost<{ mergedHead: string; advice: string }>(
      `/tasks/${taskId}/merge`, { mode: 'ff' })
    mergedDone.value[i] = true
    showToast(`✓ ${r.advice}`)
  } catch (e: any) {
    showToast(`✗ 合并未执行: ${e?.message || e}`)
  } finally {
    mergeBusyIdx.value = -1
  }
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

// ── v2 语境路由(发起者感知): 回复永远面向「当前持球方」——单输入框, 零模式切换 ──
// 规则: ① 存在 waiting_input 任务 → 转达该任务(attachTo)
//       ② 存在活跃任务 且 最后 assistant 消息为 coding subagent 产出 → 转达(排队)
//       ③ 其余 → architect 外循环
// 覆盖: 内联 @执行器 前缀(一次性指派, 发送时剥离) > 菜单单次翻转(发送后复位)
type RouteTarget =
  | { kind: 'architect' }
  | { kind: 'task'; taskId: string }
  | { kind: 'assign'; agent: string }
const routeMenuOpen = ref(false)
const routeOverride = ref<RouteTarget | null>(null)
/** 活跃任务: waiting_input 优先, 否则最新 pending_confirm/running。 */
const activeTask = computed(() => {
  const ts = props.tasks || []
  return ts.find((t) => t.status === 'waiting_input')
    || ts.find((t) => t.status === 'pending_confirm' || t.status === 'running')
    || null
})
/** 最后一条 assistant 消息的 agent 标注(architect 消息无 agent; subagent 消息 agent=cline/opencode/codex)。 */
const lastAssistantAgent = computed(() => {
  for (let i = props.turns.length - 1; i >= 0; i--) {
    const m = props.turns[i]
    if (m.role === 'assistant') return (m as any).agent || ''
  }
  return ''
})
/** 内联 @执行器 前缀(一次性指派; 命中返回执行器类型, 发送时剥离前缀)。 */
const INLINE_AGENTS = ['cline', 'opencode', 'codex']
const inlineAgent = computed(() => {
  const v = (input.value || '').trimStart()
  for (const a of INLINE_AGENTS) {
    if (v === `@${a}` || v.startsWith(`@${a} `)) return a
  }
  return null
})
/** 有效路由: 单次翻转 > 内联 @ > 发起者感知。 */
const effectiveRoute = computed<RouteTarget>(() => {
  if (routeOverride.value) return routeOverride.value
  if (inlineAgent.value) return { kind: 'assign', agent: inlineAgent.value }
  const waiting = (props.tasks || []).find((t) => t.status === 'waiting_input')
  if (waiting) return { kind: 'task', taskId: waiting.id }
  const act = activeTask.value
  if (act && lastAssistantAgent.value && lastAssistantAgent.value !== 'architect') {
    return { kind: 'task', taskId: act.id }
  }
  return { kind: 'architect' }
})
function taskTitleOf(id?: string): string {
  const t = (props.tasks || []).find((x) => x.id === id)
  return (t?.title as string) || ''
}
/** 工具条路由按钮配色: 中性(architect) / sky(转达任务) / peach(一次性指派)——一眼可辨路由态。 */
const routeBtnClass = computed(() => {
  if (effectiveRoute.value.kind === 'assign') return 'bg-ctp-peach/15 text-ctp-peach hover:bg-ctp-peach/25'
  if (effectiveRoute.value.kind === 'task') return 'bg-ctp-sky/15 text-ctp-sky hover:bg-ctp-sky/25'
  return 'btn-ghost'
})
function routeDetail(r: RouteTarget): string {
  if (r.kind === 'assign') return `一次性指派 ${r.agent} coding subagent(发送后复位)`
  if (r.kind === 'task') {
    const t = (props.tasks || []).find((x) => x.id === r.taskId)
    return `转达任务「${taskTitleOf(r.taskId) || r.taskId}」${t?.executorType ? `(${t.executorType})` : ''}`
  }
  return 'architect 外循环(分析/设计/编排)'
}
/** 菜单单次翻转: 仅作用于下一次发送(发送后自动复位)。 */
function pickRoute(r: RouteTarget) {
  routeMenuOpen.value = false
  routeOverride.value = r
}
/** 快捷挡直切开关(闪电 icon): 标准=关(暗, 按执行器能力档位自动适配) / 快捷=开(高亮, T0 直通车), 点击取反, 上抛宿主 REST 即时生效。挡位体系 T0-T4 见 gears.py; 细档在执行器配置标定。 */
const quickOn = computed(() => (props.analysisMode || 'strict') === 'quick')
/** 空白对话(会话未创建)锁定: 挡位是会话级字段, 无 conv_id 可写。 */
const quickLocked = computed(() => props.hasSession === false)
const quickTitle = computed(() => {
  if (quickLocked.value) return '快捷挡需在已有会话中切换 — 发送首条消息创建会话后可用'
  return quickOn.value
    ? 'T0 直通车已开启 — 直出任务卡·关 KB（点击关闭回到标准挡）'
    : '标准挡 — 按执行器能力档位自动适配（点击开启 T0 直通车）'
})
function toggleQuickMode() {
  if (quickLocked.value) return
  emit('set-analysis-mode', quickOn.value ? 'strict' : 'quick')
}

// ── 执行器选择(路由钮内, 靠右): 完整名称显示 + 清单选择; 绑定/克隆语义在宿主 ──
const defaultExecutor = computed(() =>
  (props.executors || []).find((e) => e.default) || null)
/** 按钮完整名称: 已绑定=「id · type」; 未绑定=「默认 {id}」; 无注册表=「执行器」。 */
const executorLabel = computed(() => {
  const b = props.boundExecutorId
  if (b) {
    const t = (props.executors || []).find((e) => e.id === b)?.type
    return t && t !== b ? `${b} · ${t}` : b
  }
  return defaultExecutor.value ? `默认 ${defaultExecutor.value.id}` : '执行器'
})
function executorFull(e: { id: string; type?: string }): string {
  return e.type && e.type !== e.id ? `${e.id} · ${e.type}` : e.id
}
function pickExecutor(id: string) {
  routeMenuOpen.value = false
  if (id === props.boundExecutorId) return
  emit('bind-executor', id)
}

// ── 语境摘要(转达下发): 摘要模式选史 → REST 生成 → 可编辑草稿卡 → 发送/自动通过 ──
const DIGEST_AUTO_KEY = 'arch.digestAutoSend'
const digestMode = ref(false)
const selIds = ref<Set<string>>(new Set())
const digestBusy = ref(false)
const digestDraft = ref<string | null>(null)   // 非空=草稿卡(可编辑)
const digestSentOpen = reactive<Record<number, boolean>>({})

// ── 工具审批操作条(task_approval 消息) ──
const approvalDone = reactive<Record<string, 'approved' | 'rejected'>>({})
async function respondApproval(m: any, approved: boolean) {
  const jobId = m?.meta?.approvalJobId
  const requestId = m?.meta?.approvalRequestId
  if (!jobId || !requestId || approvalDone[m.id]) return
  try {
    await apiPost(`/exec/${jobId}/approval`, {
      requestId, approved,
      reason: approved ? 'approved' : 'rejected by user',
    })
    approvalDone[m.id] = approved ? 'approved' : 'rejected'
  } catch { /* 失败保持可重试 */ }
}
const digestAutoSend = ref(localStorage.getItem(DIGEST_AUTO_KEY) === '1')
/** 摘要入口仅转达语境(路由=任务)显示; architect 路由本就全史可见无需摘要。 */
const canDigest = computed(() => effectiveRoute.value.kind === 'task')
function toggleDigestMode() {
  if (!canDigest.value) return
  digestMode.value = !digestMode.value
  if (!digestMode.value) exitDigest()
}
function exitDigest() {
  digestMode.value = false
  selIds.value = new Set()
  digestDraft.value = null
}
function toggleSel(m: any) {
  if (!digestMode.value || !m?.id) return   // 本地乐观回合无 id, 不可选
  const s = new Set(selIds.value)
  if (s.has(m.id)) s.delete(m.id)
  else s.add(m.id)
  selIds.value = s
}
/** 生成摘要: REST → 自动通过(跳卡直发) 或 草稿卡人工审核。 */
async function generateDigest() {
  if (!selIds.value.size || digestBusy.value || !props.convId) return
  digestBusy.value = true
  try {
    const r = await apiPost<{ digest: string; chars: number; summarized: boolean }>(
      `/sessions/${props.convId}/msg-digest`, { msgIds: [...selIds.value] })
    const digest = (r as any)?.digest || (r as any)?.data?.digest || ''
    if (!digest) return
    if (digestAutoSend.value) {
      await sendDigest(digest)          // 自动通过: 不落审核卡
      exitDigest()
    } else {
      digestDraft.value = digest
    }
  } catch { /* 生成失败: 保留选择可重试 */ } finally {
    digestBusy.value = false
  }
}
async function sendDigest(digest: string) {
  const r = effectiveRoute.value
  if (r.kind !== 'task' || props.busy) return
  emit('send', { text: '', attachTo: r.taskId, digest })
}
function confirmDigest() {
  if (digestDraft.value?.trim()) void sendDigest(digestDraft.value)
  exitDigest()
}
function onAutoSendToggle(e: Event) {
  digestAutoSend.value = (e.target as HTMLInputElement).checked
  localStorage.setItem(DIGEST_AUTO_KEY, digestAutoSend.value ? '1' : '0')
}
watch(canDigest, (ok) => { if (!ok && digestMode.value) exitDigest() })
/** 转达摘要回执折叠卡展开态。 */
function toggleDigestSent(i: number) {
  digestSentOpen[i] = !digestSentOpen[i]
}
/** 草稿卡标题: 当前转达目标任务。 */
const digestTargetTitle = computed(() => {
  const r = effectiveRoute.value
  return r.kind === 'task' ? (taskTitleOf(r.taskId).slice(0, 20) || '当前任务') : '当前任务'
})
/** 占位文案随语境联动(转达任务/指派执行器时给出方向提示)。 */
const inputPlaceholder = computed(() => {
  if (props.readOnly) return t('session.readOnlyHint')
  const r = effectiveRoute.value
  if (r.kind === 'task') return `回复当前任务「${taskTitleOf(r.taskId).slice(0, 16) || '…'}」…`
  if (r.kind === 'assign') return `@${r.agent} `
  return t('requirement.chat.placeholder')
})

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
  // 语境路由: 组装 attachTo(转达任务卡)/agent(一次性指派), 剥离内联 @执行器 前缀
  const r = effectiveRoute.value
  let text = input.value.trim()
  const ia = inlineAgent.value
  if (ia) text = text.replace(new RegExp(`^@${ia}[\\s\\u00A0]*`), '').trim()
  emit('send', {
    text,
    attachTo: r.kind === 'task' ? r.taskId : undefined,
    agent: r.kind === 'assign' ? r.agent : undefined,
  })
  routeOverride.value = null // 单次翻转复位(避免持久模式陷阱)
  input.value = ''
  cmdMenuOpen.value = false
  resetInputHeight()
  nextTick(() => scrollRef.value?.scrollTo({ top: scrollRef.value.scrollHeight, behavior: 'smooth' }))
}

/** 本地命令(前端拦截, 不发后端): 会话操作/状态切换——与工具条按钮同动作。 */
const LOCAL_CMD_LIST = [
  { name: '绘图', desc: '切换绘图增强(IR→代码)' },
  { name: '提取需求', desc: '从对话历史提取需求卡(ready)，系统未自动识别时用' },
  { name: '摘要', desc: '生成会话标题与摘要' },
  { name: '提炼', desc: '提炼会话为数据资产' },
  { name: '归档', desc: '结束会话(有可提炼内容时提示)' },
  { name: '选摘', desc: '选取历史生成摘要转达执行器' },
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
/** 本地命令分发: 绘图/方案/选摘在组件内执行; 摘要/提炼/归档上抛宿主(与工具条同动作)。 */
function runLocalCmd(name: string) {
  if (name === '绘图') {
    emit('toggle-diagram-skill', !props.diagramSkill)
  } else if (name === '提取需求') {
    emit('send', { text: '/提取需求' })
    return
  } else if (name === '选摘') {
    toggleDigestMode()
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

/** 工具栏「提取需求」: 发 /提取需求 直通(系统确定性提取, 同对话指令路径)。 */
function sendExtractReq() {
  emit('send', { text: '/提取需求' })
}

// ── 提案卡确认存入：finalize 入池(待执行)；按钮自带 reqId, 多提案各自独立确认 ──
const confirmingProposalId = ref('')
// 提案卡状态核验(防重复存入): p.confirmed 是本地态, 刷新即失——以后端为准
const proposalState = reactive<Record<string, string>>({})   // reqId -> draft/ready/done
const proposalChecked = reactive<Record<string, boolean>>({})
async function ensureProposalState(m: KbAnalysisTurn) {
  const p = m.proposal
  if (!p || p.confirmed || proposalChecked[p.id]) return
  proposalChecked[p.id] = true
  try {
    const r = await apiGet<Record<string, any>>(`/requirements/${p.id}`)
    const st = String(r?.status || '')
    if (st) proposalState[p.id] = st
    if (st === 'ready' || st === 'done') p.confirmed = true   // 已存入: 抑制存入按钮
  } catch { /* 状态获取失败不阻塞卡片展示 */ }
}
// cv-188: 追踪 proposal 挂载本身——attachProposal 在回合已存在时写入,
// turns.length 不变, 旧 watcher(只看长度)永不触发 → 实时卡漏判「已存入」
watch(() => props.turns.map((t) => t.proposal?.id || '').join(','), () => {
  for (const m of props.turns) if (m.proposal) void ensureProposalState(m)
}, { immediate: true })
/** 已存入(ready): 本地确认态或后端状态任一即可; done=已完成(不可再跑)。 */
function proposalStored(m: KbAnalysisTurn): boolean {
  const p = m.proposal
  if (!p) return false
  return p.confirmed || proposalState[p.id] === 'ready'
}
function proposalDone(m: KbAnalysisTurn): boolean {
  const p = m.proposal
  return !!p && proposalState[p.id] === 'done'
}
async function confirmProposal(m: KbAnalysisTurn) {
  const p = m.proposal
  if (!p || proposalStored(m) || confirmingProposalId.value) return   // 防重复存入
  confirmingProposalId.value = p.id
  try {
    const analysis = {
      ...(p.analysis ?? {}),
      implementationPath: p.analysis?.implementationPath || p.analysis?.designMd || '',
    }
    const row = await apiPost<Record<string, unknown>>(`/requirements/${p.id}/finalize`, { analysis })
    if (row && (row as any).id) {
      p.confirmed = true
      proposalState[p.id] = String((row as any).status || 'ready')
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
/** 提案卡运行: /执行 直通——按会话绑定执行器建任务卡(确认卡后 subagent 启动)。 */
function runProposal() {
  emit('send', { text: '/执行' })
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
      <!-- 模型 chip(语境路由 chip 移至输入区) -->
      <span class="ml-auto flex shrink-0 items-center gap-1">
        <slot name="header-inline" />
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
      <!-- 摘要模式操作栏: 点选消息 → 生成摘要(草稿卡/自动通过) -->
      <div
        v-if="digestMode"
        class="flex items-center gap-2 rounded-md border border-ctp-teal/30 bg-ctp-teal/10 px-2.5 py-1.5 text-[11px] text-ctp-teal"
      >
        <ClipboardDocumentIcon class="w-3.5 h-3.5 shrink-0" />
        <span>摘要模式: 点击消息选取/取消（已选 {{ selIds.size }} 条）</span>
        <span class="flex-1" />
        <button
          class="btn btn-xs btn-primary"
          :disabled="!selIds.size || digestBusy"
          @click="generateDigest"
        >{{ digestBusy ? '生成中…' : '生成摘要' }}</button>
        <button
          class="btn btn-xs btn-ghost"
          @click="toggleDigestMode"
        >取消</button>
      </div>
        <div
          v-for="(m, i) in turns"
          :key="i"
          :id="(m as any).id ? `msg-${(m as any).id}` : undefined"
          class="animate-fade-up flex items-start gap-2 rounded-lg scroll-mt-2"
          :class="selIds.has((m as any).id) ? 'ring-1 ring-ctp-blue' : (digestMode ? 'cursor-pointer hover:ring-1 hover:ring-ctp-blue/40' : '')"
          @copy="onMsgCopy"
          @click="toggleSel(m)"
        >
        <div
          class="flex-1 min-w-0 rounded-lg rounded-tl-none px-3 py-2 text-xs bg-ctp-surface0/80"
          :class="m.role === 'user' ? 'ring-1 ring-ctp-sky/20' : ''"
        >
          <!-- 产出者标注(读侧归因): architect 外循环 / 具体执行器(泵以 agent=executor_type 落库) -->
          <div
            v-if="m.role === 'assistant'"
            class="mb-1 flex items-center gap-1 text-[9px]"
            :class="(m as any).agent ? 'text-ctp-teal' : 'text-ctp-overlay0'"
          >
            <CpuChipIcon class="w-3 h-3 shrink-0" />
            <span class="font-mono">{{ (m as any).agent || 'architect' }}</span>
          </div>
          <!-- A6.2 守门: 渲染只经统一投影(m.item), 禁历史卡片键/执行器类型分支 -->
          <TaskCard
            v-if="m.item?.type === 'task' && taskById(m.item.payload?.taskId)"
            :conv-id="convId"
            :task="taskById(m.item.payload?.taskId)!"
            class="mb-2"
            @confirm="(id: string) => emit('task-confirm', id)"
            @cancel="(id: string) => emit('task-cancel', id)"
            @set-executor="(id: string, ex: string) => emit('task-executor', { taskId: id, executorType: ex })"
          />
          <div
            v-if="m.item?.type === 'approval'"
            class="mb-2 flex items-center gap-2 rounded-md border border-ctp-yellow/30 bg-ctp-yellow/10 px-2.5 py-1.5"
          >
            <ExclamationCircleIcon class="w-4 h-4 shrink-0 text-ctp-yellow" />
            <span class="text-[11px] text-ctp-yellow flex-1 min-w-0 truncate">
              {{ approvalDone[m.id] === 'approved' ? '✓ 已批准' : approvalDone[m.id] === 'rejected' ? '✗ 已拒绝' : `工具 ${m.item.payload?.approvalRequestId || ''} 请求执行，等待确认` }}
            </span>
            <template v-if="!approvalDone[m.id]">
              <button
                class="btn btn-primary !py-0.5 !px-2 !text-[10px] shrink-0"
                @click="respondApproval(m, true)"
              >批准</button>
              <button
                class="btn !py-0.5 !px-2 !text-[10px] shrink-0"
                @click="respondApproval(m, false)"
              >拒绝</button>
            </template>
          </div>
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
              v-if="m.role === 'assistant' && !m.item"
              class="text-ctp-overlay0 hover:text-ctp-mauve transition-colors p-0.5"
              :title="t('session.subs.feedHint')"
              :disabled="feedBusyIdx === i"
              @click="emit('feed-turn', { index: i, id: (m as any).id })"
            >
              <PaperAirplaneIcon class="w-3 h-3 rotate-90" />
            </button>
            <button
              v-if="m.role === 'assistant' && !m.item"
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
            <button
              class="text-ctp-overlay0 hover:text-ctp-peach transition-colors p-0.5"
              title="回退到此 — 之后消息作废(运行中任务须先停止)"
              :disabled="busy"
              @click="emit('rollback-to', i)"
            >
              <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M3 7v6h6" /><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13" /></svg>
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
          <!-- 完成卡合并入口(环节十五): git 事实检视(主目录推进/分支内容/可否直并) -->
          <div
            v-if="m.item?.type === 'turn_completed' && m.item?.status === 'done' && m.item?.payload?.taskId"
            class="mt-1.5 flex items-center gap-2"
          >
            <button
              class="flex items-center gap-1.5 text-[10px] text-ctp-green hover:text-ctp-teal transition-colors"
              :disabled="mergeBusyIdx === i"
              title="合并入口检查 — 主目录是否有推进/是否可直接合并"
              @click="runMergePrecheck(i, m.item.payload?.taskId)"
            >
              <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><circle cx="18" cy="18" r="3" /><circle cx="6" cy="6" r="3" /><path d="M6 21V9a9 9 0 0 0 9 9" /></svg>
              合并检查
            </button>
            <button
              v-if="!mergedDone[i]"
              class="flex items-center gap-1.5 text-[10px] text-ctp-blue hover:text-ctp-sky transition-colors"
              :disabled="mergeBusyIdx === i"
              title="确认合并 — 门禁通过后执行(ff 仅快进; 主目录有推进时提示先 rebase)"
              @click="confirmMerge(i, m.item.payload?.taskId)"
            >
              <svg class="w-3 h-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5" /></svg>
              确认合并
            </button>
            <span v-else class="text-[10px] text-ctp-green">✓ 已合并</span>
            <span v-if="mergeBusyIdx === i" class="text-[10px] text-ctp-overlay0">处理中…</span>
          </div>
          <!-- 转达摘要回执: 折叠卡(留"给执行器发过什么"的感知, 点开看全文) -->
          <div
            v-if="m.item?.type === 'digest'"
            class="rounded-md border border-ctp-teal/25 bg-ctp-teal/5 px-2.5 py-1.5"
          >
            <button
              class="flex items-center gap-1.5 text-[10px] text-ctp-teal"
              @click="toggleDigestSent(i)"
            >
              <ClipboardDocumentIcon class="w-3 h-3" />
              转达摘要 · {{ m.item.payload?.chars ?? m.content.length }} 字
              <span>{{ digestSentOpen[i] ? '▲ 收起' : '▼ 展开' }}</span>
            </button>
            <div
              v-if="digestSentOpen[i]"
              class="mt-1.5 whitespace-pre-wrap text-[11px] leading-relaxed text-ctp-subtext1"
            >{{ m.content }}</div>
          </div>
          <ChatMessageBlocks
            v-else
            :content="m.content"
          />

          <!-- 需求卡动作(创建即 ready): [一键建卡执行]——点击发 /指令 后端直通 -->
          <div
            v-if="m.item?.type === 'spec'"
            class="mt-2 flex items-center gap-2"
          >
            <button
              class="btn btn-xs btn-primary"
              :disabled="busy"
              title="从已定稿规约生成待确认任务卡"
              @click="emit('send', { text: '/执行' })"
            >一键建卡执行</button>
            <span class="text-[10px] text-ctp-overlay0">卡上确认后 coding subagent 启动</span>
          </div>

          <!-- 规约 JSON 落库按钮(字段签名识别, 任何含载荷的助手消息) -->
          <div
            v-if="!m.item && specPayloadOf(i)"
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
                v-if="proposalDone(m)"
                class="chip !px-1.5 !text-[9px] bg-ctp-surface0 text-ctp-overlay0 shrink-0"
              >已完成</span>
              <template v-else-if="proposalStored(m)">
                <span
                  class="chip !px-1.5 !text-[9px] bg-ctp-green/15 text-ctp-green shrink-0"
                >
                  <CheckIcon class="w-3 h-3" />{{ t('assetChat.extractPlan.confirmedChip') }}
                </span>
                <button
                  class="btn btn-xs btn-blue"
                  :disabled="busy"
                  title="按会话绑定执行器建实施任务卡——任务卡上确认后 coding subagent 启动"
                  @click="runProposal"
                >
                  <BoltIcon class="w-3 h-3" />运行
                </button>
              </template>
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
                  v-for="f in diffSummary(m.acceptance).top"
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

      <!-- 语境摘要草稿卡: 可编辑 → 发送给执行器 / 重新生成 / 取消; 可勾选以后自动通过 -->
      <div
        v-if="digestDraft !== null"
        class="rounded-lg border border-ctp-teal/30 bg-ctp-teal/5 px-3 py-2.5"
      >
        <div class="flex items-center gap-1.5 text-[11px] font-medium text-ctp-teal">
          <ClipboardDocumentIcon class="w-3.5 h-3.5" />
          <span>转达摘要（可编辑）— 将发给执行器「{{ digestTargetTitle }}」</span>
        </div>
        <textarea
          v-model="digestDraft"
          rows="5"
          class="input mt-2 text-xs"
        />
        <div class="mt-2 flex flex-wrap items-center gap-2">
          <button
            class="btn btn-xs btn-primary"
            :disabled="busy || !digestDraft.trim()"
            title="把摘要随转达发给执行器"
            @click="confirmDigest"
          >发送给执行器</button>
          <button
            class="btn btn-xs btn-ghost"
            :disabled="digestBusy"
            @click="generateDigest"
          >{{ digestBusy ? '生成中…' : '重新生成' }}</button>
          <button
            class="btn btn-xs btn-ghost"
            @click="exitDigest"
          >取消</button>
          <span class="flex-1" />
          <label
            class="flex cursor-pointer items-center gap-1 text-[10px] text-ctp-overlay0"
            title="勾选后: 生成摘要不再人工审核, 直接发给执行器"
          >
            <input
              type="checkbox"
              :checked="digestAutoSend"
              @change="onAutoSendToggle"
            >以后自动通过
          </label>
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
      <!-- 快捷挡直切(闪电): 选中=蓝色填充 / 未选中=置灰半透明(悬停恢复); 空白对话禁用(title 说明原因) -->
      <button
        class="btn btn-xs !px-1.5"
        :class="quickOn ? 'btn-blue' : 'btn-ghost opacity-50 hover:opacity-100'"
        :disabled="quickLocked"
        :title="quickTitle"
        @click="toggleQuickMode"
      >
        <BoltIcon class="w-3.5 h-3.5" />
      </button>
      <!-- 语境摘要(仅转达语境): 选史 → 生成摘要 → 随转达下发执行器 -->
      <button
        v-if="canDigest"
        class="btn btn-xs !px-1.5"
        :class="digestMode ? 'btn-teal' : 'btn-ghost'"
        title="语境摘要(/选摘) — 选取会话历史生成摘要, 随转达发给执行器"
        @click="toggleDigestMode"
      >
        <ClipboardDocumentIcon class="w-3.5 h-3.5" />
      </button>
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
        title="提取需求 — /提取需求(从对话历史提取需求卡)"
        @click="sendExtractReq"
      >
        <SparklesIcon class="w-3.5 h-3.5" />
      </button>
      <slot name="toolbar-extra" />
      <!-- v2 语境路由(发起者感知自动变 + 菜单单次翻转): 靠右加宽, 同钮显示当前执行器完整名称 -->
      <div class="relative shrink-0 ml-auto">
        <button
          class="btn btn-xs gap-1 !px-2 max-w-[200px]"
          :class="routeBtnClass"
          :title="routeDetail(effectiveRoute) + '（点击切换）；执行器选择见菜单底部'"
          @click="routeMenuOpen = !routeMenuOpen"
        >
          <AtSymbolIcon class="w-3.5 h-3.5 shrink-0" />
          <span
            class="truncate text-[10px] font-mono"
            :class="props.boundExecutorId ? 'text-ctp-teal' : 'opacity-70'"
          >{{ executorLabel }}</span>
        </button>
        <div
          v-if="routeMenuOpen"
          class="absolute bottom-full right-0 z-50 mb-1 w-72 flex-col gap-1 rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1.5 shadow-lg flex"
          @mouseleave="routeMenuOpen = false"
        >
          <div class="px-1.5 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">回复对象（单次, 发送后复位）</div>
          <button
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
            :class="effectiveRoute.kind === 'architect' && !routeOverride ? 'bg-ctp-blue/10' : ''"
            @click="pickRoute({ kind: 'architect' })"
          >
            <span class="font-mono text-ctp-sky">@architect</span>
            <span class="ml-1.5 text-ctp-subtext0">外循环(分析/设计/编排)</span>
          </button>
          <button
            v-if="activeTask"
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0"
            :class="effectiveRoute.kind === 'task' && effectiveRoute.taskId === activeTask.id && !routeOverride ? 'bg-ctp-blue/10' : ''"
            @click="pickRoute({ kind: 'task', taskId: activeTask.id })"
          >
            <span class="font-mono text-ctp-sky truncate">→ {{ taskTitleOf(activeTask.id) || '活跃任务' }}</span>
            <span class="ml-1.5 text-ctp-subtext0">转达（{{ activeTask.status === 'waiting_input' ? '等待回复' : '排队' }}）</span>
          </button>
          <!-- 会话执行器: 绑定后新任务卡默认使用(与 /执行 直通、模型建卡同链) -->
          <div class="mx-1 my-0.5 border-t border-ctp-surface0" />
          <div class="px-1.5 pt-0.5 text-[9px] uppercase tracking-wide text-ctp-overlay0">会话执行器（新任务卡默认）</div>
          <button
            v-for="e in (props.executors || [])"
            :key="e.id"
            class="w-full rounded px-2 py-1 text-left text-[11px] transition-colors hover:bg-ctp-surface0 flex items-center gap-1.5"
            :class="e.id === props.boundExecutorId ? 'bg-ctp-teal/10' : ''"
            @click="pickExecutor(e.id)"
          >
            <CpuChipIcon class="w-3 h-3 shrink-0 text-ctp-teal" />
            <span class="font-mono truncate">{{ executorFull(e) }}</span>
            <span class="flex-1" />
            <span
              v-if="e.id === props.boundExecutorId"
              class="chip !text-[9px] bg-ctp-teal/15 text-ctp-teal shrink-0"
            >已绑定</span>
            <span
              v-else-if="e.default"
              class="chip !text-[9px] bg-ctp-surface0/60 text-ctp-overlay0 shrink-0"
            >默认</span>
          </button>
          <div
            v-if="!(props.executors || []).length"
            class="px-2 py-1.5 text-[10px] text-ctp-overlay0"
          >注册表无启用执行器</div>
          <div class="px-1.5 pt-0.5 text-[10px] text-ctp-overlay0">
            ℹ 临时单次换引擎：输入框以 <span class="font-mono">@cline</span> 开头发送
          </div>
        </div>
      </div>
    </div>

    <!-- 知识资产面板(K2): 任务回执/里程碑沉淀清单, 检索+删除(会话中心场景移至左栏, showAssetsPanel=false 隐藏) -->
    <AssetsPanel
      v-if="props.showAssetsPanel !== false && props.convId"
      :conv-id="props.convId"
      :read-only="props.readOnly"
    />

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
        :placeholder="inputPlaceholder"
        @input="autoResize"
        @keydown="onInputKeydown"
      />
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
