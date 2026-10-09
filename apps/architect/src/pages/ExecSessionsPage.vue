<script setup lang="ts">
/**
 * 执行器会话深链页（2026-10 重构）——常规 agent 会话页模式。
 *
 * 全屏无工作台框架(顶层路由 /exec-session-view)；?job= 定位：
 * - 有关联会话 → 渲染该会话消息流(项目/主会话头信息 + 气泡对话 + 10s 轮询)
 * - 无关联会话 → 降级事件时间线(留痕档案)
 * 入口：会话中心 exec 标签(点行/↗)；旧 /workbench/exec-sessions 重定向至此。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { BoltIcon, ArrowPathIcon, ArrowTopRightOnSquareIcon } from '@heroicons/vue/24/outline'
import { apiGet } from '@/services/api-client'
import { projectService } from '@/services/project-service'

const { t } = useI18n()
const route = useRoute()

interface Ev { seq: number; kind: string; text: string; ts: number; toolName?: string; [k: string]: unknown }
interface Msg { id?: string; role?: string; content: string; time?: number; item?: { kind?: string; title?: string } | null }
interface ConvHead { title: string; kind: string; executorId: string; parentConvId: string; projectId: string }

const jobId = ref('')
const jobRow = ref<{ title?: string; executorType?: string; lastStatus?: string; taskStatus?: string } | null>(null)
const convId = ref('')
const conv = ref<ConvHead | null>(null)
const parentTitle = ref('')
const projectName = ref('')
const messages = ref<Msg[]>([])
const loading = ref(false)
let poll: number | undefined

/* ── 降级形态: 无关联会话 → 事件时间线 ── */
const events = ref<Ev[]>([])
const live = ref(false)
let evTimer: number | undefined

const KIND_META: Record<string, { color: string; tag: string }> = {
  session_ready: { color: 'text-ctp-green', tag: 'READY' },
  user_input: { color: 'text-ctp-sky', tag: 'IN' },
  input_required: { color: 'text-ctp-yellow', tag: 'WAIT' },
  text: { color: 'text-ctp-subtext1', tag: 'TXT' },
  tool: { color: 'text-ctp-sapphire', tag: 'TOOL' },
  usage: { color: 'text-ctp-overlay0', tag: 'USAGE' },
  notice: { color: 'text-ctp-peach', tag: 'NOTICE' },
  approval_request: { color: 'text-ctp-red', tag: 'AUTH' },
  team: { color: 'text-ctp-mauve', tag: 'TEAM' },
  mcp: { color: 'text-ctp-teal', tag: 'MCP' },
  verify: { color: 'text-ctp-lavender', tag: 'VERIFY' },
  turn_outcome: { color: 'text-ctp-overlay1', tag: 'TURN' },
  turn_done: { color: 'text-ctp-overlay1', tag: 'TURN' },
  progress: { color: 'text-ctp-overlay0', tag: 'PROG' },
  done: { color: 'text-ctp-green', tag: 'DONE' },
  failed: { color: 'text-ctp-red', tag: 'FAIL' },
  aborted: { color: 'text-ctp-yellow', tag: 'STOP' },
  finished: { color: 'text-ctp-overlay1', tag: 'FIN' },
}
const kindMeta = (k: string) => KIND_META[k] || { color: 'text-ctp-overlay0', tag: k.slice(0, 6).toUpperCase() }

const fmt = (ts?: number) => ts ? new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleTimeString() : ''
const fmtFull = (ts?: number) => ts ? new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleString() : ''

const heading = computed(() => conv.value?.title || jobRow.value?.title || jobId.value)
const isRunning = computed(() => !jobRow.value?.lastStatus && jobRow.value?.taskStatus !== 'done')

