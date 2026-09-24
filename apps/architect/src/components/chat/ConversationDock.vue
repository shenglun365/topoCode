<script setup lang="ts">
/**
 * 全局会话栏(右侧 dock) —— architect 唯一对话入口(P1 决策2)。
 * 会话引擎在 conversation-store；本组件只做外观与会话切换。
 */
import { useAppDialog } from '@/composables/useAppDialog'
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  XMarkIcon, PlusIcon, ChatBubbleLeftRightIcon, ChevronDownIcon,
  ExclamationCircleIcon, PaperAirplaneIcon, ChatBubbleOvalLeftEllipsisIcon,
  PencilSquareIcon, SparklesIcon, BookOpenIcon, ArchiveBoxIcon, CubeTransparentIcon,
  DocumentTextIcon, ListBulletIcon,
} from '@heroicons/vue/24/outline'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import SessionOutlineWindow from '@/components/chat/SessionOutlineWindow.vue'
import { useConversationStore } from '@/stores/conversation-store'
import { sessionService, type ConversationMeta } from '@/services/session-service'
import { currentProjectParams } from '@/services/project-service'
import { namingService } from '@/services/naming-service'
import { apiBaseUrl, apiGet, apiPost, getToken } from '@/services/api-client'
import { readModelPref } from '@topo/web-core/shell'

const props = withDefaults(defineProps<{
  /** inline=停靠形态(页面右栏内嵌)；缺省=全局右侧悬浮 dock。 */
  inline?: boolean
  /** 新建会话的默认类型(资产地图页传 asset, 会话中心传 requirement)——首条消息创建会话时落库。 */
  defaultKind?: string
  /** 页面级技能场景(如资产地图=['extract'])：随发送注入。 */
  skillScenarios?: string[]
  /** 场景标识(sessions=会话中心 / asset=资产管理)：对话状态按场景隔离互不影响。 */
  scope?: string
  /** 知识资产面板(输入框上方): 缺省显示; 会话中心移至左栏后传 false。 */
  assetsPanel?: boolean
  /** 会话大纲按钮+浮窗(输入框上侧工具栏): 缺省关闭, 会话中心开启。 */
  outline?: boolean
}>(), { inline: false })

const { t } = useI18n()
const dialog = useAppDialog()
const router = useRouter()
const conv = useConversationStore()

const recent = ref<ConversationMeta[]>([])
const listOpen = ref(false)

// ── 会话大纲浮窗(按钮在 #toolbar-extra; 浮窗 Teleport 到 body) ──
const outlineOpen = ref(false)

// ── 会话操作(工具条): 提炼报告由服务端沉淀为会话消息 ──
const mining = ref(false)
function activeProject(): string {
  return ((conv.activeMeta as any)?.projectId || '') as string
}
/** 项目作用域(cv-204 硬隔离): 活动会话项目 → URL 项目; 皆无 → ''(空态, 不发全局查询)。 */
function scopePid(): string {
  return activeProject() || currentProjectParams().project || ''
}
async function mineActive() {
  const pid = activeProject()
  if (!conv.activeId || !pid || mining.value) return
  mining.value = true
  try {
    // 提炼报告由服务端沉淀为会话消息(统一时间线)
    await apiPost('/capabilities/mine', { conversationId: conv.activeId, project: pid })
  } catch (e) {
    await dialog.alert(e instanceof Error ? e.message : String(e))
  } finally { mining.value = false }
}
async function archiveActive() {
  if (!conv.activeId || (conv.activeMeta as any)?.status === 'archived') return
  try {
    const r = await sessionService.update(conv.activeId, { status: 'archived' } as any)
    ;(conv.activeMeta as any).status = 'archived'
    window.dispatchEvent(new CustomEvent('arch:sessions-changed', { detail: conv.activeId }))
    if ((r as any)?.mineableHint && activeProject()) {
      if (await dialog.confirm(t('session.mineOnEnd'))) await mineActive()
    }
  } catch { /* 保持 */ }
}

async function loadRecent() {
  try {
    // cv-205 项目硬隔离: 只拉当前项目会话(无项目上下文 → 空列表, 不发 scope=all)
    const pid = scopePid()
    if (!pid) { recent.value = []; return }
    recent.value = await sessionService.list({ limit: 30, project: pid })
  } catch { /* 列表失败保持旧值 */ }
}

// ── 会话标题: 悬停 → 手动修改(行内输入框) / 自动摘要 ──
const editingTitle = ref(false)
const titleDraft = ref('')
const titleSummarizing = ref(false)
function startTitleEdit() {
  titleDraft.value = conv.activeTitle || ''
  editingTitle.value = true
}
async function saveTitle() {
  if (!editingTitle.value) return
  editingTitle.value = false
  await commitTitle(titleDraft.value)
}
async function onRenameTitle(t: string) {
  await commitTitle(t)
}
async function commitTitle(title: string) {
  title = (title || '').trim()
  if (!title || title === conv.activeTitle) return
  conv.activeTitle = title
  if (conv.activeId) {
    try { await sessionService.update(conv.activeId, { title }) } catch { /* 保存失败保持本地 */ }
    window.dispatchEvent(new CustomEvent('arch:sessions-changed', { detail: conv.activeId }))
  }
}
async function summarizeTitle() {
  if (!conv.activeId || titleSummarizing.value) return
  titleSummarizing.value = true
  try {
    const updated = await sessionService.summarize(conv.activeId, true)
    conv.activeTitle = updated.title || conv.activeTitle
    window.dispatchEvent(new CustomEvent('arch:sessions-changed', { detail: conv.activeId }))
  } catch { /* 摘要失败静默 */ } finally {
    titleSummarizing.value = false
  }
}
onMounted(() => {
  if (props.scope) conv.setScope(props.scope)
  void loadRecent()
  // 会话集合变更(store 广播: 新建/回合完成/归档/改名) → dock 列表同步刷新
  window.addEventListener('arch:sessions-changed', onSessionsChanged)
  // 会话被删除(左侧列表) → 当前对话区若是该会话则清空(左右联动)
  window.addEventListener('arch:conversation-removed', onConversationRemoved)
  syncTimer = setInterval(() => void pollRunningState(), 5000)
  conv.connectEvents()   // cv-221: SSE 连接上移 store(单例单连接, 事件入缓冲统一消费)
})
onUnmounted(() => {
  if (syncTimer) clearInterval(syncTimer)
  window.removeEventListener('arch:sessions-changed', onSessionsChanged)
  window.removeEventListener('arch:conversation-removed', onConversationRemoved)
})
function onSessionsChanged() { void loadRecent() }
watch(() => conv.activeId, () => { if (conv.activeId) void maybeHintWeakModel() })

