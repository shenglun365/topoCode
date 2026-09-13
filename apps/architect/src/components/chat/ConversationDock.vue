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
  PencilSquareIcon, SparklesIcon,
} from '@heroicons/vue/24/outline'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import { useConversationStore } from '@/stores/conversation-store'
import { sessionService, type ConversationMeta } from '@/services/session-service'
import { namingService } from '@/services/naming-service'
import { apiBaseUrl, apiGet, apiPost } from '@/services/api-client'

const props = withDefaults(defineProps<{
  /** inline=停靠形态(页面右栏内嵌)；缺省=全局右侧悬浮 dock。 */
  inline?: boolean
  /** 新建会话的默认类型(资产地图页传 asset, 会话中心传 requirement)——首条消息创建会话时落库。 */
  defaultKind?: string
  /** 页面级技能场景(如资产地图=['extract'])：随发送注入。 */
  skillScenarios?: string[]
  /** 场景标识(sessions=会话中心 / asset=资产管理)：对话状态按场景隔离互不影响。 */
  scope?: string
}>(), { inline: false })

const { t } = useI18n()
const dialog = useAppDialog()
const router = useRouter()
const conv = useConversationStore()

const recent = ref<ConversationMeta[]>([])
const listOpen = ref(false)

// ── 会话操作(工具条): 提炼报告由服务端沉淀为会话消息 ──
const mining = ref(false)
function activeProject(): string {
  return ((conv.activeMeta as any)?.projectId || '') as string
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
    // scope=all: 跨全库汇总 — 与会话中心同口径(会话管理+资产管理统一视图)
    recent.value = await sessionService.list({ limit: 30, scope: 'all' })
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
  connectConvEvents()
})
onUnmounted(() => {
  if (syncTimer) clearInterval(syncTimer)
  window.removeEventListener('arch:sessions-changed', onSessionsChanged)
  window.removeEventListener('arch:conversation-removed', onConversationRemoved)
  disconnectConvEvents()
})
function onSessionsChanged() { void loadRecent() }

/** ── 会话事件流(SSE): job 消息实时刷新 + coding 子会话未读 badge ── */
let evtSource: EventSource | null = null
let evtReconnect: ReturnType<typeof setTimeout> | null = null
let refreshPending: ReturnType<typeof setTimeout> | null = null
function onConvEvent(d: any) {
  if (d?.type === 'sub-unread' && d.conversationId === conv.activeId) {
    conv.subUnread = Number(d.count) || 0
    return
  }
  if (d?.type !== 'conv-message' || !d.conversationId) return
  if (d.conversationId === conv.activeId && conv.viewMode === 'main') {
    // 主视图: 主会话新消息(作业 done 卡等) → 防抖重拉
    if (refreshPending) clearTimeout(refreshPending)
    refreshPending = setTimeout(() => {
      refreshPending = null
      void conv.refreshActiveMessages()
    }, 400)
  } else if (d.conversationId === conv.activeSubId && conv.viewMode === 'coding') {
    // coding 视图: 活跃子会话新消息 → 重拉子流
    if (refreshPending) clearTimeout(refreshPending)
    refreshPending = setTimeout(() => {
      refreshPending = null
      void conv.refreshSubMessages()
    }, 400)
  }
}
function connectConvEvents() {
  try {
    evtSource = new EventSource(`${apiBaseUrl()}/events`)
    evtSource.onmessage = (ev) => {
      try { onConvEvent(JSON.parse(ev.data)) } catch { /* 非事件帧忽略 */ }
    }
    evtSource.onerror = () => {
      disconnectConvEvents()
      evtReconnect = setTimeout(connectConvEvents, 5000)
    }
  } catch { /* SSE 不可用(离线) → 退化为手动刷新 */ }
}
function disconnectConvEvents() {
  evtSource?.close()
  evtSource = null
  if (evtReconnect) { clearTimeout(evtReconnect); evtReconnect = null }
}

