<script setup lang="ts">
/**
 * 执行器会话深链页（2026-10 v4）——完整 agent 会话模式。
 *
 * 全屏无工作台框架(顶层路由 /exec-session-view)；?job= 定位：
 * - 有关联会话 → 复用 dock 对话栈(conversation-store + AnalysisChat)：
 *   回合折叠/展开/伸缩、任务卡、输入框直发(执行器直通)、SSE 实时、窗口锁
 * - 无关联会话(serve 直通作业) → 事件聚合会话视图：user/assistant 回合 +
 *   折叠工具块(USAGE/progress 丢弃——细节收敛) + 状态分隔条 + 输入框直发
 *   (POST /arch/exec-sessions/{job}/input → runner user_input/steer) + 停止
 * 头信息: 项目 chip + 主会话标题 + 子会话标题 + 执行器 + 运行状态。
 */
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import {
  BoltIcon, ArrowPathIcon, ArrowTopRightOnSquareIcon,
  PaperAirplaneIcon, StopIcon, ChevronRightIcon, ListBulletIcon,
  DocumentArrowDownIcon,
} from '@heroicons/vue/24/outline'
import { apiGet, apiPost } from '@/services/api-client'
import { projectService } from '@/services/project-service'
import { useConversationStore } from '@/stores/conversation-store'
import { useConvWindowLock } from '@/composables/useConvWindowLock'
import { copyText } from '@/utils/clipboard'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'
import ChatMessageBlocks from '@/components/ChatMessageBlocks.vue'
import ServeOutlineWindow from '@/components/sessions/ServeOutlineWindow.vue'

const { t } = useI18n()
const route = useRoute()
const conv = useConversationStore()
const convLock = useConvWindowLock()

interface Ev { seq: number; kind: string; text: string; ts: number; toolName?: string; [k: string]: unknown }

const jobId = ref('')
const jobRow = ref<{ title?: string; executorType?: string; lastStatus?: string; taskStatus?: string } | null>(null)
const convId = ref('')
const parentTitle = ref('')
const projectName = ref('')
const loading = ref(false)
// 2610 会话窗口(F1): ?conv= 直开形态——主会话/architect/coding 子会话通吃,
// 无作业上下文(时间线/serve 输入隐藏), 纯对话栈; 头部带会话/项目强标识
const convHead = ref<{ kind?: string; title?: string; executorId?: string; projectId?: string } | null>(null)
const kindLabel = computed(() => convHead.value?.kind === 'coding'
  ? t('execSessionView.subSession') : t('execSessionView.mainSession'))
const copiedId = ref(false)
async function copyConvId() {
  if (await copyText(String(convId.value || jobId.value))) {
    copiedId.value = true
    setTimeout(() => { copiedId.value = false }, 1200)
  }
}

/* ── serve 直通形态: 事件 → 回合聚合会话视图 ── */
const events = ref<Ev[]>([])
const live = ref(false)
let evTimer: number | undefined
const feedEl = ref<HTMLElement | null>(null)

interface ToolCall { name: string; ok: boolean; startTs: number; endTs: number; text: string }
interface AggTurn {
  kind: 'user' | 'assistant' | 'tools' | 'status'
  ts: number
  text?: string
  tools?: ToolCall[]
  status?: { tag: string; color: string; text: string }
}

const STATUS_META: Record<string, { tag: string; color: string }> = {
  session_ready: { tag: 'READY', color: 'text-ctp-green' },
  input_required: { tag: 'WAIT', color: 'text-ctp-yellow' },
  notice: { tag: 'NOTICE', color: 'text-ctp-peach' },
  approval_request: { tag: 'AUTH', color: 'text-ctp-red' },
  team: { tag: 'TEAM', color: 'text-ctp-mauve' },
  mcp: { tag: 'MCP', color: 'text-ctp-teal' },
  verify: { tag: 'VERIFY', color: 'text-ctp-lavender' },
  done: { tag: 'DONE', color: 'text-ctp-green' },
  failed: { tag: 'FAIL', color: 'text-ctp-red' },
  aborted: { tag: 'STOP', color: 'text-ctp-yellow' },
  finished: { tag: 'FIN', color: 'text-ctp-overlay1' },
}

