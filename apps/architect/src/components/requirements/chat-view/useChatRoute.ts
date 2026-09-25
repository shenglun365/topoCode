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
/** 快捷挡直切开关(闪电 icon): architect 模式=关(暗, 需求分析→规约→任务完整链, 按执行器能力档位自动适配) / coding 执行器模式=开(高亮, 直出任务卡·关 KB), 点击取反, 上抛宿主 REST 即时生效。挡位体系 T0-T4 见 gears.py; 细档在执行器配置标定。 */
const quickOn = computed(() => (props.analysisMode || 'strict') === 'quick')
/** 空白对话(会话未创建)锁定: 挡位是会话级字段, 无 conv_id 可写。 */
const quickLocked = computed(() => props.hasSession === false)
const quickTitle = computed(() => {
  if (quickLocked.value) return '模式切换需在已有会话中进行 — 发送首条消息创建会话后可用'
  return quickOn.value
    ? 'coding 执行器模式 — 直出任务卡·关 KB（点击切回 architect 模式）'
    : 'architect 模式 — 需求分析→规约→任务，按执行器能力档位自动适配（点击切至 coding 执行器模式）'
})
function toggleQuickMode() {
  if (quickLocked.value) return
  emit('set-analysis-mode', quickOn.value ? 'strict' : 'quick')
}

/** 需求澄清挡位(cv-190): 自动=规约有缺口才集中提问 / 强制=先澄清后落卡(明确指令自动跳过)。 */
const clarifyForced = computed(() => (props.clarifyMode || 'auto') === 'forced')
const clarifyTitle = computed(() => {
  if (quickLocked.value) return '澄清挡位需在已有会话中切换 — 发送首条消息创建会话后可用'
  return clarifyForced.value
    ? '强制澄清 — 每个需求回合先集中提问补齐要素再落卡（明确指令自动跳过；点击切回自动）'
    : '自动澄清 — 规约有要素缺口时才集中提问（点击切为强制澄清）'
})
function toggleClarifyMode() {
  if (quickLocked.value) return
  emit('set-clarify-mode', clarifyForced.value ? 'auto' : 'forced')
}

/** worktree 隔离挡位(cv-202): 缺省就地; 显式开启后任务在 worktree 分支作业。 */
const isolatedOn = computed(() => !!props.isolated)
const isolatedTitle = computed(() => {
  if (quickLocked.value) return '隔离模式需在已有会话中切换 — 发送首条消息创建会话后可用'
  return isolatedOn.value
    ? '隔离模式 开 — 任务在独立 worktree 分支作业, 完成后合并回项目目录（点击关闭）'
    : '隔离模式 关 — 直接写入项目目录（点击开启隔离）'
})
function toggleIsolated() {
  if (quickLocked.value) return
  emit('set-isolated', !isolatedOn.value)
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

  return {
    INLINE_AGENTS,
    activeTask,
    clarifyForced,
    clarifyTitle,
    defaultExecutor,
    effectiveRoute,
    executorFull,
    executorLabel,
    inlineAgent,
    isolatedOn,
    isolatedTitle,
    lastAssistantAgent,
    pickExecutor,
    pickRoute,
    quickLocked,
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
