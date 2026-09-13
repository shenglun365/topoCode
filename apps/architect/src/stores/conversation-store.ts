/**
 * 会话引擎 store(P1) —— 全局唯一对话栏(右侧 dock)的单一事实源。
 *
 * 吸收原 AgentWorkbench / AssetManagementWorkspace 各自持有的聊天逻辑:
 *  - turns/busy/流式事件处理(chatStream WS)统一在此；
 *  - 页面专属的工具事件反应(资产提取刷新/提案卡等)经 registerChatHook 订阅；
 *  - 全部会话(资产/需求/设计)共用，会话全量持久化(裁决5)。
 */
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { chatStream, stageOfTool, type ChatStreamEvent, type KbAnalysisTurn } from '@/services/kb-analysis-agent'
import type { SemanticAsset } from '@/types'
import { sessionService, type ConversationMeta } from '@/services/session-service'
import { requirementService } from '@/services/requirement-service'
import { readModelPref } from '@topo/web-core/shell'
import { useDiagramSkill } from '@/composables/useDiagramSkill'
import { useChatProgress } from '@/composables/useChatProgress'

/** 页面订阅的聊天事件钩子(返回 false 表示已独占处理本轮默认行为；一般不返回)。 */
export type ChatHook = (ev: ChatStreamEvent, ctx: { turnIndex: number }) => void | boolean

const DOCK_KEY = 'arch.conversation.dock'

