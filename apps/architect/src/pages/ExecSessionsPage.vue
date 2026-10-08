<script setup lang="ts">
/**
 * 执行器会话浏览器（2610 执行器会话拓展 B3）——简版 webui 单独窗口。
 *
 * 数据面：GET /arch/exec-sessions（B2，architect 自持留痕）+ ?since= 增量轮询。
 * 左栏会话档案（任务关联/终态），右栏事件时间线（kind 分色）；
 * 活跃会话可开 live 跟进（2s 轮询）；新标签打开即"单独窗口"形态。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import {
  CommandLineIcon, BoltIcon, ArrowPathIcon,
} from '@heroicons/vue/24/outline'
import PageHeader from '@/components/PageHeader.vue'
import { apiGet } from '@/services/api-client'

const { t } = useI18n()
const route = useRoute()

interface SessionRow {
  jobId: string; eventCount: number; firstTs: number; lastTs: number
  lastStatus: string; taskId: string; title: string; executorType: string
  conversationId: string; sessionRef: string; taskStatus: string
}
interface Ev { seq: number; kind: string; text: string; ts: number; [k: string]: unknown }

const sessions = ref<SessionRow[]>([])
const selected = ref('')
const events = ref<Ev[]>([])
const loading = ref(false)
const live = ref(false)
let timer: number | undefined

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

const isActive = (s: SessionRow) => !s.lastStatus && s.taskStatus !== 'done'
const selectedRow = computed(() => sessions.value.find((s) => s.jobId === selected.value))

async function loadSessions(keep = true) {
  loading.value = true
  try {
    sessions.value = await apiGet<SessionRow[]>('/arch/exec-sessions?limit=100')
    const fromQuery = String(route.query.job || '')
    const pick = (keep && selected.value) || fromQuery
      || sessions.value[0]?.jobId || ''
    if (pick && pick !== selected.value) await openSession(pick)
  } finally { loading.value = false }
}

async function openSession(jobId: string) {
  selected.value = jobId
  events.value = []
  await fetchEvents(false)
}

async function fetchEvents(incr: boolean) {
  if (!selected.value) return
  const since = incr ? events.value.at(-1)?.seq ?? 0 : 0
  const r = await apiGet<{ events: Ev[]; empty: boolean }>(
    `/arch/exec-sessions/${encodeURIComponent(selected.value)}/events?since=${since}`)
  if (r.events.length) events.value = incr ? [...events.value, ...r.events] : r.events
}

function toggleLive() {
  live.value = !live.value
  if (live.value) {
    timer = window.setInterval(() => fetchEvents(true), 2000)
  } else {
    window.clearInterval(timer)
    timer = undefined
  }
}

onMounted(loadSessions)
onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })

const fmt = (ts: number) => ts ? new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleTimeString() : ''
</script>

<template>
  <div class="p-5 space-y-3">
    <PageHeader :title="t('execSessions.title')" :desc="t('execSessions.desc')" />

    <div class="grid grid-cols-1 lg:grid-cols-[20rem_1fr] gap-3">
      <!-- 左: 会话档案 -->
      <div class="panel overflow-hidden flex flex-col">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <CommandLineIcon class="w-4 h-4 text-ctp-green" />{{ t('execSessions.list') }}
            <span class="chip bg-ctp-surface0 text-ctp-overlay0">{{ sessions.length }}</span>
          </span>
          <button class="btn btn-xs" @click="loadSessions()">
            <ArrowPathIcon class="w-3 h-3" />
          </button>
        </div>
        <div class="overflow-auto max-h-[36rem] divide-y divide-ctp-surface0">
          <button
            v-for="s in sessions" :key="s.jobId"
            class="w-full text-left px-3 py-2 text-xs"
            :class="s.jobId === selected ? 'bg-ctp-surface1' : 'hover:bg-ctp-surface0/50'"
            @click="openSession(s.jobId)"
          >
            <div class="flex items-center gap-1.5">
              <span class="chip shrink-0 bg-ctp-surface0 text-ctp-subtext0">{{ s.executorType || '?' }}</span>
              <span class="flex-1 truncate font-medium">{{ s.title || s.jobId }}</span>
              <span v-if="isActive(s)" class="w-1.5 h-1.5 rounded-full bg-ctp-green shrink-0 animate-pulse" />
            </div>
            <div class="text-[10px] text-ctp-overlay0 mt-0.5 flex gap-2">
              <span>{{ s.eventCount }} ev</span>
              <span>{{ fmt(s.lastTs) }}</span>
              <span v-if="s.lastStatus" :class="kindMeta(s.lastStatus).color">{{ s.lastStatus }}</span>
            </div>
          </button>
          <div v-if="!sessions.length && !loading" class="px-3 py-8 text-center text-xs text-ctp-overlay0">
            {{ t('execSessions.empty') }}
          </div>
        </div>
      </div>

      <!-- 右: 事件时间线 -->
      <div class="panel overflow-hidden flex flex-col">
        <div class="panel-header">
          <span class="flex items-center gap-2 truncate">
            <BoltIcon class="w-4 h-4 text-ctp-peach shrink-0" />
            <span class="truncate">{{ selectedRow?.title || selected || '—' }}</span>
            <span v-if="selectedRow?.sessionRef" class="chip bg-ctp-surface0 text-ctp-overlay0 shrink-0">ref</span>
          </span>
          <button class="btn btn-xs" :class="live ? 'btn-green' : ''" :disabled="!selected" @click="toggleLive">
            <ArrowPathIcon class="w-3 h-3" />{{ live ? t('execSessions.liveOn') : t('execSessions.live') }}
          </button>
        </div>
        <div class="overflow-auto max-h-[36rem] p-3 space-y-1">
          <div v-if="!events.length" class="py-10 text-center text-xs text-ctp-overlay0">
            {{ t('execSessions.noEvents') }}
          </div>
          <div
            v-for="ev in events" :key="ev.seq"
            class="flex items-start gap-2 text-[11px] leading-relaxed"
          >
            <span class="text-ctp-overlay0 shrink-0 w-14 text-right font-mono">{{ fmt(ev.ts) }}</span>
            <span class="shrink-0 w-14 font-mono" :class="kindMeta(ev.kind).color">{{ kindMeta(ev.kind).tag }}</span>
            <span class="flex-1 min-w-0 whitespace-pre-wrap break-all"
                  :class="ev.kind === 'text' ? 'text-ctp-subtext1' : 'text-ctp-text'">
              {{ (ev.text || '').slice(0, 500) }}
              <span v-if="ev.toolName" class="text-ctp-sapphire font-mono"> [{{ ev.toolName }}]</span>
            </span>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