/** 轻量渲染: 转义 + 换行/代码块/粗体(常规 agent 页文案观感, 不引重库) */
function renderText(text: string): string {
  const esc = (s: string) => s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  const body = esc(text || '')
  return body
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) => `<pre class="rounded bg-ctp-mantle p-2 my-1 overflow-x-auto text-[11px] leading-relaxed"><code>${code}</code></pre>`)
    .replace(/`([^`\n]+)`/g, '<code class="rounded bg-ctp-surface0 px-1 py-0.5 text-[11px] font-mono">$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\n/g, '<br>')
}

async function loadJob() {
  const rows = await apiGet<Array<Record<string, unknown>>>('/arch/exec-sessions?limit=200')
  const row = rows.find((r) => r.jobId === jobId.value)
  if (!row) return
  jobRow.value = row as typeof jobRow.value
  const cid = String(row.conversationId || '')
  if (!cid) { await fetchEvents(false); return }
  convId.value = cid
  await loadMessages()
  if (isRunning.value) poll = window.setInterval(loadMessages, 10000)
}

async function loadMessages() {
  if (!convId.value) return
  loading.value = true
  try {
    const r = await apiGet<{ conv?: ConvHead; parent?: { title?: string } | null; messages: Msg[] }>(
      `/arch/sessions/${encodeURIComponent(convId.value)}/messages`)
    conv.value = r.conv || null
    parentTitle.value = r.parent?.title || ''
    messages.value = r.messages || []
    void ensureProjectName()
    scrollToBottom()
  } finally { loading.value = false }
}

async function ensureProjectName() {
  if (projectName.value) return
  const pid = conv.value?.projectId || String(route.query.project || '')
  if (!pid) return
  try {
    const ps = await projectService.listProjects()
    projectName.value = String(ps.find((p) => p.id === pid)?.name || pid)
  } catch { projectName.value = pid }
}

function scrollToBottom() {
  requestAnimationFrame(() => {
    const el = document.getElementById('esv-feed')
    if (el) el.scrollTop = el.scrollHeight
  })
}

/* ── 事件时间线(降级) ── */
async function fetchEvents(incr: boolean) {
  if (!jobId.value) return
  const since = incr ? events.value.at(-1)?.seq ?? 0 : 0
  const r = await apiGet<{ events: Ev[]; empty: boolean }>(
    `/arch/exec-sessions/${encodeURIComponent(jobId.value)}/events?since=${since}`)
  if (r.events.length) events.value = incr ? [...events.value, ...r.events] : r.events
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
  jobId.value = String(route.query.job || '')
  if (!jobId.value) return
  await loadJob()
})
onBeforeUnmount(() => {
  if (poll) window.clearInterval(poll)
  if (evTimer) window.clearInterval(evTimer)
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
      <span class="min-w-0 flex-1 truncate text-sm font-medium text-ctp-text" :title="heading">{{ heading }}</span>
      <span v-if="conv?.executorId || jobRow?.executorType" class="chip shrink-0 bg-ctp-mauve/15 text-ctp-mauve">⌨ {{ conv?.executorId || jobRow?.executorType }}</span>
      <span v-if="isRunning" class="chip shrink-0 animate-pulse bg-ctp-green/15 text-ctp-green">● {{ t('execSessionView.running') }}</span>
      <span v-if="jobRow?.lastStatus" class="chip shrink-0 bg-ctp-surface0 text-ctp-overlay0">{{ jobRow.lastStatus }}</span>
      <button v-if="convId" class="btn btn-xs shrink-0" :title="t('execSessionView.openCenter')" @click="openInCenter">
        <ArrowTopRightOnSquareIcon class="w-3 h-3" />{{ t('execSessionView.openCenter') }}
      </button>
    </header>

    <!-- 空态: 无 ?job= -->
    <div v-if="!jobId" class="flex flex-1 items-center justify-center text-xs text-ctp-overlay0">
      {{ t('execSessionView.noJob') }}
    </div>

    <!-- 降级: 无关联会话 → 事件时间线 -->
    <template v-else-if="!convId">
      <div class="flex min-h-0 flex-1 flex-col p-4">
        <div class="flex items-center gap-2 pb-2 text-[11px] text-ctp-overlay0">
          <span>{{ t('execSessionView.timelineFallback') }}</span>
          <button class="btn btn-xs ml-auto" :class="live ? 'btn-green' : ''" @click="toggleLive">
            <ArrowPathIcon class="w-3 h-3" />{{ live ? t('execSessions.liveOn') : t('execSessions.live') }}
          </button>
        </div>
        <div class="overflow-auto min-h-0 flex-1 rounded-lg border border-ctp-surface0 p-3">
          <div v-if="!events.length" class="py-10 text-center text-xs text-ctp-overlay0">{{ t('execSessions.noEvents') }}</div>
          <div v-for="ev in events" :key="ev.seq" class="flex items-start gap-2 text-[11px] leading-relaxed">
            <span class="w-14 shrink-0 text-right font-mono text-ctp-overlay0">{{ fmt(ev.ts) }}</span>
            <span class="w-14 shrink-0 font-mono" :class="kindMeta(ev.kind).color">{{ kindMeta(ev.kind).tag }}</span>
            <span class="min-w-0 flex-1 break-all whitespace-pre-wrap"
                  :class="ev.kind === 'text' ? 'text-ctp-subtext1' : 'text-ctp-text'">
              {{ (ev.text || '').slice(0, 500) }}
              <span v-if="ev.toolName" class="font-mono text-ctp-sapphire"> [{{ ev.toolName }}]</span>
            </span>
          </div>
        </div>
      </div>
    </template>

    <!-- 常规 agent 会话页: 消息流 -->
    <template v-else>
      <div id="esv-feed" class="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        <div class="mx-auto max-w-3xl space-y-3">
          <div v-if="!messages.length && !loading" class="py-16 text-center text-xs text-ctp-overlay0">
            {{ t('execSessionView.noMessages') }}
          </div>
          <div v-for="(m, i) in messages" :key="m.id || i" class="flex flex-col">
            <!-- 用户输入: 右对齐蓝泡 -->
            <div v-if="m.role === 'user'" class="flex flex-col items-end">
              <div class="max-w-[85%] rounded-lg rounded-br-sm bg-ctp-blue/15 px-3 py-2 text-xs leading-relaxed text-ctp-text"
                   v-html="renderText(m.content)" />
              <span class="mt-0.5 text-[10px] text-ctp-overlay0">{{ fmtFull(m.time) }}</span>
            </div>
            <!-- 执行器输出: 左对齐, role 头 + 内容 -->
            <div v-else class="flex flex-col items-start">
              <span class="mb-0.5 text-[10px] font-medium uppercase tracking-wider text-ctp-peach">{{ t('execSessionView.executor') }}</span>
              <div class="max-w-[92%] rounded-lg rounded-bl-sm bg-ctp-surface0/60 px-3 py-2 text-xs leading-relaxed text-ctp-text">
                <div v-if="m.item" class="mb-1 flex items-center gap-1.5">
                  <span class="chip bg-ctp-teal/15 text-ctp-teal !text-[9px]">{{ m.item.kind || 'item' }}</span>
                  <span v-if="m.item.title" class="text-[11px] font-medium text-ctp-subtext1">{{ m.item.title }}</span>
                </div>
                <div v-html="renderText(m.content)" />
              </div>
              <span class="mt-0.5 text-[10px] text-ctp-overlay0">{{ fmtFull(m.time) }}</span>
            </div>
          </div>
        </div>
      </div>
      <!-- 底部只读提示 -->
      <footer class="shrink-0 border-t border-ctp-surface0 bg-ctp-mantle px-4 py-1.5 text-center text-[10px] text-ctp-overlay0">
        {{ t('execSessionView.readonlyHint') }}
      </footer>
    </template>
  </div>
</template>
