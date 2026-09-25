/**
 * 资产工作区 · 会话集成域（MS6-W1 搬移，纯移动零逻辑改动）。
 * 全局会话栏(dock)联动：turns 视图/工具事件钩子/提取去抖刷新/规约提案卡/引用提问。
 */
import { computed, ref, shallowRef } from 'vue'
import { useI18n } from 'vue-i18n'
import { useConversationStore } from '@/stores/conversation-store'
import { namingService, type NamingConvention } from '@/services/naming-service'
import type { ConversationDetail, SemanticAsset } from '@/types'
import type { WsDeps } from './useAssetCore'

/** ChatTurn 最小形状(conversation-store turns 元素)。 */
interface ChatTurn { role: string; content: string; assets?: any[]; conventions?: NamingConvention[] }

export function useAssetChat(D: WsDeps) {
  const { t } = useI18n()
  const conv = useConversationStore()
  const core = D.core

  // ---- P1 全局会话栏: 聊天引擎在 conversation-store，页面经钩子响应工具事件 ----
  const historyOpen = ref(false)
  /** 对话回合反应式视图(提取进度等页面写回合，dock 内同步渲染)。 */
  const turns = computed<ChatTurn[]>(() => conv.turns as unknown as ChatTurn[])
  /** 直连提取进度(原复用对话 busy/abort，会话引擎化后独立)。 */
  const extractBusy = ref(false)
  const extractAbort = shallowRef<AbortController | null>(null)

  /** 确保 dock 当前是资产会话(非资产会话时新开)。 */
  function ensureAssetConversation() {
    if (!conv.activeId) conv.newConversation(t('assetMgmt.chatTitle'))
  }
  /** 导入指定历史会话(资产管理 → 全局会话栏)。 */
  function importHistory(detail: ConversationDetail) {
    conv.applyConversation(detail)
    conv.setDockOpen(true)
    historyOpen.value = false
  }

  /** PR3 会话导入·新建: 资产场景新开空白会话(默认 architect 角色)。 */
  function onImportNewConversation() {
    conv.newConversation(t('assetMgmt.chatTitle'))
    conv.setDockOpen(true)
    historyOpen.value = false
  }

  // ---- 对话区：引用资产 → agent 确认 ----

  // 提取完成 → 主动刷新资产数据(agent 在对话中执行 asset.semantic.extract 落库后，
  // 资产列表/状态/覆盖度不会自动更新；此处去抖合并刷新，回合结束时兜底再刷一次)。
  let extractDirty = false
  let extractRefreshTimer: ReturnType<typeof setTimeout> | null = null
  function refreshAfterExtract() {
    extractDirty = false
    if (extractRefreshTimer) { clearTimeout(extractRefreshTimer); extractRefreshTimer = null }
    void Promise.all([core.loadSemantic(), core.refreshStatus(), core.loadOverview(), D.framework.loadCoverage()])
  }
  function markExtracted() {
    extractDirty = true
    if (extractRefreshTimer) clearTimeout(extractRefreshTimer)
    extractRefreshTimer = setTimeout(refreshAfterExtract, 1500)
  }
  function isExtractDirty() {
    return extractDirty
  }

  /** 页面级工具事件反应：资产提取刷新 / 规约提案挂卡(dock 内卡片) / 提取后兜底刷新。
   *  返回注销函数(由 SFC 在 setup 内注册 + onUnmounted 注销——生命周期留在宿主)。 */
  function registerChatHook() {
    return conv.registerChatHook((ev, ctx) => {
      if (ev.type === 'tool_result' && ev.ok) {
        if (ev.tool === 'asset.semantic.extract') markExtracted()
        else if (ev.tool === 'convention.propose') void onConventionProposed(ctx.turnIndex)
      } else if (ev.type === 'done') {
        if (extractDirty) refreshAfterExtract()
      }
    })
  }

  /** 快捷提问(引用/询问按钮): 经全局会话栏发送(asset 场景)。 */
  function askAgent(text: string) {
    if (conv.busy || !text.trim()) return
    ensureAssetConversation()
    void conv.send(text, { skillScenarios: ['extract'] })
  }

  // ── A4 命名规约归纳提议卡（agent 检测命名模式 → pending 提案；确认固化/忽略） ──

  /** 已展示过的规约提案 id（防历史 pending 在每次发送时重复弹卡）。 */
  const seenConventionIds = ref<Set<string>>(new Set())
  /** 会话首轮发送前是否已快照既有 pending 提案。 */
  const conventionSeeded = ref(false)

  function seedConventionIds() {
    if (conventionSeeded.value) return
    conventionSeeded.value = true
    // 会话首轮发送前快照既有 pending 提案，避免把历史提案当本次新提议
    namingService.conventions('pending').then((rows) => {
      for (const r of rows) if (r.id) seenConventionIds.value.add(r.id)
    }).catch(() => {})
  }

  /** tool_result(convention.propose, ok) → 拉取 pending 提案，把新增的挂到当前助手回合。 */
  async function onConventionProposed(idx: number) {
    try {
      const rows = await namingService.conventions('pending')
      const fresh = rows.filter((r) => r.id && !seenConventionIds.value.has(r.id))
      if (!fresh.length) return
      fresh.forEach((r) => seenConventionIds.value.add(r.id))
      const turn = turns.value[idx]
      if (!turn) return
      turn.conventions = [...(turn.conventions ?? []), ...fresh]
    } catch (err: any) {
      console.warn('[naming] 拉取规约提案失败:', err?.message)
    }
  }

  async function onConventionConfirm(id: string) {
    try {
      await namingService.updateConvention(id, { status: 'active' })
    } catch (err: any) {
      console.warn('[naming] 规约确认失败:', err?.message)
    }
  }

  async function onConventionIgnore(id: string) {
    try {
      await namingService.deleteConvention(id)
    } catch (err: any) {
      console.warn('[naming] 规约忽略失败:', err?.message)
    }
  }

  // 引用组件到对话输入框（预填不发送，用户可补充问题）→ 全局会话栏。
  function referenceComp(name: string, id: string) {
    ensureAssetConversation()
    conv.pushDraft(core.compRefText(name, id))
  }

  function referenceAsset(a: SemanticAsset) {
    const anchor = a.astRefs?.[0]
    const pos = anchor ? `${anchor.file}:L${anchor.startLine}-L${anchor.endLine}` : ''
    askAgent(t('assetMgmt.referencePrompt', { name: a.name, id: a.id, kind: t(`assetMgmt.kind.${a.kind}`), pos }))
  }

  return {
    conv, historyOpen, turns, extractBusy, extractAbort,
    ensureAssetConversation, importHistory, onImportNewConversation,
    registerChatHook, isExtractDirty, refreshAfterExtract, markExtracted,
    askAgent, seenConventionIds, conventionSeeded, seedConventionIds,
    onConventionProposed, onConventionConfirm, onConventionIgnore,
    referenceComp, referenceAsset,
  }
}
