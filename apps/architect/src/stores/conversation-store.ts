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
import { apiBaseUrl, getToken } from '@/services/api-client'
import { currentProjectParams } from '@/services/project-service'
import { requirementService } from '@/services/requirement-service'
import { outlineAbbrCache } from '@/services/outline-cache'
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

  /** 提案卡: tool_result(req.propose) → 拉取需求详情挂到当前助手回合(arr=流式回合所在数组, 场景切换安全)。
   * cv-205 方案 A: 提案卡渲染已退役——需求唯一宿主是 specReady 消息卡(会话
   * 刷新链 rehydrateProposals 供给载荷)。本函数只保留 会话↔需求绑定 语义。 */
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
    } catch { /* 提案卡失败不影响对话 */ }
  }

  function resetChat() {
    turns.value = []
    busy.value = false
    busyLabel.value = ''
    flushPendingMsgRefresh()
  }

  /** ── v2 统一会话: 单流(消息带 agent 标注, 读侧视觉归因) + 任务清单 ── */
  /** coding subagent 任务清单(arch_tasks, 倒序; SSE task 事件/操作后刷新)。 */
  const tasks = ref<any[]>([])

  // cv-189: 存量历史里的纯占位气泡("(已调用工具)"等, 弱模型模仿产物)不展示;
  // 新落库的紧凑工具回执(meta.kind=tool_round)保留
  // cv-194/cv-196: 展示层过滤——纯占位气泡隐藏; task_card/specReady 气泡由
  // 富组件承载(任务清单 TaskCard/需求提案卡)不再重复渲染(落库不动, 真相源保留)
  const _TOOL_PLACEHOLDER_RE = /^[（(]\s*(?:已调用工具|调用知识库检索|调用工具|工具已调用)\s*[)）][。.!！]?\s*$/
  const _CARD_BUBBLE_KINDS = new Set(['task_card', 'specReady', 'task_status'])
  /** acceptance 列(TEXT JSON string[])安全解析——字符串/数组皆容。 */
  function _jsonArr(v: unknown): string[] {
    if (Array.isArray(v)) return v.map(String)
    if (typeof v === 'string' && v.trim()) {
      try { const a = JSON.parse(v); return Array.isArray(a) ? a.map(String) : [] }
      catch { return v ? v.split('\n').filter(Boolean) : [] }
    }
    return []
  }
  /** 卡片消息保留条件: 有 A6.2 投影(item) → 交卡片分支渲染(需求卡/状态条/
   * TaskCard, cv-205 重进会话与实时同构); 无投影(旧数据/投影失败) → 维持
   * 气泡过滤兜底。 */
  const _card_kept = (m: any) => !_CARD_BUBBLE_KINDS.has(m?.meta?.kind || '') || !!m?.item

  /** 任务刷新(会话打开/操作后/SSE task 事件)。 */
  async function refreshTasks() {
    if (!activeId.value) { tasks.value = []; return }
    try {
      const { apiGet } = await import('@/services/api-client')
      const res = await apiGet<{ tasks: any[] }>(`/tasks?convId=${activeId.value}`)
      tasks.value = res?.tasks || []
    } catch { /* 保持现状 */ }
  }

  /** 任务操作(轻门禁确认/取消/停止/转达)。 */
  async function taskAction(taskId: string, action: 'confirm' | 'cancel' | 'input' | 'ignore', text?: string) {
    const { apiPost } = await import('@/services/api-client')
    try {
      if (action === 'input') {
        await apiPost(`/tasks/${taskId}/input`, { text: text || '' })
      } else {
        await apiPost(`/tasks/${taskId}/${action}`, {})
      }
      await refreshTasks()
      void refreshActiveMessages()
      return true
    } catch { return false }
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
      .map((m) => ({ role: m.role, content: m.content, id: m.id, meta: (m as any).meta, agent: (m as any).agent || '', item: (m as any).item }))
      .filter(_card_kept)
      .filter((m) => !(m.role === 'assistant' && m.content && _TOOL_PLACEHOLDER_RE.test(m.content.trim())
        && (m.meta as any)?.kind !== 'tool_round'))
      .filter((m) => !(m.role === 'user' && (m.meta as any)?.synthetic))
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
    dirtyConvs.delete(meta.id)        // cv-221: 切入即视为已拉取(open 自带 pull)
    scheduleDrain(0)                  // 重放缓冲中挂起的该会话事件(若钻窗内未拉取)
    setDockOpen(true)
    try {
      const detail = await sessionService.messages(meta.id)
      // 过期响应守卫: 拉取期间会话已被删除/切换 → 丢弃, 不复活旧会话到对话区
      if (activeId.value !== meta.id) return
      applyConversation({ ...detail, reqId: meta.reqId })
    } catch { /* 无历史 → 空对话 */ }
    void refreshTasks()
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
          // cv-205: 完整需求内容——需求卡全文展示并原样转入执行器
          design: String(r.design || ''),
          acceptance: _jsonArr(r.acceptance),
          allowedScope: _jsonArr(r.allowedScope),
          forbiddenScope: _jsonArr(r.forbiddenScope),
          analysis: r.analysis || {},
          // 确认态: 新生命周期 ready/done 即已存入; 兼容旧 analyzed(池化)
          confirmed: ['ready', 'done'].includes(r.status)
            || ((r.location ?? 'proposal') === 'pool' && r.status === 'analyzed'),
        }
        // 挂载目标(方案 A): 优先 spec 消息卡(item.type==='spec' 同需求)——
        // 需求卡唯一宿主吃这份载荷; 兜底 内容含 RQ 编号的最后一条助手消息
        // → 最后一条空位助手消息(非 spec 流/旧数据)
        let target = -1
        for (let i = turns.value.length - 1; i >= 0; i--) {
          const t = turns.value[i]
          if (t.role === 'assistant' && (t as any).item?.type === 'spec'
            && (t as any).item?.payload?.requirementId === r.id) { target = i; break }
        }
        if (target < 0) {
          for (let i = turns.value.length - 1; i >= 0; i--) {
            const t = turns.value[i]
            if (t.role === 'assistant' && (t.content || '').includes(r.id)) { target = i; break }
          }
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
    tasks.value = []
    activeId.value = ''
    activeReqId.value = ''
    activeTitle.value = title
    activeMeta.value = null
    setDockOpen(true)
  }

  /**
   * 会话已被删除(左侧列表等外部触发)：清各场景快照中该会话的痕迹；
   * 若正是当前打开的会话 → 清空对话区回到新会话态(右侧不残留已删会话)。
   */
  function dropConversation(convId: string) {
    if (!convId) return
    for (const [k, snap] of scopeCache) {
      if (snap.activeId === convId) scopeCache.delete(k)
    }
    // 大纲标题缩略缓存随会话删除清理(K3 浮窗)
    outlineAbbrCache.removeConversation(convId)
    if (activeId.value === convId) newConversation()
  }

  /** 发送一轮对话: 统一 WS 流式 + 默认回合处理 + 页面钩子; digest=语境摘要(转达下发, text 可空)。 */
  async function send(text: string, opts?: { reqId?: string; skillScenarios?: string[]; kind?: string; agent?: string; attachTo?: string; digest?: string; synthetic?: boolean }) {
    if (busy.value || (!text.trim() && !opts?.digest)) return
    // 固定回合数组引用: 对话中途切换场景(scope)时, 流式写入仍落在原场景回合里
    const arr = turns.value
    const userTurn: any = { role: 'user', content: text || '📎 语境摘要转达', agent: opts?.agent || '' }
    if (opts?.synthetic) userTurn.meta = { synthetic: true }   // cv-197: 不回显
    arr.push(userTurn)
    const idx = arr.push({ role: 'assistant', content: '' }) - 1
    busy.value = true
    beginProgress()
    const ac = new AbortController(); abortCtl.value = ac
    const hadNoConv = !activeId.value
    let convNotified = false
    try {
      // 本地引导消息(meta.kind='hint')纯前端提示, 不进入模型上下文;
      // digest-only 发送时占位 userTurn 不发给后端(后端拼 digest, 避免占位文案进转达)
      const msgs = arr.slice(0, -1)
        .filter((m) => m.meta?.kind !== 'hint' && !(opts?.digest && !text && m === userTurn))
        .map((m) => ({ role: m.role, content: m.content }))
      await chatStream(msgs, {
        synthetic: opts?.synthetic,
        conversationId: activeId.value || undefined,
        kind: opts?.kind ?? (activeMeta.value as any)?.kind ?? undefined,
        reqId: opts?.reqId ?? (activeReqId.value || undefined),
        title: activeTitle.value || undefined,
        modelId: readModelPref('architect') || undefined,
        diagramSkill: diagramSkill.value,
        skillScenarios: opts?.skillScenarios,
        agent: opts?.agent,
        attachTo: opts?.attachTo,
        digest: opts?.digest,
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
          console.info('[arch-live] done', { cardClosed: (ev as any).cardClosed,
            content: (ev.content || '').slice(0, 40), turnHasText: !!arr[idx]?.content })
          if (ev.cardClosed) {
            // cv-205 落卡收尾: 卡片即回合产物, 服务端不落占位消息——
            // 本地空占位回合同步移除(否则空白气泡; 刷新即消失=数据库本无此行)。
            // 已流出的叙述文本保留(有价值, 尽管刷新后不回放)。
            // 卡片实时可见由 turnEnd 收尾补偿拉取保证(cv-221, 消费者统一)。
            if (!(arr[idx].content || '').trim() && !arr[idx].reasoning) {
              arr.splice(idx, 1)
            }
          } else {
            arr[idx].content = ev.content ?? arr[idx].content
            if (ev.messageId) arr[idx].id = ev.messageId
            if (ev.meta) arr[idx].meta = ev.meta   // 守卫标记等元数据(卡片渲染用)
          }
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
      // cv-221: 回合收尾补偿拉取泛化到所有回合类型(原仅 cardClosed 分支
      // 300ms 强拉)——入缓冲走统一消费者, 尾沿刷新一次
      enqueueEvent({ type: 'turnEnd', conversationId: activeId.value || '' })
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
    const arr = turns.value
    const convId = activeId.value
    const turn = arr[index]
    if (!turn) return
    const msgId = turn.id
    arr.splice(index, 1)
    // 大纲标题缩略缓存随消息删除清理(K3 浮窗)
    if (msgId && convId) outlineAbbrCache.removeMessages(convId, [msgId])
    if (msgId && convId) {
      requirementService.deleteMessage(convId, msgId).catch(() => { /* 本地已删, 后端失败忽略 */ })
    }
  }

  /** 回退到消息 N(环节十五): 截断其后全部消息(停止→调整上下文→再执行)。 */
  async function rollbackTo(index: number) {
    const arr = turns.value
    const convId = activeId.value
    const turn = arr[index]
    if (!turn) return
    const msgId = turn.id
    if (!msgId || !convId) return
    await requirementService.rollbackMessages(convId, msgId)
    const removed = arr.splice(index + 1)
    // 被截断消息的缩略缓存一并清理(K3 浮窗; 保留锚点自身——回合仍在)
    const removedIds = removed.map((m) => m.id).filter((x): x is string => !!x)
    if (removedIds.length) outlineAbbrCache.removeMessages(convId, removedIds)
  }

  function stop() { abortCtl.value?.abort() }

  async function refreshActiveMeta() {
    if (!activeId.value) return
    try {
      // cv-204/205 硬隔离: 活动会话必属其项目——按项目查, 不发无参全局列表
      const pid = (activeMeta.value as any)?.projectId
        || currentProjectParams().project || ''
      const list = await sessionService.list({ limit: 400, project: pid })
      activeMeta.value = list.find((c) => c.id === activeId.value) ?? activeMeta.value
      if (activeMeta.value?.title) activeTitle.value = activeMeta.value.title
    } catch { /* 列表刷新失败不影响对话 */ }
  }

  /**
   * 重拉当前会话消息(SSE conv-message 事件触发——coding 子会话事件双落到
   * 主会话的消息无需手动刷新即见)。流式回合进行中(busy)不刷(避免打断渲染),
   * 但请求改为挂起——busy 解除后补偿刷新一次(cv-194: 回合中落流的需求卡/
   * 任务回执此前被静默丢弃, 只能刷新页面才可见)。
   */
  let pendingMsgRefresh = false
  async function refreshActiveMessages() {
    if (!activeId.value) return
    if (busy.value) { pendingMsgRefresh = true; console.info('[arch-live] refresh 推迟(busy)'); return }
    try {
      const detail = await sessionService.messages(activeId.value)
      const _cards = (detail?.messages ?? []).filter((m: any) => m?.meta?.kind || m?.item)
      console.info('[arch-live] refresh 拉到', (detail?.messages ?? []).length, '条, 卡片',
        _cards.map((m: any) => m?.meta?.kind || m?.item?.type).join(','))
      if (activeId.value && !busy.value) {
        applyConversation({ ...detail, reqId: activeReqId.value, title: activeTitle.value } as any)
        // cv-196: 补偿刷新整表替换 turns 会抹掉实时挂载的提案卡——
        // 与 openConversation 同口径重挂(rehydrateProposals 现成机制)
        void rehydrateProposals(activeId.value)
      }
    } catch { /* 重拉失败保持现状 */ }
  }

  /** busy 解除后的补偿刷新(cv-194): 250ms 让 done 内容挂载先完成。 */
  function flushPendingMsgRefresh() {
    if (!pendingMsgRefresh) return
    pendingMsgRefresh = false
    console.info('[arch-live] flush 挂起刷新(250ms 后)')
    setTimeout(() => { if (!busy.value) void refreshActiveMessages() }, 250)
  }

  // ── cv-221 实时通路根修: 消息缓冲区异步消费 + 拉取即真相 ──────────────
  // 不变量: ①消费期判卫(守卫在 drain 时评估, 接收侧零丢弃——SSE 通知可先于
  // WS chat_start 绑定到达, 接收侧判卫会被会话守卫丢弃=卡片实时不可见实证);
  // ②拉取即真相(事件只是信号, 断窗/后台节流由 4 触发点补偿: turnEnd/SSE重连/
  // visibility/会话切换); ③单消费者(刷新调度收敛于此, busy defer 唯一互斥);
  // ④通道职责: WS=回合交互流式渲染(不过缓冲), SSE=实体通知(入缓冲),
  // progress=瞬态 patch(进缓冲, 按任务 150ms 折叠, 微任务级常规延迟)。

  const _REFRESH_FOLD_KINDS = new Set(['conv-message', 'items', 'flow-transition', 'task', 'turnEnd'])
  const PROGRESS_COALESCE_MS = 150
  const queue: any[] = []                      // 有序 FIFO(刷新型折叠, 保序)
  const pendingProgress = new Map<string, { ev: any; at: number }>()  // progress last-wins(按任务)
  const dirtyConvs = new Set<string>()         // 非活跃会话脏标记(切换时拉取)
  const lastProgressAt = new Map<string, number>()
  let drainTimer: ReturnType<typeof setTimeout> | null = null

  /** 事件入队(唯一接收口): 刷新型按 (type+convId) 折叠, progress 按任务 last-wins。 */
  function enqueueEvent(ev: any) {
    if (!ev?.type) return
    if (ev.type === 'progress') {
      pendingProgress.set(String(ev.taskId || ''), { ev, at: Date.now() })
      scheduleDrain(0)
      return
    }
    if (_REFRESH_FOLD_KINDS.has(ev.type)) {
      const i = queue.findIndex((q) => q.type === ev.type && q.conversationId === ev.conversationId)
      if (i >= 0) queue[i] = ev
      else queue.push(ev)
    } else {
      queue.push(ev)
    }
    scheduleDrain(0)
  }

  function scheduleDrain(delayMs = 0) {
    if (drainTimer) return
    drainTimer = setTimeout(() => { drainTimer = null; drain() }, delayMs)
  }

  function drain() {
    while (queue.length) {
      applyBufferedEvent(queue.shift()!)
    }
    // progress 挂起面: 距上次生效 ≥150ms 即生效(首到即时, 突发取最新值);
    // 未到期 → 定时到剩余时间
    const now = Date.now()
    let earliest = Infinity
    for (const [tid, p] of pendingProgress) {
      const wait = PROGRESS_COALESCE_MS - (now - (lastProgressAt.get(tid) || 0))
      if (wait <= 0) {
        lastProgressAt.set(tid, now)
        pendingProgress.delete(tid)
        applyProgressPatch(p.ev)
      } else {
        earliest = Math.min(earliest, wait)
      }
    }
    if (queue.length) scheduleDrain(0)
    else if (pendingProgress.size && earliest !== Infinity) scheduleDrain(earliest)
  }

  function applyBufferedEvent(ev: any) {
    switch (ev.type) {
      case 'task':
        void refreshTasks()
        void refreshActiveMeta()
        markDirty(ev.conversationId)
        return
      case 'flow-transition':
        void refreshActiveMeta()
        markDirty(ev.conversationId)
        return
      case 'conv-message':
      case 'items':
        markDirty(ev.conversationId)
        return
      case 'turnEnd':
        scheduleRefresh()
        return
      default:
        return
    }
  }

  /** 脏标记: 活跃会话 → 调度拉取; 非活跃 → 记账(切换时拉取, 数据零丢失)。 */
  function markDirty(convId?: string) {
    if (!convId || convId === activeId.value) scheduleRefresh()
    else dirtyConvs.add(convId)
  }

  /** 刷新调度(400ms 尾沿合并; busy 由 refreshActiveMessages 内部 defer)。 */
  let refreshTimer: ReturnType<typeof setTimeout> | null = null
  function scheduleRefresh() {
    if (refreshTimer) return
    refreshTimer = setTimeout(() => { refreshTimer = null; void refreshActiveMessages() }, 400)
  }

  /** 执行进展 patch(自 Dock 收编; 瞬态修饰态——任务状态真相走 task 事件+拉取)。 */
  function applyProgressPatch(d: any) {
    const patch = {
      toolCount: d.toolCount || 0, msgCount: d.msgCount || 0, at: d.at || Date.now(),
      lastText: d.lastText ?? '', lastTool: d.lastTool ?? '',
      process: d.process ?? [], inputTokens: d.inputTokens || 0, outputTokens: d.outputTokens || 0,
    }
    const t = (tasks.value || []).find((x: any) => x.id === d.taskId)
    if (t) t.progress = { ...(t.progress || {}), ...patch }
    const rr = (activeMeta.value as any)?.runningRole
    if (rr) rr.progress = { ...(rr.progress || {}), ...patch }
  }

  // ── SSE 连接(store 单例单连接; 自 Dock 收编) ─────────────────────────
  let evtSource: EventSource | null = null
  let evtReconnect: ReturnType<typeof setTimeout> | null = null

  function connectEvents() {
    if (evtSource || typeof EventSource === 'undefined') return
    try {
      const tok = getToken()
      evtSource = new EventSource(`${apiBaseUrl()}/events${tok ? `?token=${encodeURIComponent(tok)}` : ''}`)
      // 断窗补偿: 首连/重连成功即拉取活动会话(重连期间丢失的通知由此兜底)
      evtSource.onopen = () => { void refreshActiveMessages(); void refreshActiveMeta() }
      evtSource.onmessage = (e) => {
        try {
          const d = JSON.parse(e.data)
          if (d?.type) enqueueEvent(d)
        } catch { /* 非事件帧忽略 */ }
      }
      evtSource.onerror = () => {
        disconnectEvents()
        evtReconnect = setTimeout(connectEvents, 5000)
      }
    } catch { /* SSE 不可用(离线) → 退化为手动刷新 */ }
  }

  function disconnectEvents() {
    evtSource?.close()
    evtSource = null
    if (evtReconnect) { clearTimeout(evtReconnect); evtReconnect = null }
  }

  // 后台标签定时器节流兜底: 回前台即拉取活动会话
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        void refreshActiveMessages()
        void refreshActiveMeta()
      }
    })
  }

  return {
    flushPendingMsgRefresh,
    enqueueEvent, connectEvents,
    dockOpen, setDockOpen, toggleDock,
    scope, setScope,
    activeId, activeTitle, activeReqId, activeMeta,
    turns, busy, insertDraft, pushDraft,
    diagramSkill, toggleDiagramSkill,
    busyLabel, toolTrail,
    tasks, refreshTasks, taskAction,
    registerChatHook,
    openConversation, newConversation, applyConversation, dropConversation,
    send, sendAnswers, deleteTurn, rollbackTo, stop, refreshActiveMeta, refreshActiveMessages, pushLocalHint,
  }
})