/** 任务执行器切换(待确认态): PATCH /tasks/{id}/executor。 */
async function onTaskExecutor(p: { taskId: string; executorType: string }) {
  try {
    await apiPost(`/tasks/${p.taskId}/executor`, { executorType: p.executorType })
    await conv.refreshTasks()
  } catch { conv.pushLocalHint('执行器切换失败(稍后重试)') }
}

/** 发送入口(语境路由): attachTo=转达任务卡, agent=一次性指派 subagent(后端注入指派契约), digest=语境摘要。 */
async function onSendChat(p: { text: string; attachTo?: string; agent?: string; digest?: string; synthetic?: boolean }) {
  conv.send(p.text, {
    ...(props.skillScenarios?.length ? { skillScenarios: props.skillScenarios } : {}),
    ...(props.defaultKind ? { kind: props.defaultKind } : {}),
    ...(p.attachTo ? { attachTo: p.attachTo } : {}),
    ...(p.agent ? { agent: p.agent } : {}),
    ...(p.digest ? { digest: p.digest } : {}),
    ...(p.synthetic ? { synthetic: true } : {}),
  })
  onSent()
}

/** 本地命令(/摘要 /提炼 /归档 /引导): 与工具条按钮同动作。 */
function onLocalCmd(name: string) {
  if (name === '摘要') { void summarizeTitle() }
  else if (name === '提炼') { void mineActive() }
  else if (name === '归档') { void archiveActive() }
}
function onConversationRemoved(e: Event) {
  const id = (e as CustomEvent).detail as string
  if (id) conv.dropConversation(id)
  void loadRecent()   // 会话切换浮层清单同步(删除后不残留)
}

function switchTo(meta: ConversationMeta) {
  listOpen.value = false
  void conv.openConversation(meta)
  void loadRecent()
}
function newChat() {
  listOpen.value = false
  conv.newConversation()
  void loadRecent()
}
function onSent() { void loadRecent() }

/** dock 内「刷新资产」卡事件 → 资产地图页监听的全局事件。 */
function emitRefreshAsset(id: string) {
  window.dispatchEvent(new CustomEvent('arch:refresh-asset', { detail: id }))
}

// ── 会话级执行器模型(随选随生效于下次执行; running 作业模型已固化) ──
const boundModelNames = computed<string[]>(() => {
  if (!boundExecutorId.value) return []
  const ex = executorList.value.find((e) => e.id === boundExecutorId.value) as any
  return ((ex?.config?.models) || [])
    .map((m: any) => m?.name || m?.model || '').filter(Boolean)
})
const currentExecutorModel = computed(
  () => ((conv.activeMeta as any)?.executorModel as string) || '')
