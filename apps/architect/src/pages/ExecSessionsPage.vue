<script setup lang="ts">
/**
 * 执行器会话浏览器（2610 执行器会话拓展 B3 → 2026-10 会话中心并入复用）。
 *
 * 数据面：ExecSessionListPanel(mode=page, 会话档案列表) + 右栏事件时间线。
 * 独立页定位 = 「浏览器新 tab 打开」形态；会话中心左栏标签复用同组件(panel 态)。
 * 支持 ?job=<jobId> 定位(新 tab 打开时高亮该会话)。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRoute } from 'vue-router'
import { BoltIcon, ArrowPathIcon } from '@heroicons/vue/24/outline'
import PageHeader from '@/components/PageHeader.vue'
import ExecSessionListPanel from '@/components/sessions/ExecSessionListPanel.vue'
import { apiGet } from '@/services/api-client'

const { t } = useI18n()
const route = useRoute()

interface Ev { seq: number; kind: string; text: string; ts: number; [k: string]: unknown }

const selected = ref('')
const events = ref<Ev[]>([])
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

const jobTitle = ref('')

async function onPickJob(jobId: string, row?: { title?: string }) {
  selected.value = jobId
  jobTitle.value = row?.title || ''
  events.value = []
  await fetchEvents(false)
}

async function fetchEvents(incr: boolean) {
  if (!selected.value) return
  const since = incr ? events.value.at(-1)?.seq ?? 0 : 0
  const r = await apiGet<{ events: Ev[]; empty: boolean; title?: string }>(
    `/arch/exec-sessions/${encodeURIComponent(selected.value)}/events?since=${since}`)
  if (r.events.length) events.value = incr ? [...events.value, ...r.events] : r.events
  if (!incr && r.title) jobTitle.value = r.title
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

onMounted(() => {
  const fromQuery = String(route.query.job || '')
  if (fromQuery) void onPickJob(fromQuery)
})

onBeforeUnmount(() => { if (timer) window.clearInterval(timer) })

const panelTitle = computed(() => jobTitle.value || selected.value || '—')
const fmt = (ts: number) => ts ? new Date(ts < 1e12 ? ts * 1000 : ts).toLocaleTimeString() : ''
</script>

<template>
  <div class="p-5 space-y-3">
    <PageHeader :title="t('execSessions.title')" :desc="t('execSessions.desc')" />

    <div class="grid grid-cols-1 lg:grid-cols-[20rem_1fr] gap-3">
      <!-- 左: 会话档案(复用面板组件 page 态) -->
      <div class="panel overflow-hidden flex flex-col">
        <div class="panel-header">
          <span class="flex items-center gap-2">
            <span class="chip bg-ctp-surface0 text-ctp-overlay0">{{ t('execSessions.list') }}</span>
          </span>
        </div>
        <div class="p-1 flex-1 min-h-0">
          <ExecSessionListPanel mode="page" @job="onPickJob" />
        </div>
      </div>

      <!-- 右: 事件时间线 -->
      <div class="panel overflow-hidden flex flex-col">
        <div class="panel-header">
          <span class="flex items-center gap-2 truncate">
            <BoltIcon class="w-4 h-4 text-ctp-peach shrink-0" />
            <span class="truncate">{{ panelTitle }}</span>
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
