/**
 * useChat · route 域（MS6-W3 机械迁出：域内逐行原文，跨域引用 D. 前缀重写）。
 */
import { computed, ref } from 'vue'

import type { ChatDeps } from './chatTypes'

export function useChatRoute(D: ChatDeps) {
  const props = D.props
  const emit = D.emit

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
  const v = (D.input.input.value || '').trimStart()
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
/** 生效执行器(2610 统一模型): ""=architect 分析管线; coding 执行器=直通。
    legacy: analysisMode=quick 且无绑定 → 默认 coding 执行器(读侧兼容口径)。 */
const effectiveExecutorId = computed(() => {
  const b = (props.boundExecutorId || '').trim()
  if (b && b !== 'architect') return b
  if (!b && (props.analysisMode || '') === 'quick') return '__legacy_quick__'
  return ''
})
/** 默认 coding 执行器(直通开=切到它; architect 内置条目不参选)。 */
const defaultCodingExecutor = computed(() =>
  (props.executors || []).find((e) => e.default && e.id !== 'architect')
  || (props.executors || []).find((e) => e.id !== 'architect') || null)
/** 直通开关(闪电 icon): 开=coding 执行器持球(直通对话·不走需求/任务) /
    关=architect 分析管线(需求分析→规约→任务); 点击换绑, 上抛宿主 REST。 */
const quickOn = computed(() => !!effectiveExecutorId.value)
const quickTitle = computed(() => {
  if (props.hasSession === false) return (quickOn.value
    ? 'coding 执行器模式(已预置) — 首条消息创建会话即以直通模式处理'
    : 'architect 模式(预置) — 首条消息创建会话后生效')
  return quickOn.value
    ? 'coding 执行器模式 — 直通对话·不走需求/任务体系，architect 仅做通道代理（点击切回 architect 模式）'
    : 'architect 模式 — 需求分析→规约→任务（点击切至 coding 执行器直通模式）'
})
function toggleQuickMode() {
  const target = quickOn.value ? 'architect' : (defaultCodingExecutor.value?.id || '')
  if (!target) {
    emit('switch-executor', '')
    return
  }
  emit('switch-executor', target)
}

/** 需求澄清挡位(cv-190): 自动=规约有缺口才集中提问 / 强制=先澄清后落卡(明确指令自动跳过)。 */
const clarifyForced = computed(() => (props.clarifyMode || 'auto') === 'forced')
const clarifyTitle = computed(() => {
  if (props.hasSession === false) return (clarifyForced.value
    ? '强制澄清(已预置) — 首条消息创建会话即生效'
    : '自动澄清(预置) — 首条消息创建会话后生效')
  return clarifyForced.value
    ? '强制澄清 — 每个需求回合先集中提问补齐要素再落卡（明确指令自动跳过；点击切回自动）'
    : '自动澄清 — 规约有要素缺口时才集中提问（点击切为强制澄清）'
})
function toggleClarifyMode() {
  emit('set-clarify-mode', clarifyForced.value ? 'auto' : 'forced')
}

/** worktree 隔离挡位(cv-202): 缺省融合模式; 显式开启后任务在 worktree 分支作业。 */
const isolatedOn = computed(() => !!props.isolated)
const isolatedTitle = computed(() => {
  if (props.hasSession === false) return (isolatedOn.value
    ? '隔离模式 开(已预置) — 首条消息创建会话即生效'
    : '隔离模式 关(预置) — 首条消息创建会话后生效')
  return isolatedOn.value
    ? '隔离模式 开 — 任务在独立 worktree 分支作业, 完成后合并回项目目录（点击关闭）'
    : '融合模式 关 — 直接写入项目目录，改动即时生效（点击切换隔离模式）'
})
function toggleIsolated() {
  emit('set-isolated', !isolatedOn.value)
}

// ── 执行器选择(路由钮内, 靠右): 完整名称显示 + 清单选择(统一换绑语义) ──
function isEffectiveExecutor(id: string): boolean {
  if (effectiveExecutorId.value) return id === effectiveExecutorId.value
  return id === 'architect'
}
/** 按钮完整名称: 生效=「id · type」; legacy quick=「默认 {id}·直通」; architect=「architect」。 */
const executorLabel = computed(() => {
  const eff = effectiveExecutorId.value
  if (!eff) return 'architect'
  if (eff === '__legacy_quick__') {
    const d = defaultCodingExecutor.value
    return d ? `默认 ${d.id}` : '执行器'
  }
  const t = (props.executors || []).find((e) => e.id === eff)?.type
  return t && t !== eff ? `${eff} · ${t}` : eff
})
function executorFull(e: { id: string; type?: string }): string {
  return e.type && e.type !== e.id ? `${e.id} · ${e.type}` : e.id
}
function pickExecutor(id: string) {
  routeMenuOpen.value = false
  if (isEffectiveExecutor(id)) return
  emit('switch-executor', id)
}

  return {
    INLINE_AGENTS,
    activeTask,
    clarifyForced,
    clarifyTitle,
    defaultCodingExecutor,
    effectiveExecutorId,
    effectiveRoute,
    executorFull,
    executorLabel,
    inlineAgent,
    isolatedOn,
    isolatedTitle,
    isEffectiveExecutor,
    lastAssistantAgent,
    pickExecutor,
    pickRoute,
    quickOn,
    quickTitle,
    routeBtnClass,
    routeDetail,
    routeMenuOpen,
    routeOverride,
    taskTitleOf,
    toggleClarifyMode,
    toggleIsolated,
    toggleQuickMode,
  }
}
