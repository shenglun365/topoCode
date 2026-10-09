<script setup lang="ts">
/**
 * 执行器会话深链页（2026-10 v3）——完整 agent 会话模式。
 *
 * 全屏无工作台框架(顶层路由 /exec-session-view)；?job= 定位：
 * - 有关联会话 → 复用 dock 对话栈(conversation-store + AnalysisChat)：
 *   回合折叠/展开/伸缩、任务卡、输入框直发(执行器直通)、SSE 实时、窗口锁
 * - 无关联会话 → 降级事件时间线(留痕档案)
 * 头信息: 项目 chip + 主会话标题 + 子会话标题 + 执行器 + 运行状态。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { BoltIcon, ArrowPathIcon, ArrowTopRightOnSquareIcon } from '@heroicons/vue/24/outline'
import { apiGet } from '@/services/api-client'
import { projectService } from '@/services/project-service'
import { useConversationStore } from '@/stores/conversation-store'
import { useConvWindowLock } from '@/composables/useConvWindowLock'
import { useAppDialog } from '@/composables/useAppDialog'
import AnalysisChat from '@/components/requirements/AnalysisChat.vue'

const { t } = useI18n()
const route = useRoute()
const conv = useConversationStore()
const convLock = useConvWindowLock()
const dialog = useAppDialog()

interface Ev { seq: number; kind: string; text: string; ts: number; toolName?: string; [k: string]: unknown }

const jobId = ref('')
const jobRow = ref<{ title?: string; executorType?: string; lastStatus?: string; taskStatus?: string } | null>(null)
const convId = ref('')
const parentTitle = ref('')
const projectName = ref('')
const loading = ref(false)

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

const heading = computed(() => (conv.activeMeta as any)?.title || jobRow.value?.title || jobId.value)
const isRunning = computed(() => !jobRow.value?.lastStatus && jobRow.value?.taskStatus !== 'done')
const isArchived = computed(() => (conv.activeMeta as any)?.status === 'archived')
const jobState = computed(() => (isRunning.value
  ? { role: 'coding', executorId: jobRow.value?.executorType || (conv.activeMeta as any)?.executorId, status: 'running' }
  : null))

async function loadJob() {
  const rows = await apiGet<Array<Record<string, unknown>>>('/arch/exec-sessions?limit=200')
  const row = rows.find((r) => r.jobId === jobId.value)
  if (!row) return
  jobRow.value = row as typeof jobRow.value
  const cid = String(row.conversationId || '')
  if (!cid) { await fetchEvents(false); return }
  convId.value = cid
  await openConversation(cid)
}

/** 打开会话(store 全栈: turns/任务/busy/SSE) + 头信息(主会话标题/项目) */
async function openConversation(cid: string) {
  loading.value = true
  try {
    // 头信息一次取齐(BE: messages 接口带 conv/parent 头)
    try {
      const h = await apiGet<{ conv?: { projectId?: string }; parent?: { title?: string } | null }>(
        `/arch/sessions/${encodeURIComponent(cid)}/messages?limit=1`)
      parentTitle.value = h.parent?.title || ''
      void ensureProjectName(h.conv?.projectId)
    } catch { /* 头信息失败不阻断会话打开 */ }
    // 窗口唯一性: 同子会话已在别的窗口打开 → 接管确认
    const lk = await convLock.claim(cid)
    if (!lk.claimed) {
      const ok = await dialog.confirm(t('session.subs.lockTaken', { tab: lk.owner || '?' }), {
        confirmText: t('session.subs.lockTakeover'), danger: false })
      if (!ok) { window.close(); return }
      convLock.takeover(cid)
    }
    await conv.openConversation({ id: cid } as any)
    conv.connectEvents()
  } finally { loading.value = false }
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
      <span class="min-w-0 flex-1 truncate text-sm font-medium text-ctp-text" :title="heading">{{ heading }}</span>
      <span v-if="(conv.activeMeta as any)?.executorId || jobRow?.executorType" class="chip shrink-0 bg-ctp-mauve/15 text-ctp-mauve">⌨ {{ (conv.activeMeta as any)?.executorId || jobRow?.executorType }}</span>
      <span v-if="isRunning" class="chip shrink-0 animate-pulse bg-ctp-green/15 text-ctp-green">● {{ t('execSessionView.running') }}</span>
      <span v-else-if="jobRow?.lastStatus" class="chip shrink-0 bg-ctp-surface0 text-ctp-overlay0">{{ jobRow.lastStatus }}</span>
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
        :has-session="!!conv.activeId"
        :conv-id="conv.activeId || undefined"
        :tasks="conv.tasks"
        :ctx-usage="((conv.activeMeta as any)?.meta?.ctxUsage) ?? null"
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
  </div>
</template>