export const useConversationStore = defineStore('archConversation', () => {
  // ── dock 外观 ──
  const dockOpen = ref(localStorage.getItem(DOCK_KEY) === '1')
  function setDockOpen(v: boolean) {
    dockOpen.value = v
    localStorage.setItem(DOCK_KEY, v ? '1' : '0')
  }
  function toggleDock() { setDockOpen(!dockOpen.value) }

  // ── 当前会话 ──
  const activeId = ref('')
  const activeTitle = ref('')
  const activeReqId = ref('')
  const activeMeta = ref<ConversationMeta | null>(null)

  // ── 场景隔离: 会话中心/资产管理各自保留最后对话状态, 互不影响 ──
  // dock 挂 scope prop → setScope 切换工作区: 当前状态存快照, 目标场景恢复快照。
  interface ScopeSnapshot {
    activeId: string; activeTitle: string; activeReqId: string
    activeMeta: ConversationMeta | null; turns: KbAnalysisTurn[]
  }
  const scope = ref('sessions')
  const scopeCache = new Map<string, ScopeSnapshot>()
  function setScope(next: string) {
    if (next === scope.value) return
    scopeCache.set(scope.value, {
      activeId: activeId.value, activeTitle: activeTitle.value,
      activeReqId: activeReqId.value, activeMeta: activeMeta.value,
      turns: turns.value,
    })
    scope.value = next
    const snap = scopeCache.get(next)
    if (snap) {
      activeId.value = snap.activeId; activeTitle.value = snap.activeTitle
      activeReqId.value = snap.activeReqId; activeMeta.value = snap.activeMeta
      turns.value = snap.turns
    } else {
      resetChat()
      activeId.value = ''; activeTitle.value = ''
      activeReqId.value = ''; activeMeta.value = null
    }
  }

  // ── 聊天状态(原 AgentWorkbench/AssetMgmt 本地状态统一化) ──
  const turns = ref<KbAnalysisTurn[]>([])
  const busy = ref(false)
  const abortCtl = ref<AbortController | null>(null)
  const insertDraft = ref<{ text: string; nonce: number } | null>(null)
  let draftNonce = 0
  const { diagramSkill, toggleDiagramSkill } = useDiagramSkill()
  const { busyLabel, toolTrail, begin: beginProgress, onChatEvent: onProgressEvent } = useChatProgress()

  // ── 页面事件订阅(资产页等) ──
  const hooks = new Set<ChatHook>()
  function registerChatHook(fn: ChatHook) {
    hooks.add(fn)
    return () => hooks.delete(fn)
  }
  /** 引用预填: 页面「引用组件」等按钮 → 追加进对话输入框。 */
  function pushDraft(text: string) {
    insertDraft.value = { text, nonce: ++draftNonce }
  }

  /** 提案卡: tool_result(req.propose) → 拉取需求详情挂到当前助手回合(arr=流式回合所在数组, 场景切换安全)。 */
  async function attachProposal(ev: ChatStreamEvent, arr: KbAnalysisTurn[]) {
    try {
      const m = String(ev.summary || '').match(/RQ-\d+/)
      const reqId = m ? m[0] : ''
      if (!reqId) return
      const { apiGet } = await import('@/services/api-client')
      const row = await apiGet<Record<string, any>>(`/requirements/${reqId}`)
      if (!row?.id) return
      // 绑定会话↔需求：自然语言「确认存入」经 agent req.finalize 时依赖此绑定
      activeReqId.value = row.id
      const last = arr[arr.length - 1]
      if (last && last.role === 'assistant') {
        last.proposal = {
          id: row.id, title: row.title, desc: row.desc, priority: row.priority,
          analysis: row.analysis,
        }
      }
    } catch { /* 提案卡失败不影响对话 */ }
  }

  function resetChat() {
    turns.value = []
    busy.value = false
    busyLabel.value = ''
  }

  /**
   * 会话集合变更广播(新建/更新)：左侧会话列表(SessionsPage)与各 dock 实例
   * 监听刷新——新会话在首条消息发送时才由后端创建，列表无从本地感知。
   */
  function notifySessionsChanged(convId?: string) {
    window.dispatchEvent(new CustomEvent('arch:sessions-changed', { detail: convId || '' }))
  }

  function applyConversation(conv: { id: string; reqId?: string; kind?: string; title?: string; messages?: { id?: string; role: 'user' | 'assistant'; content: string }[] }) {
    const msgs = (conv.messages ?? []).filter((m) => m.content?.trim())
    // 旧会话可能累积了重复的页面引导消息——相邻同文 assistant 消息折叠为一条
    turns.value = msgs
      .map((m) => ({ role: m.role, content: m.content, id: m.id, meta: (m as any).meta }))
      .filter((m, i, all) => !(i > 0 && m.role === 'assistant' && all[i - 1].role === 'assistant' && all[i - 1].content === m.content))
    activeId.value = conv.id
    if (typeof conv.reqId === 'string') activeReqId.value = conv.reqId
    if (conv.title) activeTitle.value = conv.title
  }

  /** 打开已有会话(dock 或会话中心触发): 载入持久化历史。 */
  async function openConversation(meta: Pick<ConversationMeta, 'id' | 'reqId' | 'title'>) {
    resetChat()
    activeId.value = meta.id
    activeReqId.value = meta.reqId || ''
    activeTitle.value = meta.title || ''
    activeMeta.value = meta as ConversationMeta
    setDockOpen(true)
    try {
      const detail = await sessionService.messages(meta.id)
      applyConversation({ ...detail, reqId: meta.reqId })
    } catch { /* 无历史 → 空对话 */ }
    void rehydrateProposals(meta.id)
    // PR1 双维度: 打开会话 → 标记已读(归档会话跳过)
    if ((meta as any).status !== 'archived') {
      sessionService.update(meta.id, { reviewState: 'read' }).catch(() => { /* 标记失败无碍 */ })
      if (activeMeta.value) activeMeta.value = { ...activeMeta.value, reviewState: 'read' } as ConversationMeta
    }
  }

  /**
   * 历史会话还原方案卡：req.propose 产物不在落库消息里(工具块落库前已剥离，
   * 卡片原是纯前端实时挂载)——按需求的 sourceConversationId 拉回并挂到对应
   * 助手回合；确认态随需求状态(已定稿入池 → 显示「已存入待执行」)。
   */
  async function rehydrateProposals(convId: string) {
    try {
      const { apiGet, apiPatch } = await import('@/services/api-client')
      const rows = await apiGet<any[]>('/requirements')
      const mine = (rows || []).filter((r: any) =>
        r.sourceConversationId === convId && r.status !== 'cancelled')
      if (!mine.length || activeId.value !== convId) return
      // 恢复会话↔需求绑定(刷新后 activeReqId 丢失会致 NL「确认定稿」失败):
      // 优先未定稿提案, 兜底最新一条; 并 PATCH 落库绑定
      const pending = mine.filter((r: any) => (r.location ?? '') === 'proposal')
      const bind = pending[pending.length - 1] ?? mine[mine.length - 1]
      if (bind?.id && !activeReqId.value) {
        activeReqId.value = bind.id
        apiPatch(`/requirements/conversations/${convId}`, { reqId: bind.id }).catch(() => {})
      }
      for (const r of mine) {
        const proposal = {
          id: r.id, title: r.title, desc: r.desc || '', priority: r.priority || 'P1',
          analysis: r.analysis || {},
          confirmed: (r.location ?? 'proposal') === 'pool' && r.status === 'analyzed',
        }
        // 挂到内容中提到该 RQ 编号的最后一条助手消息; 没提到则兜底最后一条空位助手消息
        let target = -1
        for (let i = turns.value.length - 1; i >= 0; i--) {
          const t = turns.value[i]
          if (t.role === 'assistant' && (t.content || '').includes(r.id)) { target = i; break }
        }
        if (target < 0) {
          for (let i = turns.value.length - 1; i >= 0; i--) {
            if (turns.value[i].role === 'assistant' && !turns.value[i].proposal) { target = i; break }
          }
        }
        if (target >= 0) turns.value[target].proposal = proposal
      }
    } catch { /* 还原失败不影响历史展示 */ }
  }

  /** 新会话(无类别——仅标题/摘要；阶段由消息级工具推导)。 */
  function newConversation(title = '') {
    resetChat()
    activeId.value = ''
    activeReqId.value = ''
    activeTitle.value = title
    activeMeta.value = null
    setDockOpen(true)
  }

  /** 发送一轮对话: 统一 WS 流式 + 默认回合处理 + 页面钩子。 */
  async function send(text: string, opts?: { reqId?: string; skillScenarios?: string[]; kind?: string; targetRole?: 'architect' | 'coding' }) {
    if ((busy.value && opts?.targetRole !== 'coding') || !text.trim()) return
    // 固定回合数组引用: 对话中途切换场景(scope)时, 流式写入仍落在原场景回合里
    const arr = turns.value
    arr.push({ role: 'user', content: text })
    const idx = arr.push({ role: 'assistant', content: '' }) - 1
    busy.value = true
    beginProgress()
    const ac = new AbortController(); abortCtl.value = ac
    const hadNoConv = !activeId.value
    let convNotified = false
    try {
      // 本地引导消息(meta.kind='hint')纯前端提示, 不进入模型上下文
      const msgs = arr.slice(0, -1).filter((m) => m.meta?.kind !== 'hint').map((m) => ({ role: m.role, content: m.content }))
      await chatStream(msgs, {
        conversationId: activeId.value || undefined,
        kind: opts?.kind ?? (activeMeta.value as any)?.kind ?? undefined,
        reqId: opts?.reqId ?? (activeReqId.value || undefined),
        title: activeTitle.value || undefined,
        modelId: readModelPref('architect') || undefined,
        diagramSkill: diagramSkill.value,
        skillScenarios: opts?.skillScenarios,
        targetRole: opts?.targetRole,
        signal: ac.signal,
      }, (ev) => {
        if (ev.conversationId) {
          activeId.value = ev.conversationId
          // 新会话落库(首条消息创建) → 广播列表刷新(左侧会话列表同步可见)
          if (hadNoConv && !convNotified) {
            convNotified = true
            notifySessionsChanged(ev.conversationId)
          }
        }
        onProgressEvent(ev)
        // 页面钩子(资产提取/规约提议等页面反应)
        for (const fn of hooks) fn(ev, { turnIndex: idx })
        if (ev.type === 'chat_start') {
          if (ev.userMessageId && idx >= 1 && !arr[idx - 1].id) arr[idx - 1].id = ev.userMessageId
        } else if (ev.type === 'chunk') {
          arr[idx].content += ev.delta ?? ''
        } else if (ev.type === 'reasoning') {
          arr[idx].reasoning = (arr[idx].reasoning ?? '') + (ev.delta ?? '')
        } else if (ev.type === 'done') {
          arr[idx].content = ev.content ?? arr[idx].content
          if (ev.messageId) arr[idx].id = ev.messageId
          if (ev.meta) arr[idx].meta = ev.meta   // 守卫标记等元数据(卡片渲染用)
          // 用户正观看的会话流式完成 → 保持已读(后端落库时置了 unread)
          if (ev.conversationId && ev.conversationId === activeId.value) {
            sessionService.update(ev.conversationId, { reviewState: 'read' }).catch(() => { /* 无碍 */ })
          }
          notifySessionsChanged(ev.conversationId)
          void refreshActiveMeta()
        } else if (ev.type === 'tool_result') {
          const stage = stageOfTool(ev.tool)
          if (stage) arr[idx].stage = stage
          if (ev.tool === 'req.propose' && ev.ok) void attachProposal(ev, arr)
          if (ev.assets?.length) arr[idx].assets = ev.assets as SemanticAsset[]
        } else if (ev.type === 'error') {
          arr[idx].content = ev.message || ''
        }
      })
    } catch (err) {
      arr[idx].content = (err instanceof Error ? err.message : '') || ''
    } finally {
      abortCtl.value = null
      busy.value = false
    }
  }

  function sendAnswers(answers: Record<string, string>) {
    const text = Object.entries(answers).map(([k, v]) => `${k}: ${v}`).join('\n')
    return send(text)
  }

  /**
   * 本地引导消息(「引导」按钮输出)：仅在当前对话流渲染,
   * 不发后端/不落库/不进上下文——会话切换或重开自然消失。
   */
  function pushLocalHint(text: string) {
    turns.value.push({ role: 'assistant', content: text, meta: { kind: 'hint' } })
  }

  async function deleteTurn(index: number) {
    const turn = turns.value[index]
    if (!turn) return
    const msgId = turn.id
    turns.value.splice(index, 1)
    if (msgId && activeId.value) {
      requirementService.deleteMessage(activeId.value, msgId).catch(() => { /* 本地已删, 后端失败忽略 */ })
    }
  }

  function stop() { abortCtl.value?.abort() }

  async function refreshActiveMeta() {
    if (!activeId.value) return
    try {
      const list = await sessionService.list({ limit: 400 })
      activeMeta.value = list.find((c) => c.id === activeId.value) ?? activeMeta.value
      if (activeMeta.value?.title) activeTitle.value = activeMeta.value.title
    } catch { /* 列表刷新失败不影响对话 */ }
  }

  return {
    dockOpen, setDockOpen, toggleDock,
    scope, setScope,
    activeId, activeTitle, activeReqId, activeMeta,
    turns, busy, insertDraft, pushDraft,
    diagramSkill, toggleDiagramSkill,
    busyLabel, toolTrail,
    registerChatHook,
    openConversation, newConversation, applyConversation,
    send, sendAnswers, deleteTurn, stop, refreshActiveMeta, pushLocalHint,
  }
})