/** 细节收敛聚合: USAGE/progress/turn_outcome 丢弃; text 合并回合; TOOL 配对折叠。 */
function aggregate(evs: Ev[]): AggTurn[] {
  const turns: AggTurn[] = []
  const pending = new Map<string, ToolCall>()     // ▶ 未配对的工具(跨回合收口)
  const GAP_MS = 120_000
  const flushTools = (ts: number) => {
    if (!pending.size) return
    turns.push({ kind: 'tools', ts, tools: [...pending.values()] })
    pending.clear()
  }
  for (const ev of evs) {
    const k = ev.kind || ''
    if (k === 'usage' || k === 'progress' || k === 'turn_outcome' || k === 'turn_done') continue
    if (k === 'tool') {
      const name = ev.toolName || String((ev as any).tool || '') || '?'
      if (!ev.text || !ev.text.startsWith('✓')) {
        pending.set(`${name}#${ev.seq}`, { name, ok: false, startTs: ev.ts, endTs: ev.ts, text: ev.text || '' })
      } else {
        // ✓ 完成事件配对最近的同名 ▶(无则独立成块)
        let matched = false
        for (const [key, tc] of [...pending.entries()].reverse()) {
          if (tc.name === name && !tc.ok) {
            tc.ok = true; tc.endTs = ev.ts; tc.text = ev.text
            pending.set(key, tc); matched = true; break
          }
        }
        if (!matched) pending.set(`${name}#${ev.seq}`, { name, ok: true, startTs: ev.ts, endTs: ev.ts, text: ev.text })
      }
      continue
    }
    flushTools(ev.ts)                              // 非 tool 事件收口工具块
    if (k === 'user_input') {
      turns.push({ kind: 'user', ts: ev.ts, text: ev.text })
      continue
    }
    if (k === 'text') {
      const last = turns.at(-1)
      if (last?.kind === 'assistant' && ev.ts - last.ts <= GAP_MS) {
        last.text = `${last.text || ''}${ev.text || ''}`   // 流式分片直接连接
        last.ts = ev.ts
      } else {
        turns.push({ kind: 'assistant', ts: ev.ts, text: ev.text || '' })
      }
      continue
    }
    const meta = STATUS_META[k]
    if (meta) turns.push({ kind: 'status', ts: ev.ts, status: { tag: meta.tag, color: meta.color, text: ev.text || '' } })
  }
  flushTools(evs.at(-1)?.ts || 0)
  return turns
}

const aggTurns = computed(() => aggregate(events.value))
const toolCount = (t: AggTurn) => t.tools?.length || 0
const toolSpan = (t: AggTurn) => {
  if (!t.tools?.length) return ''
  const dur = Math.max(0, (t.tools.at(-1)!.endTs - t.tools[0].startTs))
  return dur >= 1000 ? `${Math.round(dur / 1000)}s` : ''
}
const expandedTools = ref<Set<number>>(new Set())
function toggleTools(key: number) {
  const s = new Set(expandedTools.value)
  s.has(key) ? s.delete(key) : s.add(key)
  expandedTools.value = s
}

/* ── 执行器回合折叠: 长文(>阈值)默认收起, 头部行可点开合(同工具块交互) ── */
const FOLD_THRESHOLD = 300
const unfolded = ref<Set<number>>(new Set())
const shouldFold = (tn: AggTurn) => (tn.text || '').length > FOLD_THRESHOLD
const isUnfolded = (tn: AggTurn) => !shouldFold(tn) || unfolded.value.has(tn.ts)
function toggleFold(tn: AggTurn) {
  if (!shouldFold(tn)) return
  const s = new Set(unfolded.value)
  s.has(tn.ts) ? s.delete(tn.ts) : s.add(tn.ts)
  unfolded.value = s
}
/* ── 遗留次级: serve 执行回执另存草稿(sourceKind=receipt, 文档态续加工) ── */
const savedReceiptTs = ref(0)
async function saveReceiptDraft(tn: AggTurn): Promise<void> {
  const content = (tn.text || '').trim()
  if (!content || savedReceiptTs.value) return
  savedReceiptTs.value = tn.ts
  try {
    const { reqDraftService } = await import('@/services/req-draft-service')
    await reqDraftService.create({
      title: `执行回执·${(projectName.value || '会话').slice(0, 24)}`,
      contentMd: content,
      sourceConvId: jobId.value,
      sourceKind: 'receipt',
    })
  } catch { /* 失败按钮恢复可重试 */ } finally {
    setTimeout(() => { if (savedReceiptTs.value === tn.ts) savedReceiptTs.value = 0 }, 1800)
  }
}