/** 角色即视图: coding → 切子会话信息流(无子会话提示); architect → 回主会话流。 */
async function onRoleChange(role: 'architect' | 'coding') {
  if (role === 'coding') {
    const ok = await conv.setViewMode('coding')
    if (!ok) conv.pushLocalHint('暂无 coding 子会话——`/执行` 启动作业后自动创建')
  } else {
    void conv.setViewMode('main')
  }
}
function onConversationRemoved(e: Event) {
  const id = (e as CustomEvent).detail as string
  if (id) conv.dropConversation(id)
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
function onGotoRequirements(reqId?: string) {
  // 提案卡 → 会话中心定位(需求深链优先——按 reqId 匹配会话; 兜底当前会话)。
  // 同页 query 变化由 SessionsPage watch 响应(选中并打开对话栏)。
  const select = reqId || conv.activeId || undefined
  router.push({ path: '/workbench/sessions', query: select ? { select } : undefined })
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

/** 指令符号表(与后端 SESSION_CMDS 对齐): 引导消息 chips 点击填入对话框 */
const SESSION_CMDS: Array<{ cmd: string; desc: string }> = [
  { cmd: '/执行', desc: '预览执行方案' },
  { cmd: '/确认执行', desc: '启动执行作业' },
  { cmd: '/定稿', desc: '确认规约版本(ready)' },
  { cmd: '/继续', desc: '转达补充给作业' },
  { cmd: '/diff', desc: '查看作业差异' },
  { cmd: '/调整', desc: '修订需求/方案' },
]
function fillCmd(cmd: string) {
  conv.pushDraft(cmd)
}

/** 引导消息: 仅渲染进对话流(本地), 不发后端/不进上下文, 切换会话自然消失。 */
const GUIDE_MD = [
  '⚡ **会话引导**（仅本地提示，不进入对话上下文）',
  '',
  '- `/执行` 生成执行预览 → `/确认执行` 启动作业',
  '- `/调整` + 调整点 修订规约（生成新 draft 版本）',
  '- 作业提问时直接回复补充 → `/继续` 转达给 agent',
  '- `/diff` 查看作业产物；完成后可标记需求完成',
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

// ── 守卫卡片指令: guard-repair 独立外循环修复, 结果本地消息(不落库/不进上下文) ──
const guardRepairBusy = ref(false)
async function onGuardRepair(p: { index: number; meta: Record<string, any>; action: string }) {
  if (guardRepairBusy.value || !conv.activeId) return
  guardRepairBusy.value = true
  try {
    const m = conv.turns[p.index]
    const r = await apiPost<Record<string, any>>(`/sessions/${conv.activeId}/guard-repair`, {
      messageId: m?.id || '', claim: p.meta?.claim || '',
      need: p.meta?.need || '', content: m?.content || '', action: p.action,
    })
    conv.pushLocalHint(
      String(r?.summary || (r?.action === 'corrected' ? (r as any)?.correction : '') || '修复未产出结果'))
  } catch (e) {
    conv.pushLocalHint(`⚠️ 守卫修复失败：${e instanceof Error ? e.message : String(e)}`)
  } finally {
    guardRepairBusy.value = false
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
      + (r?.ok ? '；可发送 `/定稿` 或 `/执行` 继续。' : ''))
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
function resumeJob() {
  void conv.send('/继续', { ...(props.skillScenarios?.length ? { skillScenarios: props.skillScenarios } : {}) })
  onSent()
}

// running 态准实时同步: 复用 5s 轮询——刷新 workState + 增量消息(泵产物)
async function syncRunningState(force = false) {
  if (!conv.activeId) return
  if (!force && !isRunning.value) return
  try {
    const list = await sessionService.list({ limit: 400, scope: 'all' })
    const meta = list.find((c) => c.id === conv.activeId)
    if (meta) {
      const prev = workState.value
      conv.activeMeta = { ...(conv.activeMeta as ConversationMeta),
                          workState: (meta as any).workState } as ConversationMeta
      if (prev === 'running' && (meta as any).workState !== 'running') {
        // 相位回落(回合结束/终态) → 全量拉一次消息(泵期间的增量可见)
        const detail = await sessionService.messages(conv.activeId)
        conv.applyConversation({ ...detail, reqId: conv.activeReqId })
      }
    }
  } catch { /* 列表失败无碍 */ }
}

// 验收视图(done 消息卡「验收」): 差异+简报+通过/返工
const acceptOpen = ref(false)
const acceptMsg = ref('')
const acceptDiff = ref('')
const acceptMeta = ref<Record<string, any> | null>(null)
const acceptBusy = ref(false)
async function openAccept(meta: Record<string, any>) {
  acceptMeta.value = meta
  acceptMsg.value = ''
  acceptDiff.value = ''
  acceptOpen.value = true
  try {
    const d = await apiGet<{ message: string }>(`/sessions/${conv.activeId}/diff`)
    acceptDiff.value = d?.message || ''
  } catch (e: any) {
    acceptDiff.value = e?.message || String(e)
  }
}
async function acceptPass() {
  if (!conv.activeReqId || acceptBusy.value) return
  acceptBusy.value = true
  try {
    await apiPost(`/requirements/${conv.activeReqId}/done`, { done: true })
    acceptMsg.value = t('session.job.acceptDone')
    acceptOpen.value = false
  } catch (e: any) {
    acceptMsg.value = e?.message || String(e)
  } finally {
    acceptBusy.value = false
  }
}
function acceptRework() {
  acceptOpen.value = false
  conv.pushDraft(t('session.job.reworkDraft'))
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

      <!-- 验收视图(作业 done 消息卡入口): 差异 + 简报 + 通过/返工 -->
      <div
        v-if="acceptOpen"
        class="absolute inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 backdrop-blur-sm p-4"
        @click.self="acceptOpen = false"
      >
        <div class="panel flex max-h-[80%] w-full max-w-lg flex-col">
          <div class="panel-header">
            <span>{{ t('session.job.acceptTitle') }}（{{ acceptMeta?.branch || '' }}）</span>
            <button class="btn btn-xs btn-ghost" @click="acceptOpen = false">
              <XMarkIcon class="w-3.5 h-3.5" />
            </button>
          </div>
          <div class="min-h-0 flex-1 space-y-3 overflow-auto p-3">
            <div class="whitespace-pre-wrap rounded-lg border border-ctp-surface1 bg-ctp-mantle/60 p-2.5 text-[11px] leading-relaxed text-ctp-subtext0">{{ acceptDiff || '…' }}</div>
            <p v-if="acceptMsg" class="text-[11px] text-ctp-yellow break-all">{{ acceptMsg }}</p>
          </div>
          <div class="flex items-center justify-end gap-2 border-t border-ctp-surface0 p-2.5">
            <button class="btn btn-xs" :disabled="acceptBusy" @click="acceptRework">{{ t('session.job.rework') }}</button>
            <button class="btn btn-xs btn-primary" :disabled="acceptBusy || !conv.activeReqId" @click="acceptPass">{{ t('session.job.pass') }}</button>
          </div>
        </div>
      </div>

      <AnalysisChat
        class="h-full"
        :turns="conv.viewMode === 'coding' ? conv.subTurns : conv.turns"
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
        :job-state="jobState"
        :bound-executor-id="boundExecutorId"
        :executor-models="boundModelNames"
        :executor-model="currentExecutorModel"
        :sub-unread="conv.subUnread"
        @role-change="onRoleChange"
        @bind-coding="openRoles"
        @set-model="onSetModel"
        @send="(text: string, role?: 'architect' | 'coding') => { conv.send(text, { ...(props.skillScenarios?.length ? { skillScenarios: props.skillScenarios } : {}), ...(props.defaultKind ? { kind: props.defaultKind } : {}), ...(role ? { targetRole: role } : {}) }); onSent() }"
        @job-accept="openAccept"
        @job-resume="resumeJob"
        @guard-repair="onGuardRepair"
        @fill-cmd="fillCmd"
        @feed-turn="onFeedTurn"
        @spec-apply="onSpecApply"
        @answers="(a) => { conv.sendAnswers(a); onSent() }"
        @delete-turn="conv.deleteTurn"
        @toggle-diagram-skill="conv.toggleDiagramSkill"
        @goto-requirements="onGotoRequirements"
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
              :title="t('session.workState.runningHint')"
            >▶ {{ jobState?.role === 'coding'
              ? `coding·${jobState.executorId || '?'}${jobState.status === 'waiting_input' ? ' · 等待回复' : ''}`
              : t('session.workState.running') }}<button
                class="ml-0.5 rounded px-1 text-ctp-red hover:bg-ctp-red/15"
                :disabled="stopBusy"
                :title="t('session.job.stop')"
                @click.stop="stopExec"
              >⏹</button></span>
          </div>
        </template>
        <template #toolbar-extra>
          <button
            v-if="isExecutionConv"
            class="btn btn-xs btn-ghost"
            :disabled="guideBusy"
            :title="t('session.actions.guide')"
            @click="showGuide"
          >{{ guideBusy ? '…' : t('session.actions.guide') }}</button>
          <button
            class="btn btn-xs"
            :class="titleSummarizing ? 'btn-blue' : 'btn-ghost'"
            :disabled="titleSummarizing || !conv.activeId"
            :title="t('session.actions.summarize')"
            @click="summarizeTitle"
          >{{ titleSummarizing ? '…' : t('session.actions.summarize') }}</button>
          <button
            class="btn btn-xs btn-ghost"
            :disabled="mining || !activeProject()"
            :title="t('session.mineOnEnd')"
            @click="mineActive"
          >{{ mining ? '…' : t('session.mine') }}</button>
          <button
            class="btn btn-xs btn-ghost"
            :disabled="!conv.activeId || (conv.activeMeta as any)?.status === 'archived'"
            :title="t('session.archiveHint')"
            @click="archiveActive"
          >{{ t('session.archive') }}</button>
        </template>
      </AnalysisChat>
    </div>
  </aside>
</template>