async function onSetModel(model: string) {
  if (!conv.activeId) return
  try {
    const r = await apiPost<{ summary?: string }>(`/sessions/${conv.activeId}/model`,
                                                  { model })
    conv.activeMeta = { ...(conv.activeMeta as ConversationMeta),
                        executorModel: model } as ConversationMeta
    conv.pushLocalHint(String(r?.summary || '模型已切换'))
  } catch (e: any) {
    conv.pushLocalHint(`⚠️ 模型切换失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

// ── S3 coding 子会话池: 新建(清空自持上下文)/切换活跃/查看 ──
interface SubSession { id: string; title: string; executorId?: string; sessionRef?: string
  hasSessionRef?: boolean; active?: boolean; status?: string
  runningRole?: { role: string; status?: string }; msgCount?: number }
const subsOpen = ref(false)
const subsBusy = ref(false)
const subsMsg = ref('')
const codingSubs = ref<SubSession[]>([])
const isMainSession = computed(() => (conv.activeMeta as any)?.kind !== 'coding')
async function loadSubs() {
  if (!conv.activeId || !isMainSession.value) return
  try {
    codingSubs.value = await apiGet<SubSession[]>(`/sessions/${conv.activeId}/coding-sessions`)
  } catch { codingSubs.value = [] }
}
async function openSubs() {
  subsMsg.value = ''
  await loadSubs()
  subsOpen.value = true
}
async function newSub() {
  if (!conv.activeId || subsBusy.value) return
  subsBusy.value = true
  try {
    await apiPost(`/sessions/${conv.activeId}/coding-sessions`, {})
    await loadSubs()
    await syncRunningState(true)
  } catch (e: any) {
    subsMsg.value = e?.message || String(e)
  } finally { subsBusy.value = false }
}
async function activateSub(id: string) {
  if (!conv.activeId || subsBusy.value) return
  subsBusy.value = true
  try {
    await apiPost(`/sessions/${conv.activeId}/coding-sessions/${id}/activate`, {})
    await loadSubs()
  } catch (e: any) {
    subsMsg.value = e?.message || String(e)
  } finally { subsBusy.value = false }
}
function viewSub(id: string) {
  subsOpen.value = false
  listOpen.value = false
  void conv.openConversation({ id } as ConversationMeta)
}

// ── S3 投喂门: 主会话消息 → 过滤 → 活跃子会话+作业 ──
const feedBusyIdx = ref(-1)
async function onFeedTurn(p: { index: number; id?: string; summarize?: boolean }) {
  if (feedBusyIdx.value >= 0 || !conv.activeId) return
  const m = conv.turns[p.index]
  if (!m) return
  feedBusyIdx.value = p.index
  try {
    const r = await apiPost<{ summary?: string; delivered?: boolean }>(
      `/sessions/${conv.activeId}/feed`,
      { messageId: m.id || '', text: m.id ? undefined : m.content,
        ...(p.summarize ? { summarize: true } : {}) })
    conv.pushLocalHint(String(r?.summary || '已投喂'))
  } catch (e: any) {
    conv.pushLocalHint(`⚠️ 转达失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    setTimeout(() => { feedBusyIdx.value = -1 }, 600)
  }
}

// ── 执行器绑定(会话模型 v3): 一次绑定不可换; 换=克隆 ──
interface ExecutorRow { id: string; type: string; enabled?: boolean }
const executorList = ref<ExecutorRow[]>([])
const boundExecutorId = computed(
  () => ((conv.activeMeta as any)?.executorId as string) || '')
// ── 生命周期重构: 工作相位 + 角色集声明 + 作业控制 ──
watch(() => conv.activeId, () => { void loadSubs() })

async function loadExecutors() {
  try {
    const r = await apiGet<{ executors: ExecutorRow[] }>('/agent/executors')
    executorList.value = (r?.executors || []).filter((e) => e.enabled !== false)
  } catch { /* 绑定器降级为空列表 */ }
}
onMounted(() => { void loadExecutors() })

const workState = computed(() => ((conv.activeMeta as any)?.workState as string) || 'architect')
const isRunning = computed(() => workState.value === 'running'
  && (conv.activeMeta as any)?.status !== 'archived')
// 绑定需求的 architect 态会话: 「引导」按钮可见(触发词提示按需输出)
const isExecutionConv = computed(() =>
  !!(conv.activeReqId) && (conv.activeMeta as any)?.status !== 'archived'
  && !isRunning.value)

/** 模型准入提示(三维矩阵): 会话模型测评 T2(弱, 全面补偿档)时提示换更强模型——
 * 刻度细则见 agent/governance/gears.py; 提示不拦截(可按 T2 最低档运行)。
 * 每次会话打开提示一次(不弹窗不打断, 本地消息)。 */
const t2Hinted = new Set<string>()
let capProfilesCache: Record<string, any> | null = null
async function maybeHintWeakModel() {
  const mid = readModelPref('architect') || ''
  if (!mid || t2Hinted.has(conv.activeId) || t2Hinted.has(mid)) return
  try {
    if (!capProfilesCache) {
      const d = await apiGet<{ profiles: any[] }>('/llm/model-profiles')
      capProfilesCache = Object.fromEntries((d.profiles ?? []).map((p: any) => [p.modelId, p]))
    }
    const p = capProfilesCache[mid]
    if (p && Number(p.tier) === 2) {
      t2Hinted.add(conv.activeId); t2Hinted.add(mid)
      conv.pushLocalHint('💡 模型准入提示: 当前会话模型测评较弱(T2 档, <6B 级)。系统将按全面补偿模式运行(结构化指令+核心逻辑图+步骤编排), 但产出质量与速度受限——建议在模型设置中切换 T0/T1 档模型。')
    }
  } catch { /* profiles 不可得 → 不提示 */ }
}

/** 分析挡位(会话级 strict/quick): 本地镜像(即时反馈) + 切换会话时从 activeMeta 同步; 变更上抛 REST 即时生效。 */
const analysisMode = ref<'strict' | 'quick'>('strict')
/** 需求澄清挡位(cv-190): auto | forced——随会话打开从真相源同步。 */
const clarifyMode = ref<'auto' | 'forced'>('auto')
/** worktree 隔离模式(cv-202): 缺省就地。 */
const isolated = ref(false)
watch(() => conv.activeId, () => {
  analysisMode.value = ((conv.activeMeta as any)?.analysisMode as 'strict' | 'quick') || 'strict'
  clarifyMode.value = ((conv.activeMeta as any)?.clarifyMode as 'auto' | 'forced') || 'auto'
  isolated.value = !!(conv.activeMeta as any)?.isolated
})
async function onSetClarifyMode(mode: 'auto' | 'forced') {
  if (!conv.activeId) return
  clarifyMode.value = mode // 本地即时反馈(不等 REST)
  try {
    const r = await apiPost<{ clarifyMode?: 'auto' | 'forced' }>(`/sessions/${conv.activeId}/clarify-mode`, { mode })
    if (r?.clarifyMode) clarifyMode.value = r.clarifyMode
    if (conv.activeMeta) (conv.activeMeta as any).clarifyMode = clarifyMode.value
  } catch { /* REST 失败保留本地值(下轮打开会话时从后端真相源校正) */ }
}

async function onSetIsolated(on: boolean) {
  if (!conv.activeId) return
  isolated.value = on
  try {
    const r = await apiPost<{ isolated?: boolean }>(`/sessions/${conv.activeId}/isolated`, { on })
    if (typeof r?.isolated === 'boolean') isolated.value = r.isolated
    if (conv.activeMeta) (conv.activeMeta as any).isolated = isolated.value
  } catch { /* REST 失败保留本地值 */ }
}

async function onSetAnalysisMode(mode: 'strict' | 'quick') {
  if (!conv.activeId) return
  analysisMode.value = mode // 本地即时反馈(不等 REST)
  try {
    const r = await apiPost<{ analysisMode?: 'strict' | 'quick' }>(`/sessions/${conv.activeId}/analysis-mode`, { mode })
    if (r?.analysisMode) analysisMode.value = r.analysisMode
    if (conv.activeMeta) (conv.activeMeta as any).analysisMode = analysisMode.value
  } catch { /* REST 失败保留本地值(下轮打开会话时从后端真相源校正) */ }
}

/** 引导消息: 仅渲染进对话流(本地), 不发后端/不进上下文, 切换会话自然消失。 */
const GUIDE_MD = [
  '⚡ **会话引导**（仅本地提示，不进入对话上下文）',
  '',
  '- 直接对话: architect 外循环帮你分析/设计方案',
  '- 方案成熟时 architect 会出**任务卡**——确认后 coding subagent 开始执行',
  '- 也可用输入框 @ 选择器直接指派 `@cline`',
  '- subagent 提问(⏸)/完成(✅)/失败(❌)都落本会话流; 回复即转达',
  '- 顶部 tab(全部/architect/coding)过滤查看两类消息',
].join('\n')
const guideBusy = ref(false)
async function showGuide() {
  if (!isExecutionConv.value || guideBusy.value) return
  guideBusy.value = true
  try {
    // agent 建议: 后端按会话状态(RQ 版本链/作业账本/最近消息)生成, 旁路不进上下文
    const r = conv.activeId
      ? await sessionService.guide(conv.activeId).catch(() => ({ text: '', fallback: true }))
      : { text: '', fallback: true }
    conv.pushLocalHint((r?.text || '').trim() || GUIDE_MD)
  } finally {
    guideBusy.value = false
  }
}

// ── 「写入需求」按钮: 规约 JSON 确定性落库(零 LLM), 结果本地消息 ──
const specApplyBusy = ref(false)
async function onSpecApply(p: { index: number; payload: Record<string, unknown> }) {
  if (specApplyBusy.value || !conv.activeId) return
  specApplyBusy.value = true
  try {
    const r = await apiPost<Record<string, any>>(`/sessions/${conv.activeId}/spec-apply`, {
      payload: p.payload,
    })
    conv.pushLocalHint(
      String(r?.summary || '落库未产出结果')
      + (r?.ok ? '；可继续对话让 architect 发起任务。' : ''))
  } catch (e) {
    conv.pushLocalHint(`⚠️ 写入需求失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    specApplyBusy.value = false
  }
}
// running 归属(S2 双收件人): 推导字段来自会话行(后端 runningRole), 不再锁定输入
const jobState = computed(() =>
  ((conv.activeMeta as any)?.runningRole as { role: string; executorId?: string; status?: string } | undefined) || null)

// RQ 状态徽标 + 登记簿完成标记(第二入口, 裁决#3/#8)
const reqStatus = ref<{ id: string; status?: string; activeVer?: number } | null>(null)
const markDoneBusy = ref(false)
async function refreshReqStatus() {
  if (!conv.activeReqId) { reqStatus.value = null; return }
  try {
    reqStatus.value = await apiGet(`/requirements/${conv.activeReqId}`)
  } catch { reqStatus.value = null }
}
watch(() => conv.activeReqId, () => { void refreshReqStatus() }, { immediate: true })
async function markReqDone(done: boolean) {
  if (!conv.activeReqId || markDoneBusy.value) return
  markDoneBusy.value = true
  try {
    await apiPost(`/requirements/${conv.activeReqId}/done`, { done })
    await refreshReqStatus()
  } catch { /* 无碍 */ } finally {
    markDoneBusy.value = false
  }
}

// 执行器绑定/克隆对话框: 未绑定 → bind(一次); 已绑定 → clone(换执行器开新会话)
const rolesOpen = ref(false)
const rolesDraft = ref('')
const rolesBusy = ref(false)
const rolesMsg = ref('')
const bindMode = computed<'bind' | 'clone'>(() => (boundExecutorId.value ? 'clone' : 'bind'))
async function openRoles() {
  rolesMsg.value = ''
  rolesDraft.value = ''
  if (!executorList.value.length) await loadExecutors()
  rolesOpen.value = true
}
async function saveRoles() {
  if (!conv.activeId || rolesBusy.value || !rolesDraft.value) return
  rolesBusy.value = true
  rolesMsg.value = ''
  try {
    if (bindMode.value === 'bind') {
      const updated = await apiPost(`/sessions/${conv.activeId}/bind`,
                                    { executorId: rolesDraft.value })
      conv.activeMeta = { ...(conv.activeMeta as ConversationMeta),
                          executorId: (updated as any)?.executorId ?? rolesDraft.value } as ConversationMeta
      rolesOpen.value = false
    } else {
      const created = await apiPost(`/sessions/${conv.activeId}/clone`,
                                    { executorId: rolesDraft.value })
      rolesOpen.value = false
      const newId = (created as any)?.id
      if (newId) {
        listOpen.value = false
        await conv.openConversation({ id: newId } as ConversationMeta)
      }
    }
  } catch (e: any) {
    rolesMsg.value = e?.message || String(e)
  } finally {
    rolesBusy.value = false
  }
}

/** 工具栏执行器选择(与 saveRoles 同链): 未绑=bind; 已绑切换=克隆新会话(显式确认)。 */
async function onBindExecutor(executorId: string) {
  if (!conv.activeId || !executorId || executorId === boundExecutorId.value) return
  if (boundExecutorId.value) {
    const okGo = await dialog.confirm(
      `会话已绑定「${boundExecutorId.value}」。\n切换到「${executorId}」将克隆一个新会话（绑定不可换），继续？`,
      { danger: true })
    if (!okGo) return
  }
  try {
    if (!boundExecutorId.value) {
      const updated = await apiPost(`/sessions/${conv.activeId}/bind`,
                                    { executorId })
      conv.activeMeta = { ...(conv.activeMeta as ConversationMeta),
                          executorId: (updated as any)?.executorId ?? executorId } as ConversationMeta
    } else {
      const created = await apiPost(`/sessions/${conv.activeId}/clone`,
                                    { executorId })
      const newId = (created as any)?.id
      if (newId) await conv.openConversation({ id: newId } as ConversationMeta)
    }
  } catch (e: any) {
    void dialog.alert(e?.message || String(e))
  }
}

// 作业控制: 停止(仅 UI, 裁决#5) / 继续执行(增量回合)
const stopBusy = ref(false)
async function stopExec() {
  if (!conv.activeId || stopBusy.value) return
  stopBusy.value = true
  try {
    await apiPost(`/sessions/${conv.activeId}/stop-exec`, {})
    await syncRunningState(true)
  } catch { /* 提示随对账刷新 */ } finally {
    stopBusy.value = false
  }
}

// 流程相位(会话状态机): 徽章展示 + interrupted 恢复动作(governance/flow.py)
const flowPhase = computed(() => String((conv.activeMeta as any)?.flowState || ''))
function flowLabel(p: string): string {
  const k = `session.flow.${p}`
  return t(k) === k ? p : t(k)
}
const flowRecoverBusy = ref(false)
async function recoverFlow() {
  if (!conv.activeId || flowRecoverBusy.value) return
  flowRecoverBusy.value = true
  try {
    await apiPost(`/sessions/${conv.activeId}/recover`, {})
    await conv.refreshActiveMeta()
    void conv.refreshActiveMessages()
  } catch { /* 状态随对账刷新 */ } finally {
    flowRecoverBusy.value = false
  }
}

// 回执已阅(reviewing 消化出口): dismiss → 相位重算(合并/建下张卡之外的显式消化)
async function onTaskDismiss(id: string) {
  try {
    await apiPost(`/tasks/${id}/dismiss`, {})
    void conv.refreshTasks()
    void conv.refreshActiveMeta()
    void conv.refreshActiveMessages()
  } catch { /* 状态随对账刷新 */ }
}
// running 态准实时同步: 复用 5s 轮询——刷新 workState + 增量消息(泵产物)
async function syncRunningState(force = false) {
  if (!conv.activeId) return
  if (!force && !isRunning.value) return
  if (!scopePid()) return   // cv-205: 无项目上下文不查询(硬隔离)
  try {
    // cv-205: 活动会话必属当前项目——按项目查(不发 scope=all)
    const list = await sessionService.list({ limit: 400, project: scopePid() })
    const meta = list.find((c) => c.id === conv.activeId)
    if (meta) {
      const prev = workState.value
      conv.activeMeta = { ...(conv.activeMeta as ConversationMeta),
                          workState: (meta as any).workState } as ConversationMeta
      if ((meta as any).workState === 'running') {
        // 执行中轮询兜底: SSE progress 丢帧/断连时, 过程面板仍按库中 progress(0.5s 节流落库)刷新
        void conv.refreshTasks()
      }
      if (prev === 'running' && (meta as any).workState !== 'running') {
        // 相位回落(回合结束/终态) → 全量拉一次消息(泵期间的增量可见)
        const detail = await sessionService.messages(conv.activeId)
        conv.applyConversation({ ...detail, reqId: conv.activeReqId })
      }
    }
  } catch { /* 列表失败无碍 */ }
}

// 命名规约提议卡(资产对话): 确认固化 / 忽略(原资产页逻辑迁至 dock)
async function onConventionConfirm(id: string) {
  try { await namingService.updateConvention(id, { status: 'active' }) } catch { /* 忽略 */ }
}
async function onConventionIgnore(id: string) {
  try { await namingService.deleteConvention(id) } catch { /* 忽略 */ }
}

// ── running 相位轮询同步(workState/泵消息); 旧 bus 澄清通道已移除(指令符号体系) ──
let syncTimer: ReturnType<typeof setInterval> | null = null
async function pollRunningState() {
  if (!conv.dockOpen) return
  void syncRunningState()          // running 相位准实时同步(workState/泵消息)
}
</script>

<template>
  <!-- 收起态: 右缘浮标(仅全局悬浮形态) -->
  <button
    v-if="!props.inline && !conv.dockOpen"
    class="fixed right-0 top-1/2 z-40 -translate-y-1/2 rounded-l-xl border border-r-0 border-ctp-surface1 bg-ctp-mantle px-1.5 py-4 text-ctp-subtext0 shadow-lg hover:text-ctp-text"
    :title="t('session.dock.open')"
    @click="conv.setDockOpen(true)"
  >
    <ChatBubbleOvalLeftEllipsisIcon class="h-5 w-5" />
  </button>

  <!-- 展开态: 全局悬浮(右缘 overlay) / inline(页面右栏停靠) -->
  <aside
    v-else-if="props.inline || conv.dockOpen"
    :class="props.inline
      ? 'relative flex h-full min-h-0 w-full flex-col bg-ctp-base'
      : 'fixed right-0 top-0 z-40 flex h-full w-[26rem] flex-col border-l border-ctp-surface0 bg-ctp-base shadow-2xl'"
  >
    <!-- 头部: 标题 + kind + 会话切换(仅悬浮形态; inline 停靠的标题编辑在对话面板 header 内) -->
    <div v-if="!props.inline" class="relative shrink-0 border-b border-ctp-surface0 px-3 py-2">
      <div class="flex items-center gap-2">
        <span class="group/t flex min-w-0 flex-1 items-center gap-1">
          <input
            v-if="editingTitle"
            v-model="titleDraft"
            class="input w-full min-w-0 !px-1.5 !py-0.5 text-xs"
            @click.stop
            @keydown.enter.prevent="saveTitle"
            @keydown.esc="editingTitle = false"
            @blur="saveTitle"
          >
          <template v-else>
            <span class="min-w-0 truncate text-xs font-medium text-ctp-text">
              {{ conv.activeTitle || t('session.dock.untitled') }}
            </span>
            <span
              v-if="conv.activeId"
              class="hidden shrink-0 items-center gap-0.5 group-hover/t:flex"
            >
              <button class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface0 hover:text-ctp-blue" :title="t('session.actions.rename')" @click.stop="startTitleEdit">
                <PencilSquareIcon class="h-3 w-3" />
              </button>
              <button class="rounded p-0.5 text-ctp-overlay0 hover:bg-ctp-surface0 hover:text-ctp-blue" :title="t('session.actions.summarize')" @click.stop="summarizeTitle">
                <SparklesIcon class="h-3 w-3" :class="titleSummarizing ? 'animate-pulse' : ''" />
              </button>
            </span>
          </template>
        </span>
        <template v-if="!props.inline">
          <button
            class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface0 hover:text-ctp-text"
            :title="t('session.dock.newChat')"
            @click="newChat"
          >
            <PlusIcon class="h-4 w-4" />
          </button>
          <button
            class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface0 hover:text-ctp-text"
            :title="t('session.dock.switch')"
            @click="listOpen = !listOpen"
          >
            <ChevronDownIcon class="h-4 w-4" />
          </button>
          <button
            class="rounded p-1 text-ctp-subtext0 hover:bg-ctp-surface0 hover:text-ctp-text"
            :title="t('common.close')"
            @click="conv.setDockOpen(false)"
          >
            <XMarkIcon class="h-4 w-4" />
          </button>
        </template>
      </div>

      <!-- 会话切换浮层 -->
      <div
        v-if="listOpen"
        class="absolute left-2 right-2 top-full z-50 max-h-80 overflow-auto rounded-lg border border-ctp-surface1 bg-ctp-mantle p-1 shadow-xl"
      >
        <button
          v-for="c in recent"
          :key="c.id"
          class="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-ctp-surface0"
          :class="c.id === conv.activeId ? 'bg-ctp-surface0' : ''"
          @click="switchTo(c)"
        >
          <span class="min-w-0 flex-1 truncate text-ctp-text">{{ c.title }}</span>
          <span
            v-if="c.reviewState && c.reviewState !== 'read'"
            class="h-1.5 w-1.5 shrink-0 rounded-full"
            :class="c.reviewState === 'error' ? 'bg-ctp-red' : c.reviewState === 'awaiting_reply' ? 'bg-ctp-yellow' : 'bg-ctp-blue'"
          />
          <span class="shrink-0 text-[10px] text-ctp-overlay0">{{ c.msgCount }}</span>
        </button>
        <p v-if="!recent.length" class="px-2 py-3 text-center text-xs text-ctp-overlay0">
          {{ t('common.empty') }}
        </p>
      </div>
    </div>

    <!-- 会话信息面板(可折叠): 待执行方案 / 操作 / 待审提案 / 关联执行 -->
    <!-- 对话主体 -->
    <div class="min-h-0 flex-1">
      <!-- coding 子会话池(S3): 新建/切换/查看 -->
      <div
        v-if="subsOpen"
        class="absolute inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
        @click.self="subsOpen = false"
      >
        <div class="panel w-full max-w-sm">
          <div class="panel-header">
            <span>{{ t('session.subs.title') }}</span>
            <button class="btn btn-xs btn-ghost" @click="subsOpen = false">
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
          <div class="p-3 space-y-2">
            <p class="text-[11px] text-ctp-subtext0">{{ t('session.subs.hint') }}</p>
            <p v-if="subsMsg" class="text-[11px] text-ctp-yellow break-all">{{ subsMsg }}</p>
            <div
              v-for="s in codingSubs"
              :key="s.id"
              role="button"
              tabindex="0"
              class="w-full flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors cursor-pointer"
              :class="s.active ? 'border-ctp-blue/50 bg-ctp-blue/5' : 'border-ctp-surface1 hover:border-ctp-blue/40'"
              @click="activateSub(s.id)"
              @keydown.enter.prevent="activateSub(s.id)"
            >
              <span
                class="h-2 w-2 shrink-0 rounded-full"
                :class="s.runningRole?.role === 'coding'
                  ? (s.runningRole.status === 'waiting_input' ? 'bg-ctp-yellow' : 'bg-ctp-peach animate-pulse')
                  : (s.active ? 'bg-ctp-blue' : 'bg-ctp-overlay1')"
              />
              <span class="min-w-0 flex-1">
                <span class="block text-xs text-ctp-text truncate">{{ s.title }}</span>
                <span class="block text-[10px] text-ctp-subtext0">
                  {{ s.hasSessionRef ? '● 有执行器会话(可复活)' : '○ 新上下文' }}
                  · {{ s.msgCount || 0 }} 条
                  <template v-if="s.runningRole?.role === 'coding'">· {{ s.runningRole.status }}</template>
                </span>
              </span>
              <span v-if="s.active" class="chip !text-[9px] bg-ctp-blue/15 text-ctp-blue">{{ t('session.subs.active') }}</span>
              <button
                class="btn btn-xs btn-ghost shrink-0"
                :title="t('session.subs.view')"
                @click.stop="viewSub(s.id)"
              >↗</button>
            </div>
            <p v-if="!codingSubs.length" class="text-[11px] text-ctp-overlay1">
              {{ t('session.subs.empty') }}
            </p>
            <button
              class="btn btn-primary w-full !py-1.5 text-xs"
              :disabled="subsBusy"
              @click="newSub"
            >{{ subsBusy ? '…' : t('session.subs.new') }}</button>
          </div>
        </div>
      </div>

      <!-- roles 声明器(能力声明即用, 不锁定) -->
      <div
        v-if="rolesOpen"
        class="absolute inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
        @click.self="rolesOpen = false"
      >
        <div class="panel w-full max-w-sm">
          <div class="panel-header">
            <span>{{ t('session.role.manageTitle') }}</span>
            <button class="btn btn-xs btn-ghost" @click="rolesOpen = false">
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
          <div class="p-3 space-y-2">
            <p class="text-[11px] text-ctp-subtext0">{{ t('session.role.manageHint') }}</p>
            <p v-if="boundExecutorId" class="text-[11px] text-ctp-blue break-all">
              {{ t('session.role.bound') }}: {{ boundExecutorId }}
            </p>
            <p v-if="rolesMsg" class="text-[11px] text-ctp-yellow break-all">{{ rolesMsg }}</p>
            <button
              v-for="e in executorList"
              :key="e.id"
              class="w-full flex items-center gap-2 rounded-lg border px-3 py-2 text-left transition-colors"
              :class="rolesDraft === e.id ? 'border-ctp-blue/50 bg-ctp-blue/5' : 'border-ctp-surface1 hover:border-ctp-blue/40'"
              @click="rolesDraft = e.id"
            >
              <span
                class="h-3 w-3 shrink-0 rounded-full border"
                :class="rolesDraft === e.id ? 'bg-ctp-blue border-ctp-blue' : 'border-ctp-overlay1'"
              />
              <span class="min-w-0 flex-1">
                <span class="block text-xs text-ctp-text">{{ e.id }}</span>
                <span class="block text-[10px] text-ctp-subtext0">{{ t('session.role.executorOf') }}: {{ e.type || '—' }}</span>
              </span>
              <span v-if="e.id === boundExecutorId" class="chip !text-[9px] bg-ctp-surface0/60">{{ t('session.role.bound') }}</span>
            </button>
            <p v-if="!executorList.length" class="text-[11px] text-ctp-overlay1">
              {{ t('session.role.noExecutors') }}
            </p>
            <button
              class="btn btn-primary w-full !py-1.5 text-xs"
              :disabled="rolesBusy || !rolesDraft"
              @click="saveRoles"
            >{{ rolesBusy ? t('common.saving') : (bindMode === 'bind' ? t('session.role.bind') : t('session.role.clone')) }}</button>
          </div>
        </div>
      </div>

      <AnalysisChat
        class="h-full"
        :turns="conv.turns"
        :busy="conv.busy"
        :busy-label="conv.busyLabel"
        :tool-trail="conv.toolTrail"
        :insert-draft="conv.insertDraft"
        :title="conv.activeTitle || t('session.dock.untitled')"
        :editable="!!conv.activeId && !conv.busy"
        :title-summarizing="titleSummarizing"
        @rename="onRenameTitle"
        @summarize-title="summarizeTitle"
        :diagram-skill="conv.diagramSkill"
        :read-only="(conv.activeMeta as any)?.status === 'archived'"
        :show-assets-panel="props.assetsPanel"
        :job-state="jobState"
        :bound-executor-id="boundExecutorId"
        :executor-models="boundModelNames"
        :executors="executorList"
        :executor-model="currentExecutorModel"
        :analysis-mode="analysisMode"
        :clarify-mode="clarifyMode"
        :isolated="isolated"
        :has-session="!!conv.activeId"
        :conv-id="conv.activeId || undefined"
        :tasks="conv.tasks"
        :ctx-usage="((conv.activeMeta as any)?.meta?.ctxUsage) ?? null"
        @set-analysis-mode="onSetAnalysisMode"
        @set-clarify-mode="onSetClarifyMode"
        @set-isolated="onSetIsolated"
        @task-confirm="(id: string) => void conv.taskAction(id, 'confirm')"
        @task-cancel="(id: string) => void conv.taskAction(id, 'cancel')"
        @task-ignore="(id: string) => void conv.taskAction(id, 'ignore')"
        @task-dismiss="(id: string) => void onTaskDismiss(id)"
        @task-executor="(p: any) => void onTaskExecutor(p)"
        @local-cmd="onLocalCmd"
        @bind-coding="openRoles"
        @bind-executor="onBindExecutor"
        @set-model="onSetModel"
        @send="onSendChat"
        @feed-turn="onFeedTurn"
        @spec-apply="onSpecApply"
        @answers="(a) => { conv.sendAnswers(a); onSent() }"
        @delete-turn="conv.deleteTurn"
        @rollback-to="conv.rollbackTo"
        @toggle-diagram-skill="conv.toggleDiagramSkill"
        @convention-confirm="onConventionConfirm"
        @convention-ignore="onConventionIgnore"
        @refresh-asset="emitRefreshAsset"
        @stop="conv.stop"
      >
        <!-- 内联按钮: 子会话池(多子会话管理; 单子会话时 Coding 入口即全部) -->
        <template #header-inline>
          <button
            v-if="isMainSession && codingSubs.length > 1"
            class="btn !py-0 !px-2 !text-[10px]"
            :title="t('session.subs.title')"
            @click="openSubs"
          >{{ t('session.subs.manage') }}({{ codingSubs.length }})</button>
        </template>
        <template #header-extra>
          <div v-if="conv.activeId" class="flex shrink-0 items-center gap-1.5">
            <span
              v-if="flowPhase && flowPhase !== 'free'"
              class="chip !text-[10px]"
              :class="flowPhase === 'interrupted' ? 'bg-ctp-red/15 text-ctp-red'
                : flowPhase === 'executing' ? 'bg-ctp-blue/15 text-ctp-blue'
                : 'bg-ctp-surface0/60 text-ctp-subtext1'"
              :title="t('session.flow.title')"
            >◈ {{ flowLabel(flowPhase) }}</span>
            <button
              v-if="flowPhase === 'interrupted'"
              class="btn !py-0 !px-1.5 !text-[10px]"
              :disabled="flowRecoverBusy"
              :title="t('session.flow.recoverHint')"
              @click="recoverFlow"
            >{{ t('session.flow.recover') }}</button>
            <span
              v-if="reqStatus && (conv.activeMeta as any)?.status !== 'archived'"
              class="chip !text-[10px]"
              :class="reqStatus.status === 'ready' ? 'bg-ctp-green/15 text-ctp-green'
                : reqStatus.status === 'done' ? 'bg-ctp-overlay0/20 text-ctp-overlay1' : 'bg-ctp-surface0/60 text-ctp-subtext1'"
              :title="t('session.reqState.title')"
            >{{ conv.activeReqId }} · {{ t(`req.status.${reqStatus.status || 'raw'}`) }}<template v-if="reqStatus.activeVer"> v{{ reqStatus.activeVer }}</template></span>
            <button
              v-if="reqStatus?.status === 'ready' || reqStatus?.status === 'done'"
              class="btn !py-0 !px-1.5 !text-[10px]"
              :class="reqStatus.status === 'done' ? 'btn-ghost' : ''"
              :disabled="markDoneBusy"
              :title="reqStatus.status === 'done' ? t('session.reqState.title') : t('session.job.acceptHint')"
              @click="markReqDone(reqStatus.status !== 'done')"
            >{{ reqStatus.status === 'done' ? t('session.reqState.undoDone') : t('session.reqState.markDone') }}</button>
            <span
              v-if="isRunning"
              class="chip !text-[10px] animate-pulse inline-flex items-center gap-1"
              :class="jobState?.role === 'coding' ? 'bg-ctp-peach/15 text-ctp-peach' : 'bg-ctp-blue/15 text-ctp-blue'"
              :title="`${t('session.workState.runningHint')}${(jobState as any)?.progress ? `\\n工具调用 ×${(jobState as any).progress.toolCount} · 消息 ×${(jobState as any).progress.msgCount} · ${new Date((jobState as any).progress.at || 0).toLocaleTimeString()}` : ''}`"
            >▶ {{ jobState?.role === 'coding'
              ? `coding·${jobState.executorId || '?'}${jobState.status === 'waiting_input' ? ' · 等待回复' : (jobState as any)?.progress ? ` · ⚙×${(jobState as any).progress.toolCount}` : ''}`
              : t('session.workState.running') }}<button
                class="ml-0.5 rounded px-1 text-ctp-red hover:bg-ctp-red/15"
                :disabled="stopBusy"
                :title="t('session.job.stop')"
                @click.stop="stopExec"
              >⏹</button></span>
          </div>
        </template>
        <template #toolbar-extra>
          <!-- 会话大纲浮窗开关(会话中心启用): 开合两态均缩略为此按钮 -->
          <button
            v-if="props.outline"
            class="btn btn-xs !px-1.5"
            :class="outlineOpen ? 'btn-blue' : 'btn-ghost'"
            :disabled="!conv.activeId"
            :title="t('session.outline.title')"
            @click="outlineOpen = !outlineOpen"
          ><ListBulletIcon class="w-3.5 h-3.5" /></button>
          <!-- 纯 icon 工具条(title 提示); 动作均可用 /命令 触达(引导/摘要/提炼/归档) -->
          <button
            v-if="isExecutionConv"
            class="btn btn-xs btn-ghost !px-1.5"
            :disabled="guideBusy"
            :title="`${t('session.actions.guide')} — /引导`"
            @click="showGuide"
          ><BookOpenIcon class="w-3.5 h-3.5" :class="guideBusy ? 'animate-pulse' : ''" /></button>
          <button
            class="btn btn-xs !px-1.5"
            :class="titleSummarizing ? 'btn-blue' : 'btn-ghost'"
            :disabled="titleSummarizing || !conv.activeId"
            :title="`${t('session.actions.summarize')} — /摘要`"
            @click="summarizeTitle"
          ><DocumentTextIcon class="w-3.5 h-3.5" :class="titleSummarizing ? 'animate-pulse' : ''" /></button>
          <button
            class="btn btn-xs btn-ghost !px-1.5"
            :disabled="mining || !activeProject()"
            :title="`${t('session.mine')} — /提炼`"
            @click="mineActive"
          ><CubeTransparentIcon class="w-3.5 h-3.5" :class="mining ? 'animate-pulse' : ''" /></button>
          <button
            class="btn btn-xs btn-ghost !px-1.5"
            :disabled="!conv.activeId || (conv.activeMeta as any)?.status === 'archived'"
            :title="`${t('session.archive')} — /归档`"
            @click="archiveActive"
          ><ArchiveBoxIcon class="w-3.5 h-3.5" /></button>
        </template>
      </AnalysisChat>
    </div>

    <!-- 会话大纲浮窗(Teleport body): 关闭/最小化缩回工具栏大纲按钮 -->
    <SessionOutlineWindow
      v-if="props.outline && outlineOpen"
      @close="outlineOpen = false"
    />
  </aside>
</template>