/** 回合摘要: 剥 md 常见记号取首段截断(折叠态/大纲条目共用) */
function turnSummary(tn: AggTurn): string {
  const raw = (tn.text || '').replace(/[#*`|>[\]_-]+/g, ' ').replace(/\s+/g, ' ').trim()
  return raw.slice(0, 80)
}

/* ── 对话索引(大纲): 检索过滤 + 点击滚动定位/高亮; 定位到收起回合自动展开 ── */
const outlineOpen = ref(false)
const flashTs = ref(0)
const outlineItems = computed(() => {
  let idx = 0
  return aggTurns.value
    .filter((tn) => tn.kind === 'user' || tn.kind === 'assistant')
    .map((tn) => ({ key: tn.ts, kind: tn.kind as 'user' | 'assistant', ts: tn.ts,
                    summary: turnSummary(tn), chars: (tn.text || '').length, idx: idx++ }))
})
function gotoAgg(ts: number) {
  const tn = aggTurns.value.find((x) => x.ts === ts)
  if (tn && !isUnfolded(tn)) toggleFold(tn)
  const el = document.getElementById(`agg-${ts}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
    flashTs.value = ts
    setTimeout(() => { if (flashTs.value === ts) flashTs.value = 0 }, 1600)
  }
}

const fmt = (ts?: number) => ts ? new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleTimeString() : ''
const fmtFull = (ts?: number) => ts ? new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleString() : ''

const heading = computed(() => (conv.activeMeta as any)?.title || convHead.value?.title
  || jobRow.value?.title || jobId.value || convId.value)
// 2610 会话窗口: 执行态来源按形态分型——?conv= 读会话行(权威), ?job= 读作业行
const isRunning = computed(() => {
  if (convId.value && !jobId.value) {
    return ((conv.activeMeta as any)?.workState === 'running'
      || !!conv.optimisticRole) && (conv.activeMeta as any)?.status !== 'archived'
  }
  return !jobRow.value?.lastStatus && jobRow.value?.taskStatus !== 'done'
})
const isArchived = computed(() => (conv.activeMeta as any)?.status === 'archived')
const jobState = computed(() => (isRunning.value
  ? { role: 'coding', executorId: (conv.activeMeta as any)?.runningRole?.executorId
      || jobRow.value?.executorType || (conv.activeMeta as any)?.executorId,
      status: (conv.activeMeta as any)?.runningRole?.status || 'running' }
  : null))
const serveActive = computed(() => !convId.value && jobId.value && isRunning.value)

/* ── 执行器面(2610 统一模型): 注册表清单 + 会话换绑(在跑拒绝, 对话连续) ── */
const executors = ref<Array<{ id: string; type?: string; default?: boolean }>>([])
async function loadExecutors() {
  try {
    const d = await apiGet<{ executors: typeof executors.value }>('/agent/executors')
    executors.value = d.executors || []
  } catch { /* 空清单降级 */ }
}
onMounted(loadExecutors)
async function onSwitchExecutor(executorId: string) {
  if (!executorId) {
    conv.pushLocalHint('⚠️ 无可用 coding 执行器——请先在「设置 → 执行器」配置')
    return
  }
  if (!conv.activeId) return
  try {
    const r = await apiPost<{ summary?: string }>(`/sessions/${conv.activeId}/executor`, { executorId })
    conv.pushLocalHint(String(r?.summary || '执行器已切换'))
    await conv.refreshActiveMeta()
  } catch (e: any) {
    conv.pushLocalHint(`⚠️ 换绑失败：${e instanceof Error ? e.message : String(e)}`)
  }
}

/* ── serve 输入框(直发 runner) ── */
const serveInput = ref('')
const sending = ref(false)
const serveMsg = ref('')
const inputEl = ref<HTMLTextAreaElement | null>(null)

function autoResize() {
  const el = inputEl.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = `${Math.min(el.scrollHeight, 160)}px`
}

async function sendServe() {
  const text = serveInput.value.trim()
  if (!text || sending.value) return
  sending.value = true
  serveMsg.value = ''
  try {
    const r = await apiPost<{ delivery?: string }>(
      `/arch/exec-sessions/${encodeURIComponent(jobId.value)}/input`, { text })
    serveInput.value = ''
    if (inputEl.value) inputEl.value.style.height = 'auto'
    serveMsg.value = r.delivery === 'steered' ? t('execSessionView.steered') : ''
    if (!live.value) toggleLive()                  // 输入后自动跟进回流
    void fetchEvents(true)
  } catch (e) {
    serveMsg.value = e instanceof Error ? e.message : String(e)
  } finally { sending.value = false }
}

async function stopServe() {
  if (!jobId.value) return
  try {
    await apiPost(`/arch/exec-sessions/${encodeURIComponent(jobId.value)}/stop`, {})
    serveMsg.value = t('execSessionView.stopping')
    void fetchEvents(true)
  } catch (e) {
    serveMsg.value = e instanceof Error ? e.message : String(e)
  }
}

async function loadJob() {
  const rows = await apiGet<Array<Record<string, unknown>>>('/arch/exec-sessions?limit=200')
  const row = rows.find((r) => r.jobId === jobId.value)
  if (!row) return
  jobRow.value = row as typeof jobRow.value
  const cid = String(row.conversationId || '')
  if (!cid) { await fetchEvents(false); if (isRunning.value) toggleLive(); return }
  convId.value = cid
  await openConversation(cid)
}

/** 打开会话(store 全栈: turns/任务/busy/SSE) + 头信息(主会话标题/项目) */
/** 2610 会话窗口: 锁冲突三选(接管/跳转原窗口/取消)——独立窗口打开已持锁会话时 */
const lockPrompt = ref<{ cid: string; owner?: string } | null>(null)

async function openConversation(cid: string) {
  loading.value = true
  try {
    // 头信息一次取齐(BE: messages 接口带 conv/parent 头)
    try {
      const h = await apiGet<{ conv?: { projectId?: string; title?: string; kind?: string; executorId?: string }; parent?: { title?: string } | null }>(
        `/arch/sessions/${encodeURIComponent(cid)}/messages?limit=1`)
      parentTitle.value = h.parent?.title || ''
      convHead.value = h.conv || null
      void ensureProjectName(h.conv?.projectId)
    } catch { /* 头信息失败不阻断会话打开 */ }
    // 窗口唯一性: 同会话已在别的窗口打开 → 三选(接管/跳转原窗口/取消)
    const lk = await convLock.claim(cid)
    if (!lk.claimed) {
      lockPrompt.value = { cid, owner: lk.owner }
      return
    }
    await _openLocked(cid)
  } finally { loading.value = false }
}

async function _openLocked(cid: string) {
  await conv.openConversation({ id: cid } as any)
  conv.connectEvents()
}

async function onLockTakeover() {
  const cid = lockPrompt.value?.cid || ''
  lockPrompt.value = null
  if (!cid) return
  convLock.takeover(cid)
  loading.value = true
  try { await _openLocked(cid) } finally { loading.value = false }
}

/** 取消打开并跳转原窗口: 尝试聚焦持锁窗口(opener 链), 关闭本窗;
 *  close 被浏览器拦截(非脚本开的 tab) → 兜底导航会话中心该会话。 */
function onLockJumpOriginal() {
  const cid = lockPrompt.value?.cid || ''
  lockPrompt.value = null
  try { (window.opener as any)?.focus?.() } catch { /* 跨源/无 opener 静默 */ }
  window.close()
  setTimeout(() => {
    const q = new URLSearchParams({ select: cid })
    const pid = String(route.query.project || convHead.value?.projectId || '')
    if (pid) q.set('project', pid)
    window.location.href = `${window.location.pathname}#/workbench/sessions?${q.toString()}`
  }, 400)
}

function onLockCancel() {
  const cid = lockPrompt.value?.cid || ''
  lockPrompt.value = null
  window.close()
  setTimeout(() => {
    const q = new URLSearchParams({ select: cid })
    const pid = String(route.query.project || convHead.value?.projectId || '')
    if (pid) q.set('project', pid)
    window.location.href = `${window.location.pathname}#/workbench/sessions?${q.toString()}`
  }, 400)
}

async function ensureProjectName(pid?: string) {
  const id = pid || String(route.query.project || '')
  if (!id || projectName.value) return
  try {
    const ps = await projectService.listProjects()
    projectName.value = String(ps.find((p) => p.id === id)?.name || id)
  } catch { projectName.value = id }
}

/** 输入框直发: coding 子会话 → 执行器直通(store send 继承 activeMeta.kind) */
function onSend(p: { text: string }) {
  conv.send(p.text)
}

/* ── serve 事件流(增量轮询) ── */
async function fetchEvents(incr: boolean) {
  if (!jobId.value) return
  const since = incr ? events.value.at(-1)?.seq ?? 0 : 0
  const r = await apiGet<{ events: Ev[]; empty: boolean }>(
    `/arch/exec-sessions/${encodeURIComponent(jobId.value)}/events?since=${since}`)
  if (r.events.length) {
    events.value = incr ? [...events.value, ...r.events] : r.events
    nextTick(() => { if (feedEl.value) feedEl.value.scrollTop = feedEl.value.scrollHeight })
  }
}

function toggleLive() {
  live.value = !live.value
  if (live.value) evTimer = window.setInterval(() => fetchEvents(true), 2000)
  else { window.clearInterval(evTimer); evTimer = undefined }
}

/** 顶部条: 会话中心打开该会话(dock 对话流; 复用 ?select= 深链激活) */
function openInCenter() {
  const q = new URLSearchParams()
  q.set('select', convId.value)
  if (route.query.project) q.set('project', String(route.query.project))
  window.location.href = `${window.location.pathname}#/workbench/sessions?${q.toString()}`
}

onMounted(async () => {
  // 2610 会话窗口(F1): ?conv= 直开(主会话/architect/coding 子会话通吃)
  const cv = String(route.query.conv || '')
  if (cv) {
    convId.value = cv
    await openConversation(cv)
    void ensureProjectName(String(route.query.project || '')
      || convHead.value?.projectId || '')
    return
  }
  jobId.value = String(route.query.job || '')
  if (!jobId.value) return
  await loadJob()
})
// 2610 标识(多开防混淆): 浏览器标签标题 = 会话标题 · 项目名
watch([heading, projectName], () => {
  document.title = [heading.value || '会话', projectName.value, 'TopoCode']
    .filter(Boolean).join(' · ')
}, { immediate: true })
onBeforeUnmount(() => {
  if (evTimer) window.clearInterval(evTimer)
  if (convId.value) convLock.release(convId.value)
})
</script>

<template>
  <div class="flex h-screen min-h-0 flex-col bg-ctp-base">
    <!-- 头部: 项目 / 主会话 / 执行器会话 -->
    <header class="flex shrink-0 items-center gap-2 border-b border-ctp-surface0 bg-ctp-mantle px-4 py-2.5">
      <BoltIcon class="w-4 h-4 shrink-0 text-ctp-peach" />
      <span v-if="projectName" class="chip shrink-0 bg-ctp-blue/15 text-ctp-blue" :title="t('execSessionView.project')">{{ projectName }}</span>
      <span v-if="parentTitle" class="hidden shrink-0 items-center text-[11px] text-ctp-overlay0 md:flex">
        {{ t('execSessionView.mainConv') }}<span class="ml-1 font-medium text-ctp-subtext1">{{ parentTitle }}</span>
        <span class="mx-1.5 text-ctp-surface2">/</span>
      </span>
      <span class="chip shrink-0 bg-ctp-overlay0/15 text-ctp-overlay1" :title="convId">{{ kindLabel }}</span>
      <span
        class="chip shrink-0 cursor-pointer select-none font-mono !text-[10px] bg-ctp-surface0/70 text-ctp-subtext0 hover:text-ctp-text"
        title="点击复制会话 ID(多开防混淆)"
        @click="copyConvId"
      >{{ copiedId ? '✓ 已复制' : (convId || jobId) }}</span>
      <span class="min-w-0 flex-1 truncate text-sm font-medium text-ctp-text" :title="heading">{{ heading }}</span>
      <span v-if="(conv.activeMeta as any)?.executorId || jobRow?.executorType" class="chip shrink-0 bg-ctp-mauve/15 text-ctp-mauve">⌨ {{ (conv.activeMeta as any)?.executorId || jobRow?.executorType }}</span>
      <span v-if="isRunning" class="chip shrink-0 animate-pulse bg-ctp-green/15 text-ctp-green">● {{ t('execSessionView.running') }}</span>
      <span v-else-if="jobRow?.lastStatus" class="chip shrink-0 bg-ctp-surface0 text-ctp-overlay0">{{ jobRow.lastStatus }}</span>
      <button v-if="jobId && !convId" class="btn btn-xs shrink-0" :title="t('session.outline.title')" @click="outlineOpen = !outlineOpen">
        <ListBulletIcon class="w-3 h-3" />
      </button>
      <button v-if="jobId" class="btn btn-xs shrink-0" :class="live ? 'btn-green' : ''" :title="t('execSessions.live')" @click="toggleLive">
        <ArrowPathIcon class="w-3 h-3" />{{ live ? t('execSessions.liveOn') : t('execSessions.live') }}
      </button>
      <button v-if="convId" class="btn btn-xs shrink-0" :title="t('execSessionView.openCenter')" @click="openInCenter">
        <ArrowTopRightOnSquareIcon class="w-3 h-3" />{{ t('execSessionView.openCenter') }}
      </button>
    </header>

    <!-- 空态: 无 ?job= 且无 ?conv= -->
    <div v-if="!jobId && !convId" class="flex flex-1 items-center justify-center text-xs text-ctp-overlay0">
      {{ t('execSessionView.noJob') }}
    </div>

    <!-- serve 直通: 事件聚合会话视图 + 输入框直发 -->
    <template v-else-if="!convId">
      <div ref="feedEl" class="min-h-0 flex-1 overflow-y-auto overflow-x-hidden px-4 py-4">
        <div class="mx-auto max-w-3xl space-y-3">
          <div v-if="!aggTurns.length && !loading" class="py-16 text-center text-xs text-ctp-overlay0">
            {{ t('execSessions.noEvents') }}
          </div>

          <template v-for="(tn, i) in aggTurns" :key="i">
            <!-- 用户回合: 右蓝泡 -->
            <div v-if="tn.kind === 'user'" :id="`agg-${tn.ts}`" class="flex min-w-0 flex-col items-end rounded-lg transition-shadow" :class="flashTs === tn.ts ? 'ring-2 ring-ctp-blue/50' : ''">
              <div class="max-w-[85%] min-w-0 rounded-lg rounded-br-sm bg-ctp-blue/15 px-3 py-2 text-xs leading-relaxed text-ctp-text whitespace-pre-wrap break-words">{{ tn.text }}</div>
              <span class="mt-0.5 text-[10px] text-ctp-overlay0">{{ fmtFull(tn.ts) }}</span>
            </div>

            <!-- 执行器回合: 可折叠头行 + markdown 全文(长文默认收起) -->
            <div
              v-else-if="tn.kind === 'assistant'"
              :id="`agg-${tn.ts}`"
              class="flex min-w-0 w-full flex-col items-start rounded-lg transition-shadow"
              :class="flashTs === tn.ts ? 'ring-2 ring-ctp-blue/50' : ''"
            >
              <button
                class="mb-0.5 flex w-full items-center gap-1.5 rounded px-0.5 py-0.5 text-left hover:bg-ctp-surface0/40"
                :title="shouldFold(tn) ? t('execSessionView.toggleTurn') : ''"
                @click="toggleFold(tn)"
              >
                <ChevronRightIcon v-if="shouldFold(tn)" class="w-3 h-3 shrink-0 text-ctp-overlay1 transition-transform" :class="isUnfolded(tn) ? 'rotate-90' : ''" />
                <span v-else class="w-3 shrink-0" />
                <span class="shrink-0 text-[10px] font-medium uppercase tracking-wider text-ctp-peach">{{ t('execSessionView.executor') }}</span>
                <span v-if="!isUnfolded(tn)" class="min-w-0 flex-1 truncate text-[10px] text-ctp-overlay0">{{ turnSummary(tn) }}</span>
                <span v-else class="flex-1" />
                <span v-if="shouldFold(tn)" class="shrink-0 font-mono text-[9px] text-ctp-overlay0">{{ t('execSessionView.charsN', { n: (tn.text || '').length }) }}</span>
                <span
                  role="button"
                  tabindex="0"
                  class="shrink-0 rounded p-0.5 text-ctp-overlay0 hover:text-ctp-green transition-colors"
                  :title="t('session.subs.saveDraftHint')"
                  @click.stop="saveReceiptDraft(tn)"
                  @keydown.enter.stop="saveReceiptDraft(tn)"
                ><DocumentArrowDownIcon class="w-3 h-3" :class="savedReceiptTs === tn.ts ? 'animate-pulse' : ''" /></span>
                <span class="shrink-0 text-[10px] text-ctp-overlay0">{{ fmt(tn.ts) }}</span>
              </button>
              <div v-show="isUnfolded(tn)" class="w-full min-w-0 break-words rounded-lg rounded-bl-sm bg-ctp-surface0/60 px-3 py-2 text-xs leading-relaxed text-ctp-text">
                <ChatMessageBlocks :content="tn.text || ''" />
              </div>
            </div>

            <!-- 工具轨迹: 折叠块(默认收起) -->
            <div v-else-if="tn.kind === 'tools'" class="rounded-md border border-ctp-surface0 bg-ctp-crust/40">
              <button class="flex w-full items-center gap-1.5 px-2.5 py-1.5 text-[11px] text-ctp-subtext0 hover:bg-ctp-surface0/40" @click="toggleTools(tn.ts)">
                <ChevronRightIcon class="w-3 h-3 transition-transform" :class="expandedTools.has(i) ? 'rotate-90' : ''" />
                <span class="font-mono text-ctp-sapphire">🔧 {{ t('execSessionView.toolsN', { n: toolCount(tn) }) }}</span>
                <span class="min-w-0 flex-1 truncate text-left text-ctp-overlay0">{{ [...new Set(tn.tools?.map((x) => x.name) || [])].join(' · ') }}</span>
                <span v-if="toolSpan(tn)" class="ml-auto text-ctp-overlay0">{{ toolSpan(tn) }}</span>
              </button>
              <div v-if="expandedTools.has(tn.ts)" class="space-y-1 border-t border-ctp-surface0 px-2.5 py-2">
                <div v-for="(tc, j) in tn.tools" :key="j" class="flex items-start gap-2 text-[11px] leading-relaxed">
                  <span class="w-14 shrink-0 text-right font-mono text-ctp-overlay0">{{ fmt(tc.startTs) }}</span>
                  <span class="shrink-0 font-mono" :class="tc.ok ? 'text-ctp-green' : 'text-ctp-yellow'">{{ tc.ok ? '✓' : '▶' }}</span>
                  <span class="min-w-0 flex-1 break-all font-mono text-ctp-subtext1">{{ tc.name }}</span>
                </div>
              </div>
            </div>

            <!-- 状态分隔条 -->
            <div v-else-if="tn.status" class="flex items-center gap-2 py-0.5 text-[10px]">
              <span class="h-px flex-1 bg-ctp-surface0" />
              <span class="font-mono" :class="tn.status.color">{{ tn.status.tag }}</span>
              <span v-if="tn.status.text" class="max-w-[60%] truncate text-ctp-overlay0" :title="tn.status.text">{{ tn.status.text }}</span>
              <span class="h-px flex-1 bg-ctp-surface0" />
            </div>
          </template>
        </div>
      </div>

      <!-- serve 输入框: 直发 runner(steer/排队) -->
      <footer class="shrink-0 border-t border-ctp-surface0 bg-ctp-mantle px-4 py-2.5">
        <div class="mx-auto flex max-w-3xl items-end gap-2">
          <textarea
            ref="inputEl"
            v-model="serveInput"
            rows="1"
            class="input min-w-0 flex-1 resize-none !py-2 text-xs"
            :disabled="!serveActive"
            :placeholder="serveActive ? t('execSessionView.inputPlaceholder') : t('execSessionView.jobEnded')"
            @input="autoResize"
            @keydown.enter.exact.prevent="sendServe"
          />
          <button v-if="serveActive" class="btn btn-primary shrink-0 !py-2" :disabled="!serveInput.trim() || sending" @click="sendServe">
            <PaperAirplaneIcon class="w-4 h-4" />{{ t('common.send') }}
          </button>
          <button v-if="serveActive" class="btn btn-red shrink-0 !py-2" @click="stopServe">
            <StopIcon class="w-4 h-4" />{{ t('common.stop') }}
          </button>
        </div>
        <p v-if="serveMsg" class="mx-auto mt-1 max-w-3xl text-[10px] text-ctp-overlay0">{{ serveMsg }}</p>
      </footer>

      <!-- serve 大纲浮窗(Teleport): 检索 + 滚动定位回合(须在条件链分支内,
           独立 v-if 兄弟会打断 v-else-if/v-else 链 → AnalysisChat 错配渲染) -->
      <ServeOutlineWindow
        v-if="outlineOpen"
        :items="outlineItems"
        @close="outlineOpen = false"
        @goto="gotoAgg"
      />
    </template>

    <!-- agent 会话模式: 复用 dock 对话栈(回合折叠/伸缩/任务卡/输入直发/SSE) -->
    <div v-else class="min-h-0 flex-1">
      <AnalysisChat
        class="h-full"
        :turns="conv.turns"
        :busy="conv.busy"
        :busy-label="conv.busyLabel"
        :tool-trail="conv.toolTrail"
        :title="heading"
        :editable="!!conv.activeId && !conv.busy"
        :read-only="isArchived"
        :show-assets-panel="false"
        :job-state="jobState"
        :bound-executor-id="(conv.activeMeta as any)?.executorId || ''"
        :executors="executors"
        :analysis-mode="((conv.activeMeta as any)?.analysisMode as 'strict' | 'quick' | undefined) || 'strict'"
        :has-session="!!conv.activeId"
        :conv-id="conv.activeId || undefined"
        :tasks="conv.tasks"
        :ctx-usage="((conv.activeMeta as any)?.meta?.ctxUsage) ?? null"
        @switch-executor="onSwitchExecutor"
        @task-confirm="(id: string) => void conv.taskAction(id, 'confirm')"
        @task-cancel="(id: string) => void conv.taskAction(id, 'cancel')"
        @task-ignore="(id: string) => void conv.taskAction(id, 'ignore')"
        @send="onSend"
        @answers="(a: any) => void conv.sendAnswers(a)"
        @delete-turn="conv.deleteTurn"
        @rollback-to="conv.rollbackTo"
        @stop="conv.stop"
      />
    </div>

    <!-- 锁冲突三选(2610): 接管 / 取消打开并跳转原窗口 / 取消 -->
    <div
      v-if="lockPrompt"
      class="fixed inset-0 z-50 flex items-center justify-center bg-ctp-crust/60 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
    >
      <div class="w-[26rem] max-w-full rounded-xl border border-ctp-surface0 bg-ctp-mantle p-4 shadow-2xl">
        <p class="whitespace-pre-wrap text-sm leading-relaxed text-ctp-text">{{ t('execSessionView.lockTaken', { tab: lockPrompt.owner || '?' }) }}</p>
        <div class="mt-4 flex flex-wrap items-center justify-end gap-2">
          <button class="btn btn-ghost text-xs" @click="onLockCancel">{{ t('execSessionView.lockCancel') }}</button>
          <button class="btn text-xs" :title="t('execSessionView.lockJumpHint')" @click="onLockJumpOriginal">{{ t('execSessionView.lockJump') }}</button>
          <button class="btn text-xs btn-blue" @click="onLockTakeover">{{ t('execSessionView.lockTakeover') }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
